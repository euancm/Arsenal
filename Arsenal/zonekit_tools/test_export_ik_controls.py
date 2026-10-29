"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import os
import sys
import unittest
from unittest.mock import patch

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stalker2_arsenal import export_animation as ex


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
        bpy.ops.object.mode_set(mode='OBJECT')
        self.parent = self.rig.pose.bones['upper_arm_parent.R']
        self.parent['IK_FK'] = 0.0
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

    def test_failed_export_writes_nothing_and_restores_state(self):
        bpy.context.scene.frame_set(9, subframe=0.25)
        before = tuple(self.control.location)
        with patch.object(ex, 'resolve_animation_mapping', return_value=(
                [('hand_ik.R', 'hand_ik.R', 'rot_loc')], [])), patch.object(
                    ex, 'export_action') as export:
            written, failures = ex.run_exports(
                bpy.context, self.rig, self.rig, [(self.action, self.slot, [])])
        self.assertEqual(written, [])
        self.assertEqual(len(failures), 1)
        self.assertIn('hand_ik.R', failures[0][1])
        export.assert_not_called()
        self.assertEqual(tuple(self.control.location), before)
        self.assertEqual(bpy.context.scene.frame_current, 9)
        self.assertEqual(bpy.context.scene.frame_subframe, 0.25)
        self.assertEqual(self.rig.animation_data.action, self.action)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
