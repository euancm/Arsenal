import bpy
import uuid
import math
import json
from . import preferences
from .map_bones import BoneMapping
from . import bone_functions as b_fun

oops = bpy.ops.object
pops = bpy.ops.pose
aops = bpy.ops.armature
RETARGET_BACKUP_COLLECTION = 'Arsenal Retarget Backups'
RETARGET_BACKUP_ID = 'ARSENAL_retarget_backup_id'
RETARGET_BACKUP_MARKER = 'ARSENAL_retarget_backup'
RETARGET_BACKUP_COLLECTION_MARKER = 'ARSENAL_retarget_backup_collection'
RETARGET_CUSTOM_MAPPING = 'ARSENAL_custom_retarget_mapping'


def create_retarget_backup(context, source_armature):
    if source_armature.get(RETARGET_BACKUP_MARKER, False):
        raise RuntimeError('This armature is already a retarget backup; select the original source armature.')

    existing_backup_id = source_armature.get(RETARGET_BACKUP_ID)
    if existing_backup_id:
        existing_backup = next((
            obj for obj in bpy.data.objects
            if obj != source_armature
            and obj.type == 'ARMATURE'
            and obj.get(RETARGET_BACKUP_MARKER, False)
            and obj.get(RETARGET_BACKUP_ID) == existing_backup_id
        ), None)
        if existing_backup:
            for collection in existing_backup.users_collection:
                if collection.get(RETARGET_BACKUP_COLLECTION_MARKER, False):
                    collection.hide_viewport = True
                    collection.hide_render = True
                    return existing_backup_id

    root = source_armature
    while root.parent:
        root = root.parent
    collection = bpy.data.collections.get(RETARGET_BACKUP_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(RETARGET_BACKUP_COLLECTION)
        context.scene.collection.children.link(collection)
    collection[RETARGET_BACKUP_COLLECTION_MARKER] = True

    backup_id = uuid.uuid4().hex
    copies = {}

    def copy_hierarchy(source_object, parent_copy=None):
        if source_object in copies:
            return copies[source_object]
        backup_object = source_object.copy()
        if source_object.data:
            backup_object.data = source_object.data.copy()
        backup_object.parent = parent_copy
        collection.objects.link(backup_object)
        copies[source_object] = backup_object

        for child in source_object.children:
            copy_hierarchy(child, backup_object)

    copy_hierarchy(root)

    armature_sources = {
        source_object for source_object in copies
        if source_object.type == 'ARMATURE'
    }
    bound_meshes = [
        obj for obj in bpy.data.objects
        if obj.type == 'MESH'
        and any(
            modifier.type == 'ARMATURE' and modifier.object in armature_sources
            for modifier in obj.modifiers
        )
    ]
    for mesh in bound_meshes:
        mesh_root = mesh
        while mesh_root.parent and mesh_root.parent not in copies:
            mesh_root = mesh_root.parent
        copy_hierarchy(mesh_root, copies.get(mesh_root.parent))

    for source_object, backup_object in copies.items():
        for modifier in backup_object.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object in copies:
                modifier.object = copies[modifier.object]
        for constraint in backup_object.constraints:
            if getattr(constraint, 'target', None) in copies:
                constraint.target = copies[constraint.target]
        if backup_object.type == 'ARMATURE':
            for pose_bone in backup_object.pose.bones:
                for constraint in pose_bone.constraints:
                    if getattr(constraint, 'target', None) in copies:
                        constraint.target = copies[constraint.target]

    backup_armature = copies[source_armature]
    backup_armature[RETARGET_BACKUP_ID] = backup_id
    backup_armature[RETARGET_BACKUP_MARKER] = True
    source_armature[RETARGET_BACKUP_ID] = backup_id
    collection.hide_viewport = True
    collection.hide_render = True
    return backup_id


def parent_importer_camera_to_rig(context, source_armature, rig):
    camera = context.scene.camera
    if (not camera
            or camera.parent != source_armature
            or camera.parent_type != 'BONE'
            or camera.parent_bone not in {'jnt_camera', 'camera'}
            or 'Camera' not in rig.data.bones):
        return False

    camera.parent = rig
    camera.parent_type = 'BONE'
    camera.parent_bone = 'Camera'
    camera.location = (0.0, 0.0, 0.0)
    camera.rotation_mode = 'XYZ'
    camera.rotation_euler = (math.radians(90.0), 0.0, math.radians(-90.0))
    camera.scale = (1.0, 1.0, 1.0)
    context.view_layer.update()
    return True


def merge_appended_weapon_rig(context, rig, weapon_armature):
    if not weapon_armature or weapon_armature.type != 'ARMATURE' or weapon_armature == rig:
        return False

    source_root = weapon_armature.data.bones.get('Weapon')
    target_root = rig.data.bones.get('Weapon')
    if not source_root or not target_root:
        raise RuntimeError("The appended weapon rig and generated rig must both contain a 'Weapon' root bone.")

    source_bones = [bone for bone in weapon_armature.data.bones if bone.name != 'Weapon']
    conflicts = [bone.name for bone in source_bones if bone.name in rig.data.bones]
    if conflicts:
        raise RuntimeError('Weapon controls conflict with Rigify bones: ' + ', '.join(conflicts))

    source_root_world = weapon_armature.matrix_world @ source_root.matrix_local
    target_root_world = rig.matrix_world @ target_root.matrix_local
    source_to_rig = (
        rig.matrix_world.inverted_safe()
        @ target_root_world
        @ source_root_world.inverted_safe()
        @ weapon_armature.matrix_world
    )
    rotation_transform = source_to_rig.to_3x3()

    # Constraint axes and custom shapes are expressed in each bone's local
    # rest frame.  Rebuilding the bones in the destination armature changes
    # that frame, so retain the frame conversion for settings copied below.
    bone_frame_deltas = {}

    active_object = context.view_layer.objects.active
    if active_object and active_object.mode != 'OBJECT':
        oops.mode_set(mode='OBJECT')
    oops.select_all(action='DESELECT')
    rig.select_set(True)
    context.view_layer.objects.active = rig
    oops.mode_set(mode='EDIT')
    edit_bones = rig.data.edit_bones
    weapon_collection = rig.data.collections.get('Weapon')
    if weapon_collection is None:
        weapon_collection = rig.data.collections.new('Weapon')

    for source_bone in source_bones:
        target_bone = edit_bones.new(source_bone.name)
        target_bone.head = source_to_rig @ source_bone.head_local
        target_bone.tail = source_to_rig @ source_bone.tail_local
        target_bone.align_roll(rotation_transform @ source_bone.z_axis)
        target_bone.use_connect = False
        target_bone.use_deform = source_bone.use_deform
        for property_name in (
                'inherit_scale', 'use_inherit_rotation', 'use_local_location',
                'use_relative_parent', 'bbone_segments', 'bbone_x', 'bbone_z'):
            if hasattr(source_bone, property_name) and hasattr(target_bone, property_name):
                try:
                    setattr(target_bone, property_name, getattr(source_bone, property_name))
                except (AttributeError, TypeError, ValueError):
                    pass
        for key in source_bone.keys():
            target_bone[key] = source_bone[key]
        weapon_collection.assign(target_bone)

    # The Weapon control is also used as a deform bone by meshes weighted to
    # the authored root. Rigify's control bone is otherwise non-deforming.
    target_root.use_deform = source_root.use_deform = True

    for source_bone in source_bones:
        if source_bone.parent:
            edit_bones[source_bone.name].parent = edit_bones[source_bone.parent.name]
            edit_bones[source_bone.name].use_connect = source_bone.use_connect

    oops.mode_set(mode='OBJECT')

    for source_bone in source_bones:
        target_bone = rig.data.bones[source_bone.name]
        bone_frame_deltas[source_bone.name] = (
            target_bone.matrix_local.inverted_safe()
            @ source_to_rig
            @ source_bone.matrix_local
        )
    bone_frame_deltas['Weapon'] = (
        target_root.matrix_local.inverted_safe()
        @ source_to_rig
        @ source_root.matrix_local
    )

    source_root_pose = weapon_armature.pose.bones['Weapon']
    target_root_pose = rig.pose.bones['Weapon']
    copy_weapon_pose_settings(
        source_root_pose, target_root_pose, weapon_armature, rig,
        copy_transform=False, frame_delta=bone_frame_deltas.get('Weapon'))
    for source_constraint in source_root_pose.constraints:
        target_constraint = target_root_pose.constraints.new(source_constraint.type)
        copy_constraint_settings(source_constraint, target_constraint, weapon_armature, rig,
                                 bone_frame_deltas.get('Weapon'))
        if target_constraint.type == 'CHILD_OF':
            target_constraint.influence = 0.0

    for source_bone in source_bones:
        source_pose = weapon_armature.pose.bones[source_bone.name]
        target_pose = rig.pose.bones[source_bone.name]
        copy_weapon_pose_settings(source_pose, target_pose, weapon_armature, rig,
                                  frame_delta=bone_frame_deltas.get(source_bone.name))

        for source_constraint in source_pose.constraints:
            target_constraint = target_pose.constraints.new(source_constraint.type)
            copy_constraint_settings(source_constraint, target_constraint, weapon_armature, rig,
                                     bone_frame_deltas.get(source_bone.name))
            if target_constraint.type == 'CHILD_OF':
                target_constraint.influence = 0.0

    # Store a correct Child Of inverse in the merged armature's space. This
    # makes the constraint ready for later animation authoring when enabled.
    context.view_layer.update()
    for owner_pose in rig.pose.bones:
        for constraint in owner_pose.constraints:
            if constraint.type != 'CHILD_OF' or not constraint.target:
                continue
            target_pose = constraint.target.pose.bones.get(constraint.subtarget)
            if not target_pose:
                continue
            target_matrix = constraint.target.matrix_world @ target_pose.matrix
            owner_matrix = rig.matrix_world @ owner_pose.matrix
            constraint.inverse_matrix = target_matrix.inverted_safe() @ owner_matrix

    weapon_meshes = []
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not any(modifier.type == 'ARMATURE' and modifier.object == weapon_armature
                   for modifier in obj.modifiers):
            continue

        weapon_meshes.append(obj)
        world_matrix = obj.matrix_world.copy()
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object == weapon_armature:
                modifier.object = rig
        if obj.parent == weapon_armature:
            obj.parent = rig
            obj.parent_type = 'OBJECT'
            context.view_layer.update()
            obj.matrix_world = world_matrix

    for weapon_mesh in weapon_meshes:
        weapon_mesh.select_set(False)
    weapon_armature.select_set(False)
    bpy.data.objects.remove(weapon_armature, do_unlink=True)
    return True


def copy_weapon_pose_settings(source_pose, target_pose, source_armature, target_armature,
                              copy_transform=True, frame_delta=None):
    if copy_transform:
        target_pose.rotation_mode = source_pose.rotation_mode
        target_pose.location = source_pose.location.copy()
        target_pose.rotation_euler = source_pose.rotation_euler.copy()
        target_pose.rotation_quaternion = source_pose.rotation_quaternion.copy()
        target_pose.rotation_axis_angle = source_pose.rotation_axis_angle[:]
        target_pose.scale = source_pose.scale.copy()
    target_pose.lock_location = source_pose.lock_location
    target_pose.lock_rotation = source_pose.lock_rotation
    target_pose.lock_rotation_w = source_pose.lock_rotation_w
    target_pose.lock_scale = source_pose.lock_scale
    target_pose.custom_shape = source_pose.custom_shape
    if frame_delta is not None:
        frame_scale = frame_delta.to_scale()
        target_pose.custom_shape_scale_xyz = tuple(
            source_pose.custom_shape_scale_xyz[i] * frame_scale[i] for i in range(3))
        target_pose.custom_shape_translation = frame_delta.to_3x3() @ source_pose.custom_shape_translation
        shape_rotation = source_pose.custom_shape_rotation_euler.to_matrix().to_4x4()
        converted_rotation = frame_delta.to_3x3().to_4x4() @ shape_rotation
        target_pose.custom_shape_rotation_euler = converted_rotation.to_euler()
    else:
        target_pose.custom_shape_scale_xyz = source_pose.custom_shape_scale_xyz
        target_pose.custom_shape_translation = source_pose.custom_shape_translation.copy()
        target_pose.custom_shape_rotation_euler = source_pose.custom_shape_rotation_euler.copy()
    target_pose.use_custom_shape_bone_size = source_pose.use_custom_shape_bone_size
    target_pose.color.palette = source_pose.color.palette
    if source_pose.custom_shape_transform:
        target_pose.custom_shape_transform = target_armature.pose.bones.get(
            source_pose.custom_shape_transform.name)
    for key in source_pose.keys():
        target_pose[key] = source_pose[key]


def copy_constraint_settings(source_constraint, target_constraint, source_armature, target_armature,
                             frame_delta=None):
    for property_info in source_constraint.bl_rna.properties:
        name = property_info.identifier
        if name in {'rna_type', 'name', 'type'} or property_info.is_readonly:
            continue
        try:
            value = getattr(source_constraint, name)
            if frame_delta is not None and source_constraint.type == 'LIMIT_LOCATION' and name.endswith(('_x', '_y', '_z')):
                continue
            if name == 'target' and value == source_armature:
                value = target_armature
            setattr(target_constraint, name, value)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue
    target_constraint.name = source_constraint.name
    if frame_delta is not None and source_constraint.type == 'LIMIT_LOCATION':
        matrix = frame_delta.to_3x3()
        for axis_name in 'xyz':
            for bound in ('min', 'max'):
                setattr(target_constraint, f'use_{bound}_{axis_name}', False)
        for source_axis, axis_name in enumerate('xyz'):
            mapped = max(range(3), key=lambda i: abs(matrix[i][source_axis]))
            sign = matrix[mapped][source_axis]
            for bound in ('min', 'max'):
                enabled = getattr(source_constraint, f'use_{bound}_{axis_name}')
                value = getattr(source_constraint, f'{bound}_{axis_name}')
                if not enabled:
                    continue
                target_bound = bound if sign >= 0 else ('max' if bound == 'min' else 'min')
                target_axis = 'xyz'[mapped]
                setattr(target_constraint, f'use_{target_bound}_{target_axis}', True)
                setattr(target_constraint, f'{target_bound}_{target_axis}', value * sign)

UE_REQUIRED_BONES = {
    'shoulder.L', 'upper_arm.L', 'forearm.L', 'hand.L',
    'shoulder.R', 'upper_arm.R', 'forearm.R', 'hand.R',
    'thigh.L', 'shin.L', 'foot.L', 'toe.L',
    'thigh.R', 'shin.R', 'foot.R', 'toe.R',
}


def validate_ue_mannequin(armature_object, mapping):
    mapped_bones = {mapping.get_name(bone.name): bone for bone in armature_object.data.bones}
    if 'spine' not in mapped_bones:
        return (
            "This button requires the standard Unreal mannequin spine, but the built-in "
            "mapping could not find 'spine'. Use 'Convert char by mapping' with a mapping "
            "for this skeleton."
        )

    missing_bones = sorted(UE_REQUIRED_BONES - mapped_bones.keys())
    if missing_bones:
        missing = ', '.join(missing_bones[:8])
        if len(missing_bones) > 8:
            missing += ', ...'
        return (
            "This button requires the standard Unreal mannequin bone names. "
            f"The built-in mapping is missing: {missing}. "
            "Use 'Convert char by mapping' with a mapping for this skeleton."
        )

    spine = mapped_bones['spine']
    spine_length = 1
    while True:
        spine_children = [
            child for child in spine.children
            if mapping.get_name(child.name).startswith('spine')
        ]
        if not spine_children:
            break
        spine = spine_children[0]
        spine_length += 1

    if spine_length not in {6, 7}:
        return (
            "The built-in Unreal mannequin mapping must produce a spine chain "
            "of 6 or 7 bones; this skeleton maps to "
            f"{spine_length}. Use 'Convert char by mapping' with a matching mapping."
        )

    return None


def validate_custom_mapping(armature_object, mapping, mapping_name):
    mapped_bones = {mapping.get_name(bone.name): bone for bone in armature_object.data.bones}
    if 'spine' not in mapped_bones:
        return (
            f"The active mapping '{mapping_name}' does not map a source bone to Rigify's 'spine'. "
            "Check that the mapping goes from the source armature to Rigify bone names, then save "
            "and select that mapping before converting."
        )

    missing_bones = sorted(UE_REQUIRED_BONES - mapped_bones.keys())
    if missing_bones:
        missing = ', '.join(missing_bones[:8])
        if len(missing_bones) > 8:
            missing += ', ...'
        return f"The active mapping '{mapping_name}' is missing required Rigify bones: {missing}."

    spine = mapped_bones['spine']
    spine_length = 1
    while True:
        spine_children = [
            child for child in spine.children
            if mapping.get_name(child.name).startswith('spine')
        ]
        if not spine_children:
            break
        spine = spine_children[0]
        spine_length += 1

    if spine_length not in {6, 7}:
        return (
            f"The active mapping '{mapping_name}' must produce a 6- or 7-bone spine chain; "
            f"it maps to {spine_length} bones."
        )

    return None


class ConvertToRigifyOperator(bpy.types.Operator):
    """Convert character to rigify"""
    bl_idname = "object.ARSENAL_convert_to_rigify"
    bl_label = "Convert UE character to rigify"
    bl_options = {'REGISTER', 'UNDO'}

    # example_prop: bpy.props.BoolProperty(name="Example prop", default=False)

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            # and len(context.selected_objects) > 0
            and context.view_layer.objects.active
            and context.object.type == 'ARMATURE'
            and (context.object.mode == 'OBJECT'))

    def execute(self, context):
        armature_object = context.object
        mapping = BoneMapping('uemannequin_rigify', False)
        mapping_error = validate_ue_mannequin(armature_object, mapping)
        if mapping_error:
            self.report({'ERROR'}, mapping_error)
            return {'CANCELLED'}

        mesh_objects = [child for child in armature_object.children if child.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, 'The armature must have a child mesh to convert.')
            return {'CANCELLED'}

        backup_id = create_retarget_backup(context, armature_object)
        parent = armature_object.parent
        mesh_object = mesh_objects[0]
        if parent:
            parent.select_set(True)
        mesh_object.select_set(True)

        oops.transform_apply(location = True, rotation = True, scale = True)
        if parent:
            parent.select_set(False)
        mesh_object.select_set(False)

        mapping_reverse = BoneMapping('uemannequin_rigify', True)
        mapping.rename_armature(armature_object.data)
        oops.mode_set(mode = 'OBJECT')
        oops.ARSENAL_generate_metarig()
        metarig = context.object
        oops.mode_set(mode = 'OBJECT')
        pops.rigify_generate()
        armature_object.select_set(True)
        mapping_reverse.rename_armature(armature_object.data)
        oops.mode_set(mode = 'OBJECT')
        oops.ARSENAL_bind_rigify_to_armature()
        
        objs = bpy.data.objects

        objs.remove(armature_object)
        objs.remove(metarig)
        if parent:
            objs.remove(parent)
        # self.prefs = preferences.get_prefs()

        # self.report({'INFO'}, self.prefs.hello)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)


class ConvertToRigifyByMappingOperator(bpy.types.Operator):
    """Convert character to rigify"""
    bl_idname = "object.ARSENAL_convert_to_rigify_by_mapping"
    bl_label = "Convert character to rigify by mapping"
    bl_options = {'REGISTER', 'UNDO'}

    # example_prop: bpy.props.BoolProperty(name="Example prop", default=False)

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            # and len(context.selected_objects) > 0
            and context.view_layer.objects.active
            and context.object.type == 'ARMATURE'
            and (context.object.mode == 'OBJECT'))

    def execute(self, context):
        armature_object = context.object
        ui = context.window_manager.arsenal_ui
        mapping = BoneMapping(ui.active_mapping, False)
        mapping_error = validate_custom_mapping(armature_object, mapping, ui.active_mapping)
        if mapping_error:
            self.report({'ERROR'}, mapping_error)
            return {'CANCELLED'}

        mesh_objects = [child for child in armature_object.children if child.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, 'The armature must have a child mesh to convert.')
            return {'CANCELLED'}

        appended_weapon = context.scene.objects.get('Weapon')
        if appended_weapon and appended_weapon.type == 'ARMATURE':
            if mapping.get_name('jnt_offset', safe=False) != 'Weapon':
                self.report({'ERROR'}, "Map source bone 'jnt_offset' to target 'Weapon' before converting the appended weapon rig.")
                return {'CANCELLED'}

            weapon_target_names = {
                bone.name for bone in appended_weapon.data.bones
                if bone.name != 'Weapon'
            }
            missing_targets = sorted(weapon_target_names - set(mapping.mapping.values()))
            if missing_targets:
                self.report(
                    {'ERROR'},
                    'Add mapping entries for the appended Weapon controls: '
                    + ', '.join(missing_targets)
                )
                return {'CANCELLED'}

            missing_sources = sorted(
                source_name for source_name, target_name in mapping.mapping.items()
                if target_name in weapon_target_names
                and source_name not in armature_object.data.bones
            )
            if missing_sources:
                self.report(
                    {'ERROR'},
                    'Weapon source bones are missing from the character armature: '
                    + ', '.join(missing_sources)
                )
                return {'CANCELLED'}

        backup_id = create_retarget_backup(context, armature_object)
        parent = armature_object.parent
        mesh_object = mesh_objects[0]
        if parent:
            parent.select_set(True)
        mesh_object.select_set(True)

        oops.transform_apply(location = True, rotation = True, scale = True)
        if parent:
            parent.select_set(False)
        mesh_object.select_set(False)

        # mapping_reverse = BoneMapping(ui.active_mapping, True)
        mapping.rename_armature(armature_object.data)

        oops.mode_set(mode = 'OBJECT')
        oops.ARSENAL_generate_metarig()
        metarig = context.object
        oops.mode_set(mode = 'OBJECT')
        pops.rigify_generate()
        rig = context.object
        rig[RETARGET_BACKUP_ID] = backup_id
        if appended_weapon and appended_weapon.type == 'ARMATURE':
            try:
                merge_appended_weapon_rig(context, rig, appended_weapon)
            except Exception as error:
                self.report({'ERROR'}, f'Could not merge the appended Weapon rig: {error}')
                return {'CANCELLED'}
        parent_importer_camera_to_rig(context, armature_object, rig)
        rig[RETARGET_CUSTOM_MAPPING] = json.dumps([
            [source_name, target_name]
            for source_name, target_name in mapping.mapping.items()
            if source_name and target_name and target_name in rig.pose.bones
        ])
        rig.select_set(False)
        armature_object.select_set(True)
        context.view_layer.objects.active = armature_object
        aops.ARSENAL_add_prefix(prefix = 'DEF-')
        armature_object.select_set(False)
        context.view_layer.objects.active = mesh_object
        mesh_object.select_set(True)
        oops.parent_clear(type = 'CLEAR')
        rig.select_set(True)
        context.view_layer.objects.active = rig
        oops.parent_set(type = 'ARMATURE')

        objs = bpy.data.objects

        objs.remove(armature_object)
        objs.remove(metarig)
        if parent:
            objs.remove(parent)

        mesh_object.select_set(False)
        b_fun.prepare_rig(rig)

        return {'FINISHED'}
