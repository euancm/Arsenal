"""Asset-free marker regressions in a disposable scene.

blender --background --factory-startup --python-exit-code 1 --python test_weapon_socket_markers.py
Optionally append -- <ZoneKit SK_udp.FBX> <weapon_sockets.json> for the real donor-frame check.
"""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Euler, Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import weapon_sockets as sockets

FIXTURES = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if FIXTURES and len(FIXTURES) != 2:
    raise RuntimeError('Supply both the donor FBX and socket catalogue after --.')

BASELINE = {'location': [3, -2, 1], 'rotation': [15, 25, -35], 'scale': [1, 1, 1]}
DESTINATION = '/SocketTest/SK_weapon'


def make_rig(name):
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    root = rig.data.edit_bones.new('Weapon')
    root.head, root.tail = (0, 0, 0), (0, 2, 0)
    child = rig.data.edit_bones.new('jnt_child')
    child.head, child.tail = (5, -2, 4), (7, -1, 6)
    child.parent = root
    child.roll = 0.4
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


class MarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon.register()

    @classmethod
    def tearDownClass(cls):
        addon.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.rig = make_rig('Weapon')
        self.folder = tempfile.TemporaryDirectory(prefix='arsenal-sockets-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'weapon_sockets.json'
        rotation = Euler((0.2, -0.3, 0.5)).to_quaternion()
        self.records = []
        for name, bone, location in [('Muzzle', 'jnt_offset', [0, 0, 0]),
                                     ('SilencerMuzzleSocket', 'jnt_child', [5, 2, 4])]:
            record = {
                'name': name, 'bone': bone, **BASELINE,
                'owner': '/Game/SKEL_weapon.SKEL_weapon', 'effective': True,
                'bone_transform': {'location': location,
                                   'quaternion': [rotation.x, rotation.y, rotation.z, rotation.w],
                                   'scale': [1, 1, 1]}}
            self.records.append(record)
        self.data = {'version': 1, 'units': 'cm', 'meshes': [
            {'mesh': '/Game/SK_weapon', 'skeleton': '/Game/SKEL_weapon',
             'sockets': self.records}]}
        self.write_catalogue()
        sockets.refresh_markers(self.scene, self.rig, str(self.path))

    def write_catalogue(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def payload(self):
        return sockets.export_payload(self.scene, DESTINATION)

    def assertMatrixClose(self, left, right, tolerance=0.0001):
        self.assertLess(max(abs(a - b) for row, other in zip(left, right) for a, b in zip(row, other)),
                        tolerance, f'{left}\n!=\n{right}')

    def test_reference_frame_and_noop_roundtrip_on_root_and_rotated_child(self):
        bpy.context.view_layer.update()
        for record, entry, exported in zip(self.records, self.scene.arsenal_sockets.entries,
                                           self.payload()['entries']):
            self.assertMatrixClose(entry.marker.matrix_world,
                                   sockets.reference_matrix(record) @ sockets.socket_matrix(BASELINE))
            self.assertTrue(sockets.socket_transforms_equal(exported['transform'], BASELINE))
            self.assertFalse(exported['enabled'])
            self.assertEqual(entry.marker.type, 'EMPTY')

    def test_axis_and_rotation_roundtrips(self):
        for entry in self.scene.arsenal_sockets.entries:
            for axis in range(3):
                for field, delta in [('location', 1), ('rotation', 15)]:
                    value = json.loads(json.dumps(BASELINE))
                    value[field][axis] += delta
                    entry.marker.matrix_basis = sockets.frame_matrix(entry) @ sockets.socket_matrix(value)
                    actual = self.payload()['entries'][list(self.scene.arsenal_sockets.entries).index(entry)]
                    self.assertTrue(sockets.socket_transforms_equal(actual['transform'], value), actual)
                    self.assertTrue(actual['enabled'])

    def test_component_root_uses_weapon_preview_but_preserves_game_parent(self):
        self.data['meshes'][0]['root_bone'] = 'jnt_wpn_weapon'
        record = dict(self.records[0], name='CameraSocket', bone='jnt_wpn_weapon')
        self.records.append(record)
        self.write_catalogue()
        sockets.refresh_markers(self.scene, self.rig, str(self.path))
        entry = self.scene.arsenal_sockets.entries[-1]
        bpy.context.view_layer.update()
        self.assertEqual(entry.marker.parent_bone, 'Weapon')
        self.assertMatrixClose(entry.marker.matrix_world,
                               sockets.reference_matrix(record) @ sockets.socket_matrix(record))
        self.assertEqual(self.payload()['entries'][-1]['bone'], 'jnt_wpn_weapon')
        self.assertFalse(self.payload()['entries'][-1]['enabled'])
        entry.marker.location.x += 1
        self.assertTrue(self.payload()['entries'][-1]['enabled'])
        self.scene.arsenal_sockets.active_index = len(self.records) - 1
        bpy.ops.arsenal.socket_reset()
        self.assertFalse(self.payload()['entries'][-1]['enabled'])

    def test_object_transforms_and_animation_do_not_bake_into_offsets(self):
        self.rig.matrix_world = (Matrix.Translation((20, -40, 8))
                                 @ Euler((0.3, 0.4, 0.5)).to_matrix().to_4x4()
                                 @ Matrix.Scale(2, 4))
        before = self.payload()
        child = self.rig.pose.bones['jnt_child']
        child.rotation_mode = 'XYZ'
        child.rotation_euler = (0.5, 0.2, -0.3)
        child.location = (1, 2, 3)
        bpy.context.view_layer.update()
        self.assertEqual(self.payload(), before)
        entry = self.scene.arsenal_sockets.entries[1]
        expected = (self.rig.matrix_world @ child.matrix @ sockets.bone_tail(self.rig, child.name)
                    @ entry.marker.matrix_basis)
        self.assertMatrixClose(entry.marker.matrix_world, expected)

    def test_refresh_and_template_changes_preserve_edits(self):
        entry = self.scene.arsenal_sockets.entries[0]
        entry.marker.location.x += 1
        before = self.payload()
        pointers = [e.marker for e in self.scene.arsenal_sockets.entries]
        self.scene.stalker2_animation_importer.weapon_name = 'unrelated_template'
        sockets.refresh_markers(self.scene, self.rig, str(self.path))
        self.assertEqual([e.marker for e in self.scene.arsenal_sockets.entries], pointers)
        self.assertEqual(self.payload(), before)

    def test_multi_mesh_catalogue_selects_the_imported_donor(self):
        self.data['meshes'].append(dict(self.data['meshes'][0], mesh='/Game/SK_other'))
        self.write_catalogue()
        self.assertEqual(sockets.catalogue_mesh(str(self.path), donor_name='weapon')['mesh'],
                         '/Game/SK_weapon')
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            sockets.catalogue_mesh(str(self.path))

    def test_attachment_offset_keeps_legacy_behavior_and_selects_donor(self):
        self.rig['arsenal_donor_mesh_name'] = 'weapon'
        wrong = dict(self.records[1], location=[100, 100, 100])
        self.data['meshes'].insert(0, dict(self.data['meshes'][0], mesh='/Game/SK_other', sockets=[wrong]))
        self.write_catalogue()
        expected = self.rig.data.bones['jnt_child'].head_local.copy()
        expected.x += 3
        expected.y += 2
        expected.z += 1
        offset = sockets.import_weapon._socket_offset(self.rig, self.folder.name, 'silen.FBX')
        self.assertLess((offset - expected).length, 0.00001)
        self.path.write_text(json.dumps(self.records), encoding='utf-8')
        legacy = sockets.import_weapon._socket_offset(self.rig, self.folder.name, 'silen.FBX')
        self.assertLess((legacy - expected).length, 0.00001)

    def test_reset_disabled_and_deleted_markers(self):
        entry = self.scene.arsenal_sockets.entries[0]
        entry.marker.location.x += 1
        self.assertTrue(self.payload()['entries'][0]['enabled'])
        entry.enabled = False
        self.assertFalse(self.payload()['entries'][0]['enabled'])
        bpy.ops.arsenal.socket_reset()
        self.assertFalse(self.payload()['entries'][0]['enabled'])
        bpy.data.objects.remove(entry.marker, do_unlink=True)
        with self.assertRaisesRegex(RuntimeError, 'restore'):
            self.payload()
        bpy.ops.arsenal.socket_reset()
        self.assertIsNotNone(entry.marker)
        self.assertFalse(self.payload()['entries'][0]['enabled'])

    def test_duplicate_markers_and_scale_or_parent_changes_are_errors(self):
        entry = self.scene.arsenal_sockets.entries[0]
        duplicate = entry.marker.copy()
        self.scene.collection.objects.link(duplicate)
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            self.payload()
        bpy.data.objects.remove(duplicate, do_unlink=True)
        entry.marker.scale.x *= 2
        with self.assertRaisesRegex(RuntimeError, 'scale'):
            self.payload()
        bpy.ops.arsenal.socket_reset()
        entry.marker.parent_bone = 'jnt_child'
        with self.assertRaisesRegex(RuntimeError, 'original parent'):
            self.payload()

    def test_donor_changes_are_rejected_without_discarding_edits(self):
        before = self.payload()
        self.records[0]['bone'] = 'jnt_unknown'
        self.write_catalogue()
        with self.assertRaisesRegex(RuntimeError, 'no imported bone'):
            sockets.refresh_markers(self.scene, self.rig, str(self.path))
        self.assertEqual(self.payload(), before)

    def test_rebind_to_generated_rig_preserves_world_and_export(self):
        self.rig['arsenal_component_root'] = 'jnt_wpn_weapon'
        self.records.append(dict(self.records[0], name='CameraSocket', bone='jnt_wpn_weapon'))
        self.write_catalogue()
        sockets.refresh_markers(self.scene, self.rig, str(self.path))
        before = self.payload()
        bpy.context.view_layer.update()
        worlds = [entry.marker.matrix_world.copy() for entry in self.scene.arsenal_sockets.entries]
        target = make_rig('Generated')
        target['arsenal_component_root'] = self.rig['arsenal_component_root']
        target.matrix_world = Matrix.Translation((4, -2, 3))
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode='EDIT')
        inverse = target.matrix_world.inverted()
        for bone in target.data.edit_bones:
            bone.transform(inverse)
        bpy.ops.object.mode_set(mode='OBJECT')
        sockets.rebind_markers(self.scene, self.rig, target, target.matrix_world.inverted() @ self.rig.matrix_world)
        bpy.data.objects.remove(self.rig, do_unlink=True)
        self.rig = target
        bpy.context.view_layer.update()
        for entry, world in zip(self.scene.arsenal_sockets.entries, worlds):
            self.assertMatrixClose(entry.marker.matrix_world, world)
        after = self.payload()
        for old, new in zip(before['entries'], after['entries']):
            self.assertTrue(sockets.socket_transforms_equal(old['transform'], new['transform']))

    def test_late_import_on_raised_rigify_matches_import_before_conversion(self):
        source = self.rig
        source['arsenal_retarget_backup'] = True
        source['arsenal_retarget_backup_id'] = 'socket-donor'
        target = make_rig('Generated')
        target.data['rig_id'] = 'socket-test'
        target['arsenal_weapon_backup_id'] = 'socket-donor'
        placement = (Matrix.Translation((18, -6, 148))
                     @ Euler((0.2, -0.3, 0.4)).to_matrix().to_4x4()
                     @ Matrix.Scale(1.7, 4))
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in target.data.edit_bones:
            donor = source.data.bones[bone.name]
            bone.head = placement @ donor.head_local
            bone.tail = placement @ donor.tail_local
            bone.align_roll(placement.to_3x3() @ donor.z_axis)
        target.data.edit_bones['Weapon'].roll += 0.5
        bpy.ops.object.mode_set(mode='OBJECT')
        sockets.rebind_markers(self.scene, source, target, placement)
        bpy.context.view_layer.update()
        early_worlds = [entry.marker.matrix_world.copy() for entry in self.scene.arsenal_sockets.entries]
        del target[sockets.REFERENCE_SPACE]
        for entry in list(self.scene.arsenal_sockets.entries):
            bpy.data.objects.remove(entry.marker, do_unlink=True)
        self.scene.arsenal_sockets.entries.clear()
        self.scene.arsenal_sockets.rig = None
        self.rig = target
        sockets.refresh_markers(self.scene, target, str(self.path))
        bpy.context.view_layer.update()
        self.assertMatrixClose(sockets.reference_space(target), placement, 0.001)
        for record, entry, early in zip(self.records, self.scene.arsenal_sockets.entries, early_worlds):
            self.assertMatrixClose(entry.marker.matrix_world,
                                   placement @ sockets.reference_matrix(record) @ sockets.socket_matrix(record),
                                   0.001)
            self.assertMatrixClose(entry.marker.matrix_world, early, 0.001)
        self.assertTrue(all(not entry['enabled'] for entry in self.payload()['entries']))
        edited = dict(BASELINE, location=[4, -5, 6], rotation=[-30, 40, 50])
        pointers = [entry.marker for entry in self.scene.arsenal_sockets.entries]
        for record, entry in zip(self.records, self.scene.arsenal_sockets.entries):
            name = sockets.bone_name(entry.game_bone, target)
            broken = (sockets.bone_tail(target, name).inverted()
                      @ target.data.bones[name].matrix_local.inverted() @ sockets.reference_matrix(record))
            sockets.store_frame(entry, broken)
            entry.marker.matrix_basis = broken @ sockets.socket_matrix(edited)
        self.scene.arsenal_sockets.frame_version = 0
        self.scene.arsenal_sockets.entries[0].enabled = False
        with self.assertRaisesRegex(RuntimeError, 'Refresh weapon sockets'):
            self.payload()
        sockets.refresh_markers(self.scene, target, str(self.path))
        bpy.context.view_layer.update()
        self.assertEqual(pointers, [entry.marker for entry in self.scene.arsenal_sockets.entries])
        for record, entry, exported in zip(self.records, self.scene.arsenal_sockets.entries,
                                           self.payload()['entries']):
            self.assertTrue(sockets.socket_transforms_equal(exported['transform'], edited))
            self.assertMatrixClose(entry.marker.matrix_world,
                                   placement @ sockets.reference_matrix(record) @ sockets.socket_matrix(edited), 0.001)
        self.assertFalse(self.payload()['entries'][0]['enabled'])
        self.assertTrue(self.payload()['entries'][1]['enabled'])
        target.matrix_world = Matrix.Translation((10, 20, 30))
        sockets.refresh_markers(self.scene, target, str(self.path))
        bpy.context.view_layer.update()
        for record, entry in zip(self.records, self.scene.arsenal_sockets.entries):
            self.assertMatrixClose(entry.marker.matrix_world, target.matrix_world @ placement
                                   @ sockets.reference_matrix(record) @ sockets.socket_matrix(edited), 0.001)

    def test_missing_rigify_reference_blocks_refresh_without_mutating_markers(self):
        self.rig.data['rig_id'] = 'socket-test'
        del self.rig[sockets.REFERENCE_SPACE]
        before = self.payload()
        with self.assertRaisesRegex(RuntimeError, 'source backup is missing'):
            sockets.refresh_markers(self.scene, self.rig, str(self.path))
        self.assertEqual(self.payload(), before)

    def test_blend_save_reload_keeps_authored_state(self):
        self.scene.arsenal_sockets.entries[0].marker.location.z += 1
        before = self.payload()
        path = str(Path(self.folder.name) / 'sockets.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        self.scene = bpy.context.scene
        self.assertEqual(self.payload(), before)

    def test_generated_manifest_and_script_include_validated_socket_payload(self):
        from stalker2_arsenal import export_unreal, export_animation, export_skeleton
        from stalker2_arsenal import export_static_mesh, inventory_images, weapon_cfg, weapon_upgrades
        root = Path(self.folder.name)
        static_file, skeleton_file = root / 'SM_weapon.FBX', root / 'SK_weapon.FBX'
        static_file.touch()
        skeleton_file.touch()
        self.scene.arsenal_export.output_folder = str(root)
        self.scene.arsenal_export.static_category = 'pistol'
        self.scene.arsenal_sockets.entries[0].marker.location.x += 1
        info = {'weapon_id': 'Weapon', 'sid': 'GunWeapon', 'mod': 'SocketTest',
                'cfg': self.scene.arsenal_cfg, 'magazines': [], 'attachments': [],
                'world_mesh': "StaticMesh'/SocketTest/SM_weapon.SM_weapon'",
                'skeletal_mesh': "SkeletalMesh'/SocketTest/SK_weapon.SK_weapon'"}
        with patch.object(export_animation, '_build_static_plan', return_value=(
                self.rig, None, {'Weapon': 'jnt_offset'}, [('main', 'SM_weapon', str(static_file))])), \
                patch.object(export_animation, 'weapon_name', return_value='weapon'), \
                patch.object(export_animation, 'mod_mount', return_value='/SocketTest'), \
                patch.object(export_static_mesh, 'plan_static_meshes', return_value=('weapon', [])), \
                patch.object(export_static_mesh, 'classify_meshes',
                             return_value=(SimpleNamespace(material_slots=[]), [], [])), \
                patch.object(export_skeleton, 'plan_skeleton', return_value=('', str(skeleton_file), 'weapon')), \
                patch.object(weapon_cfg, 'build_context', return_value=info), \
                patch.object(weapon_cfg, 'localization_entries', return_value=[]), \
                patch.object(weapon_cfg, 'compatible_attachment_sids', return_value=[]), \
                patch.object(inventory_images, 'export_images', return_value=[]), \
                patch.object(weapon_upgrades, 'export_images', return_value=[]):
            script, manifest = export_unreal.write_unreal_import(bpy.context)
            self.assertEqual(manifest['weapon_sockets'], self.payload())
            self.assertEqual(json.loads(Path(script).with_suffix('.json').read_text())['weapon_sockets'],
                             self.payload())
            source = Path(script).read_text()
            ast.parse(source)
            self.assertIn('def apply_weapon_sockets(self)', source)
            self.assertIn('BAKED_MANIFEST = ' + repr(str(Path(script).with_suffix('.json'))), source)
            info['skeletal_mesh'] = "SkeletalMesh'/SocketTest/Wrong.Wrong'"
            with self.assertRaisesRegex(RuntimeError, 'differs from the weapon CFG'):
                export_unreal.write_unreal_import(bpy.context)

    @unittest.skipUnless(FIXTURES, 'No external ZoneKit donor fixture supplied')
    def test_real_zonekit_reference_frames(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.rig = sockets.import_weapon._import_skeleton(bpy.context, FIXTURES[0], 'udp')
        sockets.refresh_markers(self.scene, self.rig, FIXTURES[1])
        bpy.context.view_layer.update()
        source = sockets.catalogue_mesh(FIXTURES[1])
        records = {record['name']: record for record in source['sockets'] if record['effective']}
        for entry in self.scene.arsenal_sockets.entries:
            record = records[entry.socket_name]
            head = self.rig.matrix_world @ self.rig.data.bones[
                sockets.bone_name(entry.game_bone, self.rig)].head_local
            self.assertLess((head - sockets.reference_matrix(record).translation).length, 0.001,
                            entry.socket_name)
            self.assertMatrixClose(entry.marker.matrix_world,
                                   sockets.reference_matrix(record) @ sockets.socket_matrix(record), 0.001)
        for entry in self.payload()['entries']:
            self.assertFalse(entry['enabled'], entry['name'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
