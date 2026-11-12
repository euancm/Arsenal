"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import os
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
                with patch.object(ex, '_build_static_plan'), \
                        patch.object(weapon_cfg, 'build_context'), \
                        patch('stalker2_arsenal.export_check.name_warnings', return_value=[]), patch.object(
                        ex, '_run_animation_export', return_value=(
                            written, [('shoot_aim_end', 'upper_arm_ik.R is not keyed')], 2)), \
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
                    self.assertEqual(problems, 1)
                    self.assertFalse(plans)
                    self.assertIn('does not match an original animation', export.actions[0].status)
                    self.action.name = 'idle'
                    with patch.object(ex.importer, '_scan_library', return_value=([], [], [], ['idle'])):
                        _rig, _backup, plans, problems = ex._build_plans(bpy.context)
                    self.assertEqual(problems, 1)
                    self.assertIn('Ambiguous donor files', export.actions[0].status)
        finally:
            addon.unregister()

    def test_no_actions_blocks_export_with_retarget_instructions(self):
        with patch.object(ex, '_build_plans', return_value=(self.rig, self.rig, [], 0)):
            with self.assertRaisesRegex(RuntimeError, 'Retarget Animation'):
                ex._run_animation_export(bpy.context)

    def test_cfg_failure_blocks_import_script_and_clears_old_clipboard(self):
        settings = SimpleNamespace(actions=[], summary='')
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=settings),
                                  window_manager=SimpleNamespace(clipboard='old_import.py'))
        with patch.object(ex, '_build_static_plan'), patch.object(
                weapon_cfg, 'build_context', side_effect=RuntimeError('Magazine needs a mesh')), \
                patch('stalker2_arsenal.export_unreal.write_unreal_import') as script:
            result = ex.ARSENAL_OT_ExportAllRun.execute(SimpleNamespace(report=Mock()), context)
        self.assertEqual(result, {'CANCELLED'})
        self.assertEqual(context.window_manager.clipboard, '')
        self.assertIn('Magazine needs a mesh', settings.summary)
        script.assert_not_called()

    def test_export_all_passes_only_fresh_animation_paths_to_manifest(self):
        settings = SimpleNamespace(actions=[], summary='')
        context = SimpleNamespace(scene=SimpleNamespace(arsenal_export=settings),
                                  window_manager=SimpleNamespace(clipboard='old_import.py'))
        with patch.object(ex, '_build_static_plan'), patch.object(weapon_cfg, 'build_context'), \
                patch('stalker2_arsenal.export_check.name_warnings', return_value=[]), \
                patch.object(ex, '_run_animation_export', return_value=(['fresh_idle.fbx'], [], 1)), \
                patch.object(ex, '_run_static_export', return_value=(['mesh.fbx'], [])), \
                patch.object(weapon_cfg, 'export_cfg_files', return_value=(['weapon.cfg'], {})), \
                patch('stalker2_arsenal.export_check.path_warnings', return_value=[]), \
                patch('stalker2_arsenal.export_unreal.write_unreal_import',
                      return_value=('fresh_import.py', {'game_materials': []})) as script:
            result = ex.ARSENAL_OT_ExportAllRun.execute(SimpleNamespace(report=Mock()), context)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(context.window_manager.clipboard, 'fresh_import.py')
        script.assert_called_once_with(context, animation_paths=['fresh_idle.fbx'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
