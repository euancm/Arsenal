import bpy


class SetUESceneSettingsOperator(bpy.types.Operator):
    """Set UE scene settings"""
    bl_idname = "object.arsenal_set_ue_scene_settings"
    bl_label = "Set UE settings"
    bl_options = {'REGISTER', 'UNDO'}
    #
    # @classmethod
    # def poll(cls, context):
    #     return (context.space_data.type == 'VIEW_3D')

    def execute(self, context):
        context.scene.unit_settings.scale_length = 0.01
        context.scene.render.fps = 30
        return {'FINISHED'}


class ARSENAL_PT_AnimationPanel(bpy.types.Panel):
    """
    Animation panel
    """
    bl_label = '4. Animation Tools'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            # and len(context.selected_objects) > 0
            and context.view_layer.objects.active
            and context.object.type == 'ARMATURE'
            and (context.object.mode == 'POSE'))


    def draw(self, context):
        col = self.layout.column()
        col.operator("anim.arsenal_add_keyframe", text = 'Add keyframe')
        col.operator("pose.constraints_clear", text = 'Clear constraints')
        col.operator("nla.bake")
        col.separator()
        col.operator("anim.arsenal_bake_animation", text = "Bake animation")
        col.operator_context = 'INVOKE_DEFAULT'



class ARSENAL_PT_MainPanel(bpy.types.Panel):
    """
    Addon panel
    """
    bl_label = '3. Rig & Retarget'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 2

    def draw_object(self, col, context):
        col.label(text='Rig generation')
        col.operator('object.arsenal_convert_to_rigify_by_mapping', text='Convert Character by Mapping')
        col.separator()
        col.label(text='Animation')
        col.operator('object.arsenal_retarget_animation', text='Retarget Animation')

    def draw_edit(self, col, context):
        col.label(text="Armature editing operators:")
        row = col.row()
        row.operator("armature.arsenal_arrange_bones")

        row = col.row()
        row.operator("armature.arsenal_clear_empty_bones")

        row = col.row()
        row.operator("armature.arsenal_swap_bones_weights")

        row = col.row()
        row.operator("armature.arsenal_merge_bones_with_vgroups")

    def draw_pose(self, col, context):
        col.label(text="Armature editing operators:")

        row = col.row()
        row.operator("armature.arsenal_swap_bones_weights")

        row = col.row()
        row.operator("armature.arsenal_merge_bones_with_vgroups")

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        if not context.object:
            return

        mode = context.object.mode
        if mode == 'OBJECT':
            self.draw_object(col, context)
        elif mode == 'EDIT':
            self.draw_edit(col, context)
        elif mode == 'POSE':
            self.draw_pose(col, context)
