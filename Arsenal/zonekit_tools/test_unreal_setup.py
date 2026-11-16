"""Run with Python: verify which template packages setup exports, without starting ZoneKit."""
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


path = Path(__file__).parents[1] / 'stalker2_arsenal' / 'unreal_setup.py'
spec = importlib.util.spec_from_file_location('arsenal_unreal_setup', path)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
with patch.object(sys, 'path', [str(Path(__file__).parent), *sys.path]):
    spec = importlib.util.spec_from_file_location('arsenal_template_builder', Path(__file__).with_name('build_weapon_templates.py'))
    templates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(templates)

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

    def test_attachment_catalogue_includes_sights_pump_and_distinct_laser_mounts(self):
        attachments = {
            'Sight': {'AttachType': 'EAttachType::IronSight', 'IronSight': {'MeshArray': {
                '[0]': {'MeshPrototypeSID': 'Front', 'Socket': 'IronSightFront'},
                '[1]': {'MeshPrototypeSID': 'Rear', 'Socket': 'IronSightRear'}}}},
            'Pump': {'AttachType': 'EAttachType::Grip', 'MeshPrototypeSID': 'PumpMesh'},
            'Laser': {'AttachType': 'EAttachType::Lasersight', 'MeshPrototypeSID': 'LaserMesh'},
            'Laser2': {'AttachType': 'EAttachType::Lasersight', 'MeshPrototypeSID': 'LaserMesh2'},
            'Scope': {'AttachType': 'EAttachType::Scope', 'MeshPrototypeSID': 'ScopeMesh'},
        }
        meshes = {sid: {'MeshPath': f"StaticMesh'/Game/Test/{sid}.{sid}'"}
                  for sid in ('Front', 'Rear', 'PumpMesh', 'LaserMesh', 'LaserMesh2', 'ScopeMesh')}
        config = {
            'PreinstalledAttachmentsItemPrototypeSIDs': {'[0]': {'AttachSID': 'Pump'}},
            'CompatibleAttachments': {str(index): {'AttachPrototypeSID': sid, 'Socket': socket}
                                     for index, (sid, socket) in enumerate((
                                         ('Sight', 'IronSightRear'), ('Pump', 'jnt_bolt_action'),
                                         ('Laser', 'LaserSocket'), ('Laser2', 'LaserSocket2'),
                                         ('Scope', 'ScopeSocket')))}}
        mounts = templates.attachment_mounts(config, attachments, meshes)
        self.assertEqual({row['mesh'].rsplit('/', 1)[-1]: row['socket'] for row in mounts}, {
            'Front': 'IronSightFront', 'Rear': 'IronSightRear', 'PumpMesh': 'jnt_bolt_action',
            'LaserMesh': 'LaserSocket', 'LaserMesh2': 'LaserSocket2', 'ScopeMesh': 'ScopeSocket'})
        options = templates.attachment_options(config, attachments, meshes)
        scope = next(row for row in options if row['sid'] == 'Scope')
        self.assertEqual(scope['mounts'], [{'mesh': '/Game/Test/ScopeMesh', 'socket': 'ScopeSocket'}])
        self.assertFalse(scope['preinstalled'])
        plan = setup.build_plan([], {
            'anim_tokens': ['test'], 'mesh_tokens': ['test'], 'export_dir': 'EXPORT',
            'mod': 'TestMod', 'weapon': 'test', 'attachment_meshes': [row['mesh'] for row in mounts]})
        self.assertEqual({package for package, _path in plan['exports']},
                         {row['mesh'] for row in mounts} | {setup.CHARACTER_MESH})
        meshes['LaserOverride'] = {'MeshPath': "StaticMesh'/Game/Test/LaserOverride.LaserOverride'"}
        config['CompatibleAttachments']['2']['MeshPrototypeSID'] = 'LaserOverride'
        overrides = templates.attachment_mounts(config, attachments, meshes)
        self.assertIn({'mesh': '/Game/Test/LaserOverride', 'socket': 'LaserSocket'}, overrides)
        self.assertNotIn('/Game/Test/LaserMesh', [row['mesh'] for row in overrides])

    def test_existing_skeletal_launcher_is_exported_but_not_duplicated_into_mod(self):
        path = '/Game/_STALKER2/SkeletalMeshes/weapons/attaches/GrenadeLauncher/SK_gla'
        config = {'anim_tokens': ['m160'], 'mesh_tokens': ['m160'], 'export_dir': 'EXPORT',
                  'mod': 'TestMod', 'weapon': 'test', 'attachment_meshes': [path]}
        plan = setup.build_plan([(path, 'SkeletalMesh')], config)
        self.assertEqual([package for package, _file in plan['exports']], [path, setup.CHARACTER_MESH])
        self.assertEqual(plan['copies'], [])

    def test_player_body_is_exported_as_a_mesh_but_never_copied(self):
        config = {'anim_tokens': ['test'], 'mesh_tokens': ['test'], 'export_dir': 'EXPORT',
                  'mod': 'TestMod', 'weapon': 'test'}
        plan = setup.build_plan([], config)
        self.assertEqual(plan['exports'], [(setup.CHARACTER_MESH, setup.export_file(setup.CHARACTER_MESH, 'EXPORT', '.glb'))])
        self.assertIn(setup.CHARACTER_MESH, setup.mesh_packages(plan['selection']))
        self.assertEqual(plan['copies'], [])
        self.assertEqual(setup.build_plan([], dict(config, character_mesh=''))['exports'], [])

    def test_magazine_mounts_support_arrays_and_single_meshes_without_half_variants(self):
        attachments = {
            'Magazine': {'AttachType': 'EAttachType::Magazine', 'Magazine': {
                'HasMultipleMeshes': 'true', 'MeshArray': {
                    str(index): {'MeshPrototypeSID': kind, 'MagazineMeshType': 'EMagazineMeshType::' + kind}
                    for index, kind in enumerate(('Full', 'Empty', 'Half'))}}},
            'Belt': {'AttachType': 'EAttachType::Magazine', 'MeshPrototypeSID': 'BeltMesh',
                     'Magazine': {'HasMultipleMeshes': 'false'}},
        }
        meshes = {sid: {'MeshPath': f"StaticMesh'/Game/Test/{sid}.{sid}'"}
                  for sid in ('Full', 'Empty', 'Half', 'BeltMesh')}
        config = {
            'PreinstalledAttachmentsItemPrototypeSIDs': {},
            'CompatibleAttachments': {sid: {'AttachPrototypeSID': sid, 'Socket': 'jnt_clip_base'}
                                     for sid in attachments}}
        mounts = templates.attachment_mounts(config, attachments, meshes)
        self.assertEqual({row['mesh'] for row in mounts},
                         {'/Game/Test/Full', '/Game/Test/Empty', '/Game/Test/BeltMesh'})


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


class SetupOrderTests(unittest.TestCase):
    def test_player_body_is_exported_after_the_mod_is_saved(self):
        body = setup.CHARACTER_MESH
        plan = {'selection': {'sequences': ['/Game/A'], 'skeletal_meshes': ['/Game/Gun'],
                              'character_meshes': [body]},
                'exports': [('/Game/A', 'a.fbx'), (body, 'body.glb'), ('/Game/Gun', 'gun.fbx')],
                'copies': []}
        calls = []
        library = SimpleNamespace(does_directory_exist=Mock(return_value=True),
                                  save_directory=Mock(side_effect=lambda *a, **k: calls.append('save')))
        config = {'template': 'TemplatePistol', 'weapon': 'gun', 'mod': 'TestMod', 'export_dir': 'EXPORT'}
        recorded = lambda name, result=None: Mock(side_effect=lambda *a, **k: calls.append(name) or result)
        with patch.object(setup, 'CONFIG', config), \
                patch.object(setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library, log=Mock())), \
                patch.object(setup, 'registry_assets', return_value=(None, [])), \
                patch.object(setup, 'build_plan', return_value=plan), \
                patch.object(setup, 'run_exports', side_effect=lambda _p, _c, exports: calls.append(
                    [package for package, _file in exports])), \
                patch.object(setup, 'export_sockets', recorded('sockets')), \
                patch.object(setup, 'export_textures', recorded('textures')), \
                patch.object(setup, 'checkout_copies', recorded('checkout', [])), \
                patch.object(setup, 'run_rename', return_value=0), \
                patch.object(setup, 'patch_references'), patch.object(setup, 'check_montages'), \
                patch.object(setup, 'tidy_redirectors', return_value=0), \
                patch.object(setup, 'check_references', return_value=0), \
                patch.object(setup, 'write_report'):
            setup._main()
        self.assertEqual(calls, [['/Game/A', '/Game/Gun'], 'sockets', 'textures', 'checkout', 'save', [body]])


if __name__ == '__main__':
    unittest.main()
