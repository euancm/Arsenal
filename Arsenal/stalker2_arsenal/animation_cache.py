"""Skip re-baking animations whose inputs have not changed since the last export.

Each exported action is fingerprinted from everything its FBXs are baked from: its keys, the
rig and source skeleton, the bone mapping, the donor templates, the scene frame rate and the
export code itself. The fingerprints live in the output folder next to the FBXs, together with
the size and time of each file written, so a file that was deleted or replaced is re-exported.
"""

import hashlib
import json
import os
import sys

import bpy

from .retarget_animation import action_slot_curves

CACHE_FILE = 'arsenal_animation_cache.json'
CACHE_VERSION = 1
SOURCE_MODULES = ('export_animation', 'bone_functions', 'stalker2_animation_importer', 'animation_cache')


def _plain(value, depth=0):
    """A JSON-stable form of an RNA value; floats are rounded so float noise does not invalidate."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if depth < 3:
        try:
            return [_plain(item, depth + 1) for item in value]
        except TypeError:
            pass
    return repr(value)


def _rna(struct, depth=0):
    """Every editable setting of an RNA struct (constraint, modifier...), recursing into collections."""
    values = []
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or (prop.type == 'POINTER' and not isinstance(getattr(struct, name, None), bpy.types.ID)):
            continue
        if prop.type == 'COLLECTION':
            if depth < 2:
                values.append((name, [_rna(item, depth + 1) for item in getattr(struct, name)]))
            continue
        try:
            values.append((name, _plain(getattr(struct, name))))
        except (AttributeError, RuntimeError, TypeError):
            continue
    return values


def _curve_data(curve):
    count = len(curve.keyframe_points)
    data = {}
    for prop in ('co', 'handle_left', 'handle_right'):
        flat = [0.0] * (count * 2)
        curve.keyframe_points.foreach_get(prop, flat)
        data[prop] = [round(value, 6) for value in flat]
    data['keys'] = [(key.interpolation, key.easing, round(key.back, 6), round(key.amplitude, 6),
                     round(key.period, 6)) for key in curve.keyframe_points]
    return [curve.data_path, curve.array_index, curve.mute, curve.extrapolation, data,
            [_rna(modifier) for modifier in curve.modifiers]]


def action_data(action, slot):
    curves = sorted((_curve_data(curve) for curve in action_slot_curves(action, slot)),
                    key=lambda item: (item[0], item[1]))
    return [action.name, slot.identifier if slot else '', _plain(tuple(action.frame_range)),
            action.use_frame_range, action.use_cyclic, curves]


def _armature_data(obj):
    bones = [(bone.name, bone.parent.name if bone.parent else '', _plain(bone.matrix_local),
              _plain(bone.length), bone.use_deform, bone.inherit_scale, bone.use_inherit_rotation,
              bone.use_local_location, bone.use_connect, bone.bbone_segments)
             for bone in obj.data.bones]
    return [obj.name, _plain(obj.matrix_world), bones]


def rig_data(rig, backup, keyed_props):
    """The rig, its constraints, drivers and unkeyed custom properties, and the source skeleton.

    Driven settings are covered by their drivers, keyed_props by the action fingerprint and the
    IK/FK switch is keyed or reset by export, so their current values are left out."""
    drivers = []
    driven = set()
    if rig.animation_data:
        for driver in rig.animation_data.drivers:
            driven.add(driver.data_path)
            drivers.append((driver.data_path, driver.array_index, driver.driver.type, driver.driver.expression,
                            [(variable.name, variable.type,
                              [(_plain(target.id), target.data_path, target.bone_target, target.transform_type,
                                target.transform_space) for target in variable.targets])
                             for variable in driver.driver.variables]))
    external = set()
    pose = []
    for bone in rig.pose.bones:
        constraints = []
        for constraint in bone.constraints:
            prefix = f'pose.bones["{bpy.utils.escape_identifier(bone.name)}"].constraints["{bpy.utils.escape_identifier(constraint.name)}"].'
            constraints.append([item for item in _rna(constraint) if prefix + item[0] not in driven])
            for pointer in ('target', 'pole_target'):
                target = getattr(constraint, pointer, None)
                if isinstance(target, bpy.types.Object) and target not in (rig, backup):
                    external.add(target)
        prefix = f'pose.bones["{bpy.utils.escape_identifier(bone.name)}"]'
        props = sorted((key, _plain(bone[key])) for key in bone.keys()
                       if key != 'IK_FK' and (bone.name, f'["{key}"]') not in keyed_props
                       and f'{prefix}["{key}"]' not in driven and isinstance(bone[key], (int, float, str)))
        pose.append((bone.name, bone.rotation_mode, _plain(bone.ik_stretch),
                     (bone.lock_ik_x, bone.lock_ik_y, bone.lock_ik_z), constraints, props))
    others = sorted((obj.name, _plain(obj.matrix_world)) for obj in external)
    return [_armature_data(rig), _armature_data(backup), pose, drivers, others,
            rig.get('arsenal_deformation_mapping', '')]


def _file_stamp(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]


def code_data():
    package = __package__
    sources = []
    for name in SOURCE_MODULES:
        module = sys.modules.get(f'{package}.{name}')
        path = getattr(module, '__file__', None)
        try:
            with open(path, 'rb') as handle:
                sources.append(hashlib.sha256(handle.read()).hexdigest())
        except (OSError, TypeError):
            sources.append(None)
    return sources


def _digest(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


class AnimationCache:
    """Fingerprints of the last successful export of each action, keyed by its first target."""

    def __init__(self, output_root, context, rig, backup, mapping, substeps):
        self.path = os.path.join(output_root, CACHE_FILE)
        self.entries = {}
        self.unchanged = 0
        try:
            with open(self.path, encoding='utf-8') as handle:
                stored = json.load(handle)
            if stored.get('version') == CACHE_VERSION:
                self.entries = stored.get('actions', {})
        except (OSError, ValueError, AttributeError):
            self.entries = {}
        render = context.scene.render
        self._shared = [code_data(), substeps, render.fps, _plain(render.fps_base),
                        sorted(_plain(list(item)) for item in mapping)]
        self._rig = rig
        self._backup = backup
        self._rig_digests = {}

    def fingerprint(self, action, slot, outputs, keyed):
        keyed_props = frozenset(item for item in keyed if item[1].startswith('['))
        rig_digest = self._rig_digests.get(keyed_props)
        if rig_digest is None:
            rig_digest = self._rig_digests[keyed_props] = _digest(rig_data(self._rig, self._backup, keyed_props))
        templates = [(kind, os.path.normcase(os.path.abspath(template)), _file_stamp(template),
                      os.path.normcase(os.path.abspath(target)) if target else None)
                     for kind, template, target in outputs]
        return _digest(self._shared, rig_digest, action_data(action, slot), templates)

    @staticmethod
    def _targets(outputs):
        return [os.path.normcase(os.path.abspath(target)) for _kind, _template, target in outputs if target]

    def is_current(self, outputs, fingerprint):
        targets = self._targets(outputs)
        entry = self.entries.get(targets[0]) if targets else None
        if not entry or entry.get('fingerprint') != fingerprint:
            return False
        files = entry.get('files', {})
        return all(files.get(target) == _file_stamp(target) for target in targets)

    def record(self, name, outputs, fingerprint):
        targets = self._targets(outputs)
        if targets:
            self.entries[targets[0]] = {
                'action': name,
                'fingerprint': fingerprint,
                'files': {target: _file_stamp(target) for target in targets},
            }

    def forget(self, outputs):
        targets = self._targets(outputs)
        if targets:
            self.entries.pop(targets[0], None)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        partial = self.path + '.partial'
        with open(partial, 'w', encoding='utf-8') as handle:
            json.dump({'version': CACHE_VERSION, 'actions': self.entries}, handle, indent=1)
        os.replace(partial, self.path)
