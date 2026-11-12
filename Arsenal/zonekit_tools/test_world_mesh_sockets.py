"""Asset-free world magazine socket tests: python -m unittest Arsenal.zonekit_tools.test_world_mesh_sockets."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


path = Path(__file__).parents[1] / 'stalker2_arsenal' / 'unreal_import.py'
spec = importlib.util.spec_from_file_location('world_socket_runtime', path)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Socket:
    def __init__(self, outer):
        self.outer = outer
        self.values = {'relative_location': SimpleNamespace(x=0, y=0, z=0),
                       'relative_rotation': SimpleNamespace(roll=0, pitch=0, yaw=0),
                       'relative_scale': SimpleNamespace(x=1, y=1, z=1)}

    def get_editor_property(self, name):
        return self.values[name]

    def set_editor_property(self, name, value):
        self.values[name] = value

    def get_outer(self):
        return self.outer

    def modify(self):
        pass


class Mesh:
    def __init__(self):
        self.sockets = []
        self.modify = Mock()

    def get_socket_names(self):
        return [socket.values['socket_name'] for socket in self.sockets]

    def find_socket(self, name):
        return next((socket for socket in self.sockets
                     if socket.values['socket_name'] == name), None)

    def add_socket(self, socket):
        self.sockets.append(socket)

    def remove_socket(self, socket):
        self.sockets.remove(socket)


class WorldSocketTests(unittest.TestCase):
    def setUp(self):
        self.mesh = Mesh()
        self.entry = dict(name='jnt_magazine', location=[-0.9368, 0, -3.5492],
                          rotation=[0, 0, 0], scale=[1, 1, 1])
        self.manifest = dict(game_root='/TestMod', static_meshes=['weapons/SM_test.FBX'],
                             world_mesh_sockets=dict(version=1, units='cm',
                                                     mesh='/TestMod/weapons/SM_test', entries=[self.entry]))
        self.importer = runtime.Importer.__new__(runtime.Importer)
        self.importer.manifest = self.manifest
        self.importer.library = SimpleNamespace(
            load_asset=Mock(return_value=self.mesh), save_loaded_asset=Mock(return_value=True))
        self.importer.counts = {}
        self.api = SimpleNamespace(
            StaticMesh=Mesh, StaticMeshSocket=Socket,
            Vector=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z),
            Rotator=lambda **kwargs: SimpleNamespace(**kwargs))

    def apply(self):
        with patch.object(runtime, 'unreal', self.api), patch.object(runtime, 'log'):
            self.importer.apply_world_mesh_sockets()

    def test_creates_mesh_owned_socket_and_saves_dirty_owner(self):
        self.apply()
        socket = self.mesh.find_socket('jnt_magazine')
        self.assertIs(socket.get_outer(), self.mesh)
        self.assertTrue(runtime.socket_transforms_equal(runtime.socket_transform(socket), self.entry))
        self.mesh.modify.assert_called_once()
        self.importer.library.save_loaded_asset.assert_called_once_with(self.mesh)

    def test_repeat_is_noop_and_unrelated_sockets_are_preserved(self):
        other = Socket(self.mesh)
        other.values['socket_name'] = 'Unrelated'
        self.mesh.add_socket(other)
        self.apply()
        self.importer.library.save_loaded_asset.reset_mock()
        self.apply()
        self.assertEqual(len(self.mesh.sockets), 2)
        self.assertIs(self.mesh.find_socket('Unrelated'), other)
        self.importer.library.save_loaded_asset.assert_not_called()

    def test_reimport_or_changed_rest_frame_updates_existing_socket(self):
        self.apply()
        self.entry['location'][2] = -4
        self.apply()
        self.assertEqual(len(self.mesh.sockets), 1)
        self.assertEqual(runtime.socket_transform(self.mesh.sockets[0])['location'][2], -4)

    def test_duplicate_existing_names_fail_before_modifying_mesh(self):
        for name in ('jnt_magazine', 'JNT_MAGAZINE'):
            socket = Socket(self.mesh)
            socket.values['socket_name'] = name
            self.mesh.add_socket(socket)
        with self.assertRaisesRegex(RuntimeError, 'Duplicate existing world'):
            self.apply()
        self.mesh.modify.assert_not_called()
        self.importer.library.save_loaded_asset.assert_not_called()

    def test_foreign_owned_socket_fails_before_modifying_mesh(self):
        socket = Socket(Mesh())
        socket.values['socket_name'] = 'jnt_magazine'
        self.mesh.add_socket(socket)
        with self.assertRaisesRegex(RuntimeError, 'not owned by its static mesh'):
            self.apply()
        self.mesh.modify.assert_not_called()
        self.importer.library.save_loaded_asset.assert_not_called()

    def test_failed_save_removes_new_socket(self):
        self.importer.library.save_loaded_asset.side_effect = [False, True]
        with self.assertRaisesRegex(RuntimeError, 'Could not save world'):
            self.apply()
        self.assertEqual(self.mesh.sockets, [])

    def test_failed_save_restores_existing_socket(self):
        self.apply()
        before = runtime.socket_transform(self.mesh.sockets[0])
        self.entry['location'][2] = -4
        self.importer.library.save_loaded_asset.side_effect = [False, True]
        with self.assertRaisesRegex(RuntimeError, 'Could not save world'):
            self.apply()
        self.assertEqual(runtime.socket_transform(self.mesh.sockets[0]), before)

    def test_failed_rollback_save_is_explicit(self):
        self.importer.library.save_loaded_asset.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'rollback failed.*could not save restored'):
            self.apply()

    def test_invalid_payload_rejected_before_loading_or_modifying_assets(self):
        original = copy.deepcopy(self.manifest)
        invalids = (
            lambda payload: payload.update(mesh='/Game/SM_test'),
            lambda payload: payload.update(mesh='/TestMod/OtherStaticMesh'),
            lambda payload: payload.update(version=2),
            lambda payload: payload.update(units='m'),
            lambda payload: payload['entries'].append(copy.deepcopy(payload['entries'][0])),
            lambda payload: payload['entries'][0]['location'].__setitem__(0, float('nan')),
        )
        for invalidate in invalids:
            self.importer.manifest = copy.deepcopy(original)
            invalidate(self.importer.manifest['world_mesh_sockets'])
            with self.assertRaises(RuntimeError):
                self.apply()
            self.importer.library.load_asset.assert_not_called()
        self.mesh.modify.assert_not_called()

    def test_old_manifest_is_unchanged(self):
        del self.manifest['world_mesh_sockets']
        self.apply()
        self.importer.library.load_asset.assert_not_called()

    def test_dry_run_reports_and_validates_world_mounts_without_loading_assets(self):
        with patch.object(runtime, 'build_plan', return_value={}), patch('builtins.print') as output:
            runtime.print_plan(self.manifest, '')
            output.assert_any_call('world magazine sockets: 1 on /TestMod/weapons/SM_test')
            self.manifest['world_mesh_sockets']['mesh'] = '/Game/SM_test'
            with self.assertRaises(RuntimeError):
                runtime.print_plan(self.manifest, '')
        self.importer.library.load_asset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
