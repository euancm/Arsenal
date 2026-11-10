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


class SetupCopyTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
