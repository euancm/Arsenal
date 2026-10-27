"""Run with Python: verify which template packages setup exports, without starting ZoneKit."""
import importlib.util
from pathlib import Path
import unittest


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


if __name__ == '__main__':
    unittest.main()
