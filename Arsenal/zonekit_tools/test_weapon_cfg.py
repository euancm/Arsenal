"""Regression tests for weapon CFG helpers.

Run with Blender:
blender --background --factory-startup --python-exit-code 1 --python test_weapon_cfg.py
"""
import os
import json
import sys
import unittest
import tempfile
from types import SimpleNamespace
from itertools import combinations
from unittest.mock import Mock, patch

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stalker2_arsenal import weapon_cfg
from stalker2_arsenal.weapon_cfg import detect_magazines


class Mesh:
    def __init__(self, name):
        self.name = name


class DetectMagazinesTests(unittest.TestCase):
    def detect_single_magazine(self, name):
        return detect_magazines([(Mesh(name), ())])[0]

    def test_detects_qualifier_before_mag(self):
        magazine = self.detect_single_magazine('e9_increasedmag_full')
        self.assertEqual(magazine['name'], 'Increased')

    def test_detects_qualifier_after_mag(self):
        magazine = self.detect_single_magazine('e9_mag_increased_full')
        self.assertEqual(magazine['name'], 'Increased')


class LocalizationExportTests(unittest.TestCase):
    def test_default_and_override_sids_match_exported_json(self):
        for override, stem in (('', 'GunTest'), ('CustomText', 'CustomText')):
            with self.subTest(override=override):
                cfg = SimpleNamespace(localization_sid=override, texts=[
                    SimpleNamespace(language='en', name='Test Weapon', description='Line 1\\nLine 2'),
                    SimpleNamespace(language='zh-Hans', name='\u6d4b\u8bd5', description=''),
                ])
                info = {'cfg': cfg, 'sid': 'GunTest'}
                entries = weapon_cfg.localization_entries(info)
                self.assertEqual(entries, [
                    {'SID': f'sid_items_{stem}_name', 'LanguagesToLocalizedStrings': {
                        'ELocalizationLanguage::English': 'Test Weapon',
                        'ELocalizationLanguage::ChineseSimplified': '\u6d4b\u8bd5'}},
                    {'SID': f'sid_items_{stem}_description', 'LanguagesToLocalizedStrings': {
                        'ELocalizationLanguage::English': 'Line 1\nLine 2'}},
                ])
                self.assertEqual(json.loads(weapon_cfg.localization_json(info)), entries)

    def test_all_supported_language_members_are_exported(self):
        cfg = SimpleNamespace(localization_sid='', texts=[
            SimpleNamespace(language=code, name=f'{member} name', description=f'{member} description')
            for code, member, _label in weapon_cfg.LANGUAGE_TABLE
        ])
        entries = weapon_cfg.localization_entries({'cfg': cfg, 'sid': 'GunTest'})
        for entry, suffix in zip(entries, ('name', 'description')):
            self.assertEqual(entry['LanguagesToLocalizedStrings'], {
                f'ELocalizationLanguage::{member}': f'{member} {suffix}'
                for _code, member, _label in weapon_cfg.LANGUAGE_TABLE})


class FireModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for cls_type in (weapon_cfg.ARSENAL_CfgText, weapon_cfg.ARSENAL_CfgMagazine,
                         weapon_cfg.ARSENAL_CfgAttachment,
                         weapon_cfg.ARSENAL_CfgUpgradeEffect, weapon_cfg.ARSENAL_CfgUpgrade,
                         weapon_cfg.ARSENAL_WeaponCfg):
            bpy.utils.register_class(cls_type)
        bpy.types.Scene.test_arsenal_cfg = bpy.props.PointerProperty(type=weapon_cfg.ARSENAL_WeaponCfg)

    @classmethod
    def tearDownClass(cls):
        del bpy.types.Scene.test_arsenal_cfg
        for cls_type in (weapon_cfg.ARSENAL_WeaponCfg, weapon_cfg.ARSENAL_CfgUpgrade,
                         weapon_cfg.ARSENAL_CfgUpgradeEffect, weapon_cfg.ARSENAL_CfgAttachment,
                         weapon_cfg.ARSENAL_CfgMagazine, weapon_cfg.ARSENAL_CfgText):
            bpy.utils.unregister_class(cls_type)

    def setUp(self):
        self.scene = bpy.data.scenes.new('FireModeTest')
        self.addCleanup(bpy.data.scenes.remove, self.scene)
        self.cfg = self.scene.test_arsenal_cfg
        self.info = {'cfg': self.cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'parts': [], 'magazines': []}

    def test_attachment_localization_uses_own_sids_and_language_settings(self):
        magazine = self.cfg.magazines.add()
        magazine.name = 'Extended'
        magazine.preinstalled = False
        magazine.text_name = 'Extended magazine'
        magazine.text_description = '30 rounds'
        magazine.text_language = 'fr'
        magazine.text_name = 'Chargeur'
        attachment = self.cfg.attachments.add()
        attachment.name = 'Quiet'
        attachment.text_name = 'Custom silencer'
        attachment.localization_sid = 'SharedSilencer'
        info = dict(self.info, magazines=[{'settings': magazine, 'name': magazine.name, 'preinstalled': False}],
                    attachments=[{'settings': attachment, 'sid': 'GunTest_AttachQuiet'}])
        entries = {entry['SID']: entry['LanguagesToLocalizedStrings']
                   for entry in weapon_cfg.localization_entries(info)}
        self.assertEqual(entries['sid_items_GunTest_MagExtended_name'], {
            'ELocalizationLanguage::English': 'Extended magazine',
            'ELocalizationLanguage::French': 'Chargeur'})
        self.assertEqual(entries['sid_items_GunTest_MagExtended_description'],
                         {'ELocalizationLanguage::English': '30 rounds'})
        self.assertEqual(entries['sid_items_SharedSilencer_name'],
                         {'ELocalizationLanguage::English': 'Custom silencer'})

    def test_preinstalled_magazine_text_is_not_exported_but_is_kept_for_later(self):
        magazine = self.cfg.magazines.add()
        magazine.text_name = 'Previously entered name'
        magazine.text_description = 'Previously entered description'
        magazine.localization_sid = 'OldOverride'
        info = dict(self.info, magazines=[
            {'settings': magazine, 'name': 'Default', 'preinstalled': True,
             'cost': 0, 'weight': 0, 'capacity': 15}])
        self.assertEqual(weapon_cfg.localization_entries(info), [])
        self.assertNotIn('LocalizationSID', weapon_cfg.attach_prototypes(info))
        info['magazines'][0]['preinstalled'] = False
        self.assertEqual(len(weapon_cfg.localization_entries(info)), 2)
        self.assertEqual(magazine.text_name, 'Previously entered name')

    def test_magazine_panel_only_shows_localization_for_purchasable_magazines(self):
        magazine = self.cfg.magazines.add()
        panel = SimpleNamespace(layout=Mock(), props=Mock())
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
        with patch.object(weapon_cfg, 'draw_localization') as draw, \
                patch('stalker2_arsenal.inventory_images.draw_images'):
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(panel, context)
            draw.assert_not_called()
            magazine.preinstalled = False
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(panel, context)
            self.assertEqual(draw.call_args.args[1], magazine)

    def test_custom_attachments_preserve_base_behaviour_and_use_mod_meshes(self):
        mesh = bpy.data.objects.new('Custom silencer', bpy.data.meshes.new('Custom silencer'))
        self.addCleanup(bpy.data.meshes.remove, mesh.data)
        self.addCleanup(bpy.data.objects.remove, mesh)
        item = self.cfg.attachments.add()
        item.name, item.mesh_object = 'Quiet', mesh
        item.kind = 'silencer'
        self.cfg.allow_laser = True
        items = weapon_cfg.collect_attachments(self.cfg, [(mesh, {'Weapon': 1})])
        items[0].update(sid='GunTest_AttachQuiet', mesh_path="StaticMesh'/Test/Quiet.Quiet'")
        info = dict(self.info, attachments=items)
        text = weapon_cfg.attach_prototypes(info)
        self.assertIn('refkey=EN_Silen_2', text)
        self.assertIn('MeshPrototypeSID = GunTest_AttachQuiet', text)
        self.assertIn('[0] = GunTest', text)
        setup = weapon_cfg.general_setup(info)
        self.assertIn('AttachPrototypeSID = GunTest_AttachQuiet', setup)
        self.assertNotIn('AttachPrototypeSID = EN_Silen_2', setup)
        self.assertIn('AttachPrototypeSID = EN_Laser_1', setup)
        layout = SimpleNamespace(label=Mock())
        weapon_cfg.ARSENAL_UL_CfgMagazines.draw_item(None, None, layout, None, item, None, None, '', 0)
        layout.label.assert_called_once_with(text='Quiet', icon='MESH_CYLINDER')
        with self.assertRaisesRegex(RuntimeError, 'weighted'):
            weapon_cfg.collect_attachments(self.cfg, [])

    def test_all_mode_combinations_and_defaults(self):
        modes = ('SemiAutomatic', 'Queue', 'Automatic')
        for size in range(1, 4):
            for enabled in combinations(modes, size):
                for default in enabled:
                    with self.subTest(enabled=enabled, default=default):
                        self.cfg.fire_modes = set(enabled)
                        self.cfg.default_fire_mode = default
                        self.cfg.burst_length = 5
                        text = weapon_cfg.general_setup(self.info)
                        block = text.split('FireTypes : struct.begin {bskipref}', 1)[1].split('struct.end', 1)[0]
                        self.assertEqual(block.count('EFireType::'), size)
                        for index, mode in enumerate(enabled):
                            self.assertIn(f'[{index}] = EFireType::{mode}', block)
                        self.assertIn(f'DefaultFireType = EFireType::{default}', text)
                        self.assertIn(f'FireQueueCount = {5 if "Queue" in enabled else 0}', text)

    def test_last_mode_cannot_be_disabled(self):
        for mode, prop in (('SemiAutomatic', 'fire_mode_semi'), ('Queue', 'fire_mode_burst'),
                           ('Automatic', 'fire_mode_auto')):
            with self.subTest(mode=mode):
                self.cfg.fire_modes = {mode}
                setattr(self.cfg, prop, False)
                self.assertEqual(self.cfg.fire_modes, {mode})
                self.cfg.fire_modes = set()
                self.assertEqual(self.cfg.fire_modes, {mode})
                self.assertEqual(self.cfg.default_fire_mode, mode)
                weapon_cfg.general_setup(self.info)

    def test_checkboxes_enable_modes_independently(self):
        self.cfg.fire_mode_burst = True
        self.cfg.fire_mode_auto = True
        self.assertEqual(self.cfg.fire_modes, {'SemiAutomatic', 'Queue', 'Automatic'})
        self.cfg.fire_mode_semi = False
        self.assertEqual(self.cfg.fire_modes, {'Queue', 'Automatic'})
        self.cfg.fire_mode_auto = False
        self.assertEqual(self.cfg.fire_modes, {'Queue'})

    def test_default_checkbox_is_exclusive_across_selected_modes(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue', 'Automatic'}
        for mode in ('Queue', 'Automatic', 'SemiAutomatic'):
            self.cfg.active_fire_mode = mode
            self.cfg.is_default_fire_mode = True
            self.assertEqual(self.cfg.default_fire_mode, mode)
            for other in self.cfg.fire_modes:
                self.cfg.active_fire_mode = other
                self.assertEqual(self.cfg.is_default_fire_mode, other == mode)
            self.cfg.active_fire_mode = mode
            self.cfg.is_default_fire_mode = False
            self.assertEqual(self.cfg.default_fire_mode, mode)
            self.assertTrue(self.cfg.is_default_fire_mode)

    def test_settings_dropdown_only_contains_enabled_modes_with_stable_values(self):
        for enabled in ({'SemiAutomatic'}, {'Queue'}, {'Automatic'}, {'SemiAutomatic', 'Automatic'},
                        {'Queue', 'Automatic'}, {'SemiAutomatic', 'Queue', 'Automatic'}):
            self.cfg.fire_modes = enabled
            items = weapon_cfg._active_fire_mode_items(self.cfg, None)
            self.assertEqual({item[0] for item in items}, enabled)
            self.assertEqual({item[0]: item[3] for item in items},
                             {item[0]: item[3] for item in weapon_cfg.FIRE_MODES if item[0] in enabled})
            for mode in enabled:
                self.cfg.active_fire_mode = mode
                self.assertEqual(self.cfg.active_fire_mode, mode)

    def test_disabling_default_and_selected_mode_selects_enabled_replacement(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue', 'Automatic'}
        self.cfg.active_fire_mode = 'Queue'
        self.cfg.is_default_fire_mode = True
        self.cfg.fire_mode_burst = False
        self.assertEqual(self.cfg.default_fire_mode, 'SemiAutomatic')
        self.assertEqual(self.cfg.active_fire_mode, 'SemiAutomatic')
        self.assertTrue(self.cfg.is_default_fire_mode)
        self.cfg.fire_mode_semi = False
        self.assertEqual(self.cfg.default_fire_mode, 'Automatic')
        self.assertEqual(self.cfg.active_fire_mode, 'Automatic')
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('DefaultFireType = EFireType::Automatic', text)

    def test_old_invalid_stored_selection_is_repaired(self):
        self.cfg['fire_modes'] = 4
        self.cfg['default_fire_mode'] = 2
        self.cfg['active_fire_mode'] = 1
        self.assertEqual(self.cfg.default_fire_mode, 'Automatic')
        self.assertEqual(self.cfg.active_fire_mode, 'Automatic')
        weapon_cfg.general_setup(self.info)
        self.cfg['fire_modes'] = 0
        self.assertEqual(self.cfg.fire_modes, {'SemiAutomatic'})
        self.assertEqual(self.cfg.default_fire_mode, 'SemiAutomatic')

    def test_selecting_modes_does_not_change_shared_handling_values(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue'}
        self.cfg.fire_interval = 0.25
        self.cfg.recoil_radius = 321
        for mode in ('Queue', 'SemiAutomatic'):
            self.cfg.active_fire_mode = mode
            self.assertAlmostEqual(self.cfg.fire_interval, 0.25)
            self.assertEqual(self.cfg.recoil_radius, 321)
            self.assertIn('FireInterval = 0.25', weapon_cfg.general_setup(self.info))

    def test_recoil_recovery_defaults_preserve_existing_export(self):
        self.assertAlmostEqual(self.cfg.recoil_recovery_delay, 0)
        self.assertAlmostEqual(self.cfg.recoil_recovery_time, 0.06)
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('RadiusNormalizationDelay = 0.0', text)
        self.assertIn('RadiusNormalizationInterval = 0.06', text)

    def test_recoil_recovery_values_are_exported_and_reset(self):
        self.cfg.recoil_recovery_delay = 0.15
        self.cfg.recoil_recovery_time = 0.3
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('RadiusNormalizationDelay = 0.15', text)
        self.assertIn('RadiusNormalizationInterval = 0.3', text)
        self.assertIn('FireInterval = 0.08', text)
        weapon_cfg.apply_preset(self.cfg)
        self.assertAlmostEqual(self.cfg.recoil_recovery_delay, 0)
        self.assertAlmostEqual(self.cfg.recoil_recovery_time, 0.06)

    def test_panel_draws_checkboxes_selection_default_and_burst_settings(self):
        class Layout:
            def __init__(self, calls):
                self.calls = calls
                self.enabled = True

            def row(self, **kwargs):
                return Layout(self.calls)

            def prop(self, cfg, name, **kwargs):
                self.calls.append((name, self.enabled))

            def label(self, **kwargs):
                pass

            def separator(self):
                pass

        for enabled, selected, default in (
                ({'SemiAutomatic'}, 'SemiAutomatic', 'SemiAutomatic'),
                ({'SemiAutomatic', 'Queue'}, 'Queue', 'SemiAutomatic'),
                ({'SemiAutomatic', 'Queue'}, 'SemiAutomatic', 'SemiAutomatic')):
            with self.subTest(enabled=enabled, selected=selected):
                self.cfg.fire_modes = enabled
                self.cfg.default_fire_mode = default
                self.cfg.active_fire_mode = selected
                calls = []
                panel = SimpleNamespace(layout=Layout(calls), props=lambda *args: None)
                context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
                weapon_cfg.ARSENAL_PT_CfgHandling.draw(panel, context)
                controls = dict(calls)
                self.assertEqual(controls['fire_mode_semi'], len(enabled) > 1)
                self.assertTrue(controls['fire_mode_burst'])
                self.assertTrue(controls['fire_mode_auto'])
                self.assertTrue(controls['active_fire_mode'])
                self.assertTrue(controls['is_default_fire_mode'])
                self.assertEqual('burst_length' in controls, selected == 'Queue')
                self.assertNotIn('fire_modes', controls)
                self.assertNotIn('default_fire_mode', controls)

    def test_default_checkbox_remains_interactive_after_becoming_default(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue'}
        self.cfg.active_fire_mode = 'Queue'
        states = []

        class Layout:
            enabled = True

            def row(self, **kwargs):
                return Layout()

            def prop(layout, cfg, name, **kwargs):
                if name == 'is_default_fire_mode':
                    states.append((cfg.is_default_fire_mode, layout.enabled))

            def label(self, **kwargs):
                pass

            def separator(self):
                pass

        panel = SimpleNamespace(layout=Layout(), props=lambda *args: None)
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
        weapon_cfg.ARSENAL_PT_CfgHandling.draw(panel, context)
        self.cfg.is_default_fire_mode = True
        weapon_cfg.ARSENAL_PT_CfgHandling.draw(panel, context)
        self.assertEqual(states, [(False, True), (True, True)])
        self.cfg.active_fire_mode = 'SemiAutomatic'
        self.cfg.is_default_fire_mode = True
        self.assertEqual(self.cfg.default_fire_mode, 'SemiAutomatic')

    def test_presets_and_existing_blends_keep_template_fire_modes(self):
        expected = {
            'TemplatePistol': ({'SemiAutomatic'}, 'SemiAutomatic'),
            'TemplateSMG': ({'SemiAutomatic', 'Automatic'}, 'Automatic'),
            'TemplateRifle': ({'SemiAutomatic', 'Automatic'}, 'Automatic'),
            'TemplateShotgun': ({'SemiAutomatic'}, 'SemiAutomatic'),
            'TemplateSniper': ({'SemiAutomatic'}, 'SemiAutomatic'),
        }
        for template, (enabled, default) in expected.items():
            self.cfg['setup_template'] = self.cfg.bl_rna.properties['setup_template'].enum_items[template].value
            for key in ('fire_modes', 'default_fire_mode', 'burst_length'):
                if key in self.cfg:
                    del self.cfg[key]
            weapon_cfg.general_setup(self.info)
            self.assertEqual(self.cfg.fire_modes, enabled)
            self.assertEqual(self.cfg.default_fire_mode, default)
            self.cfg.fire_modes = {'Queue'}
            weapon_cfg.apply_preset(self.cfg)
            self.assertEqual(self.cfg.fire_modes, enabled)
            self.assertEqual(self.cfg.default_fire_mode, default)

    def test_fire_settings_survive_blend_save(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue', 'Automatic'}
        self.cfg.default_fire_mode = 'Queue'
        self.cfg.active_fire_mode = 'Automatic'
        self.cfg.burst_length = 7
        self.cfg.recoil_recovery_delay = 0.15
        self.cfg.recoil_recovery_time = 0.3
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'fire_settings.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False, copy=True)
            with bpy.data.libraries.load(path) as (_source, destination):
                destination.scenes = [self.scene.name]
            loaded = destination.scenes[0]
            self.addCleanup(bpy.data.scenes.remove, loaded)
            cfg = loaded.test_arsenal_cfg
            self.assertEqual(cfg.fire_modes, self.cfg.fire_modes)
            self.assertEqual(cfg.default_fire_mode, 'Queue')
            self.assertEqual(cfg.active_fire_mode, 'Automatic')
            self.assertFalse(cfg.is_default_fire_mode)
            self.assertEqual(cfg.burst_length, 7)
            self.assertAlmostEqual(cfg.recoil_recovery_delay, 0.15)
            self.assertAlmostEqual(cfg.recoil_recovery_time, 0.3)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
