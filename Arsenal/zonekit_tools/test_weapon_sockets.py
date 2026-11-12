"""Asset-free socket transport tests: python -m unittest Arsenal.zonekit_tools.test_weapon_sockets."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch


def load_module(name):
    path = Path(__file__).parents[1] / 'stalker2_arsenal' / (name + '.py')
    spec = importlib.util.spec_from_file_location('socket_test_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load_module('unreal_setup')
runtime = load_module('unreal_import')


class SocketCatalogueTests(unittest.TestCase):
    def test_reference_pose_uses_matching_skeleton_and_explicit_mesh(self):
        mesh, other, sequence, pose = Mock(), Mock(), Mock(), Mock()
        skeleton = mesh.get_editor_property.return_value
        sequence.get_editor_property.return_value = skeleton
        options = SimpleNamespace()
        library = SimpleNamespace(load_asset=Mock(side_effect=[other, sequence]))
        evaluate = Mock(return_value=pose)
        with patch.object(setup, 'unreal', SimpleNamespace(
                EditorAssetLibrary=library, AnimPoseEvaluationOptions=lambda: options,
                AnimDataEvalType=SimpleNamespace(RAW='raw'),
                AnimPoseExtensions=SimpleNamespace(get_anim_pose_at_frame=evaluate))):
            self.assertIs(setup.socket_reference_pose(mesh, ['weapon_shoot', 'player_idle']), pose)
            with self.assertRaisesRegex(RuntimeError, 'No sequence'):
                setup.socket_reference_pose(mesh, [])
        self.assertEqual(library.load_asset.call_args_list[0].args, ('player_idle',))
        evaluate.assert_called_once_with(sequence, 0, options)
        self.assertIs(options.optional_skeletal_mesh, mesh)
        self.assertFalse(options.should_retarget)
        self.assertTrue(options.retrieve_additive_as_full_pose)

    def test_catalogue_only_mode_never_copies_or_saves_assets(self):
        config = {'weapon': 'test', 'mod': 'TestMod', 'template': 'TemplatePistol', 'export_dir': 'unused'}
        plan = {'selection': {'sequences': ['sequence'], 'skeletal_meshes': ['mesh']}}
        with patch.object(setup, 'unreal', SimpleNamespace(log=Mock())), \
                patch.object(setup, 'load_config', return_value=config), \
                patch.object(setup, 'registry_assets', return_value=(None, [])), \
                patch.object(setup, 'build_plan', return_value=plan), \
                patch.object(setup, 'export_sockets') as export, \
                patch.object(setup, 'run_exports') as exports, \
                patch.object(setup, 'checkout_copies') as copies, \
                patch.object(setup.os, 'makedirs'), \
                patch.object(setup.sys, 'argv', ['setup.py', '--sockets-only']):
            setup._main()
        export.assert_called_once_with(plan, config)
        exports.assert_not_called()
        copies.assert_not_called()

    def test_enumerates_inherited_sockets_and_retains_shadowed_records_per_mesh(self):
        inherited = Mock()
        owned = Mock()
        for socket, outer in [(inherited, '/Game/SKEL.SKEL'), (owned, '/Game/SK.SK')]:
            values = {
                'socket_name': 'CameraSocket', 'bone_name': 'jnt_offset',
                'relative_location': SimpleNamespace(x=1, y=2, z=3),
                'relative_rotation': SimpleNamespace(roll=15, pitch=30, yaw=45),
                'relative_scale': SimpleNamespace(x=1, y=1, z=1),
            }
            socket.get_editor_property.side_effect = values.__getitem__
            socket.get_path_name.return_value = outer + ':Socket'
            socket.get_outer.return_value.get_path_name.return_value = outer
        mesh = Mock()
        mesh.num_sockets.return_value = 2
        mesh.get_socket_by_index.side_effect = [owned, inherited, owned, inherited]
        mesh.find_socket.side_effect = lambda name: owned if name == 'CameraSocket' else None
        mesh.get_editor_property.return_value.get_path_name.return_value = '/Game/SKEL.SKEL'
        reference = Mock()
        reference.get_bone_names.return_value = ['jnt_offset']
        reference.get_ref_bone_pose.return_value = SimpleNamespace(
            translation=SimpleNamespace(x=0, y=0, z=0),
            rotation=SimpleNamespace(x=0, y=0, z=0, w=1),
            scale3d=SimpleNamespace(x=1, y=1, z=1))
        library = SimpleNamespace(load_asset=Mock(return_value=mesh))
        with tempfile.TemporaryDirectory() as folder, patch.object(
                setup, 'unreal', SimpleNamespace(EditorAssetLibrary=library, log=Mock(),
                                                 SkeletalMeshComponent=lambda: SimpleNamespace(
                                                     set_skeletal_mesh_asset=Mock(),
                                                     get_bone_name=Mock(return_value='jnt_offset')),
                                                 AnimPoseEvaluationOptions=SimpleNamespace,
                                                 AnimDataEvalType=SimpleNamespace(RAW='raw'),
                                                 AnimPoseExtensions=SimpleNamespace(
                                                     get_anim_pose_at_frame=Mock(return_value=reference)),
                                                 AnimPoseSpaces=SimpleNamespace(WORLD='world'))):
            setup.export_sockets({'selection': {'skeletal_meshes': ['/Game/SK', '/Game/SK2'],
                                               'sequences': ['sequence']}},
                                 {'export_dir': folder})
            data = json.loads((Path(folder) / 'weapon_sockets.json').read_text())
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['units'], 'cm')
        self.assertEqual(len(data['meshes']), 2)
        for record in data['meshes']:
            self.assertEqual(len(record['sockets']), 2)
            self.assertEqual(record['root_bone'], 'jnt_offset')
            self.assertEqual([s['effective'] for s in record['sockets']], [True, False])
            self.assertEqual(record['sockets'][0]['rotation'], [15, 30, 45])
        mesh.set_editor_property.assert_not_called()


BASELINE = {'location': [1, 2, 3], 'rotation': [15, 30, 45], 'scale': [1, 1, 1]}


class Owner:
    def __init__(self, path):
        self.path = path

    def get_path_name(self):
        return self.path + '.' + self.path.rsplit('/', 1)[-1]


class Socket:
    def __init__(self, owner, name='CameraSocket', bone='jnt_offset'):
        self.owner = owner
        self.values = {'socket_name': name, 'bone_name': bone}
        self.writes = []
        self.set_transform(BASELINE)
        self.writes.clear()

    def set_transform(self, transform):
        self.values.update(
            relative_location=SimpleNamespace(**dict(zip('xyz', transform['location']))),
            relative_rotation=SimpleNamespace(**dict(zip(('roll', 'pitch', 'yaw'), transform['rotation']))),
            relative_scale=SimpleNamespace(**dict(zip('xyz', transform['scale']))))

    def get_editor_property(self, name):
        return self.values[name]

    def set_editor_property(self, name, value):
        self.writes.append(name)
        self.values[name] = value

    def get_outer(self):
        return self.owner

    def get_path_name(self):
        return self.owner.get_path_name() + ':' + self.values['socket_name']

    def get_name(self):
        return 'Socket_' + self.values['socket_name']

    def rename(self, name, outer):
        self.owner = outer
        return True


class Mesh(Owner):
    def __init__(self):
        super().__init__('/TestMod/SK_weapon')
        self.skeleton = Owner('/TestMod/SKEL_weapon')
        self.sockets = {'CameraSocket': Socket(self)}
        self.dirty = False

    def modify(self):
        self.dirty = True

    def find_socket(self, name):
        return self.sockets.get(name)

    def get_editor_property(self, name):
        if name == 'skeleton':
            return self.skeleton
        raise KeyError(name)


class SocketWriterTests(unittest.TestCase):
    def setUp(self):
        self.mesh = Mesh()
        self.tags = {}
        self.library = SimpleNamespace(
            load_asset=Mock(return_value=self.mesh),
            get_metadata_tag=lambda owner, tag: self.tags.get(tag, ''),
            set_metadata_tag=lambda owner, tag, value: self.tags.__setitem__(tag, value),
            remove_metadata_tag=lambda owner, tag: self.tags.pop(tag, None),
            save_loaded_asset=Mock(return_value=True))
        self.api = SimpleNamespace(
            SkeletalMesh=Mesh, Vector=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z),
            Rotator=lambda **kwargs: SimpleNamespace(**kwargs), log=Mock(), log_warning=Mock(),
            SkeletalMeshComponent=lambda: SimpleNamespace(
                set_skeletal_mesh_asset=Mock(), get_bone_index=Mock(return_value=0)))
        self.entry = {
            'name': 'CameraSocket', 'bone': 'jnt_offset', 'enabled': True,
            'baseline': copy.deepcopy(BASELINE), 'transform': copy.deepcopy(BASELINE)}
        self.entry['transform']['location'][2] += 1
        self.importer = runtime.Importer.__new__(runtime.Importer)
        self.importer.manifest = {
            'game_root': '/TestMod', 'weapon_skeleton': self.mesh.path,
            'weapon_sockets': {'version': 1, 'units': 'cm', 'mesh': self.mesh.path, 'entries': [self.entry]}}
        self.importer.library = self.library
        self.importer.counts = {}

    def apply(self):
        with patch.object(runtime, 'unreal', self.api):
            self.importer.apply_weapon_sockets()

    def test_socket_save_marks_the_mesh_package_dirty(self):
        saved = []

        def save(mesh):
            if mesh.dirty:
                saved.append(runtime.socket_transform(mesh.find_socket('CameraSocket')))
            return True

        self.library.save_loaded_asset.side_effect = save
        self.apply()
        self.assertEqual(saved, [self.entry['transform']])

    def configure_missing_socket_donor(self):
        donor = Mesh()
        donor.path = '/Game/SK_donor'
        donor.skeleton = Owner('/Game/SKEL_donor')
        source = Socket(donor.skeleton)
        donor.sockets['CameraSocket'] = source
        self.mesh.sockets.clear()
        self.importer.manifest['weapon_sockets']['source_mesh'] = donor.path
        self.library.load_asset.side_effect = lambda path: donor if path == donor.path else self.mesh
        clone = Owner('/TestMod/_ArsenalSocketStaging/temporary/SocketSource')
        copied = Socket(clone)
        self.library.duplicate_asset = Mock(return_value=clone)
        self.library.delete_loaded_asset = Mock(return_value=True)
        self.api.load_object = Mock(return_value=copied)
        self.mesh.add_socket = lambda socket, add_to_skeleton: self.mesh.sockets.__setitem__(
            socket.values['socket_name'], socket)
        return source, copied

    def test_new_mesh_receives_unchanged_donor_sockets_too(self):
        source, copied = self.configure_missing_socket_donor()
        self.entry['enabled'] = False
        self.apply()
        self.assertIs(self.mesh.find_socket('CameraSocket'), copied)
        self.assertEqual(runtime.socket_transform(copied), BASELINE)
        self.assertTrue(json.loads(self.tags['ArsenalWeaponSocketsV1'])['CameraSocket']['created'])
        self.assertFalse(source.writes)
        self.library.save_loaded_asset.assert_called_once_with(self.mesh)
        self.apply()
        self.library.duplicate_asset.assert_called_once()

    def test_reimport_removing_all_sockets_reapplies_from_donor(self):
        self.apply()
        source, copied = self.configure_missing_socket_donor()
        self.apply()
        self.assertTrue(runtime.socket_transforms_equal(
            runtime.socket_transform(copied), self.entry['transform']))
        self.assertFalse(source.writes)

    def test_missing_destination_bone_is_rejected_before_copying(self):
        source, _copied = self.configure_missing_socket_donor()
        self.api.SkeletalMeshComponent = lambda: SimpleNamespace(
            set_skeletal_mesh_asset=Mock(), get_bone_index=Mock(return_value=-1))
        with self.assertRaisesRegex(RuntimeError, 'no destination bone'):
            self.apply()
        self.library.duplicate_asset.assert_not_called()
        self.assertFalse(source.writes)

    def test_changed_donor_is_rejected_before_copying(self):
        source, _copied = self.configure_missing_socket_donor()
        source.set_transform(self.entry['transform'])
        with self.assertRaisesRegex(RuntimeError, 'Donor socket.*changed'):
            self.apply()
        self.library.duplicate_asset.assert_not_called()
        self.assertFalse(source.writes)

    def test_apply_repeat_and_reset_preserve_unrelated_sockets(self):
        unrelated = Socket(self.mesh.skeleton, 'Muzzle')
        self.mesh.sockets['Muzzle'] = unrelated
        self.apply()
        self.assertTrue(runtime.socket_transforms_equal(
            runtime.socket_transform(self.mesh.sockets['CameraSocket']), self.entry['transform']))
        self.library.save_loaded_asset.assert_called_once_with(self.mesh)
        self.library.save_loaded_asset.reset_mock()
        self.apply()
        self.library.save_loaded_asset.assert_not_called()
        self.entry['enabled'] = False
        self.apply()
        self.assertEqual(runtime.socket_transform(self.mesh.sockets['CameraSocket']), BASELINE)
        self.assertEqual(json.loads(self.tags['ArsenalWeaponSocketsV1']), {})
        self.assertEqual(unrelated.writes, [])

    def test_baseline_and_legacy_payloads_make_no_writes(self):
        self.entry['transform'] = copy.deepcopy(BASELINE)
        self.apply()
        self.assertEqual(self.tags, {})
        self.library.save_loaded_asset.assert_not_called()
        del self.importer.manifest['weapon_sockets']
        self.apply()
        self.library.load_asset.assert_called_once()

    def test_every_entry_validated_before_first_write(self):
        unknown = copy.deepcopy(self.entry)
        unknown['name'] = 'UnknownSocket'
        self.importer.manifest['weapon_sockets']['entries'].append(unknown)
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            self.apply()
        self.assertFalse(self.mesh.sockets['CameraSocket'].writes)
        self.library.save_loaded_asset.assert_not_called()

    def test_shared_owners_are_never_modified(self):
        for path in ['/Game/SKEL_weapon', '/OtherMod/SKEL_weapon']:
            with self.subTest(path=path):
                self.mesh.sockets['CameraSocket'].owner = Owner(path)
                with self.assertRaisesRegex(RuntimeError, 'Unexpected owner'):
                    self.apply()
                self.assertFalse(self.mesh.sockets['CameraSocket'].writes)
        self.library.save_loaded_asset.assert_not_called()

    def test_inherited_sockets_are_independently_copied_and_only_mesh_is_saved(self):
        self.mesh.skeleton = Owner('/Game/SKEL_weapon')
        source = Socket(self.mesh.skeleton)
        self.mesh.sockets['CameraSocket'] = source
        clone = Owner('/TestMod/_ArsenalSocketStaging/temporary/SocketSource')
        copied = Socket(clone)
        self.library.duplicate_asset = Mock(return_value=clone)
        self.library.delete_loaded_asset = Mock(return_value=True)
        self.api.load_object = Mock(return_value=copied)
        self.mesh.add_socket = lambda socket, add_to_skeleton: self.mesh.sockets.__setitem__(
            socket.values['socket_name'], socket)
        self.apply()
        self.assertIs(self.mesh.find_socket('CameraSocket'), copied)
        self.assertIs(copied.get_outer(), self.mesh)
        self.assertFalse(source.writes)
        self.assertEqual(runtime.socket_transform(source), BASELINE)
        self.library.save_loaded_asset.assert_called_once_with(self.mesh)
        self.library.delete_loaded_asset.assert_called_once_with(clone)
        self.entry['enabled'] = False
        self.apply()
        self.assertEqual(runtime.socket_transform(copied), BASELINE)
        self.assertTrue(json.loads(self.tags['ArsenalWeaponSocketsV1'])['CameraSocket']['created'])

    def test_missing_copy_api_fails_before_writing_inherited_socket(self):
        source = self.mesh.sockets['CameraSocket']
        source.owner = self.mesh.skeleton
        with self.assertRaisesRegex(RuntimeError, 'independent mesh socket'):
            self.apply()
        self.assertFalse(source.writes)
        self.library.save_loaded_asset.assert_not_called()

    def test_external_edits_and_unmanaged_overrides_are_rejected(self):
        edited = copy.deepcopy(BASELINE)
        edited['location'][0] += 2
        self.mesh.sockets['CameraSocket'].set_transform(edited)
        with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
            self.apply()
        self.mesh.sockets['CameraSocket'].set_transform(BASELINE)
        self.apply()
        self.mesh.sockets['CameraSocket'].set_transform(edited)
        with self.assertRaisesRegex(RuntimeError, 'outside Arsenal'):
            self.apply()

    def test_readback_failure_restores_old_transforms(self):
        socket = self.mesh.sockets['CameraSocket']
        original_set = socket.set_editor_property

        def ignore_first_location(name, value):
            if name == 'relative_location' and value.z == 4:
                return
            original_set(name, value)
        socket.set_editor_property = ignore_first_location
        with self.assertRaisesRegex(RuntimeError, 'readback'):
            self.apply()
        self.assertEqual(runtime.socket_transform(socket), BASELINE)
        self.assertEqual(self.tags, {})

    def test_save_failure_rolls_back_and_reports_failed_rollback_save(self):
        self.library.save_loaded_asset.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'rollback failed'):
            self.apply()
        self.assertEqual(runtime.socket_transform(self.mesh.sockets['CameraSocket']), BASELINE)
        self.assertEqual(self.tags, {})

    def test_parent_bone_changes_are_rejected(self):
        self.entry['bone'] = 'jnt_unknown'
        with self.assertRaisesRegex(RuntimeError, 'bone changed'):
            self.apply()
        self.assertFalse(self.mesh.sockets['CameraSocket'].writes)

    def test_invalid_payloads_fail_before_loading_assets(self):
        payload = self.importer.manifest['weapon_sockets']
        invalids = [
            lambda: payload.update(version=2),
            lambda: payload.update(units='m'),
            lambda: payload.update(mesh='/Game/SK_weapon'),
            lambda: payload.update(source_mesh='/Game/../SK_weapon'),
            lambda: payload['entries'].append(copy.deepcopy(self.entry)),
            lambda: self.entry['transform']['rotation'].__setitem__(0, float('nan')),
            lambda: self.entry['transform']['scale'].__setitem__(0, -1),
            lambda: self.entry['transform']['scale'].__setitem__(0, 2),
        ]
        original = copy.deepcopy(self.importer.manifest)
        for invalidate in invalids:
            with self.subTest(invalidate=invalidate):
                invalidate()
                with self.assertRaises(RuntimeError):
                    self.apply()
                self.library.load_asset.assert_not_called()
                self.importer.manifest = copy.deepcopy(original)
                payload = self.importer.manifest['weapon_sockets']
                self.entry = payload['entries'][0]

    def test_orientation_comparison_accepts_equivalent_euler_rotations(self):
        transform = copy.deepcopy(BASELINE)
        transform['rotation'][2] += 360
        self.assertTrue(runtime.socket_transforms_equal(BASELINE, transform))
        transform['rotation'][2] += 0.02
        self.assertFalse(runtime.socket_transforms_equal(BASELINE, transform))

    def test_translation_threshold_uses_vector_distance(self):
        transform = copy.deepcopy(BASELINE)
        transform['location'] = [v + 0.0007 for v in transform['location']]
        self.assertFalse(runtime.socket_transforms_equal(BASELINE, transform))

    def test_socket_only_entry_point_does_not_run_other_imports(self):
        importer = Mock()
        with patch.object(runtime, 'unreal', self.api), \
                patch.object(runtime, 'find_manifest', return_value='manifest.json'), \
                patch('builtins.open', mock_open(read_data=json.dumps(self.importer.manifest))), \
                patch.object(runtime, 'Importer', return_value=importer):
            runtime._main(['--sockets-only'])
        importer.apply_weapon_sockets.assert_called_once()
        importer.run.assert_not_called()

    def test_reimport_reset_to_baseline_is_reapplied(self):
        self.apply()
        self.mesh.sockets['CameraSocket'].set_transform(BASELINE)
        self.apply()
        self.assertTrue(runtime.socket_transforms_equal(
            runtime.socket_transform(self.mesh.sockets['CameraSocket']), self.entry['transform']))

    def test_save_failure_with_successful_rollback_is_reported(self):
        self.library.save_loaded_asset.side_effect = [False, True, True]
        with self.assertRaisesRegex(RuntimeError, 'Could not save socket owner'):
            self.apply()
        self.assertEqual(runtime.socket_transform(self.mesh.sockets['CameraSocket']), BASELINE)
        self.assertFalse(self.tags)


if __name__ == '__main__':
    unittest.main()
