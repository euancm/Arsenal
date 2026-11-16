import json
import math
import os
import re
import uuid

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import import_weapon
from .notifications import completion, report
from .unreal_import import socket_transforms_equal, validate_socket_transform, validate_weapon_sockets

REFLECTION = Matrix.Diagonal((1, -1, 1, 1))
REFERENCE_SPACE = 'arsenal_socket_reference_space'
FRAME_VERSION = 1


def socket_matrix(transform):
    validate_socket_transform(transform)
    roll, pitch, yaw = map(math.radians, transform['rotation'])
    rotation = Euler((-roll, -pitch, yaw), 'XYZ').to_matrix().to_4x4()
    return REFLECTION @ (Matrix.Translation(transform['location']) @ rotation
                         @ Matrix.Diagonal((*transform['scale'], 1))) @ REFLECTION


def checked_matrix(matrix):
    location, rotation, scale = matrix.decompose()
    if (any(not math.isfinite(value) for row in matrix for value in row)
            or matrix.determinant() <= 0 or min(scale) <= 0
            or max(scale) - min(scale) > 0.00001
            or max(abs(a - b) for row, other in zip(matrix, Matrix.LocRotScale(location, rotation, scale))
                   for a, b in zip(row, other)) > 0.00001):
        raise RuntimeError('Socket transforms cannot contain shear, mirroring or nonuniform scale.')
    return location, rotation, scale


def matrix_socket(matrix):
    location, rotation, scale = checked_matrix(REFLECTION @ matrix @ REFLECTION)
    roll, pitch, yaw = rotation.to_euler('XYZ')
    return {'location': list(location), 'rotation': list(map(math.degrees, (-roll, -pitch, yaw))),
            'scale': list(scale)}


def frame_matrix(entry):
    return Matrix([entry.frame[i:i + 4] for i in range(0, 16, 4)])


def store_frame(entry, matrix):
    entry.frame = [value for row in matrix for value in row]


def reference_space(rig):
    stored = rig.get(REFERENCE_SPACE)
    if stored is not None:
        matrix = Matrix([stored[i:i + 4] for i in range(0, 16, 4)])
        checked_matrix(matrix)
        return matrix
    from . import convert_to_rigify
    backup_id = rig.get(convert_to_rigify.RETARGET_WEAPON_BACKUP_ID)
    if not backup_id:
        if rig.data.get('rig_id'):
            raise RuntimeError('The Rigify weapon source backup is missing; cannot resolve socket placement.')
        return Matrix.Identity(4)
    backups = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE'
               and obj.get(convert_to_rigify.RETARGET_BACKUP_MARKER)
               and obj.get(convert_to_rigify.RETARGET_BACKUP_ID) == backup_id]
    if len(backups) != 1:
        raise RuntimeError('Cannot identify the original weapon backup for socket placement.')
    frames = []
    for source in backups[0].data.bones:
        target = rig.data.bones.get(source.name)
        if source.name == import_weapon.ROOT_BONE or target is None:
            continue
        if source.length <= 0 or target.length <= 0:
            raise RuntimeError(f'Cannot resolve socket reference space from bone {source.name}.')
        # Merged child bones preserve the donor frame; Rigify's Weapon control does not.
        scale = Matrix.Scale(target.length / source.length, 4)
        frames.append(target.matrix_local @ scale @ source.matrix_local.inverted())
    if not frames or any(max(abs(a - b) for row, other in zip(frames[0], frame)
                             for a, b in zip(row, other)) > 0.001 for frame in frames[1:]):
        raise RuntimeError('Weapon rest bones no longer match their source backup; cannot resolve socket placement.')
    checked_matrix(frames[0])
    return frames[0]


def bone_name(game_bone, rig=None):
    name = import_weapon.rig_bone_name(game_bone)
    # FBX represents the component root as the armature object, not a Blender bone.
    if rig is not None and name not in rig.data.bones and game_bone == rig.get('arsenal_component_root'):
        return import_weapon.ROOT_BONE
    return name


def bone_tail(rig, name):
    return Matrix.Translation((0, rig.data.bones[name].length, 0))


def reference_matrix(record):
    value = record.get('bone_transform')
    if not isinstance(value, dict):
        raise RuntimeError('Socket reference transforms are missing. Regenerate and run the ZoneKit setup script.')
    quaternion = value.get('quaternion')
    if (not isinstance(quaternion, list) or len(quaternion) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in quaternion)
            or abs(sum(v * v for v in quaternion) - 1) > 0.00001):
        raise RuntimeError('Invalid socket reference bone orientation.')
    validate_socket_transform({'location': value.get('location'), 'rotation': [0, 0, 0],
                               'scale': value.get('scale')})
    x, y, z, w = quaternion
    matrix = Matrix.LocRotScale(Vector(value['location']), Quaternion((w, x, y, z)), Vector(value['scale']))
    checked_matrix(matrix)
    return REFLECTION @ matrix @ REFLECTION


def catalogue_mesh(path, source_mesh='', donor_name=''):
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if (not isinstance(data, dict) or type(data.get('version')) is not int
            or data['version'] != 1 or data.get('units') != 'cm'
            or not isinstance(data.get('meshes'), list)):
        raise RuntimeError('Regenerate the ZoneKit setup script to export the complete socket catalogue.')
    for mesh in data['meshes']:
        if (not isinstance(mesh, dict) or not isinstance(mesh.get('mesh'), str)
                or not isinstance(mesh.get('sockets'), list)):
            raise RuntimeError('Invalid source mesh in the socket catalogue.')
        for record in mesh['sockets']:
            if (not isinstance(record, dict) or type(record.get('effective')) is not bool
                    or not {'name', 'bone', 'owner', 'location', 'rotation', 'scale'} <= record.keys()):
                raise RuntimeError('Invalid socket record in the donor catalogue.')
    meshes = data['meshes']
    if source_mesh:
        meshes = [mesh for mesh in meshes if mesh['mesh'] == source_mesh]
    elif donor_name:
        meshes = [mesh for mesh in meshes
                  if mesh['mesh'].rsplit('/', 1)[-1].casefold() == f'SK_{donor_name}'.casefold()]
    if len(meshes) != 1:
        raise RuntimeError('The socket catalogue does not identify exactly one imported weapon mesh.')
    return meshes[0]


def socket_group(name):
    lowered = name.casefold()
    if lowered.endswith('socket') and any(part in lowered for part in ('scope', 'rail', 'grip', 'silencer', 'laser')):
        return 'Mount'
    if any(part in lowered for part in ('camera', 'aim', 'eye', 'colim', 'optic')):
        return 'View'
    return 'Effect'


def create_marker(scene, state, entry):
    marker = bpy.data.objects.new(entry.socket_name, None)
    state.collection.objects.link(marker)
    marker.empty_display_type = 'ARROWS'
    marker.empty_display_size = 2
    marker.show_in_front = True
    marker.show_name = True
    marker.color = {'Mount': (0.2, 0.8, 0.2, 1), 'View': (0.2, 0.5, 1, 1),
                    'Effect': (1, 0.5, 0.1, 1)}[socket_group(entry.socket_name)]
    marker.hide_render = True
    marker.lock_scale = (True, True, True)
    marker.arsenal_socket_id = entry.identity
    marker.parent = state.rig
    marker.parent_type = 'BONE'
    marker.parent_bone = bone_name(entry.game_bone, state.rig)
    marker.matrix_parent_inverse = Matrix.Identity(4)
    marker.matrix_basis = frame_matrix(entry) @ socket_matrix(json.loads(entry.baseline))
    entry.marker = marker
    return marker


def parent_preview(obj, marker, rig):
    world = obj.matrix_world.copy()
    obj.parent = marker
    obj.parent_type = 'OBJECT'
    obj.matrix_parent_inverse = marker.matrix_world.inverted()
    obj.matrix_world = world
    # Socket parenting provides rigid animation; retain the binding for export only.
    for modifier in obj.modifiers:
        if modifier.type == 'ARMATURE' and modifier.object == rig:
            modifier.show_viewport = False
            modifier.show_render = False


def marker_rest_matrix(marker):
    rig = marker.parent
    if (rig is None or rig.type != 'ARMATURE' or marker.parent_type != 'BONE'
            or marker.parent_bone not in rig.data.bones):
        raise RuntimeError(f'Socket marker {marker.name} has an invalid bone parent.')
    return (rig.matrix_world @ rig.data.bones[marker.parent_bone].matrix_local
            @ bone_tail(rig, marker.parent_bone) @ marker.matrix_parent_inverse @ marker.matrix_basis)


def preview_rest_matrix(obj):
    """Keep authored socket edits, but exclude the current bone animation pose."""
    marker = obj.parent
    if marker is None or not getattr(marker, 'arsenal_socket_id', ''):
        return obj.matrix_world.copy()
    return marker_rest_matrix(marker) @ obj.matrix_parent_inverse @ obj.matrix_basis


def bind_attachment_previews(scene):
    state = scene.arsenal_sockets
    markers = {entry.socket_name: entry.marker for entry in state.entries if entry.marker}
    for item in scene.arsenal_cfg.attachments:
        mounts = [(item.mesh_object, item.socket)]
        if item.kind == 'iron_sight' and item.front_object != item.mesh_object:
            mounts.append((item.front_object, item.front_socket))
        for obj, socket in mounts:
            if obj and socket in markers:
                parent_preview(obj, markers[socket], state.rig)


def refresh_markers(scene, rig, path):
    state = scene.arsenal_sockets
    donor = rig.get('arsenal_donor_mesh_name', '')
    source = catalogue_mesh(path, state.source_mesh, donor)
    component_root = source.get('root_bone', rig.get('arsenal_component_root', ''))
    if (not isinstance(component_root, str)
            or component_root and not re.fullmatch(r'[A-Za-z0-9_]+', component_root)
            or rig.get('arsenal_component_root') and component_root != rig['arsenal_component_root']):
        raise RuntimeError('The socket catalogue component root differs from the imported weapon.')
    if donor and source['mesh'].rsplit('/', 1)[-1].casefold() != f'SK_{donor}'.casefold():
        raise RuntimeError('The socket catalogue belongs to a different imported weapon.')
    checked_matrix(rig.matrix_world)
    placement = reference_space(rig)
    records = [record for record in source['sockets'] if record['effective']]
    names = set()
    frames = {}
    existing = {entry.socket_name: entry for entry in state.entries}
    for record in records:
        name, joint = record['name'], record['bone']
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]+', name)
                or not isinstance(joint, str) or not re.fullmatch(r'[A-Za-z0-9_]+', joint)):
            raise RuntimeError('Invalid socket name or parent bone in the donor catalogue.')
        if name.casefold() in names:
            raise RuntimeError(f'Duplicate effective socket: {name}')
        names.add(name.casefold())
        target = rig.data.bones.get(bone_name(joint, rig))
        if target is None and joint == component_root:
            target = rig.data.bones.get(import_weapon.ROOT_BONE)
        if target is None:
            raise RuntimeError(f'Socket {name} has no imported bone {joint}.')
        baseline = {key: record[key] for key in ('location', 'rotation', 'scale')}
        checked_matrix(socket_matrix(baseline))
        frames[name] = (bone_tail(rig, target.name).inverted() @ target.matrix_local.inverted()
                        @ placement @ reference_matrix(record))
        if name in existing:
            entry = existing[name]
            if (entry.game_bone != joint or not socket_transforms_equal(json.loads(entry.baseline), baseline)
                    or json.loads(entry.reference) != record['bone_transform'] or entry.marker is None):
                raise RuntimeError(f'Socket {name} changed or its marker was deleted; restore/reset it before refreshing.')
    if set(existing) - {record['name'] for record in records}:
        raise RuntimeError('The donor socket list changed; existing edits need review.')
    if state.entries and state.rig != rig:
        raise RuntimeError('Socket markers already belong to another rig.')
    if state.collection is None:
        collection = bpy.data.collections.new('Weapon Sockets')
        scene.collection.children.link(collection)
        state.collection = collection
    state.rig = rig
    if component_root:
        rig['arsenal_component_root'] = component_root
    state.source_file = os.path.abspath(path)
    state.source_mesh = source['mesh']
    rig[REFERENCE_SPACE] = [value for row in placement for value in row]
    for record in records:
        if record['name'] in existing:
            entry = existing[record['name']]
            if max(abs(a - b) for row, other in zip(frame_matrix(entry), frames[record['name']])
                   for a, b in zip(row, other)) <= 0.00001:
                continue
            local = frame_matrix(entry).inverted() @ entry.marker.matrix_basis
            store_frame(entry, frames[record['name']])
            entry.marker.matrix_basis = frames[record['name']] @ local
            continue
        entry = state.entries.add()
        entry.identity = uuid.uuid4().hex
        entry.socket_name = record['name']
        entry.game_bone = record['bone']
        entry.source_owner = record['owner']
        entry.reference = json.dumps(record['bone_transform'])
        entry.baseline = json.dumps({key: record[key] for key in ('location', 'rotation', 'scale')})
        store_frame(entry, frames[record['name']])
        create_marker(scene, state, entry)
    state.frame_version = FRAME_VERSION
    return len(records)


def import_markers(scene, rig, root):
    path = os.path.join(root, import_weapon.SOCKET_FILE)
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        # Older setups can still import meshes/attachments, but cannot author full socket transforms.
        if isinstance(data, list):
            return
        refresh_markers(scene, rig, path)


def rebind_markers(scene, source, target, source_to_target):
    placement = source_to_target @ reference_space(source)
    checked_matrix(placement)
    target[REFERENCE_SPACE] = [value for row in placement for value in row]
    state = getattr(scene, 'arsenal_sockets', None)
    if state is None or state.rig != source:
        return
    transforms = []
    for entry in state.entries:
        old_name = bone_name(entry.game_bone, source)
        name = bone_name(entry.game_bone, target)
        if entry.marker is None or name not in target.data.bones:
            raise RuntimeError(f'Cannot transfer socket {entry.socket_name} to the generated rig.')
        old_frame = frame_matrix(entry)
        local = old_frame.inverted() @ entry.marker.matrix_basis
        new_frame = (bone_tail(target, name).inverted() @ target.data.bones[name].matrix_local.inverted()
                     @ source_to_target @ source.data.bones[old_name].matrix_local
                     @ bone_tail(source, old_name) @ old_frame)
        transforms.append((entry, new_frame, local))
    state.rig = target
    for entry, frame, local in transforms:
        store_frame(entry, frame)
        entry.marker.parent = target
        entry.marker.parent_bone = bone_name(entry.game_bone, target)
        entry.marker.matrix_basis = frame @ local


def is_legacy_backup_marker(obj, rig):
    from . import convert_to_rigify
    backup_id = rig.get(convert_to_rigify.RETARGET_WEAPON_BACKUP_ID)
    if not backup_id or not obj.users_collection or any(
            not collection.get(convert_to_rigify.RETARGET_BACKUP_COLLECTION_MARKER, False)
            for collection in obj.users_collection):
        return False
    parent = obj.parent
    while parent is not None:
        if (parent.type == 'ARMATURE' and parent.get(convert_to_rigify.RETARGET_BACKUP_MARKER, False)
                and parent.get(convert_to_rigify.RETARGET_BACKUP_ID) == backup_id):
            return True
        parent = parent.parent
    return False


def marker_problem(scene, state, entry):
    marker = entry.marker
    if marker is None or marker.type != 'EMPTY':
        return 'its marker is missing'
    if marker.name not in scene.objects:
        return f'marker {marker.name} is not in the scene'
    if (marker.parent != state.rig or marker.parent_type != 'BONE'
            or marker.parent_bone != bone_name(entry.game_bone, state.rig)):
        return f'marker {marker.name} is not parented to its original bone'
    if marker.arsenal_socket_id != entry.identity:
        return f'marker {marker.name} has a different socket ID'
    if marker.constraints:
        return f'marker {marker.name} has constraints'
    if marker.animation_data:
        return f'marker {marker.name} has animation data (keyframes or drivers)'
    if marker.matrix_parent_inverse != Matrix.Identity(4):
        return f'marker {marker.name} has a parent inverse'
    return ''


def restore_marker(scene, state, entry):
    """Clear everything export_payload rejects; the caller sets the marker transform."""
    marker = entry.marker
    if marker is None or marker.type != 'EMPTY':
        return create_marker(scene, state, entry)
    if marker.name not in scene.objects:
        if state.collection is None:
            state.collection = bpy.data.collections.new('Weapon Sockets')
        if state.collection.name not in scene.collection.children_recursive:
            scene.collection.children.link(state.collection)
        if marker.name not in state.collection.objects:
            state.collection.objects.link(marker)
    marker.animation_data_clear()
    marker.constraints.clear()
    marker.arsenal_socket_id = entry.identity
    marker.parent = state.rig
    marker.parent_type = 'BONE'
    marker.parent_bone = bone_name(entry.game_bone, state.rig)
    marker.matrix_parent_inverse = Matrix.Identity(4)
    return marker


def check_markers(scene):
    """Raise one error naming every marker that would block export; returns the socket state."""
    state = getattr(scene, 'arsenal_sockets', None)
    if state is None or not state.entries:
        return None
    if state.rig is None:
        raise RuntimeError('The socket marker rig was deleted.')
    if state.frame_version != FRAME_VERSION:
        raise RuntimeError('Refresh weapon sockets to update their rig reference space before exporting.')
    checked_matrix(state.rig.matrix_world)
    animated = []
    problems = []
    for entry in state.entries:
        marker = entry.marker
        problem = marker_problem(scene, state, entry)
        if problem.endswith('has animation data (keyframes or drivers)'):
            animated.append(entry.socket_name)
        elif problem:
            problems.append(f'Socket {entry.socket_name}: {problem}. Press Reset Socket to fix it '
                            '(this also restores the donor placement).')
        elif any(obj != marker and obj.arsenal_socket_id == entry.identity
                 and not is_legacy_backup_marker(obj, state.rig) for obj in scene.objects):
            problems.append(f'Socket {entry.socket_name} has duplicate markers; delete the duplicate.')
    if animated:
        problems.append(
            f'Socket markers have keyframes or drivers: {", ".join(animated)} (often added by Auto Keying). '
            'To keep their current placement, select those markers and use Object > Animation > '
            'Clear Keyframes, and remove any drivers. Reset Socket would discard the placement.')
    if problems:
        raise RuntimeError('\n'.join(problems))
    return state


def export_payload(scene, mesh_path):
    state = check_markers(scene)
    if state is None:
        return None
    entries = []
    for entry in state.entries:
        marker = entry.marker
        transform = matrix_socket(frame_matrix(entry).inverted() @ marker.matrix_basis)
        baseline = json.loads(entry.baseline)
        if max(abs(a - b) for a, b in zip(transform['scale'], baseline['scale'])) > 0.00001:
            raise RuntimeError(f'Scale editing is unsupported for socket {entry.socket_name}.')
        transform['scale'] = baseline['scale']
        enabled = entry.enabled and not socket_transforms_equal(transform, baseline)
        entries.append({'name': entry.socket_name, 'bone': entry.game_bone,
                        'baseline': baseline, 'transform': transform, 'enabled': enabled})
    payload = {'version': 1, 'units': 'cm', 'mesh': mesh_path,
               'source_mesh': state.source_mesh, 'entries': entries}
    root = '/' + mesh_path.strip('/').split('/')[0]
    validate_weapon_sockets({'weapon_sockets': payload, 'game_root': root, 'weapon_skeleton': mesh_path})
    return payload


RETICLE_MATERIAL = 'mark'


def sight_centre(obj):
    """Area-weighted world centre of the faces using a reticle (`*mark*`) material, or None."""
    if obj is None or obj.type != 'MESH':
        return None
    slots = {index for index, slot in enumerate(obj.material_slots)
             if slot.material and RETICLE_MATERIAL in slot.material.name.casefold()}
    total, centre = 0.0, Vector()
    for polygon in obj.data.polygons:
        if polygon.material_index in slots:
            centre += polygon.center * polygon.area
            total += polygon.area
    return obj.matrix_world @ (centre / total) if total > 0 else None


def scope_eye_targets(scene):
    """(scope item, eye socket entry, donor item) for each scope with a mesh. The eye socket is named after
    the referenced SID, or the donor SID for a custom scope; the donor item is the referenced scope with
    that SID (or the imported donor entry named after it), whose donor placement calibrates the eye point."""
    entries = {entry.socket_name.casefold(): entry for entry in scene.arsenal_sockets.entries}
    scopes = [item for item in scene.arsenal_cfg.attachments if item.kind == 'scope' and item.mesh_object]
    donors = {item.name.strip().casefold(): item for item in scopes}
    # A referenced scope wins over the imported donor entry with Reference Existing turned off.
    donors.update({item.existing_sid.strip().casefold(): item for item in scopes if item.use_existing})
    result = []
    for item in scopes:
        sid = (item.existing_sid if item.use_existing else item.template_sid).strip().casefold()
        entry = entries.get(sid)
        if entry and entry.marker:
            result.append((item, entry, donors.get(sid)))
    return result


def marker_baseline_matrix(entry):
    """Rest world matrix of the marker at its donor transform."""
    marker = entry.marker
    parent = marker_rest_matrix(marker) @ marker.matrix_basis.inverted()
    return parent @ frame_matrix(entry) @ socket_matrix(json.loads(entry.baseline))


def donor_sight_centre(scene, donor):
    """The donor scope's reticle centre with its mount socket at the donor transform (rest pose)."""
    point = sight_centre(donor.mesh_object)
    mount = next((entry for entry in scene.arsenal_sockets.entries if entry.socket_name == donor.socket), None)
    if point is None or mount is None or mount.marker is None:
        return point
    return marker_baseline_matrix(mount) @ marker_rest_matrix(mount.marker).inverted() @ point


def aligned_eye_basis(entry, shift):
    """The marker basis of the donor eye point moved by `shift`, without changing its eye relief."""
    marker = entry.marker
    baseline = marker_baseline_matrix(entry)
    forward = baseline.col[0].xyz.normalized()
    shift = shift - forward * shift.dot(forward)
    parent = marker_rest_matrix(marker) @ marker.matrix_basis.inverted()
    return parent.inverted() @ Matrix.Translation(shift) @ baseline


def align_eye_points(context, active_only=None):
    """Keep each scope's donor eye-to-reticle relationship at the rest pose.

    The donor eye point moves sideways/vertically by as much as the reticle centre moved from its donor
    placement: through mount socket edits, or by a custom scope's mesh differing from its donor's.
    A custom scope's eye socket must be added by hand in ZoneKit, so its marker (the donor's) is left
    alone and the transform is returned instead. Returns (moved, custom, missing) lists."""
    scene = context.scene
    rig = scene.arsenal_sockets.rig
    pose_position = rig.data.pose_position
    rig.data.pose_position = 'REST'
    context.view_layer.update()
    moved, custom, missing = [], [], []
    try:
        for item, entry, donor in scope_eye_targets(scene):
            if active_only is not None and entry != active_only:
                continue
            point = sight_centre(item.mesh_object)
            reference = donor_sight_centre(scene, donor) if donor else None
            if point is None or reference is None:
                missing.append(item.name)
                continue
            basis = aligned_eye_basis(entry, point - reference)
            transform = matrix_socket(frame_matrix(entry).inverted() @ basis)
            if not item.use_existing:
                custom.append((item.name, entry.socket_name, entry.game_bone, transform))
                continue
            shift = (basis.translation - entry.marker.matrix_basis.translation).length
            entry.marker.matrix_basis = basis
            entry.enabled = True
            moved.append((entry.socket_name, shift))
    finally:
        rig.data.pose_position = pose_position
        context.view_layer.update()
    return moved, custom, missing


def eye_view_rotation(marker):
    """Viewport rotation looking along the marker's +X with its +Z up."""
    axes = Matrix(((0, 0, -1), (-1, 0, 0), (0, 1, 0)))
    return (marker.matrix_world.to_quaternion().to_matrix() @ axes).to_quaternion()


class ARSENAL_SocketEntry(bpy.types.PropertyGroup):
    identity: bpy.props.StringProperty()
    socket_name: bpy.props.StringProperty()
    game_bone: bpy.props.StringProperty()
    source_owner: bpy.props.StringProperty()
    baseline: bpy.props.StringProperty()
    reference: bpy.props.StringProperty()
    frame: bpy.props.FloatVectorProperty(size=16)
    enabled: bpy.props.BoolProperty(name='Use Edits', default=True,
                                   description='Export marker edits; disable to restore the donor socket placement')
    marker: bpy.props.PointerProperty(type=bpy.types.Object)


class ARSENAL_SocketState(bpy.types.PropertyGroup):
    entries: bpy.props.CollectionProperty(type=ARSENAL_SocketEntry)
    active_index: bpy.props.IntProperty()
    rig: bpy.props.PointerProperty(type=bpy.types.Object)
    collection: bpy.props.PointerProperty(type=bpy.types.Collection)
    source_file: bpy.props.StringProperty(subtype='FILE_PATH')
    source_mesh: bpy.props.StringProperty()
    frame_version: bpy.props.IntProperty()


class ARSENAL_UL_WeaponSockets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, 'enabled', text='')
        layout.label(text=item.socket_name, icon='EMPTY_ARROWS' if item.marker else 'ERROR')
        layout.label(text=socket_group(item.socket_name) + ': ' + item.game_bone)


class ARSENAL_OT_SocketRefresh(bpy.types.Operator):
    bl_idname = 'arsenal.socket_refresh'
    bl_label = 'Import / Refresh Sockets'
    bl_description = 'Load the imported weapon socket catalogue as named markers, preserving existing authored edits'
    bl_options = {'REGISTER', 'UNDO'}

    @completion('Weapon socket import')
    def execute(self, context):
        state = context.scene.arsenal_sockets
        rig = state.rig or context.scene.arsenal_ui.weapon_rig
        if rig is None and context.object and context.object.type == 'ARMATURE':
            rig = context.object
        path = state.source_file or os.path.join(
            bpy.path.abspath(context.scene.stalker2_animation_importer.animation_root), import_weapon.SOCKET_FILE)
        try:
            if rig is None:
                raise RuntimeError('Import the weapon rig first.')
            count = refresh_markers(context.scene, rig, path)
            for entry in state.entries:
                entry.marker.show_name = True
            context.view_layer.update()
            bind_attachment_previews(context.scene)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        report(self, {'INFO'}, f'{count} weapon socket markers ready')
        return {'FINISHED'}


class ARSENAL_OT_SocketSelect(bpy.types.Operator):
    bl_idname = 'arsenal.socket_select'
    bl_label = 'Select Socket'
    bl_description = 'Select and frame the active socket marker so its position and rotation can be edited in the viewport'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = context.scene.arsenal_sockets
        if not state.entries or state.entries[state.active_index].marker is None:
            report(self, {'ERROR'}, 'The selected socket marker is missing; reset it to recreate it.')
            return {'CANCELLED'}
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        marker = state.entries[state.active_index].marker
        state.collection.hide_viewport = False
        marker.hide_set(False)
        import_weapon._select_only(context, [marker], marker)
        if context.area and context.area.type == 'VIEW_3D':
            bpy.ops.view3d.view_selected(use_all_regions=False)
        return {'FINISHED'}


class ARSENAL_OT_SocketReset(bpy.types.Operator):
    bl_idname = 'arsenal.socket_reset'
    bl_label = 'Reset Socket'
    bl_description = 'Restore the selected socket marker to its donor transform; the next export also clears its applied edits'
    bl_options = {'REGISTER', 'UNDO'}
    all_sockets: bpy.props.BoolProperty(default=False)

    @classmethod
    def description(cls, context, properties):
        return ('Restore all socket markers to the donor transforms and clear their applied edits on the next import'
                if properties.all_sockets else cls.bl_description)

    def invoke(self, context, event):
        if self.all_sockets:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        state = context.scene.arsenal_sockets
        if state.rig is None or not state.entries:
            report(self, {'ERROR'}, 'Import weapon socket markers first.')
            return {'CANCELLED'}
        entries = list(state.entries) if self.all_sockets else [state.entries[state.active_index]]
        for entry in entries:
            marker = restore_marker(context.scene, state, entry)
            marker.matrix_basis = frame_matrix(entry) @ socket_matrix(json.loads(entry.baseline))
            entry.enabled = True
        return {'FINISHED'}


class ARSENAL_OT_SocketAlignSights(bpy.types.Operator):
    bl_idname = 'arsenal.socket_align_sights'
    bl_label = 'Align Eye Points to Sights'
    bl_description = ('Move each scope eye point sideways and vertically so that looking along it passes through '
                      'the centre of the scope\'s reticle (mark) surface, keeping the eye distance. Custom scopes '
                      'report the socket to add in ZoneKit instead')
    bl_options = {'REGISTER', 'UNDO'}
    active_only: bpy.props.BoolProperty(default=False)

    @classmethod
    def description(cls, context, properties):
        return ('Align only the selected eye point to its scope\'s reticle centre'
                if properties.active_only else cls.bl_description)

    def execute(self, context):
        state = context.scene.arsenal_sockets
        if state.rig is None or not state.entries:
            report(self, {'ERROR'}, 'Import weapon socket markers first.')
            return {'CANCELLED'}
        active = state.entries[state.active_index] if self.active_only else None
        try:
            moved, custom, missing = align_eye_points(context, active)
        except RuntimeError as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        lines = [f'{name}: moved {shift:.2f} cm' for name, shift in moved]
        for name, donor, bone, transform in custom:
            location = ', '.join(f'{value:.3f}' for value in transform['location'])
            lines.append(f'Custom scope {name}: add a mesh socket named after its SID on {bone} at '
                         f'({location}) with rotation 0, 0, 0 (aligned copy of {donor}; that marker is unchanged)')
        if missing:
            lines.append('No reticle (mark material) found on: ' + ', '.join(missing))
        if not moved and not custom:
            report(self, {'WARNING'}, 'No scope eye point could be aligned. ' + ' '.join(lines)
                   if lines else 'No scope with a mesh has an eye point socket marker.')
            return {'CANCELLED'}
        for line in lines:
            self.report({'INFO'}, line)
        report(self, {'INFO'}, f'Aligned {len(moved)} eye points'
               + (f', {len(custom)} custom (see the Info log)' if custom else ''))
        return {'FINISHED'}


class ARSENAL_OT_SocketViewEye(bpy.types.Operator):
    bl_idname = 'arsenal.socket_view_eye'
    bl_label = 'View Through Eye Point'
    bl_description = ('Look from the selected socket marker along its forward axis, as the aimed camera does. '
                      'Orbit or press Numpad 0 to leave the view')
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D'

    def execute(self, context):
        state = context.scene.arsenal_sockets
        if not state.entries or state.entries[state.active_index].marker is None:
            report(self, {'ERROR'}, 'The selected socket marker is missing; reset it to recreate it.')
            return {'CANCELLED'}
        marker = state.entries[state.active_index].marker
        view = context.space_data.region_3d
        distance = 20.0
        forward = marker.matrix_world.col[0].xyz.normalized()
        view.view_perspective = 'PERSP'
        view.view_rotation = eye_view_rotation(marker)
        view.view_location = marker.matrix_world.translation + forward * distance
        view.view_distance = distance
        context.space_data.clip_start = min(context.space_data.clip_start, 0.1)
        return {'FINISHED'}


class ARSENAL_PT_WeaponSockets(bpy.types.Panel):
    bl_label = 'Weapon Sockets'
    bl_parent_id = 'ARSENAL_PT_CustomWeaponPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        state = context.scene.arsenal_sockets
        layout.operator('arsenal.socket_refresh')
        if not state.entries:
            layout.label(text='Requires a regenerated ZoneKit setup catalogue.')
            return
        if state.frame_version != FRAME_VERSION:
            layout.label(text='Refresh sockets to correct the rig reference space.', icon='ERROR')
        layout.template_list('ARSENAL_UL_WeaponSockets', '', state, 'entries', state, 'active_index', rows=6)
        row = layout.row(align=True)
        row.operator('arsenal.socket_select')
        row.operator('arsenal.socket_reset')
        row.operator('arsenal.socket_reset', text='Reset All').all_sockets = True
        row = layout.row(align=True)
        row.operator('arsenal.socket_align_sights')
        row.operator('arsenal.socket_align_sights', text='Align Selected').active_only = True
        layout.operator('arsenal.socket_view_eye', icon='HIDE_OFF')
        if state.collection:
            layout.prop(state.collection, 'hide_viewport', text='Hide Markers')
        entry = state.entries[state.active_index]
        layout.label(text='Bone: ' + entry.game_bone)
        if entry.marker:
            layout.prop(entry.marker, 'location')
            layout.prop(entry.marker, 'rotation_euler', text='Rotation')
        layout.label(text='Translate/rotate only; names and bones stay unchanged.')


CLASSES = (ARSENAL_SocketEntry, ARSENAL_SocketState, ARSENAL_UL_WeaponSockets,
           ARSENAL_OT_SocketRefresh, ARSENAL_OT_SocketSelect, ARSENAL_OT_SocketReset,
           ARSENAL_OT_SocketAlignSights, ARSENAL_OT_SocketViewEye,
           ARSENAL_PT_WeaponSockets)
