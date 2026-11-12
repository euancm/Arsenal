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


def export_payload(scene, mesh_path):
    state = getattr(scene, 'arsenal_sockets', None)
    if state is None or not state.entries:
        return None
    if state.rig is None:
        raise RuntimeError('The socket marker rig was deleted.')
    if state.frame_version != FRAME_VERSION:
        raise RuntimeError('Refresh weapon sockets to update their rig reference space before exporting.')
    checked_matrix(state.rig.matrix_world)
    entries = []
    for entry in state.entries:
        marker = entry.marker
        if (marker is None or marker.type != 'EMPTY' or marker.name not in scene.objects
                or marker.parent != state.rig or marker.parent_type != 'BONE'
                or marker.parent_bone != bone_name(entry.game_bone, state.rig)
                or marker.arsenal_socket_id != entry.identity
                or marker.constraints or marker.animation_data
                or marker.matrix_parent_inverse != Matrix.Identity(4)):
            raise RuntimeError(f'Socket {entry.socket_name}: restore its marker, original parent and static local transform.')
        if sum(obj.arsenal_socket_id == entry.identity for obj in scene.objects) != 1:
            raise RuntimeError(f'Socket {entry.socket_name} has duplicate markers; delete the duplicate.')
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
            if entry.marker is None:
                create_marker(context.scene, state, entry)
            else:
                entry.marker.parent = state.rig
                entry.marker.parent_type = 'BONE'
                entry.marker.parent_bone = bone_name(entry.game_bone, state.rig)
                entry.marker.matrix_parent_inverse = Matrix.Identity(4)
                entry.marker.matrix_basis = frame_matrix(entry) @ socket_matrix(json.loads(entry.baseline))
            entry.enabled = True
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
           ARSENAL_PT_WeaponSockets)
