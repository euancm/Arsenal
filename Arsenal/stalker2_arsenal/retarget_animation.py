import bpy
import math
import json
from . import bone_functions as b_fun
from . import map_bones

oops = bpy.ops.object
RETARGET_CONSTRAINT_PREFIX = 'Arsenal Retarget '
RETARGET_BACKUP_COLLECTION = 'Arsenal Retarget Backups'
RETARGET_BACKUP_ID = 'arsenal_retarget_backup_id'
RETARGET_BACKUP_MARKER = 'arsenal_retarget_backup'
RETARGET_BACKUP_COLLECTION_MARKER = 'arsenal_retarget_backup_collection'
RETARGET_CUSTOM_MAPPING = 'arsenal_custom_retarget_mapping'


def find_retarget_backup(rig):
    backup_id = rig.get(RETARGET_BACKUP_ID)
    if not backup_id:
        return None, None

    backup = next((
        obj for obj in bpy.data.objects
        if obj != rig
        and obj.type == 'ARMATURE'
        and obj.get(RETARGET_BACKUP_MARKER, False)
        and obj.get(RETARGET_BACKUP_ID) == backup_id
    ), None)
    if not backup:
        return None, None

    collection = next((
        collection for collection in backup.users_collection
        if collection.get(RETARGET_BACKUP_COLLECTION_MARKER, False)
    ), None)
    return backup, collection


def get_pose_bone_name(data_path):
    if not data_path.startswith('pose.bones['):
        return None
    parts = data_path.split('"')
    return parts[1] if len(parts) > 2 else None


def resolve_animation_mapping(source_armature, rig):
    from .mapping_editor import build_mapping_guesses

    reference = map_bones.load_mapping('uemannequin_rigify')
    rigify_names = [target for _, target in reference]
    source_guesses = build_mapping_guesses(
        [bone.name for bone in source_armature.data.bones], rigify_names)
    source_by_rigify_name = {target: source for source, target in source_guesses.items()}
    canonical_to_rigify = {source: target for source, target in reference}

    resolved = []
    missing = []
    for target_name, source_name, transform_type in map_bones.load_mapping(
            'rigify_uemannequin', anim=True):
        if target_name == 'rig.head':
            target_name = 'head'

        rigify_source_name = canonical_to_rigify.get(source_name)
        actual_source_name = (
            rigify_source_name
            if rigify_source_name and rigify_source_name in source_armature.data.bones
            else source_by_rigify_name.get(rigify_source_name)
        )
        if source_name == 'offset' and not actual_source_name:
            actual_source_name = next((
                name for name in ('jnt_offset', 'offset')
                if name in source_armature.data.bones
            ), None)
        elif source_name == 'camera' and not actual_source_name:
            actual_source_name = next((
                name for name in ('jnt_camera', 'camera')
                if name in source_armature.data.bones
            ), None)
        if (target_name not in rig.pose.bones
            or not actual_source_name
            or actual_source_name not in source_armature.data.bones):
            missing.append((target_name, source_name))
            continue

        resolved.append((target_name, actual_source_name, transform_type))

    try:
        custom_mapping = json.loads(rig.get(RETARGET_CUSTOM_MAPPING, '[]'))
    except (TypeError, ValueError):
        custom_mapping = []
    resolved_targets = {target_name for target_name, _source, _kind in resolved}
    for source_name, target_name in custom_mapping:
        if (target_name in resolved_targets
                or source_name not in source_armature.data.bones
                or target_name not in rig.pose.bones):
            continue
        transform_type = 'rot_loc' if target_name == 'Weapon' else 'rot'
        resolved.append((target_name, source_name, transform_type))
        resolved_targets.add(target_name)

    return resolved, missing


def activate_object(context, obj, mode='OBJECT'):
    active = context.view_layer.objects.active
    if active and active.mode != 'OBJECT':
        oops.mode_set(mode='OBJECT')
    oops.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode != 'OBJECT':
        oops.mode_set(mode=mode)


def remove_retarget_constraints(rig, source_armature, target_names):
    helper_names = {target + '.copy' for target in target_names}
    for pose_bone in rig.pose.bones:
        for constraint in list(pose_bone.constraints):
            is_retarget_constraint = constraint.name.startswith(RETARGET_CONSTRAINT_PREFIX)
            is_previous_retarget_constraint = (
                constraint.type in {'COPY_ROTATION', 'COPY_LOCATION'}
                and constraint.target == source_armature
                and constraint.subtarget in helper_names
            )
            if is_retarget_constraint or is_previous_retarget_constraint:
                pose_bone.constraints.remove(constraint)


def action_slot_curves(action, slot):
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            channelbag = strip.channelbag(slot)
            if channelbag:
                curves.extend(channelbag.fcurves)
    return curves


def collect_source_actions(source_armature, mapping, action_names=None):
    mapped_source_names = {source_name for _, source_name, _ in mapping}
    source_actions = []

    for action in bpy.data.actions:
        if action.is_action_legacy:
            continue
        if action_names is not None and action.name not in action_names:
            continue

        best_slot_data = None
        for slot in action.slots:
            if slot.target_id_type != 'OBJECT':
                continue
            curves = action_slot_curves(action, slot)
            source_curves = [
                curve for curve in curves
                if get_pose_bone_name(curve.data_path) in mapped_source_names
            ]
            animated_source_names = {
                get_pose_bone_name(curve.data_path) for curve in source_curves
            }
            frame_values = [
                point.co[0]
                for curve in source_curves
                for point in curve.keyframe_points
            ]
            if not animated_source_names or not frame_values:
                continue

            slot_data = (
                slot,
                min(frame_values),
                max(frame_values),
                len(animated_source_names),
            )
            if best_slot_data is None or slot_data[3] > best_slot_data[3]:
                best_slot_data = slot_data

        if best_slot_data:
            source_actions.append((action, *best_slot_data))

    active_action = source_armature.animation_data.action if source_armature.animation_data else None
    source_actions.sort(key=lambda item: (item[0] != active_action, item[0].name.casefold()))
    return source_actions


def create_output_action(rig, source_action):
    base_name = f'{rig.name}_{source_action.name}'
    action_name = base_name
    suffix = 2
    while bpy.data.actions.get(action_name):
        action_name = f'{base_name}_{suffix}'
        suffix += 1

    action = bpy.data.actions.new(action_name)
    slot = action.slots.new('OBJECT', rig.name)
    action['arsenal_source_action'] = source_action.name
    return action, slot


def target_bone_depth(rig, target_name):
    depth = 0
    bone = rig.data.bones[target_name]
    while bone.parent:
        depth += 1
        bone = bone.parent
    return depth


def apply_retargeted_pose(context, source_armature, rig, mapping):
    rig_world_inverse = rig.matrix_world.inverted_safe()
    current_depth = None
    for target_name, source_name, _transform_type in mapping:
        depth = target_bone_depth(rig, target_name)
        if current_depth is not None and depth != current_depth:
            context.view_layer.update()
        current_depth = depth

        source_pose = source_armature.pose.bones[source_name]
        source_rest_world = source_armature.matrix_world @ source_armature.data.bones[source_name].matrix_local
        source_pose_world = source_armature.matrix_world @ source_pose.matrix
        target_rest_world = rig.matrix_world @ rig.data.bones[target_name].matrix_local
        pose_delta = source_pose_world @ source_rest_world.inverted_safe()
        target_pose_world = pose_delta @ target_rest_world
        rig.pose.bones[target_name].matrix = rig_world_inverse @ target_pose_world
    context.view_layer.update()


def insert_retarget_keyframes(rig, mapping, frame):
    for target_name, _source_name, _transform_type in mapping:
        pose_bone = rig.pose.bones[target_name]
        pose_bone.keyframe_insert(data_path='location', frame=frame, group=target_name)
        rotation_path = {
            'QUATERNION': 'rotation_quaternion',
            'AXIS_ANGLE': 'rotation_axis_angle',
        }.get(pose_bone.rotation_mode, 'rotation_euler')
        pose_bone.keyframe_insert(data_path=rotation_path, frame=frame, group=target_name)
        pose_bone.keyframe_insert(data_path='scale', frame=frame, group=target_name)


def bake_retargeted_action(context, source_armature, rig, mapping, source_action,
                           source_slot, frame_start, frame_end):
    action, slot = create_output_action(rig, source_action)
    rig.animation_data_create()
    rig.animation_data.action = action
    rig.animation_data.action_slot = slot

    ordered_mapping = sorted(
        mapping, key=lambda entry: target_bone_depth(rig, entry[0]))
    try:
        for frame in range(frame_start, frame_end + 1):
            context.scene.frame_set(frame)
            context.view_layer.update()
            # Assigning pose_bone.matrix is only approximate for bones driven by
            # constraints/drivers, and the first frame starts from wherever the
            # previous action ended, so apply twice to converge.
            for _ in range(2):
                apply_retargeted_pose(context, source_armature, rig, ordered_mapping)
                context.view_layer.update()
            insert_retarget_keyframes(rig, ordered_mapping, frame)
    except Exception:
        rig.animation_data.action = None
        bpy.data.actions.remove(action)
        raise

    action.use_fake_user = True
    return action, slot


def retarget_animation_actions(context, source_armature, rig, mapping,
                               set_anim_length=True,
                               action_names=None):
    with b_fun.forced_pose_position(source_armature, rig):
        return _retarget_animation_actions(
            context, source_armature, rig, mapping, set_anim_length, action_names)


def _retarget_animation_actions(context, source_armature, rig, mapping,
                                set_anim_length=True,
                                action_names=None):
    had_source_animation = source_armature.animation_data is not None
    source_animation = source_armature.animation_data_create()
    original_source_action = source_animation.action
    original_source_slot = source_animation.action_slot
    original_use_nla = source_animation.use_nla
    original_track_mutes = [(track, track.mute) for track in source_animation.nla_tracks]
    original_frame = context.scene.frame_current
    original_frame_start = context.scene.frame_start
    original_frame_end = context.scene.frame_end
    original_rig_action = rig.animation_data.action if rig.animation_data else None
    original_rig_slot = rig.animation_data.action_slot if rig.animation_data else None

    source_actions = collect_source_actions(source_armature, mapping, action_names)
    if not source_actions:
        raise RuntimeError('No source actions with mapped bone animation were found.')

    output_actions = []
    succeeded = False
    try:
        for track, _mute in original_track_mutes:
            track.mute = True
        source_animation.use_nla = False

        activate_object(context, rig, 'POSE')
        target_names = [target for target, _source, _kind in mapping]
        remove_retarget_constraints(rig, source_armature, target_names)
        b_fun.set_ik_fk(rig, 1.0)

        baked_actions = {}
        frame_ranges = []
        for source_action, slot, first_frame, last_frame, _matched_count in source_actions:
            source_animation.action = source_action
            source_animation.action_slot = slot
            context.view_layer.update()

            frame_start = math.floor(first_frame)
            frame_end = math.ceil(last_frame)
            frame_ranges.append((frame_start, frame_end))
            context.scene.frame_start = frame_start
            context.scene.frame_end = frame_end
            context.scene.frame_set(frame_start)
            context.view_layer.update()

            action, action_slot = bake_retargeted_action(
                context, source_armature, rig, mapping, source_action,
                slot, frame_start, frame_end)
            output_actions.append(action)
            baked_actions[source_action] = (action, action_slot)

        desired_action = baked_actions.get(original_source_action)
        if desired_action is None:
            desired_action = next(iter(baked_actions.values()))
        rig.animation_data.action, rig.animation_data.action_slot = desired_action

        if set_anim_length:
            context.scene.frame_start = min(start for start, _end in frame_ranges)
            context.scene.frame_end = max(end for _start, end in frame_ranges)
        else:
            context.scene.frame_start = original_frame_start
            context.scene.frame_end = original_frame_end

        succeeded = True
        return output_actions
    except Exception:
        rig.animation_data_create()
        rig.animation_data.action = original_rig_action
        if original_rig_action:
            rig.animation_data.action_slot = original_rig_slot
        for action in output_actions:
            bpy.data.actions.remove(action)
        raise
    finally:
        activate_object(context, rig, 'OBJECT')
        remove_retarget_constraints(
            rig, source_armature, [target for target, _source, _kind in mapping])

        if had_source_animation:
            source_animation.action = original_source_action
            if original_source_action:
                source_animation.action_slot = original_source_slot
            source_animation.use_nla = original_use_nla
            for track, was_muted in original_track_mutes:
                track.mute = was_muted
        else:
            source_armature.animation_data_clear()

        if not succeeded:
            context.scene.frame_start = original_frame_start
            context.scene.frame_end = original_frame_end
        context.scene.frame_set(original_frame)
        activate_object(context, rig, 'OBJECT')


class RetargetAnimationOperator(bpy.types.Operator):
    """Retarget source actions onto the selected Rigify rig."""
    bl_idname = 'object.arsenal_retarget_animation'
    bl_label = 'Retarget animation'
    bl_options = {'REGISTER', 'UNDO'}

    set_anim_length: bpy.props.BoolProperty(name='Set animation length', default=True)
    remove_source_actions: bpy.props.BoolProperty(
        name='Remove original actions',
        description='Delete the imported source actions once they have been retargeted',
        default=True)

    @classmethod
    def poll(cls, context):
        if (context.space_data.type != 'VIEW_3D'
                or not context.view_layer.objects.active
                or context.object.type != 'ARMATURE'
                or context.object.mode != 'OBJECT'):
            return False

        if len(context.selected_objects) == 1:
            backup, _collection = find_retarget_backup(context.object)
            return bool(context.object.data.get('rig_id') and backup)
        return len(context.selected_objects) == 2

    def execute(self, context):
        backup_collection = None
        collection_was_hidden = False
        if len(context.selected_objects) == 1:
            rig = context.object
            source_armature, backup_collection = find_retarget_backup(rig)
            if not source_armature:
                self.report({'ERROR'}, 'No saved source armature was found for this Rigify rig.')
                return {'CANCELLED'}
            if backup_collection:
                collection_was_hidden = backup_collection.hide_viewport
                backup_collection.hide_viewport = False
                context.view_layer.update()
        else:
            rig, source_armature = b_fun.get_rig_and_armature(context)

        try:
            mapping, missing = resolve_animation_mapping(source_armature, rig)
            if missing:
                self.report({'WARNING'}, f'Skipped {len(missing)} unresolved animation mappings.')
            if not mapping:
                self.report({'ERROR'}, 'No animation bone mappings matched the source skeleton and Rigify rig.')
                return {'CANCELLED'}

            actions = retarget_animation_actions(
                context, source_armature, rig, mapping,
                set_anim_length=self.set_anim_length)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            if backup_collection:
                backup_collection.hide_viewport = collection_was_hidden

        self.report({'INFO'}, f'Retargeted {len(actions)} actions onto {rig.name}.')
        if self.remove_source_actions and backup_collection:
            removed = 0
            for output in actions:
                source = bpy.data.actions.get(output.get('arsenal_source_action', ''))
                if source and source not in actions:
                    bpy.data.actions.remove(source)
                    removed += 1
            self.report({'INFO'}, f'Removed {removed} original source actions.')

        # Outputs keep the source name once it is free, otherwise the rig_ name stays to avoid clashes.
        for output in actions:
            source_name = output.get('arsenal_source_action', '')
            if source_name and not bpy.data.actions.get(source_name):
                output.name = source_name
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)