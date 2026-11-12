"""Test custom upgrade trees in a disposable Blender scene.

blender --background --factory-startup --python-exit-code 1 --python test_weapon_upgrades.py
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import export_unreal, weapon_cfg, weapon_upgrades
from stalker2_arsenal.weapon_presets import PRESETS


class UpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon.register()

    @classmethod
    def tearDownClass(cls):
        addon.unregister()

    def setUp(self):
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new('Custom upgrade tests')
        bpy.context.window.scene = self.scene
        self.cfg = self.scene.arsenal_cfg
        self.images = set(bpy.data.images)
        self.addCleanup(self.cleanup)
        self.info = {'cfg': self.cfg, 'sid': 'GunTest_HG', 'weapon_id': 'Test', 'mod': 'TestMod',
                     'mount': '/TestMod', 'player_sid': 'GunTest_HG_Player', 'parts': [], 'magazines': [],
                     'world_mesh': "StaticMesh'/TestMod/SM_Test.SM_Test'",
                     'skeletal_mesh': "SkeletalMesh'/TestMod/SK_Test.SK_Test'",
                     'animation_dir': '/TestMod/Animations/pt/test', 'anim_name': 'test'}

    def cleanup(self):
        bpy.context.window.scene = self.previous
        bpy.data.scenes.remove(self.scene, do_unlink=True)
        for image in list(bpy.data.images):
            if image not in self.images:
                bpy.data.images.remove(image, do_unlink=True)

    def custom(self):
        self.cfg.keep_upgrades = False
        return self.cfg.upgrades

    def test_base_tree_is_unchanged_and_does_not_generate_custom_prototypes(self):
        self.assertEqual(weapon_upgrades.upgrade_sids(self.info), PRESETS['TemplatePistol']['upgrades'])
        self.assertEqual(weapon_upgrades.files(self.info), {})
        self.assertEqual(weapon_upgrades.localization_entries(self.info), [])
        self.assertEqual(weapon_upgrades.export_images(self.info), [])
        for sid in PRESETS['TemplatePistol']['upgrades']:
            self.assertIn('= ' + sid, weapon_cfg.general_setup(self.info))

    def test_every_template_seeds_complete_layout_and_preserves_defaults(self):
        for template, preset in PRESETS.items():
            with self.subTest(template=template):
                self.cfg.setup_template = template
                self.cfg.keep_upgrades = False
                weapon_upgrades.seed_tree(self.cfg)
                self.assertEqual([item.template_sid for item in self.cfg.upgrades], preset['upgrades'])
                rows = weapon_upgrades.collect(self.info)
                names = {row['settings'].name for row in rows}
                for row in rows:
                    item, base, values = row['settings'], row['base'], row['values']
                    self.assertEqual(item.base_cost, float(base['BaseCost'].rstrip('f')))
                    self.assertEqual(item.horizontal, int(base['HorizontalPosition']))
                    self.assertEqual(item.target_part, base['UpgradeTargetPart'].split('::')[-1])
                    self.assertEqual([e.prototype for e in item.effects], base['EffectPrototypeSIDs'])
                    self.assertTrue(set(values['required']) <= names)
                    self.assertTrue(all(not effect.custom for effect in item.effects))
                files = weapon_upgrades.files(self.info)
                text = '\n'.join(files.values())
                self.assertEqual(text.count('SID = GunTest_Upgrade_'), len(rows))
                for row in rows:
                    for name in row['values']['required'] + row['values']['blocking']:
                        self.assertIn('= GunTest_Upgrade_' + name, text)

    def test_toggling_base_tree_retains_custom_edits_and_images(self):
        items = self.custom()
        items[0].text_name = 'My upgrade'
        items[0].base_cost = 77
        items[0].image = bpy.data.images.new('Upgrade illustration', width=100, height=60, alpha=True)
        image = items[0].image
        self.cfg.keep_upgrades = True
        self.assertEqual(weapon_upgrades.files(self.info), {})
        self.cfg.keep_upgrades = False
        self.assertEqual(items[0].text_name, 'My upgrade')
        self.assertEqual(items[0].base_cost, 77)
        self.assertEqual(items[0].image, image)

    def test_custom_effect_values_export_mod_owned_sids_and_preserve_source(self):
        items = self.custom()
        item = items[1]
        original = item.effects[0].prototype
        item.effects[0].custom = True
        item.effects[0].prototype = 'DamagePos20Effect'
        item.effects[0].value_min = 15
        item.effects[0].value_max = 15
        self.assertEqual(bpy.ops.object.arsenal_cfg_upgrade_edit(action='ADD_EFFECT'), {'FINISHED'})
        effect = items[0].effects[-1]
        effect.prototype = 'RecoilDown20Effect'
        effect.custom = True
        effect.value_min = effect.value_max = -20
        text = '\n'.join(weapon_upgrades.files(self.info).values())
        self.assertIn('{refurl=@BaseGame/EffectPrototypes.cfg;refkey=DamagePos20Effect}', text)
        self.assertIn('ValueMin = 15.0%', text)
        self.assertIn('ValueMax = -20.0%', text)
        self.assertIn('= GunTest_Upgrade_Barrel_1_Effect1', text)
        self.assertEqual(weapon_upgrades.DEFAULTS['effects'][original]['ValueMin'], '25%')

    def test_invalid_dependencies_and_effects_block_export(self):
        items = self.custom()
        first, second = items[0], items[1]
        for value in (first.name, 'DoesNotExist', second.name + ',' + second.name):
            with self.subTest(value=value):
                first.required = value
                with self.assertRaises(RuntimeError):
                    weapon_upgrades.collect(self.info)
        first.required = second.name
        second.required = first.name
        with self.assertRaisesRegex(RuntimeError, 'cycle'):
            weapon_upgrades.collect(self.info)
        first.required = ''
        second.required = ''
        first.effects[0].custom = True
        first.effects[0].value_min, first.effects[0].value_max = 10, 5
        with self.assertRaisesRegex(RuntimeError, 'Min <= Max'):
            weapon_upgrades.collect(self.info)
        first.effects[0].value_min = 0
        first.effects[0].prototype = 'CanToggleOffsetAiming'
        with self.assertRaisesRegex(RuntimeError, 'numerical'):
            weapon_upgrades.collect(self.info)

    def test_rename_or_remove_referenced_upgrade_requires_repair(self):
        items = self.custom()
        items[1].name = items[0].name
        with self.assertRaisesRegex(RuntimeError, 'unique'):
            weapon_upgrades.collect(self.info)
        weapon_upgrades.seed_tree(self.cfg)
        self.cfg.active_upgrade = 1
        bpy.ops.object.arsenal_cfg_upgrade_edit(action='REMOVE')
        with self.assertRaisesRegex(RuntimeError, 'other IDs'):
            weapon_upgrades.collect(self.info)

    def test_empty_custom_tree_stays_empty_until_explicit_reset_or_add(self):
        items = self.custom()
        items.clear()
        self.assertEqual(weapon_upgrades.upgrade_sids(self.info), [])
        self.cfg.keep_upgrades = True
        self.cfg.keep_upgrades = False
        self.assertFalse(items)
        bpy.ops.object.arsenal_cfg_upgrade_edit(action='ADD')
        self.assertEqual(len(items), 1)
        bpy.ops.object.arsenal_cfg_upgrade_edit(action='REMOVE')
        bpy.ops.object.arsenal_cfg_upgrade_edit(action='ADD')
        self.assertEqual(len(items), 1)
        bpy.ops.object.arsenal_cfg_upgrade_edit(action='RESET')
        self.assertEqual(len(items), len(PRESETS['TemplatePistol']['upgrades']))

    def test_laser_gate_uses_custom_upgrade_and_custom_attachment_reference(self):
        self.custom()
        self.cfg.allow_laser = True
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('[0] = GunTest_Upgrade_Attachment_Laser', text)
        text = '\n'.join(weapon_upgrades.files(dict(self.info, attachments=[
            {'template': 'EN_Laser_1', 'sid': 'GunTest_AttachLaser'}])).values())
        self.assertIn('[0] = GunTest_AttachLaser', text)
        self.assertNotIn('[0] = EN_Laser_1', text)

    def test_localization_and_module_image_export_are_packed_and_mod_owned(self):
        item = self.custom()[0]
        item.text_name = 'My laser'
        item.text_description = 'Line 1\\nLine 2'
        item.text_language = 'fr'
        item.text_name = 'Mon laser'
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'module.png')
            image = bpy.data.images.new('Selected illustration', width=80, height=40, alpha=True)
            image.file_format = 'PNG'
            image.save(filepath=path)
            bpy.ops.arsenal.inventory_image_file(filepath=path, upgrade_index=0,
                                                magazine_index=-1, attachment_index=-1, family='upgrade')
            self.assertEqual(tuple(item.image.size), (80, 40))
            self.assertIsNotNone(item.image.packed_file)
            info = dict(self.info, output_root=folder)
            entries = weapon_cfg.localization_entries(info)
            name = next(e for e in entries if e['SID'] == 'sid_upgrades_GunTest_Upgrade_Attachment_Laser_name')
            self.assertEqual(name['LanguagesToLocalizedStrings'],
                             {'ELocalizationLanguage::English': 'My laser', 'ELocalizationLanguage::French': 'Mon laser'})
            images = weapon_upgrades.export_images(info)
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0]['family'], 'upgrade_module')
            self.assertTrue(Path(folder, images[0]['file']).is_file())
            text = '\n'.join(weapon_upgrades.files(info).values())
            self.assertIn('Text = ' + name['SID'], text)
            self.assertIn(images[0]['asset'], text)
            bpy.ops.object.arsenal_cfg_upgrade_edit(action='CLEAR_IMAGE')
            self.assertIsNone(item.image)
            self.assertIn('Image = ' + weapon_upgrades.prototype(item)['Image'],
                          '\n'.join(weapon_upgrades.files(info).values()))

    def test_custom_cfg_files_and_manifest_include_upgrade_images_and_text(self):
        item = self.custom()[0]
        item.text_name = 'Custom upgrade'
        item.image = bpy.data.images.new('Module', width=64, height=64, alpha=True)
        info = dict(self.info, attachments=[])
        files = weapon_cfg.cfg_files(info)
        self.assertTrue(any(path.endswith('TestUpgradePrototypes.cfg') for path in files))
        self.assertTrue(any(path.endswith('TestUpgradeEffects.cfg') for path in files))
        with tempfile.TemporaryDirectory() as folder:
            static = str(Path(folder) / 'SM_Test.fbx')
            Path(static).touch()
            self.scene.arsenal_export.output_folder = folder
            self.scene.arsenal_export.unreal_mount = 'TestMod'
            info['output_root'] = folder
            rig = SimpleNamespace(data=SimpleNamespace(bones={'Weapon': SimpleNamespace()}))
            with patch.object(export_unreal.animation_export, '_build_static_plan',
                              return_value=(rig, None, {}, [('test', 'SM_Test', static)])), \
                    patch.object(export_unreal.animation_export, 'weapon_name', return_value='test'), \
                    patch.object(export_unreal.static_mesh, 'plan_static_meshes', return_value=('test', [])), \
                    patch.object(export_unreal.static_mesh, 'classify_meshes',
                                 return_value=(SimpleNamespace(material_slots=[]), [], [])), \
                    patch.object(export_unreal.export_skeleton, 'plan_skeleton', side_effect=ValueError('no donor')), \
                    patch.object(weapon_cfg, 'build_context', return_value=info):
                export_unreal.write_unreal_import(bpy.context)
            manifest = json.loads(Path(folder, 'import_test.json').read_text())
            self.assertEqual(manifest['ui_images'][0]['family'], 'upgrade_module')
            self.assertEqual(manifest['localization'][0]['SID'], 'sid_upgrades_GunTest_Upgrade_Attachment_Laser_name')

    def test_custom_upgrade_settings_survive_blend_round_trip(self):
        item = self.custom()[0]
        item.text_name = 'Persistent upgrade'
        item.effects[0].custom = True
        item.effects[0].value_min = item.effects[0].value_max = -12
        item.required_items = 'CustomBlueprint'
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'tree.blend')
            bpy.data.libraries.write(path, {self.scene})
            with bpy.data.libraries.load(path, link=False) as (_available, loaded):
                loaded.scenes = [self.scene.name]
            restored = loaded.scenes[0]
            try:
                cfg = restored.arsenal_cfg
                self.assertFalse(cfg.keep_upgrades)
                self.assertEqual(cfg.upgrades[0].text_name, 'Persistent upgrade')
                self.assertEqual(cfg.upgrades[0].effects[0].value_min, -12)
                self.assertEqual(cfg.upgrades[0].required_items, 'CustomBlueprint')
            finally:
                bpy.data.scenes.remove(restored, do_unlink=True)

    def test_custom_tree_panel_wires_each_button_with_explicit_actions_and_targets(self):
        self.custom()

        class Layout:
            def __init__(self):
                self.buttons = []

            def row(self, **kwargs):
                return self

            box = column = row

            def label(self, **kwargs):
                pass

            def prop(self, *args, **kwargs):
                pass

            def template_list(self, *args, **kwargs):
                pass

            def operator(self, name, **kwargs):
                properties = SimpleNamespace(action='REMOVE_EFFECT', magazine_index=8,
                                             attachment_index=8, upgrade_index=8, remove=True)
                self.buttons.append((name, properties))
                return properties

        layout = Layout()
        panel = SimpleNamespace(layout=layout, props=lambda *args: None)
        weapon_cfg.ARSENAL_PT_CfgAttachments.draw(panel, bpy.context)
        actions = [properties.action for name, properties in layout.buttons
                   if name == 'object.arsenal_cfg_upgrade_edit']
        self.assertEqual(actions, ['RESET', 'ADD', 'REMOVE', 'CLEAR_IMAGE', 'ADD_EFFECT', 'REMOVE_EFFECT'])
        image = next(properties for name, properties in layout.buttons if name == 'arsenal.inventory_image_file')
        self.assertEqual((image.upgrade_index, image.magazine_index, image.attachment_index), (0, -1, -1))
        clear_text = next(properties for name, properties in layout.buttons
                          if name == 'object.arsenal_cfg_clear_text')
        self.assertEqual((clear_text.upgrade_index, clear_text.magazine_index, clear_text.attachment_index),
                         (0, -1, -1))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
