"""Check registration, reload and bundled workflow resources in a disposable Blender scene.

blender --background --factory-startup --python-exit-code 1 --python test_addon_registration.py
"""
import ast
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import import_weapon, map_bones, mapping_editor, retarget_animation


class AddonRegistrationTests(unittest.TestCase):
    def test_registration_reload_and_unregister(self):
        properties = (
            'stalker2_animation_importer', 'arsenal_export', 'arsenal_cfg',
            'arsenal_setup', 'arsenal_ui', 'arsenal_inventory', 'arsenal_sockets',
        )
        for _ in range(2):
            addon.register()
            try:
                for name in properties:
                    self.assertTrue(hasattr(bpy.types.Scene, name), name)
                self.assertIn(
                    'object.arsenal_convert_to_rigify_by_mapping',
                    {cls.bl_idname for cls in addon.classes if issubclass(cls, bpy.types.Operator)},
                )
                self.assertNotIn('active_template', bpy.context.scene.arsenal_ui.bl_rna.properties)
            finally:
                addon.unregister()
            for name in properties:
                self.assertFalse(hasattr(bpy.types.Scene, name), name)
            importlib.reload(addon)

    def test_relative_imports_exist(self):
        package = Path(addon.__file__).parent
        for source in package.glob('*.py'):
            tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    names = [node.module.split('.')[0]] if node.module else [
                        alias.name for alias in node.names if alias.name != 'bl_info'
                    ]
                    for name in names:
                        self.assertTrue((package / (name + '.py')).is_file(), (source.name, name))

    def test_all_addon_operators_have_useful_tooltips(self):
        for cls in addon.classes:
            if issubclass(cls, bpy.types.Operator):
                with self.subTest(operator=cls.bl_idname):
                    self.assertGreater(len(cls.bl_description), 30)
                    self.assertNotIn('Undocumented', cls.bl_description)

    def test_multi_action_tooltips_explain_the_actual_button(self):
        from stalker2_arsenal import inventory_images, weapon_cfg
        image = inventory_images.ARSENAL_OT_InventoryImage
        self.assertIn('Clear', image.description(None, SimpleNamespace(clear=True)))
        self.assertIn('Render an inventory image', image.description(None, SimpleNamespace(clear=False)))
        self.assertIn('Scene_ArsenalInventory', image.description(None, SimpleNamespace(clear=False)))
        attachment = weapon_cfg.ARSENAL_OT_CfgAttachmentEdit
        self.assertIn('Remove', attachment.description(None, SimpleNamespace(remove=True)))
        self.assertIn('Add', attachment.description(None, SimpleNamespace(remove=False)))

    def test_inventory_scene_controls_are_not_registered(self):
        self.assertNotIn('arsenal.inventory_scene',
                         {cls.bl_idname for cls in addon.classes if issubclass(cls, bpy.types.Operator)})
        self.assertNotIn('ARSENAL_PT_InventoryScene', {cls.__name__ for cls in addon.classes})

    def test_simplified_workflow_panels(self):
        from stalker2_arsenal import export_animation, setup_panel, stalker2_animation_importer

        class Layout:
            def __init__(self):
                self.properties, self.operators = [], []

            def prop(self, _owner, name, **_kwargs):
                self.properties.append(name)

            def operator(self, name, **_kwargs):
                self.operators.append(name)
                return SimpleNamespace()

            def label(self, **_kwargs):
                pass

            def row(self, **_kwargs):
                return self

            def column(self, **_kwargs):
                return self

        addon.register()
        try:
            layout = Layout()
            from unittest.mock import patch
            with patch.object(export_animation, 'find_export_rig', return_value=(None, None)):
                export_animation.ARSENAL_PT_ExportPanel.draw(SimpleNamespace(layout=layout), bpy.context)
            self.assertEqual(layout.properties, ['output_folder'])
            self.assertEqual(layout.operators, ['object.arsenal_export_all'])
            setup_panel.ARSENAL_PT_SetupPanel.draw(SimpleNamespace(layout=layout), bpy.context)
            self.assertNotIn('dry_run', layout.properties)
            self.assertNotIn('export_additive', layout.properties)
            stalker2_animation_importer.STALKER2_PT_animation_importer.draw(
                SimpleNamespace(layout=layout), bpy.context)
            self.assertNotIn('stalker2.import_new_animations', layout.operators)
            self.assertNotIn('stalker2.import_new_animations',
                             {cls.bl_idname for cls in addon.classes if issubclass(cls, bpy.types.Operator)})
        finally:
            addon.unregister()

    def test_required_mapping_resources(self):
        self.assertTrue((Path(addon.__file__).parent / 'resources' / 'inventory_scene.blend').is_file())
        reference = dict(map_bones.load_mapping('uemannequin_rigify'))
        self.assertEqual(reference['hand_l'], 'hand.L')
        self.assertTrue(map_bones.load_mapping('rigify_uemannequin', anim=True))
        self.assertEqual(
            mapping_editor.build_mapping_guesses(['jnt_l_hand', 'jnt_r_hand'], ['hand.L', 'hand.R']),
            {'jnt_l_hand': 'hand.L', 'jnt_r_hand': 'hand.R'},
        )
        bpy.ops.object.armature_add()
        source = bpy.context.object
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            source.data.edit_bones[0].name = 'jnt_l_hand'
            bpy.ops.object.mode_set(mode='OBJECT')
            rig = bpy.data.objects.new('Test rig', bpy.data.armatures.new('Test rig'))
            bpy.context.scene.collection.objects.link(rig)
            try:
                bpy.context.view_layer.objects.active = rig
                bpy.ops.object.mode_set(mode='EDIT')
                bone = rig.data.edit_bones.new('hand_fk.L')
                bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
                bpy.ops.object.mode_set(mode='OBJECT')
                resolved, _missing = retarget_animation.resolve_animation_mapping(source, rig)
                self.assertIn(('hand_fk.L', 'jnt_l_hand', 'rot'), resolved)
            finally:
                data = rig.data
                bpy.data.objects.remove(rig, do_unlink=True)
                bpy.data.armatures.remove(data)
        finally:
            data = source.data
            bpy.data.objects.remove(source, do_unlink=True)
            bpy.data.armatures.remove(data)

    def test_shape_library_exists(self):
        with bpy.data.libraries.load(import_weapon.SHAPE_LIBRARY, link=False) as (source, _destination):
            self.assertTrue(source.objects)

    def test_gp37_finds_gp3_static_parts_but_keeps_gp37_skeleton(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'SK_gp37.FBX').touch()
            parts = root / 'AnimMesh'
            parts.mkdir()
            (parts / 'SM_wpn_gp3_SM_offset.FBX').touch()
            (parts / 'SM_wpn_gp3a_SM_offset.FBX').touch()
            skeleton, found = import_weapon.find_donor_files(folder, 'gp37')
            self.assertEqual(Path(skeleton).name, 'SK_gp37.FBX')
            self.assertEqual([(Path(path).name, joint) for path, joint in found],
                             [('SM_wpn_gp3_SM_offset.FBX', 'offset')])

    def test_templates_drive_setup_assets_and_ignore_legacy_category_override(self):
        from stalker2_arsenal import export_animation, setup_panel
        from stalker2_arsenal.weapon_presets import PRESETS
        addon.register()
        try:
            for key, preset in PRESETS.items():
                with self.subTest(template=key):
                    bpy.context.scene.arsenal_cfg.setup_template = key
                    setup_panel.apply_template_defaults(bpy.context.scene, key)
                    bpy.context.scene.arsenal_export.static_category = 'old_manual_category'
                    config = setup_panel.build_config(bpy.context)
                    self.assertEqual(config['anim_tokens'], [preset['animation']])
                    self.assertEqual(config['mesh_tokens'], [preset['mesh']])
                    self.assertEqual(export_animation.static_category(bpy.context.scene), preset['category'])
                    self.assertFalse(config['dry_run'])
                    self.assertFalse(config['export_additive'])
            for number, key in enumerate(
                    ('TemplatePistol', 'TemplateSMG', 'TemplateRifle', 'TemplateShotgun', 'TemplateSniper')):
                bpy.context.scene.arsenal_cfg['setup_template'] = number
                self.assertEqual(bpy.context.scene.arsenal_cfg.setup_template, key)
        finally:
            addon.unregister()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
