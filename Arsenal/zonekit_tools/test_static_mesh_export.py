"""Run with Blender; uses only a disposable scene, no weapon project or exports:
blender --background --factory-startup --python-exit-code 1 --python test_static_mesh_export.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from stalker2_arsenal import export_static_mesh as meshes


class WorldMeshTests(unittest.TestCase):
    def setUp(self):
        self.scene = bpy.data.scenes.new('WorldMeshTest')
        self.objects = []
        self.addCleanup(self.cleanup)
        self.rig = bpy.data.objects.new('TestRig', None)
        self.scene.collection.objects.link(self.rig)
        self.objects.append(self.rig)
        self.joints = {'Weapon': 'jnt_offset', 'Bullet': 'jnt_bullet', 'Shell': 'jnt_bullet_shell',
                       'Magazine': 'jnt_magazine'}

    def cleanup(self):
        for obj in self.objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None:
                bpy.data.meshes.remove(data)
        bpy.data.scenes.remove(self.scene)

    def mesh(self, name, owners):
        data = bpy.data.meshes.new(name)
        vertices = [(index, corner, 0) for index in range(len(owners)) for corner in range(3)]
        data.from_pydata(vertices, [], [tuple(range(3 * index, 3 * index + 3))
                                       for index in range(len(owners))])
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        obj.parent = self.rig
        for index, owner in enumerate(owners):
            group = obj.vertex_groups.get(owner) or obj.vertex_groups.new(name=owner)
            group.add(list(range(index * 3, index * 3 + 3)), 1.0, 'REPLACE')
        self.objects.append(obj)
        return obj

    def test_plan_excludes_only_world_ammunition(self):
        main = self.mesh('custom', ['Weapon', 'Bullet', 'Shell'])
        bullet = self.mesh('round', ['Bullet'])
        shell = self.mesh('case', ['Shell'])
        magazine = self.mesh('mag_full', ['Magazine'])
        _name, plan = meshes.plan_static_meshes(self.rig, self.joints, 'pistol', 'C:\\export', self.scene)
        labels = {label for label, _stem, _path in plan}
        self.assertIn(meshes.WORLD_PREFIX + main.name, labels)
        self.assertIn(meshes.WORLD_PREFIX + magazine.name, labels)
        for obj in (bullet, shell):
            self.assertIn(obj.name, labels)
            self.assertNotIn(meshes.WORLD_PREFIX + obj.name, labels)
        self.assertTrue({'Bullet', 'Shell'} <= labels)

    def test_world_geometry_removes_embedded_bullets_and_shells(self):
        main = self.mesh('custom', ['Weapon', 'Bullet', 'Shell'])
        bone = SimpleNamespace(head_local=Vector((0, 0, 0)))
        rig = SimpleNamespace(matrix_world=self.rig.matrix_world, data=SimpleNamespace(bones={'Weapon': bone}))
        part, _materials = meshes.extract_whole(rig, self.rig, main, 'Weapon', self.joints)
        try:
            self.assertEqual(len(part.faces), 1)
            self.assertEqual(len(part.verts), 3)
        finally:
            part.free()
        part, _materials = meshes.extract_whole(rig, self.rig, main, 'Weapon')
        try:
            self.assertEqual(len(part.faces), 3)
        finally:
            part.free()

    def test_export_jobs_match_the_filtered_plan(self):
        self.mesh('custom', ['Weapon', 'Bullet', 'Shell'])
        self.mesh('round', ['Bullet'])
        self.mesh('case', ['Shell'])
        self.mesh('mag_full', ['Magazine'])
        part = SimpleNamespace(free=lambda: None)
        context = SimpleNamespace(scene=self.scene,
                                  view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)))
        rig = SimpleNamespace(data=SimpleNamespace(bones={'Weapon': object()}))

        def temporary(_context, stem, _pieces):
            return bpy.data.objects.new(stem, bpy.data.meshes.new(stem))

        with patch.object(meshes, 'classify_meshes', return_value=meshes.classify_meshes(
                self.rig, self.scene, self.joints)), \
                patch.object(meshes, 'split_by_bone', return_value={
                    bone: (part, []) for bone in ('Weapon', 'Bullet', 'Shell')}), \
                patch.object(meshes, 'extract_whole', return_value=(part, [])) as extract, \
                patch.object(meshes, 'create_part_object', side_effect=temporary), \
                patch.object(meshes, 'write_static_mesh'):
            written, skipped = meshes.export_static_meshes(
                context, rig, self.rig, self.joints, 'pistol', 'C:\\export')
        self.assertEqual(len(written), 8)
        self.assertEqual(skipped, [])
        world_calls = [call for call in extract.call_args_list if len(call.args) == 5]
        self.assertEqual([call.args[2].name for call in world_calls], ['custom', 'mag_full'])

    def test_world_magazine_socket_reconstructs_bone_local_mesh_at_rest(self):
        magazine = self.mesh('mag_full', ['Magazine'])
        root = Vector((18, -6, 148))
        head = root + Vector((-1, 2, -3.5))
        rig = SimpleNamespace(
            matrix_world=Matrix.Identity(4),
            data=SimpleNamespace(bones={
                'Weapon': SimpleNamespace(head_local=root),
                'Magazine': SimpleNamespace(head_local=head)}))
        payload = meshes.world_magazine_sockets(
            rig, self.rig, self.joints,
            [{'name': 'Default', 'socket': 'jnt_magazine', 'existing_sid': 'SharedMag'},
             {'name': 'Extended', 'socket': 'jnt_magazine'}],
            '/TestMod/SM_custom')
        self.assertEqual(payload['mesh'], '/TestMod/SM_custom')
        self.assertEqual(len(payload['entries']), 1)
        entry = payload['entries'][0]
        self.assertEqual(entry['name'], 'jnt_magazine')
        self.assertEqual(entry['location'], [-1, -2, -3.5])
        self.assertEqual(entry['rotation'], [0, 0, 0])
        part, _ = meshes.extract_whole(rig, self.rig, magazine, 'Magazine')
        world, _ = meshes.extract_whole(rig, self.rig, magazine, 'Weapon')
        try:
            displacement = Vector((entry['location'][0], -entry['location'][1], entry['location'][2]))
            for local, expected in zip(part.verts, world.verts):
                self.assertLess((local.co + displacement - expected.co).length, 1e-5)
        finally:
            part.free()
            world.free()

    def test_world_magazine_socket_rejects_unmapped_mount(self):
        rig = SimpleNamespace(data=SimpleNamespace(bones={'Weapon': object()}))
        with self.assertRaisesRegex(RuntimeError, 'UnknownMount'):
            meshes.world_magazine_sockets(
                rig, self.rig, self.joints, [{'name': 'Shared', 'socket': 'UnknownMount'}],
                '/TestMod/SM_custom')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
