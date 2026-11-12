"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import math
import os
import sys
import unittest

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stalker2_arsenal import convert_to_rigify, stalker2_animation_importer as importer


class CameraPlacementTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def armature(self, name):
        bpy.ops.object.armature_add()
        armature = bpy.context.object
        bpy.ops.object.mode_set(mode='EDIT')
        bone = armature.data.edit_bones[0]
        bone.name = name
        bone.head = (2, 3, 5)
        bone.tail = (4, 6, 9)
        bone.roll = 0.4
        bpy.ops.object.mode_set(mode='OBJECT')
        armature.location = (11, -7, 4)
        armature.rotation_euler = (0.2, -0.5, 0.3)
        armature.scale = (1.2, 1.2, 1.2)
        return armature

    def assert_follows_head(self, camera, armature, bone_name, rotation):
        bone = armature.pose.bones[bone_name]
        bone.rotation_mode = 'XYZ'
        for frame in (1, 5):
            bone.location = (frame, -frame * 0.2, frame * 0.3)
            bone.rotation_euler = (frame * 0.1, 0.2, -0.3)
            bone.scale = (1.1, 1.3, 0.9)
            bone.keyframe_insert('location', frame=frame)
            bone.keyframe_insert('rotation_euler', frame=frame)
            bone.keyframe_insert('scale', frame=frame)
        for frame in (1, 3, 5):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            expected = armature.matrix_world @ bone.matrix @ rotation
            self.assertLess((camera.matrix_world.translation - expected.translation).length, 1e-4)
            self.assertGreater((camera.matrix_world.translation -
                                armature.matrix_world @ bone.tail).length, 1.0)
            actual_forward = camera.matrix_world.to_3x3() @ Vector((0, 0, -1))
            expected_forward = expected.to_3x3() @ Vector((0, 0, -1))
            self.assertLess((actual_forward - expected_forward).length, 1e-4)

    def test_imported_camera_follows_bone_head(self):
        armature = self.armature('jnt_camera')
        camera = importer._create_camera(armature)
        self.assertEqual(bpy.context.scene.camera, camera)
        self.assert_follows_head(
            camera, armature, 'jnt_camera', Matrix.Rotation(math.pi / 2, 4, 'X'))

    def test_rigify_camera_follows_bone_head(self):
        source = self.armature('jnt_camera')
        camera = importer._create_camera(source)
        rig = self.armature('Camera')
        camera.matrix_parent_inverse = Matrix.Translation((3, 4, 5))
        self.assertTrue(convert_to_rigify.parent_importer_camera_to_rig(bpy.context, source, rig))
        self.assert_follows_head(
            camera, rig, 'Camera',
            Matrix.Rotation(-math.pi / 2, 4, 'Z') @ Matrix.Rotation(math.pi / 2, 4, 'X'))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
