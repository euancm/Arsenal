"""Run with Python: verify which template packages setup exports, without starting ZoneKit."""
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


path = Path(__file__).parents[1] / 'stalker2_arsenal' / 'unreal_setup.py'
spec = importlib.util.spec_from_file_location('arsenal_unreal_setup', path)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

PLAYER = '/Game/_STALKER2/Animations/Player/AnimSequences/pt/udp'
WEAPON = '/Game/_STALKER2/Animations/Weapons/pt/udp/AnimSequences/fp'


class SetupSelectionTests(unittest.TestCase):
    def selection(self):
        return {
            'sequences': [f'{PLAYER}/Idle/AS_fp_udp_idle', f'{WEAPON}/Idle/AS_udp_fp_idle_boltlock'],
            'additive': [
                f'{PLAYER}/Shoot/AS_fp_udp_shoot',
                f'{PLAYER}/Equip/AS_fp_udp_equip',
                f'{PLAYER}/OffsetAim/AS_FP_Player_Udp_IdleToOffsetAim_01',
                f'{PLAYER}/Idle/AS_fp_udp_idle_add',
                f'{PLAYER}/Idle/AS_fp_udp_idle_aim_add',
            ],
            'skeletal_meshes': [], 'static_meshes': [], 'montages': [], 'collections': [],
            'anim_blueprints': [], 'skeletons': [],
        }

    def test_only_additive_idle_companions_stay_unexported(self):
        selection = self.selection()
        setup.export_additive_overlays(selection)
        self.assertEqual(selection['additive'], [f'{PLAYER}/Idle/AS_fp_udp_idle_add', f'{PLAYER}/Idle/AS_fp_udp_idle_aim_add'])
        exported = setup.exported(selection, {'export_additive': False})
        for name in ('AS_fp_udp_shoot', 'AS_fp_udp_equip', 'AS_FP_Player_Udp_IdleToOffsetAim_01', 'AS_udp_fp_idle_boltlock'):
            self.assertTrue(any(package.endswith('/' + name) for package in exported), name)
        self.assertFalse(any(package.endswith('_add') for package in exported))
        self.assertEqual(selection['sequences'], sorted(selection['sequences']))

    def test_additive_idles_export_only_when_asked(self):
        selection = self.selection()
        setup.export_additive_overlays(selection)
        exported = setup.exported(selection, {'export_additive': True})
        self.assertTrue(any(package.endswith('/AS_fp_udp_idle_add') for package in exported))

    def test_exported_overlays_are_still_copied_into_the_mod(self):
        selection = self.selection()
        setup.export_additive_overlays(selection)
        copied = setup.copied(selection)
        self.assertEqual(len(copied), 7)

    def test_static_part_alias_does_not_select_another_skeletal_mesh(self):
        weapon = '/Game/_STALKER2/SkeletalMeshes/weapons/pt/gp37'
        parts = '/Game/_Stalker_2/weapons/sturm_riffle/SM_ar_gp3/AnimMesh'
        assets = [
            (weapon + '/SK_gp37', 'SkeletalMesh'), (weapon + '/SK_gp3', 'SkeletalMesh'),
            (parts + '/SM_wpn_gp3_SM_offset', 'StaticMesh'),
            (parts + '/SM_wpn_gp3a_SM_offset', 'StaticMesh'),
        ]
        selection = setup.select_assets(assets, {
            'anim_tokens': ['gp37'], 'mesh_tokens': ['gp37'], 'part_tokens': ['gp3']})
        self.assertEqual(selection['skeletal_meshes'], [weapon + '/SK_gp37'])
        self.assertEqual(selection['static_meshes'], [parts + '/SM_wpn_gp3_SM_offset'])


class SetupCopyTests(unittest.TestCase):
    def test_existing_renamed_target_never_creates_an_old_donor_copy(self):
        item = ('/Game/Template', '/Mod/Template', '/Mod/Custom')
        library = SimpleNamespace(
            does_asset_exist=lambda path: path == item[2], duplicate_asset=Mock(), load_asset=Mock())
        tools = SimpleNamespace(rename_assets=Mock())
        with patch.object(setup, 'unreal', SimpleNamespace(
                EditorAssetLibrary=library, AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: tools))):
            ready = setup.checkout_copies({'copies': [item]}, {})
            self.assertEqual(setup.run_rename(ready), 0)
        library.duplicate_asset.assert_not_called()
        tools.rename_assets.assert_not_called()

    def test_copies_directly_without_revision_control_checkout(self):
        item = ('/Game/Template', '/Mod/Template', '/Mod/Custom')
        assets = {item[0]}
        library = SimpleNamespace(
            does_asset_exist=lambda path: path in assets,
            checkout_asset=Mock(),
            duplicate_asset=Mock(side_effect=lambda source, target: assets.add(target)))
        with patch.object(setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library, log=Mock())), \
                patch.object(setup, 'warn') as warning:
            self.assertEqual(setup.checkout_copies({'copies': [item]}, {}), [item])
        library.checkout_asset.assert_not_called()
        library.duplicate_asset.assert_called_once_with(item[0], item[1])
        warning.assert_not_called()

    def test_existing_mod_copy_is_not_overwritten(self):
        item = ('/Game/Template', '/Mod/Template', '/Mod/Custom')
        library = SimpleNamespace(does_asset_exist=Mock(return_value=True), duplicate_asset=Mock())
        with patch.object(setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library, log=Mock())):
            self.assertEqual(setup.checkout_copies({'copies': [item]}, {}), [item])
        library.duplicate_asset.assert_not_called()

    def test_failed_copy_warns_and_is_not_renamed(self):
        item = ('/Game/Template', '/Mod/Template', '/Mod/Custom')
        library = SimpleNamespace(
            does_asset_exist=Mock(return_value=False), duplicate_asset=Mock(return_value=None))
        with patch.object(setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library)), \
                patch.object(setup, 'warn') as warning:
            self.assertEqual(setup.checkout_copies({'copies': [item]}, {}), [])
        self.assertTrue(any('no copy in the mod' in call.args[0] for call in warning.call_args_list))


class SetupRecoveryTests(unittest.TestCase):
    def make(self):
        config = {'mod': 'TestMod', 'weapon': 'gun'}
        plan = {'selection': {field: ['donor'] for field in (
            'sequences', 'montages', 'collections', 'anim_blueprints', 'skeletal_meshes')},
            'copies': [('/Game/New', '/TestMod/New', '/TestMod/Gun'),
                       ('/Game/Existing', '/TestMod/Existing', '/TestMod/Custom')]}
        asset = Mock()
        existing = {'/TestMod/Custom'}

        def duplicate(source, target):
            existing.add(target)
            return asset

        library = SimpleNamespace(
            does_directory_exist=Mock(return_value=True), does_asset_exist=lambda path: path in existing,
            duplicate_asset=Mock(side_effect=duplicate), save_loaded_asset=Mock(return_value=True))
        return config, plan, library, asset

    def run_recovery(self, config, plan, library, failures=0):
        with patch.object(setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library, log=Mock())), \
                patch.object(setup, 'registry_assets', return_value=(None, [])), \
                patch.object(setup, 'build_plan', return_value=plan), \
                patch.object(setup, 'patch_references', return_value=failures):
            return setup.ensure_mod_assets(config)

    def test_missing_assets_are_saved_existing_assets_preserved_and_repeat_is_safe(self):
        config, plan, library, asset = self.make()
        self.assertIs(self.run_recovery(config, plan, library), plan)
        self.run_recovery(config, plan, library)
        library.duplicate_asset.assert_called_once_with('/Game/New', '/TestMod/Gun')
        library.save_loaded_asset.assert_called_once_with(asset, False)

    def test_missing_donor_collection_stops_before_writes(self):
        config, plan, library, _asset = self.make()
        plan['selection']['collections'] = []
        with self.assertRaisesRegex(RuntimeError, 'no collections'):
            self.run_recovery(config, plan, library)
        library.duplicate_asset.assert_not_called()

    def test_save_and_reference_failures_are_fatal(self):
        config, plan, library, _asset = self.make()
        library.save_loaded_asset.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'Cannot save'):
            self.run_recovery(config, plan, library)
        with self.assertRaisesRegex(RuntimeError, 'repair setup references'):
            self.run_recovery(config, plan, library, failures=1)

    def test_base_game_mount_is_rejected(self):
        config, plan, library, _asset = self.make()
        config['mod'] = 'Game'
        with self.assertRaisesRegex(RuntimeError, 'mod-owned'):
            self.run_recovery(config, plan, library)
        library.duplicate_asset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
