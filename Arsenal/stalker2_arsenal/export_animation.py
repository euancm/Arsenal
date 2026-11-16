import json
import math
import os
import re
import traceback
from contextlib import contextmanager

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import bone_functions as b_fun
from . import export_skeleton
from . import export_static_mesh as static_mesh
from . import stalker2_animation_importer as importer
from .notifications import Progress, completion, report
from .retarget_animation import (
    action_slot_curves,
    find_retarget_backup,
    get_pose_bone_name,
    resolve_animation_mapping,
)

FALLBACK_TEMPLATE = 'idle'
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
IDENTITY = Matrix.Identity(4)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_export_rig(context):
    candidates = [context.view_layer.objects.active] + list(context.scene.objects)
    for obj in candidates:
        if obj and obj.type == 'ARMATURE' and obj.data.get('rig_id'):
            backup, _collection = find_retarget_backup(obj)
            if backup:
                return obj, backup
    return None, None


def rig_action_slot(action, rig):
    best = None
    for slot in action.slots:
        if slot.target_id_type != 'OBJECT':
            continue
        names = {get_pose_bone_name(curve.data_path) for curve in action_slot_curves(action, slot)}
        # Object-level curves (e.g. a keyed rig location) have no bone name; Blender rejects `None in bones`.
        count = len({name for name in names if name is not None and name in rig.pose.bones})
        if count and (best is None or count > best[1]):
            best = (slot, count)
    return best[0] if best else None


def exportable_actions(rig):
    result = []
    for action in bpy.data.actions:
        if action.is_action_legacy or action.get(importer.ACTION_MARKER):
            continue
        if rig_action_slot(action, rig):
            result.append(action)
    return sorted(result, key=lambda item: item.name.casefold())


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------

def library_anchor_parts(path):
    parts = os.path.normpath(path).split(os.sep)
    for index in range(len(parts) - 2, 0, -1):
        if (parts[index].casefold() == 'animations'
                and parts[index + 1].casefold() in {'player', 'weapons'}):
            return parts[index - 1:]
    raise ValueError(f'Cannot find the STALKER2\\Animations folder in {path}')


def rename_weapon_folders(folders, old_name, new_name):
    """Swap the old weapon name for the new one, including the template's folder under 'pt' (e.g. pt/udp)."""
    result = []
    for index, part in enumerate(folders):
        after_pt = index > 0 and folders[index - 1].casefold() == 'pt'
        result.append(new_name if after_pt or part.casefold() == old_name.casefold() else part)
    return result


def export_relative_path(template_path, kind, old_name, new_name, suffix, folder_override, exact=False):
    parts = library_anchor_parts(template_path)
    folders = parts[:-1]
    if folder_override:
        marker = old_name if kind == 'player' else 'fp'
        index = max((i for i, part in enumerate(folders) if part.casefold() == marker.casefold()), default=None)
        if index is None and kind == 'player':
            index = max((i for i, part in enumerate(folders[:-1]) if part.casefold() == 'pt'), default=None)
            index = None if index is None else index + 1
        if index is None:
            raise ValueError(f'No "{marker}" folder to apply the folder override to in {template_path}')
        override_parts = [part for part in re.split(r'[\\/]+', folder_override) if part]
        folders = folders[:index + 1] + override_parts
    folders = rename_weapon_folders(folders, old_name, new_name)
    if exact:
        # The template's own name with the weapon swapped, as the setup script named the mod asset
        # (this keeps AS_FP_Player_<weapon>_OffsetAim-Idle_01 and its odd casing).
        stem = os.path.splitext(os.path.basename(template_path))[0]
        token = re.compile(rf'(?<![a-z0-9]){re.escape(old_name)}(?![a-z0-9])', re.IGNORECASE)
        return os.path.join(*folders, token.sub(new_name, stem) + '.fbx')
    stem = INVALID_FILENAME_CHARS.sub('_', suffix)
    if kind == 'player':
        filename = f'AS_fp_{new_name}_{stem}.fbx'
    else:
        filename = f'AS_{new_name}_fp_{stem}.fbx'
    return os.path.join(*folders, filename)


def is_inside(path, folder):
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


def plan_export(item_name, template_override, folder_override, pairs, old_name, new_name,
                output_root, library_root):
    by_key = {suffix.casefold(): (suffix, player, weapon) for suffix, player, weapon in pairs}
    if template_override:
        key = template_override.casefold()
        if key not in by_key:
            raise ValueError(f'Template "{template_override}" not found in the library')
        exact = False
    elif item_name.casefold() in by_key:
        key = item_name.casefold()
        exact = True
    elif FALLBACK_TEMPLATE in by_key:
        key = FALLBACK_TEMPLATE
        exact = False
    else:
        raise ValueError(f'No template pair for "{item_name}" (and no "{FALLBACK_TEMPLATE}" pair)')
    template = by_key[key]
    _suffix, player_template, weapon_template = template
    stand_in = importer.stand_in_half(template)

    outputs = []
    for kind, template_path in (('player', player_template), ('weapon', weapon_template)):
        if kind == stand_in:
            # The other side's idle, only needed to solve the clip; the game has no such half to replace.
            outputs.append((kind, template_path, None))
            continue
        relative = export_relative_path(
            template_path, kind, old_name, new_name, item_name, folder_override, exact)
        target = os.path.join(output_root, relative)
        if is_inside(target, library_root) or os.path.normcase(target) == os.path.normcase(template_path):
            raise ValueError('Output would overwrite the original library; choose a different output folder')
        outputs.append((kind, template_path, target))
    status = 'Matches an original animation' if exact else f'New - template "{template[0]}"'
    if stand_in:
        status += f' ({"weapon" if stand_in == "player" else "character"} only)'
    return outputs, status


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------

def bone_order(armature):
    ordered = []
    seen = set()

    def visit(bone):
        if bone.name in seen:
            return
        if bone.parent:
            visit(bone.parent)
        seen.add(bone.name)
        ordered.append(bone)

    for bone in armature.data.bones:
        visit(bone)
    return ordered


def rest_relatives(armature):
    relatives = {}
    for bone in armature.data.bones:
        if bone.parent:
            relatives[bone.name] = bone.parent.matrix_local.inverted_safe() @ bone.matrix_local
        else:
            relatives[bone.name] = bone.matrix_local.copy()
    return relatives


TRANSFORM_PROPS = {'location', 'rotation_quaternion', 'rotation_euler', 'rotation_axis_angle', 'scale'}
TEMPLATE_CURVE = re.compile(r'(?:pose\.bones\["((?:[^"\\]|\\.)*)"\]\.)?(\w+)$')


def _channels(owner):
    """Static transform values of an object or pose bone, as mutable lists."""
    return {
        'location': list(owner.location),
        'rotation_quaternion': list(owner.rotation_quaternion),
        'rotation_euler': list(owner.rotation_euler),
        'rotation_axis_angle': list(owner.rotation_axis_angle),
        'scale': list(owner.scale),
    }


def _channel_matrix(mode, values):
    if mode == 'QUATERNION':
        rotation = Quaternion(values['rotation_quaternion']).normalized()
    elif mode == 'AXIS_ANGLE':
        angle, *axis = values['rotation_axis_angle']
        rotation = Quaternion(Vector(axis).normalized(), angle) if Vector(axis).length else Quaternion()
    else:
        rotation = Euler(values['rotation_euler'], mode)
    return Matrix.LocRotScale(Vector(values['location']), rotation, Vector(values['scale']))


def _template_curve_sampler(armature):
    """Evaluate an imported template's own F-curves, without frame_set re-evaluating the whole scene.

    Returns None when anything other than its plain action could move the template, so the caller
    falls back to scene evaluation."""
    animation_data = armature.animation_data
    if (armature.parent or armature.constraints or animation_data is None or animation_data.action is None
            or animation_data.action_slot is None
            or animation_data.drivers or animation_data.nla_tracks
            or any(bone.constraints for bone in armature.pose.bones)
            or Vector(armature.delta_location).length or Vector(armature.delta_scale) != Vector((1, 1, 1))
            or Vector(armature.delta_rotation_euler).length
            or Quaternion(armature.delta_rotation_quaternion) != Quaternion()):
        return None
    bones = {bone.name: (bone.rotation_mode, _channels(bone)) for bone in armature.pose.bones}
    obj_channels = (armature.rotation_mode, _channels(armature))
    curves = []
    for curve in action_slot_curves(animation_data.action, animation_data.action_slot):
        match = TEMPLATE_CURVE.match(curve.data_path)
        if match is None:
            if curve.data_path.startswith('pose.bones['):
                continue  # custom properties do not move bones
            return None
        bone_name, prop = match.groups()
        if prop not in TRANSFORM_PROPS:
            return None
        owner = obj_channels if bone_name is None else bones.get(bone_name.replace('\\"', '"'))
        if owner is None:
            continue
        if curve.mute or curve.is_empty:
            continue
        curves.append((curve, owner[1][prop], curve.array_index))

    def sample(frame):
        for curve, values, index in curves:
            values[index] = curve.evaluate(frame)
        return (
            {name: _channel_matrix(mode, values) for name, (mode, values) in bones.items()},
            _channel_matrix(*obj_channels),
        )
    return sample


def sample_template(context, armature, frames):
    sampler = _template_curve_sampler(armature)
    if sampler is not None:
        return {frame: sampler(frame) for frame in frames}
    samples = {}
    for frame in frames:
        context.scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
        context.view_layer.update()
        samples[frame] = (
            {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in armature.pose.bones},
            armature.matrix_world.copy(),
        )
    return samples


LIMB_CONTROLS = ('thigh_fk', 'shin_fk', 'foot_fk', 'upper_arm_fk', 'forearm_fk', 'hand_fk')
TEMPLATE_SOCKETS = ('jnt_l_weapon', 'jnt_r_weapon')
# Rigify's stretchy deform spine reproduces joint positions but not the donor's spine twist or bone
# lengths. The game rotates these bones procedurally (look pitch, stance lean) and blends our clips with
# vanilla ones bone by bone in local space, so they keep the donor's local twist and scale and only swing
# to point at the rig's next spine joint, which is still solved exactly from the rig.
TWIST_LOCKED_CHAIN = {'jnt_spine_01': 'jnt_spine_02', 'jnt_spine_02': 'jnt_spine_03'}
BAKE_SUBSTEPS = 4


def visible_pose_name(rig, target_name):
    # ORG bones include FK/IK blending and finger master/stretch constraints; controls do not.
    name = target_name.replace('_fk', '', 1) if target_name.split('.')[0] in LIMB_CONTROLS else target_name
    candidate = 'ORG-' + name
    if candidate in rig.pose.bones:
        return candidate
    return target_name


def deformation_entries(rig, backup, mapping):
    from .mapping_editor import build_mapping_guesses

    entries = {
        source: visible_pose_name(rig, target)
        for target, source, _kind in mapping
    }
    deform_names = {
        bone.name[4:] for bone in rig.data.bones
        if bone.name.startswith('DEF-') and bone.use_deform
    }
    # Older rigs saved only control mappings, dropping palms and twist segments.
    bindings = build_mapping_guesses(
        [bone.name for bone in backup.data.bones], deform_names)
    for target, source, _kind in mapping:
        name = target.replace('_fk', '', 1) if target.split('.')[0] in LIMB_CONTROLS else target
        if name in deform_names:
            bindings[source] = name
    bindings.update(dict(json.loads(rig.get('arsenal_deformation_mapping', '[]'))))
    for bone in backup.data.bones:
        target = 'DEF-' + bindings.get(bone.name, bone.name)
        if target in rig.pose.bones and rig.data.bones[target].use_deform:
            entries[bone.name] = target
        elif bone.name not in entries and bone.name in rig.pose.bones:
            entries[bone.name] = bone.name
    explicitly_mapped = {source for _target, source, _kind in mapping}
    return [
        (target, source) for source, target in entries.items()
        if source not in TEMPLATE_SOCKETS or source in explicitly_mapped
    ]


def deformation_preview_issues(rig):
    issues = [
        bone.name for bone in rig.data.bones
        if bone.use_deform and bone.bbone_segments > 1
    ]
    issues.extend(name for name, _target in b_fun.upper_arm_twist_sources(rig))
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not any(
                mod.type == 'ARMATURE' and mod.object == rig for mod in obj.modifiers):
            continue
        missing = {
            group.index: group.name for group in obj.vertex_groups
            if group.name.startswith('DEF-') and (
                group.name not in rig.data.bones or not rig.data.bones[group.name].use_deform)
        }
        if missing:
            used = {
                group.group for vertex in obj.data.vertices for group in vertex.groups
                if group.group in missing and group.weight > 0
            }
            issues.extend(missing[index] for index in sorted(used))
    return issues


def read_reversed_worlds(rig, backup, entries):
    rig_world = rig.matrix_world
    backup_inverse = backup.matrix_world.inverted_safe()
    result = {}
    for read_name, source_name in entries:
        pose_world = rig_world @ rig.pose.bones[read_name].matrix
        rest_target = rig_world @ rig.data.bones[read_name].matrix_local
        rest_source = backup.matrix_world @ backup.data.bones[source_name].matrix_local
        result[source_name] = backup_inverse @ (pose_world @ rest_target.inverted_safe() @ rest_source)
    return result


def compose_transform(parent, local):
    """Compose TRS like Unreal's FTransform, without introducing matrix shear."""
    pt, pr, ps = parent.decompose()
    lt, lr, ls = local.decompose()
    return Matrix.LocRotScale(
        pt + pr @ Vector(tuple(a * b for a, b in zip(ps, lt))),
        pr @ lr, Vector(tuple(a * b for a, b in zip(ps, ls))))


def relative_transform(parent, world):
    pt, pr, ps = parent.decompose()
    wt, wr, ws = world.decompose()
    if any(abs(value) < 1e-8 for value in ps):
        raise ValueError('Cannot export animation with a zero-scale parent bone')
    offset = pr.inverted() @ (wt - pt)
    return Matrix.LocRotScale(
        Vector(tuple(a / b for a, b in zip(offset, ps))),
        pr.inverted() @ wr, Vector(tuple(a / b for a, b in zip(ws, ps))))


def aimed_donor_world(parent_world, donor_local, child_local, origin, target):
    """The donor bone's orientation and scale under parent_world, moved to origin and swung only as
    far as needed to point at target."""
    donor_world = compose_transform(parent_world, donor_local)
    _dt, dr, ds = donor_world.decompose()
    reach = dr @ Vector(tuple(a * b for a, b in zip(ds, child_local.to_translation())))
    wanted = target - origin
    if reach.length < 1e-6 or wanted.length < 1e-6:
        return Matrix.LocRotScale(origin, dr, ds)
    return Matrix.LocRotScale(origin, reach.rotation_difference(wanted) @ dr, ds)


def solve_armature(order, relatives, original_basis, reversed_world, types, base=IDENTITY, aim_chain=None):
    """Return (worlds, basis) per bone; mapped bones take the edited pose.

    aim_chain maps a bone to the child it points at. Those bones keep the donor's local twist and
    scale, take their position from the rig, and only swing to follow the edited child joint.
    """
    worlds = {}
    basis = {}
    aim_chain = aim_chain or {}
    for bone in order:
        name = bone.name
        parent_world = worlds[bone.parent.name] if bone.parent else IDENTITY
        original = original_basis[name]
        child = aim_chain.get(name)
        if name in reversed_world and child in reversed_world:
            world = aimed_donor_world(
                parent_world, relatives[name] @ original, relatives[child] @ original_basis[child],
                (base @ reversed_world[name]).to_translation(), (base @ reversed_world[child]).to_translation())
            local = relatives[name].inverted_safe() @ relative_transform(parent_world, world)
            basis[name] = Matrix.LocRotScale(*local.decompose())
        elif name in reversed_world:
            local = relatives[name].inverted_safe() @ relative_transform(
                parent_world, base @ reversed_world[name])
            # Mapping kinds govern retarget input, not export: the evaluated pose may include IK stretch
            # or translated controls, which must survive the bake as well as rotation.
            basis[name] = Matrix.LocRotScale(*local.decompose())
        else:
            basis[name] = original.copy()
        worlds[name] = compose_transform(parent_world, relatives[name] @ basis[name])
    return worlds, basis


@contextmanager
def continuous_ik_twist(rig):
    """Unwrap Rigify snap twists for subframe baking without editing the artist's action."""
    animation = rig.animation_data
    action = animation.action if animation else None
    slot = animation.action_slot if action else None
    paths = {
        control.path_from_id('rotation_euler')
        for _parent, name, _fk in IK_BASE_CONTROLS
        if (control := rig.pose.bones.get(name)) is not None
        and control.rotation_mode not in {'QUATERNION', 'AXIS_ANGLE'}
    }
    wrapped = {
        curve.data_path for curve in action_slot_curves(action, slot)
        if not curve.mute and curve.data_path in paths and curve.array_index == 1
        and any(abs(b.co.y - a.co.y) > math.pi
                for a, b in zip(curve.keyframe_points, list(curve.keyframe_points)[1:]))
    } if action else set()
    if not wrapped:
        yield
        return
    temporary = action.copy()
    try:
        temporary_slot = temporary.slots[list(action.slots).index(slot)]
        for curve in action_slot_curves(temporary, temporary_slot):
            if curve.data_path not in wrapped or curve.array_index != 1:
                continue
            previous = None
            for key in curve.keyframe_points:
                value = key.co.y
                angle = value if previous is None else previous + math.remainder(value - previous, math.tau)
                offset = angle - value
                left, right = key.handle_left.copy(), key.handle_right.copy()
                key.co.y = angle
                left.y += offset
                right.y += offset
                key.handle_left, key.handle_right = left, right
                previous = angle
            curve.update()
        animation.action = temporary
        animation.action_slot = temporary_slot
        print(f'[Arsenal export] {action.name}: unwrapped IK twist for subframe sampling '
              '(source keys unchanged)', flush=True)
        yield
    finally:
        animation.action = action
        animation.action_slot = slot
        bpy.data.actions.remove(temporary)


def sample_rig(context, rig, backup, mapping, frames, ik_bases=None):
    entries = deformation_entries(rig, backup, mapping)
    types = {source: kind for _target, source, kind in mapping}
    rows = []
    with continuous_ik_twist(rig):
        for frame in frames:
            context.scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
            apply_ik_bases(ik_bases, frame)
            context.view_layer.update()
            rows.append(read_reversed_worlds(rig, backup, entries))
    return rows, types


def channel_values(basis_series, rotation_mode):
    locations = [basis.to_translation() for basis in basis_series]
    scales = [basis.to_scale() for basis in basis_series]
    rotations = []
    previous = None
    for basis in basis_series:
        quaternion = basis.to_quaternion()
        if rotation_mode == 'QUATERNION':
            if previous is not None:
                quaternion.make_compatible(previous)
            previous = quaternion
            rotations.append(tuple(quaternion))
        else:
            euler = quaternion.to_euler(rotation_mode, previous) if previous is not None else quaternion.to_euler(rotation_mode)
            previous = euler
            rotations.append(tuple(euler))
    return locations, rotations, scales


def add_curve(action, datablock, data_path, index, group, frames, values):
    curve = action.fcurve_ensure_for_datablock(datablock, data_path, index=index, group_name=group)
    curve.keyframe_points.add(len(frames))
    curve.keyframe_points.foreach_set(
        'co', [value for frame, v in zip(frames, values) for value in (frame, v)])
    curve.keyframe_points[0].interpolation = 'CONSTANT'
    curve.update()


def write_armature_action(armature, name, frames, bone_series, object_series=None):
    """Write the baked action. A leading key one frame before the clip holds the rest pose (identity bone
    transforms): the FBX exporter writes each node's default transform from the pose at the current frame, so
    exporting from that frame gives the file a true rest pose, as the original Unreal exports have."""
    frames = [frames[0] - 1.0] + list(frames)
    armature.animation_data_clear()
    animation_data = armature.animation_data_create()
    action = bpy.data.actions.new(name)
    animation_data.action = action
    animation_data.action_slot = action.slots.new('OBJECT', armature.name)

    for bone_name, basis_series in bone_series.items():
        mode = armature.pose.bones[bone_name].rotation_mode
        if mode == 'AXIS_ANGLE':
            mode = 'QUATERNION'
            armature.pose.bones[bone_name].rotation_mode = mode
        locations, rotations, scales = channel_values([Matrix.Identity(4)] + list(basis_series), mode)
        rotation_property = 'rotation_quaternion' if mode == 'QUATERNION' else 'rotation_euler'
        for prop, series, count in (
                ('location', locations, 3),
                (rotation_property, rotations, len(rotations[0])),
                ('scale', scales, 3)):
            for index in range(count):
                add_curve(action, armature, f'pose.bones["{bone_name}"].{prop}', index,
                          bone_name, frames, [value[index] for value in series])

    if object_series:
        armature.rotation_mode = 'XYZ'
        locations, rotations, scales = channel_values([object_series[0]] + list(object_series), 'XYZ')
        for prop, series in (('location', locations), ('rotation_euler', rotations), ('scale', scales)):
            for index in range(3):
                add_curve(action, armature, prop, index, 'Object Transforms',
                          frames, [value[index] for value in series])
    return action


def export_fbx(context, armature, filepath):
    for obj in context.scene.objects:
        obj.select_set(obj == armature)
    context.view_layer.objects.active = armature
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    partial = os.path.splitext(filepath)[0] + '.partial.fbx'
    try:
        bpy.ops.export_scene.fbx(
            filepath=partial,
            use_selection=True,
            object_types={'ARMATURE'},
            bake_anim=True,
            bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_simplify_factor=0.0,
            bake_anim_step=1.0 / BAKE_SUBSTEPS,
            add_leaf_bones=False,
            armature_nodetype='ROOT',
            primary_bone_axis='Y',
            secondary_bone_axis='X',
            axis_forward='Y',
            axis_up='Z',
            global_scale=0.01,
            apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_NONE',
            path_mode='AUTO',
        )
        os.replace(partial, filepath)
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def export_action(context, rig, backup, mapping, action, slot, outputs):
    (_, player_template, player_target), (_, weapon_template, weapon_target) = outputs
    animation_data = rig.animation_data_create()
    animation_data.action = action
    animation_data.action_slot = slot
    first = math.floor(action.frame_range[0])
    last = math.ceil(action.frame_range[1])
    frames_in = [first + step / BAKE_SUBSTEPS for step in range((last - first) * BAKE_SUBSTEPS + 1)]
    frames_out = [float(frame - first) for frame in frames_in]
    ik_bases = solve_ik_bases(
        context, rig, ik_base_fallbacks(rig, keyed_pose_channels(action, slot)), first, last)

    imported = []
    created = []
    try:
        player_objects, player_actions, player, player_action = importer._import_fbx(player_template)
        imported.append((player_objects, player_actions))
        weapon_objects, weapon_actions, weapon, weapon_action = importer._import_fbx(weapon_template)
        imported.append((weapon_objects, weapon_actions))

        template_first = math.floor(min(player_action.frame_range[0], weapon_action.frame_range[0]))
        template_last = math.ceil(max(player_action.frame_range[1], weapon_action.frame_range[1]))
        if player_target is None or weapon_target is None:
            # A stand-in idle runs for as long as the clip it accompanies (as the importer baked it).
            real_action = weapon_action if player_target is None else player_action
            template_first = math.floor(real_action.frame_range[0])
            template_last = math.ceil(real_action.frame_range[1])
        template_frames = [
            min(max(frame - first + template_first, template_first), template_last)
            for frame in frames_in
        ]
        unique_frames = sorted(set(template_frames))
        player_samples = sample_template(context, player, unique_frames)
        weapon_samples = sample_template(context, weapon, unique_frames)
        player_bone_names = {bone.name for bone in player.data.bones}
        weapon_only_names = {bone.name for bone in weapon.data.bones} - player_bone_names

        reversed_rows, types = sample_rig(context, rig, backup, mapping, frames_in, ik_bases)

        player_order, weapon_order = bone_order(player), bone_order(weapon)
        player_rel, weapon_rel = rest_relatives(player), rest_relatives(weapon)
        socket_worlds = {}
        for frame in unique_frames:
            if frame != math.floor(frame):
                continue
            worlds, _basis = solve_armature(
                player_order, player_rel, player_samples[frame][0], {}, types)
            socket_worlds[frame] = {name: worlds[name] for name in TEMPLATE_SOCKETS if name in worlds}
        player_series = {bone.name: [] for bone in player_order}
        weapon_series = {bone.name: [] for bone in weapon_order}
        object_series = []

        for frame_index, template_frame in enumerate(template_frames):
            player_basis, _ = player_samples[template_frame]
            weapon_basis, weapon_original_world = weapon_samples[template_frame]
            edited = dict(reversed_rows[frame_index])
            # Rigify's unanimated raw-copy sockets are not the game's animated hand sockets.
            # Keep their donor component pose, including compensation for the changed hand axes.
            lower, upper = math.floor(template_frame), math.ceil(template_frame)
            weight = template_frame - lower
            for name, world in socket_worlds[lower].items():
                if name not in edited:
                    a, ar, scale_a = world.decompose()
                    b, br, scale_b = socket_worlds[upper][name].decompose()
                    edited[name] = Matrix.LocRotScale(
                        a.lerp(b, weight), ar.slerp(br, weight), scale_a.lerp(scale_b, weight))

            player_worlds, player_result = solve_armature(
                player_order, player_rel, player_basis,
                {name: world for name, world in edited.items() if name in player_bone_names},
                types, aim_chain=TWIST_LOCKED_CHAIN)
            weapon_world = player_worlds.get('jnt_weapon', weapon_original_world)
            weapon_inverse = weapon_world.inverted_safe()

            weapon_given = {
                name: weapon_inverse @ world for name, world in edited.items()
                if name in weapon_only_names
            }
            for name in player_bone_names:
                if name in weapon.data.bones:
                    weapon_given[name] = weapon_inverse @ player_worlds[name]
            weapon_types = dict(types)
            for name in player_bone_names:
                weapon_types.pop(name, None)
            _worlds, weapon_result = solve_armature(
                weapon_order, weapon_rel, weapon_basis, weapon_given, weapon_types)

            for name, basis in player_result.items():
                player_series[name].append(basis)
            for name, basis in weapon_result.items():
                weapon_series[name].append(basis)
            object_series.append(weapon_world)

        scene = context.scene
        scene.frame_start = 0
        scene.frame_end = int(frames_out[-1])
        created.append(write_armature_action(player, action.name, frames_out, player_series))
        created.append(write_armature_action(weapon, action.name, frames_out, weapon_series, object_series))
        scene.frame_set(-1)
        for armature, target in ((player, player_target), (weapon, weapon_target)):
            if target is not None:
                export_fbx(context, armature, target)
    finally:
        for objects, actions in reversed(imported):
            importer._remove_imported(objects, actions)
        for new_action in created:
            bpy.data.actions.remove(new_action)
    return [target for target in (player_target, weapon_target) if target is not None]


POSE_CHANNEL_RESTS = b_fun.POSE_CHANNEL_RESTS
POSE_PATH = re.compile(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]\.?(\w+|\["(?:[^"\\]|\\.)*"\])$')
IK_EXPORT_CONTROLS = (
    ('thigh_parent.L', ('foot_ik.L', 'thigh_ik.L', 'thigh_ik_target.L')),
    ('thigh_parent.R', ('foot_ik.R', 'thigh_ik.R', 'thigh_ik_target.R')),
    ('upper_arm_parent.L', ('hand_ik.L', 'upper_arm_ik.L', 'upper_arm_ik_target.L')),
    ('upper_arm_parent.R', ('hand_ik.R', 'upper_arm_ik.R', 'upper_arm_ik_target.R')),
)


def snapshot_pose(rig):
    channels = [(bone, prop, tuple(getattr(bone, prop))) for bone in rig.pose.bones for prop, _rest in POSE_CHANNEL_RESTS]
    switches = [(rig.pose.bones[name], name, rig.pose.bones[name]['IK_FK']) for name in b_fun.ik_prop_bones
                if name in rig.pose.bones and 'IK_FK' in rig.pose.bones[name]]
    return channels, switches


def restore_pose(snapshot):
    channels, switches = snapshot
    for bone, prop, value in channels:
        setattr(bone, prop, value)
    for bone, _name, value in switches:
        bone['IK_FK'] = value


def keyed_pose_channels(action, slot):
    keyed = set()
    for curve in action_slot_curves(action, slot):
        match = POSE_PATH.match(curve.data_path)
        if match:
            keyed.add((bpy.utils.unescape_identifier(match.group(1)), match.group(2)))
    return keyed


def validate_ik_controls(context, rig, action, slot):
    keyed = keyed_pose_channels(action, slot)
    derived = {(control.name, prop) for _parent, control, _fk, props in ik_base_fallbacks(rig, keyed)
               for prop in props}
    controls = []
    for parent_name, control_names in IK_EXPORT_CONTROLS:
        parent = rig.pose.bones.get(parent_name)
        if parent is None or 'IK_FK' not in parent:
            continue
        for control_name in control_names:
            control = rig.pose.bones.get(control_name)
            if control is None:
                continue
            rotation = {
                'QUATERNION': 'rotation_quaternion',
                'AXIS_ANGLE': 'rotation_axis_angle',
            }.get(control.rotation_mode, 'rotation_euler')
            missing = [
                (prop, rest) for prop, rest in POSE_CHANNEL_RESTS
                if prop in ('location', rotation, 'scale') and (control_name, prop) not in keyed
            ]
            if missing:
                controls.append((parent, control, missing))
    if not controls:
        return
    for frame in range(math.floor(action.frame_range[0]), math.ceil(action.frame_range[1]) + 1):
        context.scene.frame_set(frame)
        context.view_layer.update()
        for parent, control, missing in controls:
            if parent['IK_FK'] >= 1.0 - 1e-5:
                continue
            if ('_ik_target.' in control.name
                    and 'pole_vector' in parent and not parent['pole_vector']):
                continue
            pole = parent.get('pole_vector')
            # Rigify's IK->FK snap leaves tiny shoulder/hip offsets that export treats as rest.
            tolerance = {'location': max(1e-5, 1e-4 * control.length)} if any(
                control.name == name for _p, name, _f in IK_BASE_CONTROLS) else {}
            unkeyed = [
                prop for prop, rest in missing
                if not ((control.name, prop) in derived and (prop == 'scale' or not pole))
                and any(abs(value - default) > tolerance.get(prop, 1e-5)
                       for value, default in zip(getattr(control, prop), rest))
            ]
            if unkeyed:
                raise RuntimeError(
                    f'{control.name} uses IK at frame {frame}, but its non-rest '
                    f'{", ".join(unkeyed)} is not keyed in "{action.name}". '
                    'Key this control\'s Location, Rotation and Scale in this action before exporting; '
                    'otherwise the export resets its offset and differs from the viewport.')


def rest_unkeyed_channels(rig, action, slot):
    """Export treats unkeyed channels as rest (and an unkeyed IK/FK switch as FK)."""
    keyed = keyed_pose_channels(action, slot)
    b_fun.rest_pose_channels(rig, keyed)


IK_BASE_CONTROLS = (
    ('thigh_parent.L', 'thigh_ik.L', 'thigh_fk.L'),
    ('thigh_parent.R', 'thigh_ik.R', 'thigh_fk.R'),
    ('upper_arm_parent.L', 'upper_arm_ik.L', 'upper_arm_fk.L'),
    ('upper_arm_parent.R', 'upper_arm_ik.R', 'upper_arm_fk.R'),
)
TWIST_TOLERANCE = 1e-3
TWIST_ITERATIONS = 8


def ik_base_fallbacks(rig, keyed):
    """IK base controls whose unkeyed twist/scale export derives from the FK limb.

    Artists key the IK hand but rarely the IK upper arm, whose leftover viewport value
    is just whatever the last played action set. Export follows Rigify's IK->FK snap
    instead, which is also what keyed clips contain after Snap IK->FK (Action)."""
    result = []
    for parent_name, control_name, fk_name in IK_BASE_CONTROLS:
        parent = rig.pose.bones.get(parent_name)
        control = rig.pose.bones.get(control_name)
        fk = rig.pose.bones.get(fk_name)
        if parent is None or control is None or fk is None or 'IK_FK' not in parent:
            continue
        if control.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
            continue
        props = tuple(prop for prop in ('rotation_euler', 'scale') if (control_name, prop) not in keyed)
        if props:
            result.append((parent, control, fk, props))
    return result


def _ik_chain_end(control):
    for child in control.children:
        if any(constraint.type == 'IK' and constraint.chain_count == 2 for constraint in child.constraints):
            return child
    return None


def _twist_error(control, end, desired):
    """Signed angle about the shoulder-to-wrist axis from the IK upper arm to the FK direction."""
    axis = end.tail - control.head
    if axis.length < 1e-6:
        return 0.0
    axis.normalize()
    current = control.vector - axis * control.vector.dot(axis)
    wanted = desired - axis * desired.dot(axis)
    if current.length < 1e-6 or wanted.length < 1e-6:
        return 0.0  # straight limb: every twist gives the same direction
    return math.atan2(axis.dot(current.cross(wanted)), current.dot(wanted))


def _solve_twist(view_layer, control, axis):
    """Rigify's correct_rotation: twist about Y until the IK result points along the FK bone.

    Slow search used when the secant solve in _solve_twists does not converge."""
    def cost(angle):
        control.rotation_euler[1] = angle
        view_layer.update()
        return -control.vector.normalized().dot(axis)

    step = math.tau / 36
    best = min(range(36), key=lambda index: cost(index * step)) * step
    low, high = best - step, best + step
    ratio = (math.sqrt(5) - 1) / 2
    a, b = high - ratio * (high - low), low + ratio * (high - low)
    cost_a, cost_b = cost(a), cost(b)
    while high - low > TWIST_TOLERANCE:
        if cost_a < cost_b:
            high, b, cost_b = b, a, cost_a
            a = high - ratio * (high - low)
            cost_a = cost(a)
        else:
            low, a, cost_a = a, b, cost_b
            b = low + ratio * (high - low)
            cost_b = cost(b)
    angle = (low + high) / 2
    cost(angle)
    return angle


def _solve_twists(view_layer, limbs, starts):
    """Secant solve of every limb's twist together, so each rig update serves all limbs.

    limbs are (control, chain_end, fk); returns {control name: twist}."""
    state = {}
    stuck = []
    for control, end, fk in limbs:
        control.rotation_euler = (0.0, starts.get(control.name, 0.0), 0.0)
        if end is None:
            stuck.append((control, end, fk, None))
        else:
            state[control.name] = [control, end, fk, None]
    view_layer.update()
    results = {}
    for _iteration in range(TWIST_ITERATIONS):
        moved = False
        for name, entry in list(state.items()):
            control, end, fk, previous = entry
            angle = control.rotation_euler[1]
            error = _twist_error(control, end, fk.matrix.to_3x3().col[1].normalized())
            if abs(error) <= TWIST_TOLERANCE:
                results[name] = angle
                del state[name]
                continue
            if previous is None:
                axis = end.tail - control.head
                step = error if control.y_axis.dot(axis) >= 0.0 else -error
            else:
                slope = (error - previous[1]) / (angle - previous[0]) if angle != previous[0] else 0.0
                if abs(slope) < 1e-3:
                    stuck.append(state.pop(name))
                    continue
                step = -error / slope
            entry[3] = (angle, error)
            control.rotation_euler[1] = angle + max(-math.pi, min(math.pi, step))
            moved = True
        if not moved:
            break
        view_layer.update()
    for control, _end, fk, _previous in stuck + list(state.values()):
        axis = fk.matrix.to_3x3().col[1].normalized()
        results[control.name] = _solve_twist(view_layer, control, axis)
    return results


def _solve_scales(view_layer, limbs):
    """Rigify's correct_scale for every limb together: match each IK base's pose scale to FK."""
    for _attempt in range(4):
        moved = False
        for control, fk in limbs:
            target = fk.matrix.to_scale()
            current = control.matrix.to_scale()
            if all(abs(c - t) <= 1e-5 * abs(t) for c, t in zip(current, target)):
                continue
            control.scale = [s * t / c for s, t, c in zip(control.scale, target, current)]
            moved = True
        if not moved:
            break
        view_layer.update()
    return {control.name: tuple(control.scale) for control, _fk in limbs}


def solve_ik_bases(context, rig, fallbacks, first, last):
    """Per-frame twist/scale for each fallback limb that uses IK somewhere in [first, last]."""
    scene, view_layer = context.scene, context.view_layer
    if not fallbacks:
        return {}
    frames = range(first, last + 1)
    used = set()
    for frame in frames:
        scene.frame_set(frame)
        used.update(index for index, (parent, *_rest) in enumerate(fallbacks)
                    if parent['IK_FK'] < 1.0 - 1e-5)
    active = [fallback for index, fallback in enumerate(fallbacks) if index in used]
    if not active:
        return {}
    values = {}
    starts = {}
    for frame in frames:
        scene.frame_set(frame)
        twists, scales = [], []
        for parent, control, fk, props in active:
            if 'scale' in props:
                control.scale = (1.0, 1.0, 1.0)
                scales.append((control, fk))
            if 'rotation_euler' in props:
                if parent.get('pole_vector'):
                    control.rotation_euler = (0.0, 0.0, 0.0)
                else:
                    twists.append((control, _ik_chain_end(control), fk))
        if twists:
            starts.update(_solve_twists(view_layer, twists, starts))
        else:
            view_layer.update()
        solved_scales = _solve_scales(view_layer, scales)
        twisted = {control.name for control, _end, _fk in twists}
        row = []
        for _parent, control, _fk, props in active:
            twist = scale = None
            if 'rotation_euler' in props:
                twist = starts[control.name] if control.name in twisted else 0.0
            if 'scale' in props:
                scale = solved_scales[control.name]
            row.append((control, twist, scale))
        values[frame] = row
    return values


def apply_ik_bases(values, frame):
    if not values:
        return
    lower = math.floor(frame)
    upper = min(math.ceil(frame), max(values))
    weight = frame - lower
    for (control, twist_a, scale_a), (_control, twist_b, scale_b) in zip(values[lower], values[upper]):
        if twist_a is not None:
            control.rotation_euler[1] = twist_a + (twist_b - twist_a) * weight
        if scale_a is not None:
            control.scale = [a + (b - a) * weight for a, b in zip(scale_a, scale_b)]


def run_exports(context, rig, backup, plans, cache=None):
    """Export each plan; with a cache, actions whose inputs and FBXs are unchanged are skipped
    (their files are still returned, so the import manifest stays complete)."""
    if deformation_preview_issues(rig):
        raise RuntimeError(
            'Viewport uses unbound deform groups or Blender-only B-bones. '
            'Run Repair Deformation Preview in the Export panel, then export again.')
    scene = context.scene
    saved = (
        scene.unit_settings.scale_length,
        scene.render.fps, scene.render.fps_base,
        scene.frame_start, scene.frame_end, scene.frame_current, scene.frame_subframe,
        rig.animation_data.action if rig.animation_data else None,
        rig.animation_data.action_slot if rig.animation_data else None,
        context.view_layer.objects.active,
    )
    written = []
    failures = []
    pose = snapshot_pose(rig)
    mapping, _missing = resolve_animation_mapping(backup, rig)
    if not mapping:
        raise RuntimeError('No animation bone mappings matched the source skeleton and Rigify rig.')
    try:
        scene.unit_settings.scale_length = 1.0
        with b_fun.forced_pose_position(rig, backup), Progress(context, len(plans), 'Exporting') as progress:
            for action, slot, outputs in plans:
                progress.step(action.name)
                try:
                    fingerprint = None
                    if cache is not None:
                        fingerprint = cache.fingerprint(action, slot, outputs, keyed_pose_channels(action, slot))
                        if cache.is_current(outputs, fingerprint):
                            print(f'[Arsenal export] {action.name}: unchanged, kept the existing FBXs', flush=True)
                            written.extend(target for _kind, _template, target in outputs if target is not None)
                            cache.unchanged += 1
                            continue
                        cache.forget(outputs)
                    rig.animation_data.action = action
                    rig.animation_data.action_slot = slot
                    validate_ik_controls(context, rig, action, slot)
                    rest_unkeyed_channels(rig, action, slot)
                    written.extend(export_action(context, rig, backup, mapping, action, slot, outputs))
                    if cache is not None:
                        cache.record(action.name, outputs, fingerprint)
                except Exception as error:
                    print(f'[Arsenal export] FAILED {action.name}: {error}', flush=True)
                    traceback.print_exc()
                    failures.append((action.name, str(error)))
    finally:
        restore_pose(pose)
        (scale, fps, fps_base, frame_start, frame_end, frame_current, frame_subframe,
         rig_action, rig_slot, active) = saved
        scene.unit_settings.scale_length = scale
        scene.render.fps = fps
        scene.render.fps_base = fps_base
        scene.frame_start = frame_start
        scene.frame_end = frame_end
        if rig.animation_data:
            rig.animation_data.action = rig_action
            if rig_action:
                rig.animation_data.action_slot = rig_slot
        scene.frame_set(frame_current, subframe=frame_subframe)
        for obj in scene.objects:
            obj.select_set(obj == active)
        context.view_layer.objects.active = active
    return written, failures


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class ARSENAL_OT_RepairDeformationPreview(bpy.types.Operator):
    bl_idname = 'object.arsenal_repair_deformation_preview'
    bl_label = 'Repair Deformation Preview'
    bl_description = (
        'Bind missing wrist helpers, use one segment per game bone and give the upper arm '
        'its full twist; does not change animation keys')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig, _backup = find_export_rig(context)
        return rig is not None

    def execute(self, context):
        from .convert_to_rigify import tidy_generated_rig

        rig, _backup = find_export_rig(context)
        tidy_generated_rig(context, rig)
        issues = deformation_preview_issues(rig)
        if issues:
            self.report({'ERROR'}, 'Unbound deformation groups remain: ' + ', '.join(issues))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Repaired deformation preview; animation keys are unchanged. Save your blend.')
        return {'FINISHED'}


class ARSENAL_ExportAction(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    enabled: bpy.props.BoolProperty(name='Export', default=True)
    template: bpy.props.StringProperty(
        name='Template',
        description='Original animation to use as the base (skeleton and unmapped bones). '
                    'Leave empty to use the animation with the same name, or "idle" for new actions')
    folder: bpy.props.StringProperty(
        name='Folder',
        description='Category folder below the weapon folder, e.g. Reload/TwoHands. '
                    'Leave empty to copy the template folder')
    status: bpy.props.StringProperty()


def weapon_name(scene):
    """The weapon's file/folder name: its English display name, lowercased with only letters and digits."""
    for entry in scene.arsenal_cfg.texts:
        if entry.language == 'en':
            return re.sub(r'[^a-z0-9]', '', entry.name.lower())
    return ''


def mod_mount(export):
    """The Unreal mount path of the mod (/<Mod Name>), or '' when no Mod Name is set."""
    name = export.unreal_mount.strip().strip('/')
    return '/' + name if name else ''


def static_category(scene):
    from .weapon_presets import PRESETS
    return PRESETS[scene.arsenal_cfg.setup_template]['category']


class ARSENAL_ExportProps(bpy.types.PropertyGroup):
    output_folder: bpy.props.StringProperty(name='Output Folder', subtype='DIR_PATH')
    static_category: bpy.props.StringProperty(
        name='Weapon Category',
        description='Weapon class folder for the static meshes: _Stalker_2/weapons/<category>/p_<weapon>/AnimMesh. '
                    'The weapon name comes from the main weapon mesh object',
        default='pistol')
    actions: bpy.props.CollectionProperty(type=ARSENAL_ExportAction)
    unreal_mount: bpy.props.StringProperty(
        name='Mod Name',
        description='The name of your mod in ZoneKit (the folder the mod is in, e.g. MonkeyMod). '
                    'It is also the Unreal mount path /<Mod Name> and the ModGameData/<Mod Name> folder',
        default='')
    active_index: bpy.props.IntProperty()
    reexport_all: bpy.props.BoolProperty(
        name='Re-export Unchanged Animations',
        description='Bake every animation again, even those whose keys, rig, donor files and FBXs are '
                    'unchanged since the last export. Leave off to export only what changed',
        default=False)
    summary: bpy.props.StringProperty(default='Export checks and writes all matching rig animations automatically.')


def _settings(context):
    return context.scene.arsenal_export, context.scene.stalker2_animation_importer


def _export_basics(context):
    export, importer_settings = _settings(context)
    rig, backup = find_export_rig(context)
    if not rig:
        raise RuntimeError('Select the generated Rigify rig (with its retarget backup).')
    new_name = weapon_name(context.scene)
    if not new_name:
        raise RuntimeError('Enter the weapon\'s English Name (4. Create Your Custom Weapon > Name & Description); '
                           'the file names are made from it.')
    if INVALID_FILENAME_CHARS.search(new_name):
        raise RuntimeError('The weapon\'s English Name makes an invalid file name.')
    output_root = bpy.path.abspath(export.output_folder).strip()
    if not output_root:
        raise RuntimeError('Choose an output folder.')
    library_root = bpy.path.abspath(importer_settings.animation_root).strip()
    return export, importer_settings, rig, backup, new_name, output_root, library_root


SKIPPED_STATUS = 'Skipped'


def skipped_actions(export):
    return [item for item in getattr(export, 'actions', ()) if item.status.startswith(SKIPPED_STATUS)]


def _build_plans(context):
    export, importer_settings, rig, backup, new_name, output_root, library_root = _export_basics(context)
    old_name = importer_settings.weapon_name.strip()
    pairs, _player_only, _weapon_only, ambiguous = importer._scan_library(library_root, old_name)
    keys = {pair[0].casefold() for pair in pairs}
    pairs_by_key = {pair[0].casefold(): pair for pair in pairs}

    plans = []
    problems = 0
    export.actions.clear()
    targets = set()
    for action in exportable_actions(rig):
        item = export.actions.add()
        item.name = action.name
        slot = rig_action_slot(action, rig)
        try:
            if action.name.casefold() in ambiguous:
                raise ValueError(f'Ambiguous donor files for "{action.name}"; remove duplicate donor exports')
            if action.name.casefold() not in keys:
                item.status = (f'{SKIPPED_STATUS}: "{action.name}" does not match an original animation. '
                               'Rename it to the original action name to export it')
                continue
            pair = pairs_by_key[action.name.casefold()]
            if importer.is_variant_pair(pair) and action.get(importer.PAIR_RECORD) != importer.pair_record(pair):
                # Older imports baked this clip against an idle stand-in for the other half.
                item.status = (f'{SKIPPED_STATUS}: "{action.name}" now pairs {importer.pair_record(pair)}; '
                               'delete this action, then import and retarget the animation again to export it')
                continue
            outputs, status = plan_export(
                item.name, '', '', pairs,
                old_name, new_name, output_root, library_root)
            for _kind, _template, target in outputs:
                if target is not None:
                    normalized = os.path.normcase(os.path.abspath(target))
                    if normalized in targets:
                        raise ValueError(f'Multiple actions would write {target}; keep one action per original name')
                    targets.add(normalized)
        except ValueError as error:
            item.status = str(error)
            problems += 1
            continue
        item.status = status
        plans.append((action, slot, outputs))
    return rig, backup, plans, problems


def _build_static_plan(context):
    export, _importer_settings, rig, backup, _new_name, output_root, library_root = _export_basics(context)
    mapping, _missing = resolve_animation_mapping(backup, rig)
    bone_joints = static_mesh.weapon_bone_joints(rig, mapping)
    if not bone_joints:
        raise RuntimeError('No weapon rig bones are mapped to game joints, so there are no static meshes to export.')
    category = static_category(context.scene)
    try:
        _weapon, plan = static_mesh.plan_static_meshes(rig, bone_joints, category, output_root, context.scene)
    except ValueError as error:
        raise RuntimeError(str(error))
    if library_root and any(is_inside(path, library_root) for _bone, _stem, path in plan):
        raise RuntimeError('Output would write into the original library; choose a different output folder.')
    return rig, backup, bone_joints, plan


def _run_animation_export(context):
    from .animation_cache import AnimationCache

    rig, backup, plans, problems = _build_plans(context)
    if problems:
        details = '\n'.join(f'{item.name}: {item.status}' for item in context.scene.arsenal_export.actions
                            if item.status and not item.status.startswith(('Matches an original animation',
                                                                            SKIPPED_STATUS)))
        raise RuntimeError(f'{problems} animation actions cannot be exported:\n{details}')
    if not plans:
        skipped = skipped_actions(getattr(context.scene, 'arsenal_export', None))
        if skipped:
            raise RuntimeError('No rig animation matches an original animation name; skipped: '
                               + ', '.join(item.name for item in skipped))
        raise RuntimeError('No editable rig animations found. Use Retarget Animation in panel 3 first.')
    export = context.scene.arsenal_export
    mapping, _missing = resolve_animation_mapping(backup, rig)
    cache = AnimationCache(bpy.path.abspath(export.output_folder).strip(), context, rig, backup,
                           mapping, BAKE_SUBSTEPS)
    if export.reexport_all:
        cache.entries.clear()
    try:
        written, failures = run_exports(context, rig, backup, plans, cache)
    finally:
        cache.save()
    return written, failures, len(plans), cache.unchanged


def _run_static_export(context):
    export = context.scene.arsenal_export
    rig, backup, bone_joints, _plan = _build_static_plan(context)
    written, skipped = static_mesh.export_static_meshes(
        context, rig, backup, bone_joints,
        static_category(context.scene), bpy.path.abspath(export.output_folder).strip())
    if not written:
        raise RuntimeError('No weapon geometry is weighted to the mapped weapon bones.')
    written.append(export_skeleton.export_weapon_skeleton(context))
    return written, skipped


class ARSENAL_OT_ExportValidate(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_validate'
    bl_label = 'Validate'
    bl_description = 'Check the settings and show the files that would be written'

    def execute(self, context):
        try:
            _rig, _backup, plans, problems = _build_plans(context)
            _rig, _backup, _bone_joints, static_plan = _build_static_plan(context)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        for action, _slot, outputs in plans:
            for _kind, _template, target in outputs:
                if target is not None:
                    print(f'[Arsenal export] {action.name}: {target}')
        for bone_name, _stem, target in static_plan:
            print(f'[Arsenal export] static mesh {bone_name}: {target}')
        try:
            from . import export_check, weapon_cfg
            for problem in export_check.name_warnings(weapon_cfg.build_context(context)):
                self.report({'WARNING'}, problem)
        except Exception as error:
            self.report({'WARNING'}, f'Name check skipped: {error}')
        skipped = skipped_actions(context.scene.arsenal_export)
        for item in skipped:
            self.report({'WARNING'}, f'{item.name}: {item.status}')
        context.scene.arsenal_export.summary = (
            f'{len(plans)} animations ready, {len(skipped)} skipped, {problems} with problems; '
            f'{len(static_plan)} static meshes planned.')
        self.report({'INFO'}, context.scene.arsenal_export.summary)
        return {'FINISHED'}


def _report_animation(operator, context, result):
    written, failures, count, unchanged = result
    for name, message in failures:
        for item in context.scene.arsenal_export.actions:
            if item.name == name:
                item.status = f'Export failed: {message}'
        report(operator, {'WARNING'}, f'{name}: {message}')
    skipped = skipped_actions(context.scene.arsenal_export)
    for item in skipped:
        report(operator, {'WARNING'}, f'{item.name}: {item.status}')
    kept = f', {unchanged} unchanged and kept' if unchanged else ''
    ignored = f', {len(skipped)} skipped' if skipped else ''
    return (f'{len(written)} animation files for {count - len(failures)} actions '
            f'({len(failures)} failed{kept}{ignored})', bool(failures))


def _report_static(operator, result):
    written, skipped = result
    for label in skipped:
        operator.report({'WARNING'}, f'No geometry for "{label}"; no static mesh written for it.')
    return f'{len(written)} static meshes', bool(skipped)


class ARSENAL_OT_ExportAllRun(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_all'
    bl_label = 'Export All'
    bl_description = ('Check and export all matching animations, meshes, weapon settings and inventory images. '
                      'Copy the new ZoneKit import script path; fix any reported errors before continuing')

    @completion('Export')
    def execute(self, context):
        export = context.scene.arsenal_export
        parts = []
        warn = False
        written = []
        context.window_manager.clipboard = ''
        try:
            rig, backup, bone_joints, _plan = _build_static_plan(context)
            from . import weapon_cfg, export_check, weapon_sockets
            # Fail before writing anything: a late failure leaves new files beside an old import script.
            weapon_sockets.check_markers(context.scene)
            cfg_info = weapon_cfg.build_context(context)
            static_mesh.world_mesh_sockets(
                context.scene, rig, backup, bone_joints, cfg_info['magazines'],
                cfg_info['world_mesh'].split("'")[1].split('.')[0])
            from . import scope_reticles
            scope_reticles.check_reticles(cfg_info)
            for problem in export_check.name_warnings(cfg_info):
                report(self, {'WARNING'}, problem)
                warn = True
            result = _run_animation_export(context)
            animation_written = list(result[0])
            written += animation_written
            summary, failed = _report_animation(self, context, result)
            parts.append(summary)
            if failed:
                names = ', '.join(name for name, _message in result[1])
                details = '\n'.join(f'{name}: {message}' for name, message in result[1])
                raise RuntimeError(
                    f'Animation export failed for {names}. Fix the reported animation errors and export again. '
                    'No new Unreal import script was generated. Do not run an older import script: '
                    f'it may import stale FBXs left by a previous export.\n{details}')
            result = _run_static_export(context)
            written += result[0]
            summary, skipped = _report_static(self, result)
            parts.append(summary)
            warn = warn or skipped
            written_cfgs, cfg_info = weapon_cfg.export_cfg_files(self, context)
            parts.append('the CFG files')
            problems = export_check.path_warnings(cfg_info, written_cfgs, written + list(written_cfgs))
            for problem in problems:
                report(self, {'WARNING'}, problem)
                print(f'[Arsenal export] CHECK: {problem}')
            warn = warn or bool(problems)
            from . import export_unreal
            script_path, manifest = export_unreal.write_unreal_import(context, animation_paths=animation_written)
            parts.append('the Unreal import script')
            if manifest['game_materials']:
                print('[Arsenal export] Slots left to the game\'s own materials: ' + ', '.join(manifest['game_materials']))
            context.window_manager.clipboard = script_path
        except Exception as error:
            export.summary = f'Export blocked: {error}'
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        export.summary = 'Wrote ' + ' and '.join(parts) + '.'
        report(self, {'WARNING'} if warn else {'INFO'},
                    export.summary + ' The import script path is on the clipboard: paste it into the ZoneKit '
                    'Python bar.')
        return {'FINISHED'}


class ARSENAL_PT_ExportPanel(bpy.types.Panel):
    bl_label = '5. Export'
    bl_idname = 'ARSENAL_PT_ExportPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        export = context.scene.arsenal_export
        layout.prop(export, 'output_folder')
        layout.label(text='All matching animations are exported; unchanged ones are kept.')
        layout.prop(export, 'reexport_all')
        layout.label(text=export.summary)
        rig, _backup = find_export_rig(context)
        if rig and deformation_preview_issues(rig):
            layout.label(text='Viewport deformation needs repair', icon='ERROR')
            layout.operator('object.arsenal_repair_deformation_preview', icon='MOD_ARMATURE')
        layout.operator('object.arsenal_export_all', icon='EXPORT')


CLASSES = (
    ARSENAL_OT_RepairDeformationPreview,
    ARSENAL_ExportAction,
    ARSENAL_ExportProps,
    ARSENAL_OT_ExportValidate,
    ARSENAL_OT_ExportAllRun,
    ARSENAL_PT_ExportPanel,
)
