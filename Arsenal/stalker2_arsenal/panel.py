import bpy


class ARSENAL_PT_AnimationPanel(bpy.types.Panel):
    """
    Animation panel
    """
    bl_label = 'Animation Tools'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 6

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
    bl_label = '3. Retarget'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 3

    def draw_object(self, col, context):
        col.operator('object.arsenal_retarget_animation', text='Retarget Animation')

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        if not context.object:
            return

        if context.object.mode == 'OBJECT':
            self.draw_object(col, context)
