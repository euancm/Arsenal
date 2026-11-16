"""Check retargeting on a disposable Rigify-like rig.

blender --background --factory-startup --python-exit-code 1 --python test_retarget_animation.py
"""
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stalker2_arsenal import retarget_animation, stalker2_animation_importer

CHAIN = (('root', None), ('shoulder', 'root'), ('arm', 'shoulder'), ('hand', 'arm'))


def armature(name, bones):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for index, (bone_name, parent) in enumerate(bones):
        bone = obj.data.edit_bones.new(bone_name)
        bone.head = (0.0, float(index), 0.0)
        bone.tail = (bone.head[0], bone.head[1] + 1.0, 0.0)
        if parent:
            bone.parent = obj.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.armatures.remove(data)


class RetargetTests(unittest.TestCase):
    def setUp(self):
        self.actions_before = set(bpy.data.actions)
        self.source = armature('Source', [('s_' + name, parent and 's_' + parent) for name, parent in CHAIN])
        # Rigify routes a limb's parent through an ORG copy of the shoulder control, so the arm
        # depends on the shoulder through a constraint rather than through its parent.
        self.rig = armature('Rig', [
            ('root', None), ('shoulder', 'root'), ('ORG-shoulder', 'root'),
            ('MCH-arm_parent', 'ORG-shoulder'), ('arm', 'MCH-arm_parent'), ('hand', 'arm')])
        copy = self.rig.pose.bones['ORG-shoulder'].constraints.new('COPY_TRANSFORMS')
        copy.target, copy.subtarget = self.rig, 'shoulder'
        self.mapping = [(name, 's_' + name, 'rot') for name, _parent in CHAIN]

        # Raw FBX takes sort before most clip names.
        self.clip = bpy.data.actions.new('reload')
        self.clip[retarget_animation.IMPORTED_ACTION_MARKER] = True
        self.key(self.clip, {'s_root': (0, 0, 20), 's_shoulder': (30, 0, 0),
                             's_arm': (0, 40, 10), 's_hand': (-25, 0, 190)})
        # A raw FBX take the importer failed to delete, with object keys.
        self.leftover = bpy.data.actions.new('jnt_root|Unreal Take|Base Layer.001')
        self.key(self.leftover, {'s_root': (90, 0, 0)}, location=(30.0, -20.0, 100.0))
        self.source.animation_data.action = self.clip

    def tearDown(self):
        for obj in (self.source, self.rig):
            remove_object(obj)
        for action in set(bpy.data.actions) - self.actions_before:
            bpy.data.actions.remove(action)

    def key(self, action, rotations, location=None):
        animation = self.source.animation_data_create()
        animation.action = action
        animation.action_slot = action.slots.new('OBJECT', self.source.name) if not action.slots else action.slots[0]
        if location is not None:
            self.source.location = location
            self.source.keyframe_insert('location', frame=1)
            self.source.location = (0.0, 0.0, 0.0)
        for frame, scale in ((1, 0.0), (5, 1.0)):
            for name, degrees in rotations.items():
                bone = self.source.pose.bones[name]
                bone.rotation_mode = 'XYZ'
                bone.rotation_euler = Euler([math.radians(value * scale) for value in degrees])
                bone.keyframe_insert('rotation_euler', frame=frame)
        for bone in self.source.pose.bones:
            bone.rotation_euler = (0.0, 0.0, 0.0)

    def retarget(self):
        with mock.patch.object(retarget_animation.b_fun, 'set_ik_fk'):
            return retarget_animation.retarget_animation_actions(
                bpy.context, self.source, self.rig, self.mapping)

    def test_bakes_imported_clips_only_and_matches_source(self):
        outputs = self.retarget()

        self.assertEqual([action['arsenal_source_action'] for action in outputs], ['reload'])
        self.assertEqual(tuple(self.source.matrix_world.translation), (0.0, 0.0, 0.0))
        self.source.animation_data.action = self.clip
        self.source.animation_data.action_slot = self.clip.slots[0]
        self.rig.animation_data.action = outputs[0]
        self.rig.animation_data.action_slot = outputs[0].slots[0]
        for frame in range(1, 6):
            bpy.context.scene.frame_set(frame)
            for target, source, _kind in self.mapping:
                source_bone = self.source.pose.bones[source]
                want = (source_bone.matrix @ self.source.data.bones[source].matrix_local.inverted()
                        @ self.rig.data.bones[target].matrix_local)
                got = self.rig.pose.bones[target].matrix
                error = max(abs(want[row][column] - got[row][column])
                            for row in range(4) for column in range(4))
                self.assertLess(error, 1e-4, (frame, target))

        # The hand turns past 180 degrees; keys flipping sign would interpolate the long way.
        curves = {(curve.data_path, curve.array_index): curve
                  for layer in outputs[0].layers for strip in layer.strips
                  for bag in strip.channelbags for curve in bag.fcurves}
        for target, _source, _kind in self.mapping:
            path = f'pose.bones["{target}"].rotation_quaternion'
            components = [curves[(path, index)] for index in range(4)]
            keys = [[curve.evaluate(frame) for curve in components] for frame in range(1, 6)]
            for before, after in zip(keys, keys[1:]):
                self.assertGreater(sum(a * b for a, b in zip(before, after)), 0.0, target)

    def test_object_keys_in_a_source_cannot_shift_the_bake(self):
        del self.clip[retarget_animation.IMPORTED_ACTION_MARKER]
        self.source.animation_data.action = None
        # Without importer markers every action is a source, and the leftover bakes first.
        outputs = self.retarget()

        self.assertEqual([action['arsenal_source_action'] for action in outputs],
                         [self.leftover.name, 'reload'])
        self.assertEqual(tuple(self.source.matrix_world.translation), (0.0, 0.0, 0.0))
        self.rig.animation_data.action = outputs[1]
        self.rig.animation_data.action_slot = outputs[1].slots[0]
        bpy.context.scene.frame_set(5)
        # The root rotates about its own head, which stays at the origin.
        self.assertLess(self.rig.pose.bones['root'].matrix.translation.length, 1e-4)

    def test_remove_imported_deletes_actions_with_stray_users(self):
        holder = bpy.data.objects.new('Holder', None)
        try:
            holder.animation_data_create().action = self.leftover
            stalker2_animation_importer._remove_imported([], [self.leftover])
            self.assertNotIn('jnt_root|Unreal Take|Base Layer.001', bpy.data.actions)
        finally:
            bpy.data.objects.remove(holder)

    def test_player_body_bind_pose_is_baked_into_the_master_rest(self):
        # The body's own skeleton binds the arm a quarter turn away from the animation skeleton's rest.
        body_rig = armature('BodyRig', [('s_' + name, parent and 's_' + parent) for name, parent in CHAIN])
        bpy.context.view_layer.objects.active = body_rig
        bpy.ops.object.mode_set(mode='EDIT')
        body_rig.data.edit_bones['s_arm'].tail = (1.0, 2.0, 0.0)
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = bpy.data.objects.new('Body', bpy.data.meshes.new('Body'))
        mesh.data.from_pydata([(0.5, 2.5, 0.0)], [], [])
        bpy.context.scene.collection.objects.link(mesh)
        mesh.vertex_groups.new(name='s_arm').add([0], 1.0, 'REPLACE')
        mesh.modifiers.new('Armature', 'ARMATURE').object = body_rig
        try:
            body_arm = body_rig.data.bones['s_arm'].matrix_local
            master_arm = self.source.data.bones['s_arm'].matrix_local
            expected = master_arm @ body_arm.inverted() @ mesh.data.vertices[0].co
            stalker2_animation_importer._conform_mesh_to_rest(bpy.context, mesh, body_rig, self.source)
            self.assertFalse([m for m in mesh.modifiers if m.type == 'ARMATURE'])
            self.assertLess((mesh.data.vertices[0].co - expected).length, 1e-5)
        finally:
            bpy.data.objects.remove(mesh, do_unlink=True)
            remove_object(body_rig)

    def test_gltf_body_imports_at_centimetre_scale_in_centimetre_scenes(self):
        mesh = bpy.data.objects.new('GltfBody', bpy.data.meshes.new('GltfBody'))
        mesh.data.from_pydata([(0.0, 0.0, 0.0), (0.0, 0.0, 2.0), (1.0, 0.0, 0.0)], [], [(0, 1, 2)])
        bpy.context.scene.collection.objects.link(mesh)
        mesh.parent = self.source
        mesh.vertex_groups.new(name='s_arm').add([0, 1, 2], 1.0, 'REPLACE')
        mesh.modifiers.new('Armature', 'ARMATURE').object = self.source
        units = bpy.context.scene.unit_settings
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'body.glb')
            for obj in bpy.context.view_layer.objects:
                obj.select_set(obj in (mesh, self.source))
            bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_animations=False)
            bpy.data.objects.remove(mesh, do_unlink=True)
            units.scale_length = 0.01
            try:
                objects, actions = stalker2_animation_importer._gltf_import(path)
                restored = units.scale_length
            finally:
                units.scale_length = 1.0
            try:
                self.assertAlmostEqual(restored, 0.01, places=6)
                imported = next(obj for obj in objects if obj.type == 'MESH' and obj.find_armature())
                self.assertAlmostEqual(imported.dimensions.z, 200.0, delta=0.01)
            finally:
                stalker2_animation_importer._remove_imported(objects, actions)

    def test_gltf_body_bone_axis_convention_does_not_move_the_mesh(self):
        # glTF imports turn every bone's axes the same way; the bind pose itself matches the master.
        body_rig = armature('BodyRig', [('s_' + name, parent and 's_' + parent) for name, parent in CHAIN])
        bpy.context.view_layer.objects.active = body_rig
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in body_rig.data.edit_bones:
            bone.roll += math.pi / 2
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = bpy.data.objects.new('Body', bpy.data.meshes.new('Body'))
        mesh.data.from_pydata([(0.5, 2.5, 0.0)], [], [])
        bpy.context.scene.collection.objects.link(mesh)
        mesh.vertex_groups.new(name='s_arm').add([0], 1.0, 'REPLACE')
        mesh.modifiers.new('Armature', 'ARMATURE').object = body_rig
        try:
            stalker2_animation_importer._conform_mesh_to_rest(bpy.context, mesh, body_rig, self.source)
            self.assertLess((mesh.data.vertices[0].co - Vector((0.5, 2.5, 0.0))).length, 1e-5)
        finally:
            bpy.data.objects.remove(mesh, do_unlink=True)
            remove_object(body_rig)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], exit=False).result.wasSuccessful() or sys.exit(1)
