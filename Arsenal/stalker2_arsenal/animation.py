import bpy
from . import bone_functions as bf

poseOps = bpy.ops.pose
animOps = bpy.ops.anim
nlaOps = bpy.ops.nla
armOps = bpy.ops.armature
objOps = bpy.ops.object

class AddKeyFrameOperator(bpy.types.Operator):
    """Add keyframe to retargeted animation"""
    bl_idname = "anim.arsenal_add_keyframe"
    bl_label = "add keyframe"
    bl_description = 'Apply the evaluated pose to the selected bones and key Location, Rotation and Scale at this frame'
    bl_options = {'REGISTER', 'UNDO'}

    # example_prop: bpy.props.BoolProperty(name="Example prop", default=False)

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active
            and context.object.mode == 'POSE')

    def execute(self, context):
        poseOps.visual_transform_apply()
        animOps.keyframe_insert_menu(type = 'LocRotScale')
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)

GRIP_BONES = ('upper_arm_parent', 'upper_arm_ik', 'upper_arm_ik_target', 'hand_ik')


def grip_paths(rig, action, slot, side):
    """(data_path, index) pairs of the IK arm channels keyed by `action` for one side."""
    from bpy_extras import anim_utils
    prefixes = tuple(f'pose.bones["{name}.{side}"]' for name in GRIP_BONES)
    channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
    if channelbag is None:
        return set()
    return {(curve.data_path, curve.array_index) for curve in channelbag.fcurves
            if curve.data_path.startswith(prefixes)}


def finger_paths(rig, side):
    """Include unkeyed masters too: otherwise another action's curl leaks into the copied grip."""
    import re
    names = [bone.name for bone in rig.pose.bones
             if re.fullmatch(rf'(?:thumb|f_(?:index|middle|ring|pinky))\.\d+(?:_master)?\.{side}(?:\.\d+)?'
                             rf'|palm\.{side}', bone.name)]
    return {(rig.pose.bones[name].path_from_id(prop), index)
            for name in names for prop, rest in bf.POSE_CHANNEL_RESTS
            for index in range(len(rest))}


def copy_grip(rig, source, target, side='L', channels='ARM'):
    """Hold the selected arm/finger channels at their first-frame values in `source`.

    The hand IK control follows the weapon, so constant keys keep the hand at the source grip
    relative to the weapon while the weapon moves. Returns the number of channels keyed."""
    from bpy_extras import anim_utils
    data = rig.animation_data
    previous = data.action, data.action_slot, bpy.context.scene.frame_current
    data.action = target
    target_slot = data.action_slot
    data.action = source
    source_slot = data.action_slot
    if source_slot is None or target_slot is None:
        data.action, data.action_slot = previous[0], previous[1]
        raise ValueError('Both actions need a slot for this rig')
    source_paths = grip_paths(rig, source, source_slot, side) if channels != 'FINGERS' else set()
    paths = source_paths | (grip_paths(rig, target, target_slot, side) if channels != 'FINGERS' else set())
    fingers = finger_paths(rig, side) if channels != 'ARM' else set()
    paths |= fingers
    if channels != 'FINGERS' and (f'pose.bones["upper_arm_parent.{side}"]["IK_FK"]', 0) not in source_paths:
        data.action, data.action_slot = previous[0], previous[1]
        raise ValueError(f'"{source.name}" does not key the {side} arm IK/FK switch')
    if not paths:
        data.action, data.action_slot = previous[0], previous[1]
        raise ValueError(f'No {side} hand controls found to copy')
    bpy.context.scene.frame_set(int(source.frame_range[0]))
    source_curves = {(curve.data_path, curve.array_index): curve
                     for curve in anim_utils.action_get_channelbag_for_slot(source, source_slot).fcurves}
    values = {}
    for path, index in paths:
        curve = source_curves.get((path, index))
        if curve:
            values[path, index] = curve.evaluate(source.frame_range[0])
            continue
        if (path, index) in fingers:
            values[path, index] = dict(bf.POSE_CHANNEL_RESTS)[path.rsplit('.', 1)[-1]][index]
            continue
        owner_path, bracket, key = path.rpartition('["')
        if bracket and path.endswith('"]'):
            # path_resolve returns Rigify parent-switch properties as strings like 'P1'.
            value = rig.path_resolve(owner_path)[key[:-2]]
        else:
            value = rig.path_resolve(path)
        values[path, index] = value[index] if hasattr(value, '__len__') else value
    data.action, data.action_slot = previous[0], previous[1]
    bpy.context.scene.frame_set(previous[2])

    channelbag = anim_utils.action_ensure_channelbag_for_slot(target, target_slot)
    start, end = target.frame_range
    for (path, index), value in sorted(values.items()):
        curve = channelbag.fcurves.find(path, index=index)
        group = curve.group.name if curve and curve.group else path.split('"')[1]
        if curve:
            channelbag.fcurves.remove(curve)
        curve = channelbag.fcurves.new(path, index=index, group_name=group)
        for frame in {start, end}:
            curve.keyframe_points.insert(frame, float(value), options={'FAST'})
        curve.update()
    return len(values)


class CopyGripOperator(bpy.types.Operator):
    """Hold an arm or fingers at another action's grip throughout the active action"""
    bl_idname = 'anim.arsenal_copy_grip'
    bl_label = 'Copy Hand Grip'
    bl_description = ('Copy a fixed arm IK grip, finger pose, or both from the first frame of another action. '
                      'Use Fingers Only to match aim-transition fingers without replacing the arm motion; '
                      'use Arm IK for donor offset-aim clips that still grip the donor weapon')
    bl_options = {'REGISTER', 'UNDO'}

    source: bpy.props.StringProperty(name='Source Action', default='idle_aim')
    side: bpy.props.EnumProperty(name='Side', items=(('L', 'Left', ''), ('R', 'Right', '')), default='L')
    channels: bpy.props.EnumProperty(
        name='Copy', default='ARM', items=(
            ('ARM', 'Arm IK', 'Hold the arm IK controls at the source grip'),
            ('FINGERS', 'Fingers Only', 'Copy finger and palm controls, including master curls; preserve the arm animation'),
            ('BOTH', 'Arm IK and Fingers', 'Copy both the arm IK grip and finger pose')))

    @classmethod
    def poll(cls, context):
        rig = context.object
        return (rig and rig.type == 'ARMATURE' and rig.animation_data and rig.animation_data.action
                and 'hand_ik.L' in rig.pose.bones)

    def execute(self, context):
        rig = context.object
        target = rig.animation_data.action
        source = bpy.data.actions.get(self.source)
        if source is None or source == target:
            self.report({'ERROR'}, f'Choose a source action other than "{target.name}"')
            return {'CANCELLED'}
        try:
            count = copy_grip(rig, source, target, self.side, self.channels)
        except ValueError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        context.view_layer.update()
        self.report({'INFO'}, f'Copied {count} {self.side} grip channels from "{source.name}" to "{target.name}"')
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop_search(self, 'source', bpy.data, 'actions')
        self.layout.prop(self, 'side', expand=True)
        self.layout.prop(self, 'channels')


class BakeAnimationOperator(bpy.types.Operator):
    """Bake whole animation before export"""
    bl_idname = "anim.arsenal_bake_animation"
    bl_label = "Bake animation for deform bones"
    bl_description = ('Bake the scene frame range onto deform bones, clear their constraints and delete '
                      'non-deform controls; use a disposable rig copy, not your editable weapon rig')
    bl_options = {'REGISTER', 'UNDO'}

    #example_prop: bpy.props.BoolProperty(name="Example prop", default=False)

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active
            and context.object.mode == 'POSE')

    def execute(self, context):
        rig = context.object;

        objOps.mode_set(mode='OBJECT')
        objOps.select_all(action='DESELECT')
        rig.select_set(True);
        bf.show_all_layers(rig)
        objOps.mode_set(mode='POSE')

        deform_bones = [];
        non_deform_bones = [];
        for b in rig.data.bones:
            if b.use_deform:
                deform_bones.append(b.name)
            else:
                non_deform_bones.append(b.name)


        bf.select_bones(rig, deform_bones)
        #context.view_layer.update()
        #rig.data.bones.active = rig.data.bones['pelvis']
        #context.view_layer.update()

        #print(context.scene.frame_start)
        #return {'FINISHED'}
        nlaOps.bake(frame_start = context.scene.frame_start,
        frame_end = context.scene.frame_end,
        only_selected = True,
        clear_constraints= True,
        visual_keying = True,
        #use_current_action = True,
        bake_types = {'POSE'})

        #


        bf.select_bones(rig, non_deform_bones)

        objOps.mode_set(mode = 'EDIT')
        armOps.delete()
        objOps.mode_set(mode = 'OBJECT')
        for name in deform_bones:
            bone = rig.data.bones[name]
            bf.set_array_indices(bone.layers, [0])


            #print(bone.layers[0])
        #objOps.mode_set(mode = 'EDIT')
        #armOps.select_all(action = 'SELECT')
        objOps.mode_set(mode = 'POSE')
        bf.switch_to_layer(rig.data, 0)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)
