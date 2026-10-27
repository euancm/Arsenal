"""Run with Python: verify animation task settings without starting ZoneKit."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


path = Path(__file__).parents[1] / 'stalker2_arsenal' / 'unreal_import.py'
spec = importlib.util.spec_from_file_location('arsenal_unreal_import', path)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Properties:
    def __init__(self, **values):
        self.values = values

    def set_editor_property(self, name, value):
        self.values[name] = value

    def get_editor_property(self, name):
        return self.values[name]

    def get_name(self):
        return self.values['path'].rsplit('/', 1)[-1]

    def get_path_name(self):
        return self.values['path']

    def get_play_length(self):
        return self.values['length']


class AnimationImportTests(unittest.TestCase):
    def make_importer(self):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.wanted = Mock(return_value=True)
        importer.skeleton = Mock(return_value=object())
        importer.counts = {}
        imported = []

        def import_tasks(tasks):
            imported.extend(tasks)
            for task in tasks:
                task.set_editor_property(
                    'imported_object_paths', [task.get_editor_property('destination_name')])

        importer.tools = SimpleNamespace(import_asset_tasks=import_tasks)
        unreal = SimpleNamespace(
            log=Mock(),
            log_warning=Mock(),
            FbxImportUI=lambda: Properties(anim_sequence_import_data=Properties()),
            AssetImportTask=Properties,
            FbxFactory=Properties,
            FBXImportType=SimpleNamespace(FBXIT_ANIMATION='animation'),
            AnimPoseEvaluationOptions=SimpleNamespace,
            AnimDataEvalType=SimpleNamespace(RAW='raw'),
            AnimPoseSpaces=SimpleNamespace(LOCAL='local'),
            SystemLibrary=SimpleNamespace(
                get_console_variable_bool_value=Mock(return_value=True),
                execute_console_command=Mock()),
        )
        return importer, unreal, imported

    def test_animation_tasks_preserve_baked_local_transforms(self):
        importer, unreal, imported = self.make_importer()
        files = [
            (r'C:\export\reload.fbx', '/Test/Animations', 'reload'),
            (r'C:\export\idle.fbx', '/Test/Animations', 'idle'),
        ]
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations(files, '/Game/TestSkeleton')
        self.assertEqual(len(imported), 2)
        self.assertEqual(importer.counts, {'imported': 2})
        factories = []
        for task, (filename, folder, name) in zip(imported, files):
            self.assertEqual(task.get_editor_property('filename'), filename)
            self.assertEqual(task.get_editor_property('destination_path'), folder)
            self.assertEqual(task.get_editor_property('destination_name'), name)
            self.assertTrue(task.get_editor_property('replace_existing_settings'))
            options = task.get_editor_property('options')
            self.assertEqual(options.get_editor_property('mesh_type_to_import'), 'animation')
            self.assertIs(options.get_editor_property('skeleton'), importer.skeleton.return_value)
            self.assertTrue(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'preserve_local_transform'))
            self.assertFalse(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'use_default_sample_rate'))
            self.assertEqual(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'custom_sample_rate'), 0)
            factories.append(task.get_editor_property('factory'))
            self.assertIsInstance(factories[-1], Properties)
        self.assertIsNot(factories[0], factories[1])
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_args_list, [
            ((None, 'Interchange.FeatureFlags.Import.FBX 0'),),
            ((None, 'Interchange.FeatureFlags.Import.FBX 1'),),
        ])

    def test_interchange_setting_restored_after_import_failure(self):
        importer, unreal, _imported = self.make_importer()
        importer.tools.import_asset_tasks = Mock(side_effect=RuntimeError('import failed'))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'import failed'):
                importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/Skeleton')
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_count, 2)
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_args.args,
                         (None, 'Interchange.FeatureFlags.Import.FBX 1'))

    def test_disabled_interchange_setting_is_left_alone(self):
        importer, unreal, _imported = self.make_importer()
        unreal.SystemLibrary.get_console_variable_bool_value.return_value = False
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/Skeleton')
        unreal.SystemLibrary.execute_console_command.assert_not_called()

    def test_skipped_animations_do_not_create_import_tasks(self):
        importer, unreal, imported = self.make_importer()
        importer.wanted.return_value = False
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/TestSkeleton')
        self.assertEqual(imported, [])
        importer.skeleton.assert_not_called()

    def test_static_import_rejects_planned_vanilla_package_collision(self):
        importer, unreal, imported = self.make_importer()
        importer.manifest = {'game_root': '/Test'}
        importer.plan = {'static_meshes': [(r'C:\export\mesh.fbx', '/Test/Weapons', 'VanillaMesh')]}
        importer.library = SimpleNamespace(does_asset_exist=lambda path: path == '/Game/Weapons/VanillaMesh')
        unreal.AssetRegistryHelpers = SimpleNamespace(get_asset_registry=lambda: SimpleNamespace(
            get_assets_by_path=lambda *args, **kwargs: []))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'override vanilla weapons'):
                importer.import_static_meshes()
        self.assertEqual(imported, [])

    def test_static_import_rejects_stale_mod_override_not_in_manifest(self):
        importer, unreal, imported = self.make_importer()
        importer.manifest = {'game_root': '/Test'}
        importer.plan = {'static_meshes': []}
        importer.library = SimpleNamespace(does_asset_exist=lambda path: path == '/Game/Weapons/OldMesh')
        old = SimpleNamespace(package_name='/Test/Weapons/OldMesh',
                              asset_class_path=SimpleNamespace(asset_name='StaticMesh'))
        unreal.AssetRegistryHelpers = SimpleNamespace(get_asset_registry=lambda: SimpleNamespace(
            get_assets_by_path=lambda *args, **kwargs: [old]))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'OldMesh'):
                importer.import_static_meshes()
        self.assertEqual(imported, [])

    def test_template_package_swaps_only_complete_weapon_tokens(self):
        self.assertEqual(runtime.template_sequence_package(
            '/Mod/ladybuggun/AS_fp_ladybuggun_shoot', 'ladybuggun', 'udp', '/Mod'),
            '/Game/udp/AS_fp_udp_shoot')
        self.assertEqual(runtime.template_sequence_package(
            '/Mod/ladybuggun_extra/ladybuggunner', 'ladybuggun', 'udp', '/Mod'),
            '/Game/udp_extra/ladybuggunner')
        with self.assertRaises(ValueError):
            runtime.template_sequence_package('/Game/udp/idle', 'ladybuggun', 'udp', '/Mod')

    def test_raw_comparison_checks_every_track_key(self):
        importer, unreal, _ = self.make_importer()
        a = Properties(path='/Mod/shoot', length=1)
        b = Properties(path='/Game/shoot', length=1)
        keys = [SimpleNamespace(x=0, y=0, z=0), SimpleNamespace(x=1, y=0, z=0)]
        tracks = {a: {'hand': (keys, keys, keys)}, b: {'hand': (list(keys), keys, keys)}}
        unreal.AnimationLibrary = SimpleNamespace(
            get_animation_track_names=lambda asset: list(tracks[asset]),
            get_num_frames=lambda _asset: 1,
            get_animation_interpolation_type=lambda _asset: 'linear')
        unreal.AnimPoseExtensions = SimpleNamespace(
            get_anim_pose_at_time=lambda asset, time, _options: (asset, round(time)),
            get_bone_pose=lambda pose, name, _space: SimpleNamespace(
                translation=tracks[pose[0]][name][0][pose[1]],
                rotation=SimpleNamespace(x=0, y=0, z=0, w=1),
                scale3d=SimpleNamespace(x=1, y=1, z=1)))
        with patch.object(runtime, 'unreal', unreal):
            self.assertTrue(importer.same_raw_animation(a, b))
            unreal.AnimationLibrary.get_animation_interpolation_type = lambda asset: 'step' if asset is b else 'linear'
            self.assertFalse(importer.same_raw_animation(a, b))
            unreal.AnimationLibrary.get_animation_interpolation_type = lambda _asset: 'linear'
            tracks[b]['hand'] = ([keys[0], SimpleNamespace(x=1.01, y=0, z=0)], keys, keys)
            self.assertFalse(importer.same_raw_animation(a, b))
            tracks[b] = {}
            self.assertFalse(importer.same_raw_animation(a, b))

    def test_quaternion_sign_does_not_trigger_an_idle_rewrite(self):
        def transform(rotation, x=0):
            return SimpleNamespace(
                translation=SimpleNamespace(x=x, y=0, z=0),
                rotation=rotation, scale3d=SimpleNamespace(x=1, y=1, z=1))

        a = transform(SimpleNamespace(x=.1, y=.2, z=.3, w=.9))
        b = transform(SimpleNamespace(x=-.1, y=-.2, z=-.3, w=-.9), x=4.8e-5)
        self.assertTrue(runtime.transforms_equal(a, b))
        b.translation.x = 1.1e-4
        self.assertFalse(runtime.transforms_equal(a, b))
        b.translation.x = 0
        b.scale3d.x += 2e-5
        self.assertFalse(runtime.transforms_equal(a, b))
        b.scale3d.x = 1
        b.rotation.z = -.4
        self.assertFalse(runtime.transforms_equal(a, b))

    def test_additive_idle_uses_exported_pose_without_changing_timing_or_base(self):
        importer, unreal, _ = self.make_importer()
        source = Properties(path='/Mod/Idle/idle', length=2, additive_anim_type='none')
        target = Properties(path='/Mod/Additive/idle_add', length=1,
                            additive_anim_type='local', ref_pose_seq='common', curves='retained')
        tracks = {source: {'hand': ([], [], [])}, target: {'stale': ([], [], [])}}
        controller = Mock()
        controller.remove_all_bone_tracks.side_effect = lambda _transact: tracks[target].clear()
        controller.add_bone_curve.return_value = True

        def set_keys(name, positions, rotations, scales, should_transact):
            tracks[target][name] = (positions, rotations, scales)
            return True

        controller.set_bone_track_keys.side_effect = set_keys
        target.controller = controller
        importer.library = SimpleNamespace(save_loaded_asset=Mock())
        importer.count = Mock()
        unreal.AnimationLibrary = SimpleNamespace(
            get_num_frames=lambda _asset: 2,
            get_animation_track_names=lambda asset: list(tracks[asset]),
            get_raw_track_data=lambda asset, name: tracks[asset][name])
        unreal.AdditiveAnimationType = SimpleNamespace(
            AAT_NONE='none', AAT_LOCAL_SPACE_BASE='local', AAT_ROTATION_OFFSET_MESH_SPACE='mesh')
        unreal.AnimDataEvalType = SimpleNamespace(RAW='raw')
        unreal.AnimPoseSpaces = SimpleNamespace(LOCAL='local')
        unreal.AnimPoseEvaluationOptions = SimpleNamespace
        unreal.AnimPoseExtensions = SimpleNamespace(
            get_anim_pose_at_time=lambda asset, time, _options: (asset, time),
            get_bone_pose=lambda pose, name, _space: SimpleNamespace(
                translation=(SimpleNamespace(x=pose[1], y=0, z=0) if pose[0] is source
                             else tracks[target][name][0][round(pose[1] * 2)]),
                rotation=SimpleNamespace(x=0, y=0, z=0, w=1),
                scale3d=SimpleNamespace(x=1, y=1, z=1)))
        with patch.object(runtime, 'unreal', unreal):
            importer.sync_additive_idle(source, target)
            self.assertEqual([v.x for v in tracks[target]['hand'][0]], [0, 1, 2])
            self.assertNotIn('stale', tracks[target])
            self.assertEqual(target.get_play_length(), 1)
            self.assertEqual(target.get_editor_property('ref_pose_seq'), 'common')
            self.assertEqual(target.get_editor_property('curves'), 'retained')
            self.assertEqual(target.get_editor_property('additive_anim_type'), 'local')
            importer.sync_additive_idle(source, target)
        controller.open_bracket.assert_called_once()
        importer.library.save_loaded_asset.assert_called_once_with(target)

    def test_exported_aim_transitions_keep_their_additive_mode_and_reference(self):
        importer, unreal, _ = self.make_importer()
        unreal.AdditiveAnimationType = SimpleNamespace(
            AAT_LOCAL_SPACE_BASE='local', AAT_ROTATION_OFFSET_MESH_SPACE='mesh')
        package = '/Mod/Animations/Player/gun/Idle/AS_fp_gun_idle_to_aim'
        asset = Properties(path=package, additive_anim_type='local', tracks='edited',
                           ref_pose_seq='common', ref_pose_type='frame', ref_frame_index=0)
        importer.plan = {'player_animations': [('aim.fbx', *package.rsplit('/', 1))]}
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.mod_assets = lambda: {'sequence': {package.lower(): package}}
        importer.library = SimpleNamespace(load_asset=lambda _path: asset, save_loaded_asset=Mock(return_value=True))
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
            importer.update_additive_playback()
            self.assertEqual(asset.get_editor_property('additive_anim_type'), 'local')
            asset.set_editor_property('additive_anim_type', 'mesh')
            importer.update_additive_playback()
            self.assertEqual(asset.get_editor_property('additive_anim_type'), 'mesh')
        self.assertEqual(asset.get_editor_property('tracks'), 'edited')
        self.assertEqual(asset.get_editor_property('ref_pose_seq'), 'common')
        self.assertEqual(asset.get_editor_property('ref_pose_type'), 'frame')
        self.assertEqual(asset.get_editor_property('ref_frame_index'), 0)
        importer.library.save_loaded_asset.assert_not_called()
        self.assertEqual(importer.counts, {})

    def test_overlay_reference_restored_only_when_raw_tracks_unchanged(self):
        importer, unreal, _ = self.make_importer()
        base = Properties(path='/Mod/udp_idle')
        original_base = Properties(path='/Game/udp_idle')
        overlay = Properties(path='/Mod/Animations/Player/gun/AS_fp_gun_shoot',
                             additive_anim_type='local', ref_pose_seq=base, ref_pose_type='frame', ref_frame_index=0)
        original = Properties(path='/Game/Animations/Player/udp/AS_fp_udp_shoot',
                              additive_anim_type='local', ref_pose_seq=original_base, ref_pose_type='frame', ref_frame_index=0)
        packages = {overlay.get_path_name(): overlay, original.get_path_name(): original}
        importer.library = SimpleNamespace(
            load_asset=packages.__getitem__, does_asset_exist=packages.__contains__,
            save_loaded_asset=Mock())
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.plan = {'player_animations': []}
        importer.mod_assets = lambda: {'sequence': {overlay.get_path_name().lower(): overlay.get_path_name()}}
        importer.same_raw_animation = Mock(return_value=False)
        importer.count = Mock()
        unreal.AdditiveAnimationType = SimpleNamespace(AAT_NONE='none')
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), base)
            importer.same_raw_animation.return_value = True
            overlay.set_editor_property('ref_frame_index', 1)
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), base)
            overlay.set_editor_property('ref_frame_index', 0)
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), original_base)
            importer.update_additive_playback()
        importer.library.save_loaded_asset.assert_called_once_with(overlay)

    def test_explicitly_exported_additive_idle_is_not_regenerated(self):
        importer, unreal, _ = self.make_importer()
        idle = '/Mod/Animations/Player/gun/Idle/AS_fp_gun_idle'
        companion = '/Mod/Animations/Player/gun/Additive/AS_fp_gun_idle_add'
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.plan = {'player_animations': [
            ('idle.fbx', *idle.rsplit('/', 1)), ('idle_add.fbx', *companion.rsplit('/', 1))]}
        importer.mod_assets = lambda: {'sequence': {p.lower(): p for p in (idle, companion)}}
        importer.sync_additive_idle = Mock()
        importer.library = SimpleNamespace(load_asset=Mock())
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
        importer.sync_additive_idle.assert_not_called()
        importer.library.load_asset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
