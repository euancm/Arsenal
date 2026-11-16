"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import os
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stalker2_arsenal import export_animation as ex
from stalker2_arsenal import weapon_cfg


class ExportIKControlsTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.object.armature_add()
        self.rig = bpy.context.object
        bpy.ops.object.mode_set(mode='EDIT')
        bones = self.rig.data.edit_bones
        bones[0].name = 'upper_arm_parent.R'
        control = bones.new('hand_ik.R')
        control.head = (0, 0, 0)
        control.tail = (0, 1, 0)
        upper = bones.new('upper_arm_ik.R')
        upper.head = (0, 0, 0)
        upper.tail = (0, 1, 0)
        pole = bones.new('upper_arm_ik_target.R')
        pole.head = (0, 2, 0)
        pole.tail = (0, 3, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        self.parent = self.rig.pose.bones['upper_arm_parent.R']
        self.parent['IK_FK'] = 0.0
        self.parent['pole_vector'] = False
        self.pole = self.rig.pose.bones['upper_arm_ik_target.R']
        self.control = self.rig.pose.bones['hand_ik.R']
        self.control.rotation_mode = 'QUATERNION'
        self.control.location = (20, 30, 40)
        self.parent.keyframe_insert('["IK_FK"]', frame=1)
        self.action = self.rig.animation_data.action
        self.slot = self.rig.animation_data.action_slot

    def tearDown(self):
        data = self.rig.data
        bpy.data.objects.remove(self.rig, do_unlink=True)
        bpy.data.armatures.remove(data)
        bpy.data.actions.remove(self.action)

    def validate(self):
        ex.validate_ik_controls(bpy.context, self.rig, self.action, self.slot)

    def test_rejects_unkeyed_active_ik_offset(self):
        with self.assertRaisesRegex(RuntimeError, r'hand_ik.R.*location is not keyed'):
            self.validate()

    def test_accepts_keyed_ik_offset(self):
        for prop in ('location', 'rotation_quaternion', 'scale'):
            self.control.keyframe_insert(prop, frame=1)
        self.validate()

    def test_accepts_inactive_ik_offset(self):
        self.parent['IK_FK'] = 1.0
        self.parent.keyframe_insert('["IK_FK"]', frame=1)
        self.validate()

    def test_accepts_unkeyed_rest_control(self):
        self.control.location = (0, 0, 0)
        self.validate()

    def test_copy_fingers_preserves_arm_and_resets_unkeyed_finger_master(self):
        from stalker2_arsenal import animation
        bpy.ops.object.mode_set(mode='EDIT')
        for name in ('f_index.01.L', 'f_index.01_master.L', 'f_index.01.R'):
            bone = self.rig.data.edit_bones.new(name)
            bone.tail = (0, 1, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        finger = self.rig.pose.bones['f_index.01.L']
        master = self.rig.pose.bones['f_index.01_master.L']
        finger.rotation_mode = master.rotation_mode = 'XYZ'
        finger.rotation_euler.x = 0.3
        finger.keyframe_insert('rotation_euler', frame=1)
        source = self.action
        target = bpy.data.actions.new('finger_transition')
        self.addCleanup(bpy.data.actions.remove, target)
        self.rig.animation_data.action = target
        self.control.keyframe_insert('location', frame=1)
        self.control.keyframe_insert('location', frame=8)
        master.rotation_euler.x = 0.9
        master.keyframe_insert('rotation_euler', frame=1)
        animation.copy_grip(self.rig, source, target, 'L', channels='FINGERS')
        curves = {(c.data_path, c.array_index): c for c in ex.action_slot_curves(
            target, self.rig.animation_data.action_slot)}
        self.assertIn((self.control.path_from_id('location'), 0), curves)
        self.assertAlmostEqual(curves[finger.path_from_id('rotation_euler'), 0].evaluate(4), 0.3)
        self.assertEqual(curves[master.path_from_id('rotation_euler'), 0].evaluate(4), 0)
        self.assertFalse(any('f_index.01.R' in path for path, _index in curves))

    def test_checks_switch_later_in_clip(self):
        self.parent['IK_FK'] = 1.0
        self.parent.keyframe_insert('["IK_FK"]', frame=1)
        self.parent['IK_FK'] = 0.0
        self.parent.keyframe_insert('["IK_FK"]', frame=3)
        with self.assertRaisesRegex(RuntimeError, r'uses IK at frame 2'):
            self.validate()

    def test_checks_upper_arm_ik_orientation(self):
        self.control.keyframe_insert('location', frame=1)
        upper = self.rig.pose.bones['upper_arm_ik.R']
        upper.rotation_mode = 'XYZ'
        upper.rotation_euler.y = 0.9
        with self.assertRaisesRegex(RuntimeError, r'upper_arm_ik.R.*rotation_euler'):
            self.validate()

    def test_accepts_unkeyed_disabled_pole(self):
        self.control.keyframe_insert('location', frame=1)
        self.pole.location = (10, 20, 30)
        self.validate()

    def test_rejects_unkeyed_enabled_pole(self):
        self.control.keyframe_insert('location', frame=1)
        self.pole.location = (10, 20, 30)
        self.parent['pole_vector'] = True
        with self.assertRaisesRegex(RuntimeError, r'upper_arm_ik_target.R.*location is not keyed'):
            self.validate()

    def test_checks_pole_enabled_later_in_clip(self):
        self.control.keyframe_insert('location', frame=1)
        self.pole.location = (10, 20, 30)
        self.parent.keyframe_insert('["pole_vector"]', frame=1)
        self.parent['pole_vector'] = True
        self.parent.keyframe_insert('["pole_vector"]', frame=3)
        for curve in ex.action_slot_curves(self.action, self.slot):
            if curve.data_path.endswith('["pole_vector"]'):
                for key in curve.keyframe_points:
                    key.interpolation = 'CONSTANT'
        with self.assertRaisesRegex(RuntimeError, r'upper_arm_ik_target.R uses IK at frame 3'):
            self.validate()

    def test_missing_pole_switch_preserves_validation(self):
        self.control.keyframe_insert('location', frame=1)
        self.pole.location = (10, 20, 30)
        del self.parent['pole_vector']
        with self.assertRaisesRegex(RuntimeError, r'upper_arm_ik_target.R.*location is not keyed'):
            self.validate()

    def test_disabled_pole_does_not_skip_hand_validation(self):
        self.pole.location = (10, 20, 30)
        with self.assertRaisesRegex(RuntimeError, r'hand_ik.R.*location is not keyed'):
            self.validate()

    def test_disabled_pole_does_not_block_export(self):
        self.control.keyframe_insert('location', frame=1)
        self.pole.location = (10, 20, 30)
        before = tuple(self.pole.location)
        with patch.object(ex, 'resolve_animation_mapping', return_value=(
                [('hand_ik.R', 'hand_ik.R', 'rot_loc')], [])), patch.object(
                    ex, 'export_action', return_value=['fresh.fbx']) as export:
            written, failures = ex.run_exports(
                bpy.context, self.rig, self.rig, [(self.action, self.slot, [])])
        self.assertEqual(written, ['fresh.fbx'])
        self.assertEqual(failures, [])
        export.assert_called_once()
        self.assertEqual(tuple(self.pole.location), before)
        self.assertFalse(self.parent['pole_vector'])

    def test_failed_export_writes_nothing_and_restores_state(self):
        bpy.context.scene.frame_set(9, subframe=0.25)
        before = tuple(self.control.location)
        console = StringIO()
        with patch.object(ex, 'resolve_animation_mapping', return_value=(
                [('hand_ik.R', 'hand_ik.R', 'rot_loc')], [])), patch.object(
                    ex, 'export_action') as export, redirect_stdout(console), redirect_stderr(console):
            written, failures = ex.run_exports(
                bpy.context, self.rig, self.rig, [(self.action, self.slot, [])])
        self.assertEqual(written, [])
        self.assertEqual(len(failures), 1)
        self.assertIn('hand_ik.R', failures[0][1])
        self.assertIn(f'[Arsenal export] FAILED {self.action.name}:', console.getvalue())
        self.assertIn('Traceback (most recent call last)', console.getvalue())
        self.assertIn('location is not keyed', console.getvalue())
        export.assert_not_called()
        self.assertEqual(tuple(self.control.location), before)
        self.assertEqual(bpy.context.scene.frame_current, 9)
        self.assertEqual(bpy.context.scene.frame_subframe, 0.25)
        self.assertEqual(self.rig.animation_data.action, self.action)

    def test_export_all_blocks_import_script_when_any_animation_failed(self):
        for written in ([], ['fresh_shoot.fbx']):
            with self.subTest(written=written):
                item = SimpleNamespace(
                    name='shoot_aim_end', enabled=True, status='Matches an original animation')
                settings = SimpleNamespace(actions=[item], summary='')
                context = SimpleNamespace(
                    scene=SimpleNamespace(arsenal_export=settings),
                    window_manager=SimpleNamespace(clipboard='old_import.py'))
                operator = SimpleNamespace(report=Mock())
                with patch.object(ex, '_build_static_plan', return_value=(self.rig, self.rig, {}, [])), \
                        patch.object(ex.static_mesh, 'world_mesh_sockets'), \
                        patch.object(weapon_cfg, 'build_context'), \
                        patch('stalker2_arsenal.export_check.name_warnings', return_value=[]), patch.object(
                        ex, '_run_animation_export', return_value=(
                            written, [('shoot_aim_end', 'upper_arm_ik.R is not keyed')], 2, 0)), \
                        patch.object(ex, '_run_static_export') as static_export, \
                        patch('stalker2_arsenal.export_unreal.write_unreal_import') as script:
                    result = ex.ARSENAL_OT_ExportAllRun.execute(operator, context)
                self.assertEqual(result, {'CANCELLED'})
                self.assertEqual(context.window_manager.clipboard, '')
                self.assertIn('shoot_aim_end', settings.summary)
                self.assertEqual(item.status, 'Export failed: upper_arm_ik.R is not keyed')
                static_export.assert_not_called()
                script.assert_not_called()
                messages = '\n'.join(str(call.args[1]) for call in operator.report.call_args_list)
                self.assertIn('upper_arm_ik.R', messages)
                self.assertIn('stale FBXs', messages)
                self.assertIn('upper_arm_ik.R is not keyed', operator.report.call_args.args[1])

    def test_automatic_plan_ignores_old_selections_and_overrides(self):
        import stalker2_arsenal as addon
        addon.register()
        try:
            export = bpy.context.scene.arsenal_export
            self.action.name = 'idle'
            item = export.actions.add()
            item.name, item.enabled, item.template, item.folder = 'idle', False, 'reload', 'wrong'
            with tempfile.TemporaryDirectory() as output:
                root = os.path.join(output, 'donor')
                pair = ('idle', os.path.join(root, '_STALKER2', 'Animations', 'Player', 'pt',
                                             'udp', 'AS_fp_udp_idle.fbx'),
                        os.path.join(root, '_STALKER2', 'Animations', 'Weapons', 'pt',
                                     'udp', 'AS_udp_fp_idle.fbx'))
                basics = (export, SimpleNamespace(weapon_name='udp'), self.rig, self.rig,
                          'custom', os.path.join(output, 'export'), root)
                with patch.object(ex, '_export_basics', return_value=basics), \
                        patch.object(ex.importer, '_scan_library', return_value=([pair], [], [], [])):
                    _rig, _backup, plans, problems = ex._build_plans(bpy.context)
                    self.assertEqual(problems, 0)
                    self.assertEqual(len(plans), 1)
                    self.assertEqual(plans[0][0], self.action)
                    self.assertTrue(all('wrong' not in path for _kind, _donor, path in plans[0][2]))
                    self.action.name = 'new_feature'
                    _rig, _backup, plans, problems = ex._build_plans(bpy.context)
                    self.assertEqual(problems, 0)
                    self.assertFalse(plans)
                    self.assertTrue(export.actions[0].status.startswith(ex.SKIPPED_STATUS))
                    self.assertIn('does not match an original animation', export.actions[0].status)
                    with self.assertRaisesRegex(RuntimeError, 'skipped: new_feature'):
                        ex._run_animation_export(bpy.context)
                    self.action.name = 'idle'
                    with patch.object(ex.importer, '_scan_library', return_value=([], [], [], ['idle'])):
                        _rig, _backup, plans, problems = ex._build_plans(bpy.context)
                    self.assertEqual(problems, 1)
                    self.assertIn('Ambiguous donor files', export.actions[0].status)
        finally:
            addon.unregister()

    def test_skipped_actions_are_warned_in_the_export_summary(self):
        items = [SimpleNamespace(name='idle', status='Matches an original animation'),
                 SimpleNamespace(name='my_extra', status=f'{ex.SKIPPED_STATUS}: "my_extra" does not match')]
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=SimpleNamespace(actions=items)))
        operator = SimpleNamespace(report=Mock())
        summary, failed = ex._report_animation(operator, context, (['idle.fbx'], [], 1, 0))
        self.assertFalse(failed)
        self.assertIn('1 skipped', summary)
        self.assertIn('my_extra', operator.report.call_args.args[1])

    def test_no_actions_blocks_export_with_retarget_instructions(self):
        with patch.object(ex, '_build_plans', return_value=(self.rig, self.rig, [], 0)):
            with self.assertRaisesRegex(RuntimeError, 'Retarget Animation'):
                ex._run_animation_export(bpy.context)

    def test_cfg_failure_blocks_import_script_and_clears_old_clipboard(self):
        settings = SimpleNamespace(actions=[], summary='')
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=settings),
                                  window_manager=SimpleNamespace(clipboard='old_import.py'))
        with patch.object(ex, '_build_static_plan', return_value=(self.rig, self.rig, {}, [])), patch.object(
                weapon_cfg, 'build_context', side_effect=RuntimeError('Magazine needs a mesh')), \
                patch('stalker2_arsenal.export_unreal.write_unreal_import') as script:
            result = ex.ARSENAL_OT_ExportAllRun.execute(SimpleNamespace(report=Mock()), context)
        self.assertEqual(result, {'CANCELLED'})
        self.assertEqual(context.window_manager.clipboard, '')
        self.assertIn('Magazine needs a mesh', settings.summary)
        script.assert_not_called()

    def test_world_mount_failure_blocks_export_before_writing_files(self):
        settings = SimpleNamespace(actions=[], summary='')
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=settings),
                                  window_manager=SimpleNamespace(clipboard='old_import.py'))
        info = {'magazines': [], 'world_mesh': "StaticMesh'/TestMod/SM_test.SM_test'"}
        with patch.object(ex, '_build_static_plan', return_value=(self.rig, self.rig, {}, [])), \
                patch.object(weapon_cfg, 'build_context', return_value=info), \
                patch.object(ex.static_mesh, 'world_mesh_sockets',
                             side_effect=RuntimeError('World attachment mount MissingSocket')), \
                patch.object(ex, '_run_animation_export') as animations, \
                patch.object(ex, '_run_static_export') as meshes, \
                patch('stalker2_arsenal.export_unreal.write_unreal_import') as script:
            result = ex.ARSENAL_OT_ExportAllRun.execute(SimpleNamespace(report=Mock()), context)
        self.assertEqual(result, {'CANCELLED'})
        self.assertIn('MissingSocket', settings.summary)
        self.assertEqual(context.window_manager.clipboard, '')
        animations.assert_not_called()
        meshes.assert_not_called()
        script.assert_not_called()

    def test_unchanged_actions_keep_their_fbxs(self):
        from stalker2_arsenal.animation_cache import AnimationCache

        for prop in ('location', 'rotation_quaternion', 'scale'):
            self.control.keyframe_insert(prop, frame=1)
        mapping = [('hand_ik.R', 'hand_ik.R', 'rot_loc')]
        with tempfile.TemporaryDirectory() as output:
            template = os.path.join(output, 'template.fbx')
            target = os.path.join(output, 'out', 'idle.fbx')
            with open(template, 'w') as handle:
                handle.write('donor')
            plans = [(self.action, self.slot, [('player', template, target), ('weapon', template, None)])]

            def write(*_args):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, 'w') as handle:
                    handle.write('baked')
                return [target]

            def run():
                cache = AnimationCache(output, bpy.context, self.rig, self.rig, mapping, ex.BAKE_SUBSTEPS)
                with patch.object(ex, 'resolve_animation_mapping', return_value=(mapping, [])), \
                        patch.object(ex, 'export_action', side_effect=write) as export, \
                        redirect_stdout(StringIO()):
                    written, failures = ex.run_exports(bpy.context, self.rig, self.rig, plans, cache)
                cache.save()
                self.assertEqual((written, failures), ([target], []))
                return export.call_count, cache.unchanged

            self.assertEqual(run(), (1, 0))
            self.assertEqual(run(), (0, 1))
            self.control.location = (1, 2, 3)
            self.control.keyframe_insert('location', frame=1)
            self.assertEqual(run(), (1, 0), 'an edited key must re-export')
            os.remove(target)
            self.assertEqual(run(), (1, 0), 'a deleted FBX must re-export')
            os.utime(template, ns=(1, 1))
            self.assertEqual(run(), (1, 0), 'a changed donor template must re-export')
            self.parent['pole_vector'] = True
            self.assertEqual(run(), (1, 0), 'a changed rig setting must re-export')
            self.assertEqual(run(), (0, 1))

    def test_export_all_passes_only_fresh_animation_paths_to_manifest(self):
        settings = SimpleNamespace(actions=[], summary='')
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=settings),
                                  window_manager=SimpleNamespace(clipboard='old_import.py'))
        with patch.object(ex, '_build_static_plan', return_value=(self.rig, self.rig, {}, [])), \
                patch.object(ex.static_mesh, 'world_mesh_sockets'), \
                patch.object(weapon_cfg, 'build_context'), \
                patch('stalker2_arsenal.export_check.name_warnings', return_value=[]), \
                patch.object(ex, '_run_animation_export', return_value=(['fresh_idle.fbx'], [], 1, 0)), \
                patch.object(ex, '_run_static_export', return_value=(['mesh.fbx'], [])), \
                patch.object(weapon_cfg, 'export_cfg_files', return_value=(['weapon.cfg'], {})), \
                patch('stalker2_arsenal.export_check.path_warnings', return_value=[]), \
                patch('stalker2_arsenal.export_unreal.write_unreal_import',
                      return_value=('fresh_import.py', {'game_materials': []})) as script:
            result = ex.ARSENAL_OT_ExportAllRun.execute(SimpleNamespace(report=Mock()), context)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(context.window_manager.clipboard, 'fresh_import.py')
        script.assert_called_once_with(context, animation_paths=['fresh_idle.fbx'])


class RigifyIKBaseFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import addon_utils
        addon_utils.enable('rigify', default_set=True)
        bpy.ops.object.armature_human_metarig_add()
        metarig = bpy.context.object
        with redirect_stdout(StringIO()):
            bpy.ops.pose.rigify_generate()
        cls.rig = bpy.context.object
        cls.objects = [metarig, cls.rig]

    @classmethod
    def tearDownClass(cls):
        for obj in cls.objects:
            bpy.data.objects.remove(obj, do_unlink=True)

    def setUp(self):
        rig, bones = self.rig, self.rig.pose.bones
        rig.animation_data_clear()
        for bone in bones:
            bone.location, bone.scale = (0, 0, 0), (1, 1, 1)
            bone.rotation_quaternion, bone.rotation_euler = (1, 0, 0, 0), (0, 0, 0)
        bones['upper_arm_fk.L'].rotation_mode = 'XYZ'
        bones['upper_arm_fk.L'].rotation_euler = (0.6, 0.9, -0.4)
        bones['forearm_fk.L'].rotation_mode = 'XYZ'
        bones['forearm_fk.L'].rotation_euler = (1.1, 0, 0)
        self.parent = bones['upper_arm_parent.L']
        self.parent['IK_FK'] = 0.0
        self.parent['pole_vector'] = False
        bpy.context.view_layer.update()
        hand = bones['hand_ik.L']
        hand.matrix = bones['hand_fk.L'].matrix.copy()
        bpy.context.view_layer.update()
        for bone in ('upper_arm_fk.L', 'forearm_fk.L'):
            bones[bone].keyframe_insert('rotation_euler', frame=1)
        for prop in ('location', 'rotation_quaternion', 'scale'):
            hand.keyframe_insert(prop, frame=1)
        self.parent.keyframe_insert('["IK_FK"]', frame=1)
        self.parent.keyframe_insert('["IK_FK"]', frame=3)
        self.action = rig.animation_data.action
        self.slot = rig.animation_data.action_slot
        self.control = bones['upper_arm_ik.L']
        self.control.rotation_euler.y = 2.0
        self.control.scale = (1.1, 1.1, 1.1)

    def tearDown(self):
        bpy.data.actions.remove(self.action)

    def test_copy_grip_holds_target_arm_at_source_ik_pose(self):
        from stalker2_arsenal import animation
        rig, bones = self.rig, self.rig.pose.bones
        source = self.action
        bones['hand_ik.L'].location = (0.1, 0.2, 0.3)
        bones['hand_ik.L'].keyframe_insert('location', frame=1)
        self.parent['IK_parent'] = 1
        self.parent.keyframe_insert('["IK_parent"]', frame=1)
        target = bpy.data.actions.new('offset_aim')
        rig.animation_data.action = target
        self.parent['IK_FK'] = 1.0
        self.parent['IK_parent'] = 3
        for frame, x in ((1, 0.5), (9, 0.9)):
            self.parent.keyframe_insert('["IK_FK"]', frame=frame)
            self.parent.keyframe_insert('["IK_parent"]', frame=frame)
            bones['hand_ik.L'].location.x = x
            bones['hand_ik.L'].keyframe_insert('location', frame=frame)
        try:
            self.assertEqual(animation.copy_grip(rig, source, target), 12)
            self.assertIs(rig.animation_data.action, target)
            curves = {(curve.data_path, curve.array_index): curve
                      for curve in ex.action_slot_curves(target, rig.animation_data.action_slot)}
            expected = {('pose.bones["upper_arm_parent.L"]["IK_FK"]', 0): 0.0,
                        ('pose.bones["upper_arm_parent.L"]["IK_parent"]', 0): 1.0,
                        ('pose.bones["hand_ik.L"].location', 0): 0.1}
            for key, value in expected.items():
                points = curves[key].keyframe_points
                self.assertEqual([point.co.x for point in points], [1.0, 9.0], key)
                for point in points:
                    self.assertAlmostEqual(point.co.y, value, places=5, msg=key)
            self.assertNotIn(('pose.bones["upper_arm_fk.L"].rotation_euler', 0), curves)
            with self.assertRaisesRegex(ValueError, 'IK/FK switch'):
                animation.copy_grip(rig, target, source, side='R')
        finally:
            bpy.data.actions.remove(target)

    def test_unkeyed_ik_base_follows_fk_arm(self):
        bones = self.rig.pose.bones
        ex.validate_ik_controls(bpy.context, self.rig, self.action, self.slot)
        ex.rest_unkeyed_channels(self.rig, self.action, self.slot)
        fallbacks = ex.ik_base_fallbacks(self.rig, ex.keyed_pose_channels(self.action, self.slot))
        self.assertIn('upper_arm_ik.L', [control.name for _p, control, _f, _props in fallbacks])
        values = ex.solve_ik_bases(bpy.context, self.rig, fallbacks, 1, 3)
        bpy.context.scene.frame_set(2)
        ex.apply_ik_bases(values, 2.5)
        bpy.context.view_layer.update()
        elbow_error = (bones['MCH-forearm_ik.L'].head - bones['forearm_fk.L'].head).length
        self.assertLess(elbow_error, 1e-2 * bones['upper_arm_fk.L'].length)
        self.assertAlmostEqual(self.control.matrix.to_scale().y,
                               bones['upper_arm_fk.L'].matrix.to_scale().y, places=4)

    def test_keyed_ik_base_is_left_alone(self):
        self.control.keyframe_insert('rotation_euler', frame=1)
        self.control.keyframe_insert('scale', frame=1)
        fallbacks = ex.ik_base_fallbacks(self.rig, ex.keyed_pose_channels(self.action, self.slot))
        self.assertNotIn('upper_arm_ik.L', [control.name for _p, control, _f, _props in fallbacks])

    def test_subframe_sampling_unwraps_snap_twist_without_changing_authored_keys(self):
        self.control.rotation_euler = (0, 0.4, 0)
        self.control.keyframe_insert('rotation_euler', index=1, frame=1)
        self.control.rotation_euler.y = math.tau + 0.5
        self.control.keyframe_insert('rotation_euler', index=1, frame=2)
        curve = next(curve for curve in ex.action_slot_curves(self.action, self.slot)
                     if curve.data_path == self.control.path_from_id('rotation_euler'))
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
        original_keys = [(tuple(k.co), tuple(k.handle_left), tuple(k.handle_right))
                         for k in curve.keyframe_points]
        original_actions = set(bpy.data.actions)
        elbow = self.rig.pose.bones['MCH-forearm_ik.L']
        curve.mute = True
        bpy.context.scene.frame_set(1, subframe=0.5)
        self.control.rotation_euler.y = 0.45
        bpy.context.view_layer.update()
        expected = elbow.head.copy()
        curve.mute = False
        with patch.object(ex, 'deformation_entries', return_value=[(elbow.name, elbow.name)]):
            rows, _types = ex.sample_rig(
                bpy.context, self.rig, self.rig, [], [1.0, 1.5, 2.0])
        self.assertLess((rows[1][elbow.name].translation - expected).length, 1e-5)
        self.assertEqual(self.rig.animation_data.action, self.action)
        self.assertEqual(self.rig.animation_data.action_slot, self.slot)
        self.assertEqual(set(bpy.data.actions), original_actions)
        self.assertEqual([(tuple(k.co), tuple(k.handle_left), tuple(k.handle_right))
                          for k in curve.keyframe_points], original_keys)

    def test_unwrapped_action_is_restored_when_sampling_fails(self):
        self.control.rotation_euler.y = 0.4
        self.control.keyframe_insert('rotation_euler', index=1, frame=1)
        self.control.rotation_euler.y = math.tau + 0.5
        self.control.keyframe_insert('rotation_euler', index=1, frame=2)
        original_actions = set(bpy.data.actions)
        with patch.object(ex, 'read_reversed_worlds', side_effect=RuntimeError('sampling failed')):
            with self.assertRaisesRegex(RuntimeError, 'sampling failed'):
                ex.sample_rig(bpy.context, self.rig, self.rig, [], [1.5])
        self.assertEqual(self.rig.animation_data.action, self.action)
        self.assertEqual(self.rig.animation_data.action_slot, self.slot)
        self.assertEqual(set(bpy.data.actions), original_actions)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
