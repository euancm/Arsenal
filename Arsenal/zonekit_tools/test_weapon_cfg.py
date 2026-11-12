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
                         weapon_cfg.ARSENAL_CfgTrader, weapon_cfg.ARSENAL_CfgDistributionWeight,
                         weapon_cfg.ARSENAL_CfgFaction,
                         weapon_cfg.ARSENAL_WeaponCfg):
            bpy.utils.register_class(cls_type)
        bpy.types.Scene.test_arsenal_cfg = bpy.props.PointerProperty(type=weapon_cfg.ARSENAL_WeaponCfg)

    @classmethod
    def tearDownClass(cls):
        del bpy.types.Scene.test_arsenal_cfg
        for cls_type in (weapon_cfg.ARSENAL_WeaponCfg, weapon_cfg.ARSENAL_CfgFaction,
                         weapon_cfg.ARSENAL_CfgDistributionWeight, weapon_cfg.ARSENAL_CfgTrader,
                         weapon_cfg.ARSENAL_CfgUpgrade,
                         weapon_cfg.ARSENAL_CfgUpgradeEffect, weapon_cfg.ARSENAL_CfgAttachment,
                         weapon_cfg.ARSENAL_CfgMagazine, weapon_cfg.ARSENAL_CfgText):
            bpy.utils.unregister_class(cls_type)

    def setUp(self):
        self.scene = bpy.data.scenes.new('FireModeTest')
        self.addCleanup(bpy.data.scenes.remove, self.scene)
        self.cfg = self.scene.test_arsenal_cfg
        self.info = {'cfg': self.cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'parts': [],
                     'magazines': [], 'attachments': []}

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

    def test_weapon_and_magazine_panels_show_exact_export_sids_and_copy_values(self):
        item = self.cfg.magazines.add()
        item.name = 'Extended'
        export = SimpleNamespace(unreal_mount='TestMod')
        scene = SimpleNamespace(arsenal_cfg=self.cfg, arsenal_export=export,
                                arsenal_inventory=SimpleNamespace(source_scene=object()))
        context = SimpleNamespace(scene=scene)
        for name, template, expected_weapon, expected_magazine in (
                ('E9', 'TemplatePistol', 'Gune9_HG', 'Gune9_MagExtended'),
                ('E18 Custom', 'TemplateRifle', 'Gune18custom_ST', 'Gune18custom_MagExtended')):
            with self.subTest(name=name):
                self.cfg.text_language = 'en'
                self.cfg.text_name = name
                with patch('stalker2_arsenal.setup_panel.apply_template_defaults'):
                    self.cfg.setup_template = template
                weapon = SimpleNamespace(layout=Mock(), props=Mock())
                magazine = SimpleNamespace(layout=Mock(), props=Mock())
                with patch('stalker2_arsenal.inventory_images.draw_images'):
                    weapon_cfg.ARSENAL_PT_CfgIdentity.draw(weapon, context)
                    weapon_cfg.ARSENAL_PT_CfgAmmo.draw(magazine, context)
                weapon_row = weapon.layout.box.return_value.row.return_value
                magazine_row = magazine.layout.row.return_value
                weapon_row.label.assert_called_with(text=f'Weapon SID: {expected_weapon}')
                magazine_row.label.assert_called_with(text=f'Magazine SID: {expected_magazine}')
                self.assertEqual(weapon_row.operator.return_value.sid, expected_weapon)
                self.assertEqual(magazine_row.operator.return_value.sid, expected_magazine)
                self.assertEqual(weapon_cfg.weapon_names(scene, export, self.cfg)[1], expected_weapon)
                self.assertEqual(weapon_cfg.magazine_sid(
                    {'weapon_id': weapon_cfg.animation_export.weapon_name(scene)},
                    {'name': item.name}), expected_magazine)
        item.name = 'Increased'
        magazine = SimpleNamespace(layout=Mock(), props=Mock())
        with patch('stalker2_arsenal.inventory_images.draw_images'):
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(magazine, context)
        magazine.layout.row.return_value.label.assert_called_with(
            text='Magazine SID: Gune18custom_MagIncreased')
        item.use_existing = True
        item.existing_sid = ' SharedMagazine30 '
        self.cfg.text_name = ''
        magazine = SimpleNamespace(layout=Mock(), props=Mock())
        with patch('stalker2_arsenal.inventory_images.draw_images'):
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(magazine, context)
        magazine.layout.row.return_value.label.assert_called_with(text='Magazine SID: SharedMagazine30')
        self.assertEqual(magazine.layout.row.return_value.operator.return_value.sid, 'SharedMagazine30')

    def test_magazine_sid_is_not_offered_until_required_names_are_valid(self):
        item = self.cfg.magazines.add()
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
        for name, existing, sid in (('', False, ''), ('E9', True, ''),
                                    ('E9', True, 'Invalid SID')):
            self.cfg.text_name = name
            item.use_existing, item.existing_sid = existing, sid
            panel = SimpleNamespace(layout=Mock(), props=Mock())
            with patch('stalker2_arsenal.inventory_images.draw_images'), \
                    patch.object(weapon_cfg, 'draw_item_sid') as draw:
                weapon_cfg.ARSENAL_PT_CfgAmmo.draw(panel, context)
            draw.assert_not_called()
            self.assertTrue(any(call.kwargs.get('icon') == 'ERROR'
                                for call in panel.layout.label.call_args_list))

    def test_copy_sid_copies_exact_value_and_rejects_invalid_values(self):
        manager = SimpleNamespace(clipboard='unchanged')
        context = SimpleNamespace(window_manager=manager)
        operator = SimpleNamespace(sid='Gune9_HG', report=Mock())
        self.assertEqual(weapon_cfg.ARSENAL_OT_CfgCopySID.execute(operator, context), {'FINISHED'})
        self.assertEqual(manager.clipboard, 'Gune9_HG')
        for invalid in ('', 'Invalid SID', 'Bad;SID'):
            operator.sid = invalid
            self.assertEqual(weapon_cfg.ARSENAL_OT_CfgCopySID.execute(operator, context), {'CANCELLED'})
            self.assertEqual(manager.clipboard, 'Gune9_HG')
            self.assertEqual(operator.report.call_args.args[0], {'ERROR'})

    def test_existing_magazine_hides_definition_controls_and_keeps_settings(self):
        item = self.cfg.magazines.add()
        item.use_existing = True
        item.extra_weapon_sids = 'GunOther'
        item.preinstalled = False
        item.text_name = 'Saved text'
        panel = SimpleNamespace(layout=Mock(), props=Mock())
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
        with patch.object(weapon_cfg, 'draw_localization') as text, \
                patch('stalker2_arsenal.inventory_images.draw_images') as images:
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(panel, context)
        text.assert_not_called()
        images.assert_not_called()
        shown = {call.args[1] for call in panel.layout.column.return_value.prop.call_args_list}
        self.assertEqual(shown, {'name', 'use_existing', 'existing_sid', 'socket', 'preinstalled',
                                 'tactical_reload', 'full_reload'})
        item.use_existing = False
        self.assertEqual(item.text_name, 'Saved text')
        self.assertEqual(item.capacity, 15)
        self.assertEqual(item.extra_weapon_sids, 'GunOther')
        panel.layout.reset_mock()
        with patch.object(weapon_cfg, 'draw_localization'), \
                patch('stalker2_arsenal.inventory_images.draw_images'):
            weapon_cfg.ARSENAL_PT_CfgAmmo.draw(panel, context)
        shown = {call.args[1] for call in panel.layout.column.return_value.prop.call_args_list}
        self.assertIn('extra_weapon_sids', shown)

    def test_owned_magazine_exports_extra_weapon_sids_once_in_order(self):
        mesh = bpy.data.objects.new('Shared magazine', bpy.data.meshes.new('Shared magazine'))
        self.addCleanup(bpy.data.meshes.remove, mesh.data)
        self.addCleanup(bpy.data.objects.remove, mesh)
        item = self.cfg.magazines.add()
        item.full_object = item.empty_object = mesh
        item.extra_weapon_sids = ' GunOther, GunThird, GunOther, GunTest, , '
        for preinstalled in (True, False):
            with self.subTest(preinstalled=preinstalled):
                item.preinstalled = preinstalled
                magazines = weapon_cfg.collect_magazines(self.cfg, [])
                self.assertEqual(magazines[0]['extra_weapon_sids'], ['GunOther', 'GunThird', 'GunTest'])
                info = dict(self.info, magazines=magazines)
                text = weapon_cfg.attach_prototypes(info)
                self.assertIn(
                    'FittingWeaponsSIDs : struct.begin\n'
                    '      [0] = GunTest\n'
                    '      [1] = GunOther\n'
                    '      [2] = GunThird\n'
                    '   struct.end', text)
                self.assertEqual(text.count('= GunTest\n'), 1)
                self.assertEqual(text, weapon_cfg.attach_prototypes(info))
        item.extra_weapon_sids = ' , '
        magazines = weapon_cfg.collect_magazines(self.cfg, [])
        self.assertEqual(magazines[0]['extra_weapon_sids'], [])
        info = dict(self.info, magazines=magazines)
        self.assertIn('[0] = GunTest', weapon_cfg.attach_prototypes(info))
        magazines[0]['preinstalled'] = True
        self.assertNotIn('FittingWeaponsSIDs', weapon_cfg.attach_prototypes(info))

    def test_extra_weapon_sids_are_validated_only_for_owned_magazines(self):
        mesh = bpy.data.objects.new('Validated magazine', bpy.data.meshes.new('Validated magazine'))
        self.addCleanup(bpy.data.meshes.remove, mesh.data)
        self.addCleanup(bpy.data.objects.remove, mesh)
        item = self.cfg.magazines.add()
        item.full_object = item.empty_object = mesh
        for invalid in ('GunOther GunThird', '/Game/GunOther', 'GunOther;GunThird',
                        'GunOther\nstruct.end', 'GunOther, Bad-ID'):
            with self.subTest(invalid=invalid):
                item.extra_weapon_sids = invalid
                with self.assertRaisesRegex(RuntimeError, 'invalid extra weapon SID'):
                    weapon_cfg.collect_magazines(self.cfg, [])
        item.use_existing = True
        item.existing_sid = 'SharedMagazine'
        magazines = weapon_cfg.collect_magazines(self.cfg, [])
        self.assertEqual(magazines[0]['extra_weapon_sids'], [])
        self.assertEqual(weapon_cfg.attach_prototypes(dict(self.info, magazines=magazines)).strip(), '')

    def test_existing_magazine_needs_no_mesh_and_exports_only_references(self):
        item = self.cfg.magazines.add()
        item.name, item.existing_sid = 'Extended', ' SharedMagazine30 '
        item.use_existing, item.preinstalled = True, False
        item.socket = 'jnt_magazine'
        item.tactical_reload, item.full_reload = 0.8, 1.2
        item.text_name = 'Do not export this text'
        magazines = weapon_cfg.collect_magazines(self.cfg, [])
        self.assertEqual(magazines[0]['existing_sid'], 'SharedMagazine30')
        info = dict(self.info, magazines=magazines, world_mesh="StaticMesh'/Test/World.World'",
                    skeletal_mesh="SkeletalMesh'/Test/SK.SK'")
        self.assertEqual(weapon_cfg.attach_prototypes(info).strip(), '')
        self.assertNotIn('SharedMagazine30', weapon_cfg.mesh_prototypes(info))
        self.assertEqual(weapon_cfg.localization_entries(info), [])
        text = weapon_cfg.general_setup(info)
        self.assertEqual(text.count('AttachPrototypeSID = SharedMagazine30'), 2)
        self.assertIn('TacticalReloadTimeMultiplier = 0.8', text)
        self.assertIn('FullReloadTimeMultiplier = 1.2', text)
        self.assertIn('Socket = jnt_magazine', text)
        self.assertNotIn('GunTest_MagExtended', text)
        item.preinstalled = True
        info['magazines'] = weapon_cfg.collect_magazines(self.cfg, [])
        self.assertIn('AttachSID = SharedMagazine30', weapon_cfg.general_setup(info))
        self.assertTrue(item.use_existing)
        item.use_existing = False
        with self.assertRaisesRegex(RuntimeError, 'both a full and an empty'):
            weapon_cfg.collect_magazines(self.cfg, [])

    def test_owned_default_and_shared_extended_export_together(self):
        owned = {'name': 'Default', 'preinstalled': True, 'capacity': 15, 'cost': 0, 'weight': 0,
                 'socket': 'jnt_magazine', 'tactical': 1, 'full_reload': 1,
                 'full_path': "StaticMesh'/Test/Full.Full'", 'empty_path': "StaticMesh'/Test/Empty.Empty'"}
        item = self.cfg.magazines.add()
        item.name, item.use_existing, item.existing_sid = 'Extended', True, 'SharedMagazine30'
        item.preinstalled = False
        info = dict(self.info, magazines=[owned] + weapon_cfg.collect_magazines(self.cfg, []),
                    world_mesh="StaticMesh'/Test/World.World'", skeletal_mesh="SkeletalMesh'/Test/SK.SK'")
        text = weapon_cfg.attach_prototypes(info)
        self.assertIn('SID = GunTest_MagDefault', text)
        self.assertNotIn('SharedMagazine30', text)
        meshes = weapon_cfg.mesh_prototypes(info)
        self.assertIn('SID = GunTest_MagDefaultFull', meshes)
        self.assertNotIn('GunTest_MagExtended', meshes)
        setup = weapon_cfg.general_setup(info)
        self.assertIn('AttachPrototypeSID = GunTest_MagDefault', setup)
        self.assertIn('AttachPrototypeSID = SharedMagazine30', setup)
        self.assertNotIn('GunTest_MagExtended', setup)

    def test_existing_magazine_rejects_empty_or_invalid_sid_and_socket(self):
        item = self.cfg.magazines.add()
        item.use_existing = True
        for sid in ('', ' ', 'Bad SID', '/Game/Mag', 'Bad;SID'):
            item.existing_sid = sid
            with self.assertRaisesRegex(RuntimeError, 'existing magazine SID'):
                weapon_cfg.collect_magazines(self.cfg, [])
        item.existing_sid = 'SharedMagazine'
        item.socket = 'Invalid Socket'
        with self.assertRaisesRegex(RuntimeError, 'socket name'):
            weapon_cfg.collect_magazines(self.cfg, [])

    def test_build_context_with_only_external_magazines_does_not_read_meshes(self):
        item = self.cfg.magazines.add()
        item.use_existing = True
        item.existing_sid = 'SharedMagazine30'
        export = SimpleNamespace(output_folder=tempfile.gettempdir(), static_category='pistol',
                                 unreal_mount='TestMod')
        scene = SimpleNamespace(arsenal_cfg=self.cfg, arsenal_export=export)
        with patch.object(weapon_cfg.animation_export, '_build_static_plan', return_value=(None, None, {}, [])), \
                patch.object(weapon_cfg.static_mesh, 'classify_meshes', return_value=(object(), {}, [])), \
                patch.object(weapon_cfg.static_mesh, 'weapon_mesh_name', return_value='Test'), \
                patch.object(weapon_cfg.static_mesh, 'template_token', return_value='udp'), \
                patch.object(weapon_cfg.static_mesh, 'weighted_bones') as weighted, \
                patch.object(weapon_cfg.animation_export, 'weapon_name', return_value='Test'), \
                patch.object(weapon_cfg.animation_export, 'mod_mount', return_value='/TestMod'), \
                patch.object(weapon_cfg, 'animation_folder', return_value='/TestMod/Animations/pt/Test'):
            info = weapon_cfg.build_context(SimpleNamespace(scene=scene))
            weighted.assert_not_called()
            self.assertEqual(info['magazines'][0]['socket'], 'jnt_magazine')
            duplicate = self.cfg.magazines.add()
            duplicate.name, duplicate.use_existing, duplicate.existing_sid = 'Extra', True, item.existing_sid
            with self.assertRaisesRegex(RuntimeError, 'SIDs must be unique'):
                weapon_cfg.build_context(SimpleNamespace(scene=scene))

    def test_external_magazine_is_exempt_from_local_definition_and_mesh_checks(self):
        from stalker2_arsenal import export_check
        item = self.cfg.magazines.add()
        item.use_existing, item.existing_sid = True, 'SharedMagazine30'
        magazines = weapon_cfg.collect_magazines(self.cfg, [])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'Test.cfg')
            with open(path, 'w') as handle:
                handle.write('AttachPrototypeSID = SharedMagazine30\nAttachPrototypeSID = UndefinedItem\n')
            info = dict(self.info, magazines=magazines, output_root=folder, mount='/TestMod',
                        mod='TestMod', anim_name='Test', mesh_name='Test')
            self.assertEqual(export_check.name_warnings(info), [])
            warnings = export_check.path_warnings(info, [path])
            self.assertEqual(len(warnings), 1)
            self.assertIn('UndefinedItem', warnings[0])

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

    def test_automatic_donors_export_all_three_fire_events(self):
        for template, weapon in (('TemplateSMG', 'Viper'), ('TemplateRifle', 'AK74')):
            with self.subTest(template=template):
                with patch('stalker2_arsenal.setup_panel.apply_template_defaults'):
                    self.cfg.setup_template = template
                self.cfg.fire_modes = {'SemiAutomatic', 'Automatic'}
                text = weapon_cfg.general_setup(self.info)
                for event, suffix in (('OneShot', 'Oneshot'), ('Loop', 'Loop'), ('Break', 'Break')):
                    line = next(line for line in text.splitlines() if f'FireEvent{event} = ' in line)
                    self.assertIn(f'SFX_{weapon}_{suffix}.SFX_{weapon}_{suffix}', line)

    def test_udp_sound_is_not_silently_substituted_for_automatic_fire(self):
        self.cfg.fire_modes = {'SemiAutomatic', 'Automatic'}
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('SFX_UDP_Oneshot.SFX_UDP_Oneshot', text)
        self.assertNotIn('SFX_APB_', text)
        self.assertNotIn('FireEventLoop = ', text)

    def test_apb_firing_sound_is_independent_and_exports_complete_matched_set(self):
        before = weapon_cfg.general_setup(self.info)
        self.cfg.firing_sound_donor = 'APB'
        self.cfg.fire_modes = {'SemiAutomatic', 'Automatic'}
        text = weapon_cfg.general_setup(self.info)
        for field, suffix in (('OneShot', 'Oneshot'), ('Loop', 'Loop'), ('Break', 'Break')):
            self.assertIn(f'FireEvent{field} = AkAudioEvent', text)
            self.assertIn(f'SFX_APB_{suffix}.SFX_APB_{suffix}', text)
        self.assertIn('WeaponType-APB.WeaponType-APB', text)
        self.assertNotIn('SFX_UDP_Oneshot', text)
        self.assertIn('SFX_WeaponUnload_Auto_UDP', text)
        self.assertIn('refkey=GunUDP_HG', text)
        self.assertIn('FireInterval = 0.08', text)
        self.assertEqual(self.cfg.setup_template, 'TemplatePistol')
        self.assertTrue(weapon_cfg.has_automatic_audio(self.cfg))
        weapon_cfg.apply_preset(self.cfg)
        self.assertEqual(self.cfg.firing_sound_donor, 'APB')
        self.cfg.firing_sound_donor = 'TEMPLATE'
        self.assertEqual(weapon_cfg.general_setup(self.info), before)

    def test_all_explicit_firing_donors_export_exactly_one_of_each_field(self):
        for donor in ('APB', 'UDP', 'Viper', 'AK74'):
            with self.subTest(donor=donor):
                self.cfg.firing_sound_donor = donor
                text = weapon_cfg.general_setup(self.info)
                for field in weapon_cfg.FIRING_AUDIO_FIELDS:
                    self.assertEqual(text.count(f'{field} = '), 1)
                self.assertIn(f'SFX_{donor}_Oneshot.SFX_{donor}_Oneshot', text)
                self.assertEqual(weapon_cfg.has_automatic_audio(self.cfg), donor != 'UDP')
                if donor == 'UDP':
                    self.assertIn("FireEventLoop = AkAudioEvent''", text)
                    self.assertIn("FireEventBreak = AkAudioEvent''", text)

    def test_stock_attachment_layers_use_mod_images_and_zero_offsets(self):
        self.cfg.allow_silencer = self.cfg.allow_laser = True
        info = dict(self.info, mount='/TestMod')
        for kind in ('silencer', 'laser'):
            settings = getattr(self.cfg, f'stock_{kind}_images')
            settings.inventory_image = bpy.data.images.new(f'Stock {kind}', width=258, height=128, alpha=True)
            self.addCleanup(bpy.data.images.remove, settings.inventory_image)
        text = weapon_cfg.general_setup(info)
        for kind in ('Silencer', 'Laser'):
            self.assertIn(f'T_inv_w_Test_Stock{kind}.T_inv_w_Test_Stock{kind}', text)
        self.assertNotIn('IconPosX = 205', text)
        self.assertNotIn('IconPosX = 150', text)
        self.assertNotIn('/Integral/T_inv_w_integral_en_silen_5', text)
        self.assertIn('MeshPrototypeSID = EN_Silen_5', text)
        self.assertIn('AttachPrototypeSID = EN_Silen_2', text)

    def test_missing_stock_images_keep_donor_behavior(self):
        self.cfg.allow_silencer = self.cfg.allow_laser = True
        text = weapon_cfg.general_setup(self.info)
        self.assertIn('IconPosX = 205', text)
        self.assertIn('IconPosX = 150', text)
        self.assertIn('/Integral/T_inv_w_integral_en_silen_5', text)

    def test_export_warns_for_missing_loop_and_unaligned_stock_overlay(self):
        self.cfg.fire_modes = {'Automatic'}
        self.cfg.allow_silencer = True
        self.cfg.inventory_image = bpy.data.images.new('Body warning test', width=258, height=128, alpha=True)
        self.addCleanup(bpy.data.images.remove, self.cfg.inventory_image)
        with patch.object(weapon_cfg, 'write_cfg_files', return_value=([], self.info)), \
                patch.object(weapon_cfg, 'report') as report:
            weapon_cfg.export_cfg_files(Mock(), None)
        messages = [call.args[2] for call in report.call_args_list]
        self.assertTrue(any('no automatic-fire loop/break' in message for message in messages))
        self.assertTrue(any('Stock silencer has no aligned inventory layer' in message for message in messages))

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
                self.assertTrue(controls['firing_sound_donor'])
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
        self.cfg.firing_sound_donor = 'APB'
        self.cfg.fire_modes = {'SemiAutomatic', 'Queue', 'Automatic'}
        self.cfg.default_fire_mode = 'Queue'
        self.cfg.active_fire_mode = 'Automatic'
        self.cfg.burst_length = 7
        self.cfg.recoil_recovery_delay = 0.15
        self.cfg.recoil_recovery_time = 0.3
        self.cfg.distribution_trader = 'TraderZalesie_TradeItemGenerator'
        self.cfg.distribution_faction = 'Bandit'
        self.cfg.trader_enabled = True
        self.cfg.trader_chance = 40
        self.cfg.trader_max_quantity = 5
        self.cfg.trader_min_condition = 10
        self.cfg.npc_CloseCombat_enabled = True
        self.cfg.npc_CloseCombat_percent = 20
        self.cfg.npc_Veteran_enabled = True
        self.cfg.npc_Veteran_percent = 15
        magazine = self.cfg.magazines.add()
        magazine.use_existing = True
        magazine.existing_sid = 'SharedMagazine30'
        magazine.socket = 'jnt_clip_base'
        magazine.capacity = 42
        magazine.extra_weapon_sids = 'GunOther, GunThird'
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'fire_settings.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False, copy=True)
            with bpy.data.libraries.load(path) as (_source, destination):
                destination.scenes = [self.scene.name]
            loaded = destination.scenes[0]
            self.addCleanup(bpy.data.scenes.remove, loaded)
            cfg = loaded.test_arsenal_cfg
            self.assertTrue(cfg.magazines[0].use_existing)
            self.assertEqual(cfg.magazines[0].existing_sid, 'SharedMagazine30')
            self.assertEqual(cfg.magazines[0].socket, 'jnt_clip_base')
            self.assertEqual(cfg.magazines[0].capacity, 42)
            self.assertEqual(cfg.magazines[0].extra_weapon_sids, 'GunOther, GunThird')
            self.assertEqual(cfg.firing_sound_donor, 'APB')
            self.assertEqual(cfg.setup_template, 'TemplatePistol')
            self.assertEqual(cfg.fire_modes, self.cfg.fire_modes)
            self.assertEqual(cfg.default_fire_mode, 'Queue')
            self.assertEqual(cfg.active_fire_mode, 'Automatic')
            self.assertFalse(cfg.is_default_fire_mode)
            self.assertEqual(cfg.burst_length, 7)
            self.assertAlmostEqual(cfg.recoil_recovery_delay, 0.15)
            self.assertAlmostEqual(cfg.recoil_recovery_time, 0.3)
            self.assertEqual(cfg.distribution_trader, 'TraderZalesie_TradeItemGenerator')
            self.assertEqual(cfg.distribution_faction, 'Bandit')
            self.assertTrue(cfg.trader_enabled)
            self.assertEqual(cfg.trader_chance, 40)
            self.assertEqual(cfg.trader_max_quantity, 5)
            self.assertEqual(cfg.trader_min_condition, 10)
            self.assertTrue(cfg.npc_CloseCombat_enabled)
            self.assertEqual(cfg.npc_CloseCombat_percent, 20)
            self.assertTrue(cfg.npc_Veteran_enabled)
            self.assertEqual(cfg.npc_Veteran_percent, 15)

    def test_distribution_selection_retains_each_trader_and_factions_settings(self):
        self.assertFalse(self.cfg.trader_enabled)
        default_role = weapon_cfg.weapon_distribution.faction_defaults('TemplatePistol', 'Neutral')['roles']['CloseCombat']
        self.assertEqual(self.cfg.npc_CloseCombat_enabled, default_role[0])
        self.assertEqual(len(self.cfg.traders), 0)
        self.assertEqual(len(self.cfg.npc_factions), 0)
        self.cfg.trader_enabled = True
        self.cfg.trader_max_quantity = 5
        self.cfg.distribution_trader = 'TraderZalesie_TradeItemGenerator'
        self.assertFalse(self.cfg.trader_enabled)
        self.cfg.trader_chance = 75
        self.cfg.distribution_trader = 'RostokTraderSoviet_TradeItemGenerator'
        self.assertTrue(self.cfg.trader_enabled)
        self.assertEqual(self.cfg.trader_max_quantity, 5)
        self.assertEqual(self.cfg.trader_chance, 0)
        self.cfg.npc_CloseCombat_enabled = True
        self.cfg.npc_CloseCombat_percent = 20
        self.cfg.npc_Veteran_enabled = True
        self.cfg.npc_Veteran_percent = 15
        self.cfg.distribution_faction = 'Bandit'
        self.assertEqual(self.cfg.npc_CloseCombat_enabled, weapon_cfg.weapon_distribution.faction_defaults(
            'TemplatePistol', 'Bandit')['roles']['CloseCombat'][0])
        self.cfg.npc_CloseCombat_percent = 70
        self.cfg.distribution_faction = 'Neutral'
        self.assertTrue(self.cfg.npc_CloseCombat_enabled)
        self.assertEqual(self.cfg.npc_CloseCombat_percent, 20)
        self.assertTrue(self.cfg.npc_Veteran_enabled)
        self.assertEqual(self.cfg.npc_Veteran_percent, 15)
        weapon_cfg.apply_preset(self.cfg)
        self.assertEqual(self.cfg.npc_CloseCombat_percent, 20)
        self.assertTrue(self.cfg.trader_enabled)

    def test_distribution_panels_draw_without_creating_data_and_match_control_shape(self):
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_cfg=self.cfg))
        properties = []
        for panel_type in (weapon_cfg.ARSENAL_PT_CfgTraders, weapon_cfg.ARSENAL_PT_CfgNPCs):
            layout = Mock()
            panel_type.draw(SimpleNamespace(layout=layout), context)
            properties.extend(call.args[1] for call in layout.mock_calls
                              if call[0].endswith('prop') and len(call.args) > 1)
        self.assertEqual(len(self.cfg.traders), 0)
        self.assertEqual(len(self.cfg.npc_factions), 0)
        self.assertIn('trader_sell_unloaded', properties)
        self.assertIn('npc_CloseCombat_enabled', properties)
        self.assertIn('npc_Veteran_percent', properties)
        self.assertFalse(any('ammo' in name or 'slot' in name for name in properties))
        self.cfg.distribution_trader = 'IkarTrader_TradeItemGenerator'
        self.cfg.trader_enabled = True
        self.cfg.trader_chance = 40
        layout = Mock()
        weapon_cfg.ARSENAL_PT_CfgTraders.draw(SimpleNamespace(layout=layout), context)
        labels = [call.kwargs['text'] for call in layout.mock_calls
                  if call[0].endswith('label') and 'text' in call.kwargs]
        self.assertIn('Existing stock-pool chance: 50%', labels)
        self.assertIn('Effective stock chance: 20%', labels)
        self.assertIn('Custom attachment chance: 10%', labels)
        panels = (weapon_cfg.ARSENAL_PT_CfgText, weapon_cfg.ARSENAL_PT_CfgIdentity,
                  weapon_cfg.ARSENAL_PT_CfgDamage, weapon_cfg.ARSENAL_PT_CfgHandling,
                  weapon_cfg.ARSENAL_PT_CfgAmmo, weapon_cfg.ARSENAL_PT_CfgAttachments,
                  weapon_cfg.ARSENAL_PT_CfgTraders, weapon_cfg.ARSENAL_PT_CfgNPCs)
        self.assertEqual([panel.bl_order for panel in panels], list(range(8)))

    def test_cfg_export_writes_and_clears_distribution_in_the_normal_writer(self):
        weapon_cfg.weapon_distribution.load_defaults(self.cfg)
        for row in self.cfg.traders:
            row.enabled = False
        for row in self.cfg.npc_factions:
            for role in row.roles:
                role.enabled = False
        self.cfg.trader_enabled = True
        self.cfg.trader_chance = 40
        with tempfile.TemporaryDirectory() as folder:
            info = dict(self.info, output_root=folder, mod='TestMod', player_sid='GunTest_Player',
                        world_mesh="StaticMesh'/Test/SM_Test.SM_Test'",
                        skeletal_mesh="SkeletalMesh'/Test/SK_Test.SK_Test'",
                        anim_name='Test', animation_dir='/Test/Animations/Test')
            with patch.object(weapon_cfg, 'build_context', return_value=info):
                paths, _info = weapon_cfg.write_cfg_files(None)
                path = next(path for path in paths if path.endswith('TestMod_TestDistribution.cfg'))
                legacy = next(candidate for candidate in paths
                              if candidate.endswith('TestDistribution.cfg') and candidate != path)
                with open(legacy, 'w', encoding='utf-8') as handle:
                    handle.write('Obsolete invalid ModGameData distribution')
                with open(path, encoding='utf-8') as handle:
                    self.assertNotIn('struct.begin', handle.read())
                distribution = weapon_cfg.weapon_distribution
                self.assertIn('ItemPrototypeSID = GunTest', distribution.distribution_compose.compose([
                    distribution.payload(info)]))
                self.cfg.trader_enabled = False
                weapon_cfg.write_cfg_files(None)
                for candidate in (path, legacy):
                    with open(candidate, encoding='utf-8') as handle:
                        text = handle.read()
                    self.assertNotIn('struct.begin', text)
                    self.assertNotIn('Obsolete invalid', text)

    def test_initial_defaults_follow_template_without_requiring_ui_interaction(self):
        self.cfg.distribution_trader = 'RostokTraderNato_TradeItemGenerator'
        self.assertTrue(self.cfg.trader_enabled)
        self.assertEqual(self.cfg.trader_chance, 100)
        self.assertEqual(self.cfg.trader_min_quantity, 1)
        self.assertEqual(self.cfg.trader_max_quantity, 1)
        self.assertEqual(self.cfg.trader_min_condition, 100)
        self.assertFalse(self.cfg.trader_sell_unloaded)
        self.assertEqual(len(self.cfg.traders), 0)
        weapon_cfg.weapon_distribution.load_defaults(self.cfg)
        self.assertEqual(len(self.cfg.traders), len(weapon_cfg.weapon_distribution.TRADER_ITEMS))
        self.assertEqual(len(self.cfg.npc_factions), len(weapon_cfg.weapon_distribution.FACTIONS))
        self.assertEqual(self.cfg.traders['RostokTraderNato_TradeItemGenerator'].chance, 100)
        for role, expected in weapon_cfg.weapon_distribution.faction_defaults(
                'TemplatePistol', 'Neutral')['roles'].items():
            row = self.cfg.npc_factions['Neutral'].roles[role]
            self.assertEqual(row.enabled, expected[0])
            self.assertAlmostEqual(row.percent, expected[1], places=4)

    def test_all_template_defaults_export_without_opening_distribution_panels(self):
        info = dict(self.info, mod='TestMod', player_sid='GunTest_Player',
                    world_mesh="StaticMesh'/Test/SM_Test.SM_Test'",
                    skeletal_mesh="SkeletalMesh'/Test/SK_Test.SK_Test'",
                    anim_name='Test', animation_dir='/Test/Animations/Test')
        for template in weapon_cfg.PRESETS:
            with self.subTest(template=template), patch('stalker2_arsenal.setup_panel.apply_template_defaults'):
                self.cfg.setup_template = template
                files = weapon_cfg.cfg_files(info)
                distribution = weapon_cfg.weapon_distribution
                self.assertTrue(any(path.endswith('Distribution.cfg') for path in files))
                preset = weapon_cfg.PRESETS[template]
                general = weapon_cfg.general_setup(info)
                self.assertIn(f'refkey={preset["general_ref"]}', general)
                self.assertIn(f'refkey={preset["settings_ref"]}', weapon_cfg.player_settings(info))
                text = distribution.distribution_compose.compose([distribution.payload(info)])
                has_stock = any(row.enabled for row in self.cfg.traders) or any(
                    role.enabled and role.percent > 0 for row in self.cfg.npc_factions for role in row.roles)
                self.assertEqual('ItemPrototypeSID = GunTest' in text, has_stock)
                for sid, row in ((row.name, row) for row in self.cfg.traders):
                    self.assertEqual(row.enabled, weapon_cfg.weapon_distribution.trader_defaults(
                        template, sid)['enabled'])

    def test_special_donors_keep_their_existing_ammo_types(self):
        for template, expected in (('TemplateArev', ['Default', 'ArmorPiercing', 'Supersonic', 'Expanding']),
                                   ('TemplateGauss', ['Default']), ('TemplateRPG7', ['Default'])):
            with self.subTest(template=template), patch('stalker2_arsenal.setup_panel.apply_template_defaults'):
                self.cfg.setup_template = template
                text = weapon_cfg.general_setup(self.info)
                self.assertIn('AmmoTypeProjectiles : struct.begin {bskipref}', text)
                self.assertEqual(
                    [line.split('::')[1] for line in text.splitlines() if 'AmmoType = ' in line], expected)

    def test_template_change_resets_all_distribution_overrides(self):
        self.cfg.trader_chance = 12
        self.cfg.trader_enabled = True
        self.cfg.distribution_trader = 'TraderZalesie_TradeItemGenerator'
        self.cfg.trader_min_condition = 33
        self.cfg.npc_CloseCombat_percent = 77
        self.cfg.distribution_faction = 'Bandit'
        self.cfg.npc_Master_percent = 88
        with patch('stalker2_arsenal.setup_panel.apply_template_defaults'):
            self.cfg.setup_template = 'TemplateShotgun'
        for sid, row in ((row.name, row) for row in self.cfg.traders):
            for key, value in weapon_cfg.weapon_distribution.trader_defaults('TemplateShotgun', sid).items():
                self.assertAlmostEqual(getattr(row, key), value, places=4)
        for row in self.cfg.npc_factions:
            expected = weapon_cfg.weapon_distribution.faction_defaults('TemplateShotgun', row.name)
            for collection in ('roles', 'ranks'):
                for key, (enabled, percent) in expected[collection].items():
                    item = getattr(row, collection)[key]
                    self.assertEqual(item.enabled, enabled)
                    self.assertAlmostEqual(item.percent, percent, places=4)
        self.assertEqual(self.cfg.distribution_trader, 'TraderZalesie_TradeItemGenerator')
        self.assertEqual(self.cfg.distribution_faction, 'Bandit')

    def test_first_edit_seeds_other_fields_from_template_and_preserves_saved_overrides(self):
        self.cfg.distribution_trader = 'RostokTraderNato_TradeItemGenerator'
        self.cfg.trader_max_quantity = 5
        self.assertTrue(self.cfg.trader_enabled)
        self.assertEqual(self.cfg.trader_chance, 100)
        self.assertFalse(self.cfg.trader_sell_unloaded)
        before = self.cfg.npc_Veteran_percent
        self.cfg.npc_CloseCombat_percent = 12
        self.assertAlmostEqual(self.cfg.npc_Veteran_percent, before, places=4)
        weapon_cfg.weapon_distribution.load_defaults(self.cfg)
        self.assertEqual(self.cfg.trader_max_quantity, 5)
        self.assertEqual(self.cfg.npc_CloseCombat_percent, 12)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
