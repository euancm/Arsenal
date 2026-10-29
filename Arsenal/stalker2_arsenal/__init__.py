bl_info = {
    "name": "Stalker 2 Arsenal",
    "author": "euanm.com, based on OneClickRig by Artem Poletsky",
    "version": (1, 0, 0),
    "blender": (5, 2, 2),
    "location": "View3D > Sidebar > STALKER 2",
    "description": "Import STALKER 2 animations, generate a Rigify rig, and retarget actions",
    "warning": "",
    "wiki_url": "",
    "category": "Rigging",
}

if "bpy" in locals():
    import importlib
    importlib.reload(notifications)
    importlib.reload(generate_metarig)
    importlib.reload(convert_to_rigify)
    importlib.reload(retarget_animation)
    importlib.reload(panel)
    importlib.reload(mapping_editor)
    importlib.reload(animation)
    importlib.reload(stalker2_animation_importer)
    importlib.reload(import_weapon)
    importlib.reload(export_skeleton)
    importlib.reload(export_static_mesh)
    importlib.reload(export_animation)
    importlib.reload(export_unreal)
    importlib.reload(weapon_presets)
    importlib.reload(weapon_cfg)
    importlib.reload(debug_report)
    importlib.reload(setup_panel)
else:
    from . import notifications
    from . import generate_metarig
    from . import convert_to_rigify
    from . import retarget_animation
    from . import panel
    from . import mapping_editor
    from . import animation
    from . import stalker2_animation_importer
    from . import import_weapon
    from . import export_skeleton
    from . import export_static_mesh
    from . import export_animation
    from . import export_unreal
    from . import weapon_presets
    from . import weapon_cfg
    from . import debug_report
    from . import setup_panel
import bpy

classes = (
    stalker2_animation_importer.STALKER2_AnimationImporterProperties,
    *setup_panel.CLASSES,
    *import_weapon.CLASSES,
    stalker2_animation_importer.STALKER2_PT_animation_importer_help,
    stalker2_animation_importer.STALKER2_OT_create_base_skeleton,
    stalker2_animation_importer.STALKER2_OT_scan_animations,
    stalker2_animation_importer.STALKER2_OT_import_animations,
    stalker2_animation_importer.STALKER2_OT_import_weapon,
    stalker2_animation_importer.STALKER2_OT_import_new_animations,
    stalker2_animation_importer.STALKER2_PT_animation_importer,
    generate_metarig.GenerateMetarigOperator,
    convert_to_rigify.ConvertToRigifyByMappingOperator,
    retarget_animation.RetargetAnimationOperator,
    animation.AddKeyFrameOperator,
    animation.BakeAnimationOperator,
    panel.ARSENAL_PT_AnimationPanel,
    panel.ARSENAL_PT_MainPanel,
    mapping_editor.MappingEntry,
    mapping_editor.GenerateMappingGuessOperator,
    mapping_editor.GenerateWeaponMappingGuessOperator,
    mapping_editor.SnapWeaponRigOperator,
    mapping_editor.CreateMappingOperator,
    mapping_editor.ARSENAL_PT_BoneMappingsPanel,
    mapping_editor.ARSENAL_IU_Props,
    mapping_editor.MappingRemoveEntryOperator,
    mapping_editor.MappingAddEntryOperator,
    mapping_editor.SaveMappingOperator,
    mapping_editor.RemoveMappingOperator,
    mapping_editor.AddPrefixOperator,
    *export_animation.CLASSES,
    *export_unreal.CLASSES,
    *weapon_cfg.CLASSES,
    *debug_report.CLASSES,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.stalker2_animation_importer = bpy.props.PointerProperty(
        type = stalker2_animation_importer.STALKER2_AnimationImporterProperties
    )
    bpy.types.Scene.arsenal_export = bpy.props.PointerProperty(type = export_animation.ARSENAL_ExportProps)
    bpy.types.Scene.arsenal_cfg = bpy.props.PointerProperty(type = weapon_cfg.ARSENAL_WeaponCfg)
    bpy.types.Scene.arsenal_setup = bpy.props.PointerProperty(type = setup_panel.ARSENAL_SetupProps)

    bpy.types.Scene.arsenal_ui = bpy.props.PointerProperty(type = mapping_editor.ARSENAL_IU_Props)

def unregister():
    del bpy.types.Scene.stalker2_animation_importer
    del bpy.types.Scene.arsenal_export
    del bpy.types.Scene.arsenal_cfg
    del bpy.types.Scene.arsenal_setup
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.arsenal_ui

if __name__ == "__main__":
    register()
