import bpy
import math
import json
from . import bone_functions as b_fun
from . import map_bones
from .notifications import Progress, completion, report

oops = bpy.ops.object
RETARGET_CONSTRAINT_PREFIX = 'Arsenal Retarget '
RETARGET_BACKUP_COLLECTION = 'Arsenal Retarget Backups'
RETARGET_BACKUP_ID = 'arsenal_retarget_backup_id'
RETARGET_BACKUP_MARKER = 'arsenal_retarget_backup'
RETARGET_BACKUP_COLLECTION_MARKER = 'arsenal_retarget_backup_collection'
RETARGET_CUSTOM_MAPPING = 'arsenal_custom_retarget_mapping'
# Set by the STALKER 2 animation importer on every clip it bakes onto the master armature.
IMPORTED_ACTION_MARKER = 'stalker2_animation_importer'
SOURCE_PAIR_RECORD = 'stalker2_source_pair'


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


CLEAN_THRESHOLD = 0.001


def clean_action(action, slot, threshold=CLEAN_THRESHOLD):
    """Drop keyframes that sit within the threshold of both neighbours, like Clean Keyframes.
    First and last keys are kept so the action length is unchanged. Returns the number removed."""
    removed = 0
    for fcurve in action_slot_curves(action, slot):
        points = fcurve.keyframe_points
        count = len(points)
        if count < 3:
            continue
        values = [point.co[1] for point in points]
        redundant = []
        previous = values[0]
        for index in range(1, count - 1):
            if abs(values[index] - previous) <= threshold and abs(values[index] - values[index + 1]) <= threshold:
                redundant.append(index)
            else:
                previous = values[index]
        for index in reversed(redundant):
            points.remove(points[index], fast=True)
        if redundant:
            fcurve.update()
            removed += len(redundant)
    return removed


def collect_source_actions(source_armature, mapping, action_names=None):
    mapped_source_names = {source_name for _, source_name, _ in mapping}
    source_actions = []
    # Imported clips are marked. Once any exist, unmarked actions are raw FBX takes or other
    # leftovers: baking them wastes time and their object keys would move the source armature.
    imported_only = action_names is None and any(
        action.get(IMPORTED_ACTION_MARKER, False) for action in bpy.data.actions)

    for action in bpy.data.actions:
        if action.is_action_legacy:
            continue
        if action_names is not None and action.name not in action_names:
            continue
        if imported_only and not action.get(IMPORTED_ACTION_MARKER, False):
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
    if source_action.get(SOURCE_PAIR_RECORD):
        action[SOURCE_PAIR_RECORD] = source_action[SOURCE_PAIR_RECORD]
    return action, slot


def target_bone_depth(rig, target_name):
    depth = 0
    bone = rig.data.bones[target_name]
    while bone.parent:
        depth += 1
        bone = bone.parent
    return depth


def plain_target_bones(rig, mapping):
    """Mapped controls whose evaluated pose is exactly what is assigned: no constraints and no
    drivers on their transforms, so a child can be solved from them without a depsgraph update."""
    driven = set()
    if rig.animation_data:
        for fcurve in rig.animation_data.drivers:
            name = get_pose_bone_name(fcurve.data_path)
            if name:
                driven.add(name)
    return {
        target_name for target_name, _source, _kind in mapping
        if not rig.pose.bones[target_name].constraints and target_name not in driven
    }


def target_dependencies(rig, target_names):
    """Bones each target's evaluated parent space depends on: ancestors, plus the bones
    their constraints follow (Rigify routes many parents through ORG/MCH copy constraints)."""
    pose_bones = rig.pose.bones
    upstream = {}

    def bones_above(name):
        if name in upstream:
            return upstream[name]
        upstream[name] = found = set()
        pose_bone = pose_bones[name]
        sources = [] if pose_bone.parent is None else [pose_bone.parent.name]
        for constraint in pose_bone.constraints:
            if getattr(constraint, 'target', None) == rig and getattr(constraint, 'subtarget', ''):
                sources.append(constraint.subtarget)
        for source in sources:
            if source in pose_bones:
                found.add(source)
                found |= bones_above(source)
        return found

    result = {}
    for name in target_names:
        parent = pose_bones[name].parent
        result[name] = set() if parent is None else {parent.name} | bones_above(parent.name)
    return result


def apply_retargeted_pose(context, source_armature, rig, mapping,
                          source_matrix=None, rig_matrix=None, plain=frozenset(),
                          dependencies=None):
    """Pose the mapped controls to follow the source. mapping must be ordered parents first.

    source_matrix and rig_matrix pin the object transforms the bake started with.
    """
    if dependencies is None:
        dependencies = target_dependencies(rig, [entry[0] for entry in mapping])
    source_matrix = source_armature.matrix_world if source_matrix is None else source_matrix
    rig_matrix = rig.matrix_world if rig_matrix is None else rig_matrix
    rig_world_inverse = rig_matrix.inverted_safe()
    solved = {}
    targets = {}
    changed = set()
    for target_name, source_name, _transform_type in mapping:
        pose_bone = rig.pose.bones[target_name]
        source_pose = source_armature.pose.bones[source_name]
        source_rest_world = source_matrix @ source_armature.data.bones[source_name].matrix_local
        source_pose_world = source_matrix @ source_pose.matrix
        target_rest_world = rig_matrix @ pose_bone.bone.matrix_local
        pose_delta = source_pose_world @ source_rest_world.inverted_safe()
        target_pose = rig_world_inverse @ pose_delta @ target_rest_world

        parent = pose_bone.parent
        if parent is not None and parent.name in solved:
            # The parent already holds a known pose, so solve locally instead of re-evaluating.
            pose_bone.matrix_basis = pose_bone.bone.convert_local_to_pose(
                target_pose, pose_bone.bone.matrix_local,
                parent_matrix=solved[parent.name],
                parent_matrix_local=parent.bone.matrix_local,
                invert=True)
        else:
            # Assigning pose_bone.matrix reads the evaluated parent chain, so it must see
            # anything it depends on that was posed since the last update. Driver
            # dependencies are not traced; the convergence check catches those.
            if not changed.isdisjoint(dependencies[target_name]):
                context.view_layer.update()
                changed.clear()
            pose_bone.matrix = target_pose
        changed.add(target_name)
        if target_name in plain:
            solved[target_name] = target_pose
        targets[target_name] = target_pose
    context.view_layer.update()
    return targets


def pose_converged(rig, targets, tolerance=1e-4):
    for target_name, target_pose in targets.items():
        matrix = rig.pose.bones[target_name].matrix
        for row in range(3):
            for column in range(4):
                if abs(matrix[row][column] - target_pose[row][column]) > tolerance * max(
                        1.0, abs(target_pose[row][column])):
                    return False
    return True


def insert_retarget_keyframes(rig, mapping, frame, previous=None):
    """Key the mapped controls. previous holds each control's last keyed rotation, so a
    rotation near 180 degrees keeps one sign/winding rather than interpolating the long way."""
    for target_name, _source_name, _transform_type in mapping:
        pose_bone = rig.pose.bones[target_name]
        pose_bone.keyframe_insert(data_path='location', frame=frame, group=target_name)
        rotation_path = {
            'QUATERNION': 'rotation_quaternion',
            'AXIS_ANGLE': 'rotation_axis_angle',
        }.get(pose_bone.rotation_mode, 'rotation_euler')
        if previous is not None and rotation_path != 'rotation_axis_angle':
            rotation = getattr(pose_bone, rotation_path).copy()
            if target_name in previous:
                rotation.make_compatible(previous[target_name])
                setattr(pose_bone, rotation_path, rotation)
            previous[target_name] = rotation
        pose_bone.keyframe_insert(data_path=rotation_path, frame=frame, group=target_name)
        pose_bone.keyframe_insert(data_path=rotation_path, frame=frame, group=target_name)
        pose_bone.keyframe_insert(data_path='scale', frame=frame, group=target_name)


def bake_retargeted_action(context, source_armature, rig, mapping, source_action,
                           source_slot, frame_start, frame_end,
                           source_matrix=None, rig_matrix=None):
    action, slot = create_output_action(rig, source_action)
    rig.animation_data_create()
    rig.animation_data.action = action
    rig.animation_data.action_slot = slot
    # The fresh action keys nothing yet, so whatever the previous clip left on the controls
    # (a posed finger master, an IK switch) would be baked into this one as compensation.
    b_fun.rest_pose_channels(rig)
    b_fun.key_ik_fk(rig, frame_start)

    ordered_mapping = sorted(
        mapping, key=lambda entry: target_bone_depth(rig, entry[0]))
    plain = plain_target_bones(rig, ordered_mapping)
    dependencies = target_dependencies(rig, [entry[0] for entry in ordered_mapping])
    previous_rotations = {}
    try:
        for frame in range(frame_start, frame_end + 1):
            context.scene.frame_set(frame)
            context.view_layer.update()
            # Assigning pose_bone.matrix is only approximate for bones driven by
            # constraints/drivers, so repeat until the evaluated pose matches.
            for _ in range(3):
                targets = apply_retargeted_pose(
                    context, source_armature, rig, ordered_mapping,
                    source_matrix, rig_matrix, plain, dependencies)
                if pose_converged(rig, targets):
                    break
            insert_retarget_keyframes(rig, ordered_mapping, frame, previous_rotations)
    except Exception:
        rig.animation_data.action = None
        bpy.data.actions.remove(action)
        raise

    action.use_fake_user = True
    return action, slot


def retarget_animation_actions(context, source_armature, rig, mapping,
                               set_anim_length=True,
                               action_names=None):
    with b_fun.forced_pose_position(source_armature, rig), b_fun.muted_deformers(source_armature, rig):
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
    # Object-level keys in a source action must not shift the frame the bones are compared in.
    source_matrix = source_armature.matrix_world.copy()
    rig_matrix = rig.matrix_world.copy()

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
        with Progress(context, len(source_actions), 'Retargeting') as progress:
            for source_action, slot, first_frame, last_frame, _matched_count in source_actions:
                progress.step(source_action.name)
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
                    slot, frame_start, frame_end, source_matrix, rig_matrix)
                output_actions.append(action)
                clean_action(action, action_slot)
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
        source_armature.matrix_world = source_matrix

        if not succeeded:
            context.scene.frame_start = original_frame_start
            context.scene.frame_end = original_frame_end
        context.scene.frame_set(original_frame)
        activate_object(context, rig, 'OBJECT')


class RetargetAnimationOperator(bpy.types.Operator):
    """Retarget source actions onto the selected Rigify rig."""
    bl_idname = 'object.arsenal_retarget_animation'
    bl_label = 'Retarget animation'
    bl_description = ('Bake imported source actions onto the selected Rigify controls using the bone mapping; '
                      'the Remove original actions option deletes the source actions afterwards')
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

    @completion('Retarget')
    def execute(self, context):
        backup_collection = None
        collection_was_hidden = False
        if len(context.selected_objects) == 1:
            rig = context.object
            source_armature, backup_collection = find_retarget_backup(rig)
            if not source_armature:
                report(self, {'ERROR'}, 'No saved source armature was found for this Rigify rig.')
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
                report(self, {'WARNING'}, f'Skipped {len(missing)} unresolved animation mappings.')
            if not mapping:
                report(self, {'ERROR'}, 'No animation bone mappings matched the source skeleton and Rigify rig.')
                return {'CANCELLED'}

            actions = retarget_animation_actions(
                context, source_armature, rig, mapping,
                set_anim_length=self.set_anim_length)
        except Exception as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            if backup_collection:
                backup_collection.hide_viewport = collection_was_hidden

        report(self, {'INFO'}, f'Retargeted {len(actions)} actions onto {rig.name}.')
        if self.remove_source_actions and backup_collection:
            removed = 0
            for output in actions:
                source = bpy.data.actions.get(output.get('arsenal_source_action', ''))
                if source and source not in actions:
                    bpy.data.actions.remove(source)
                    removed += 1
            report(self, {'INFO'}, f'Removed {removed} original source actions.')

        # Outputs keep the source name once it is free, otherwise the rig_ name stays to avoid clashes.
        for output in actions:
            source_name = output.get('arsenal_source_action', '')
            if source_name and not bpy.data.actions.get(source_name):
                output.name = source_name
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)