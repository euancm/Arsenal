"""Donor import regressions in disposable Blender scenes.

blender --background --factory-startup --python-exit-code 1 --python test_weapon_import.py
Optionally append -- <ZoneKit Export folder> [weapon_sockets.json] to check real Dnipro/GP37
magazines and accessories. The optional catalogue must contain both donors' reference frames.
No scene or donor file is saved.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import import_weapon as weapon
from stalker2_arsenal import export_animation
from stalker2_arsenal import stalker2_animation_importer as animation
from stalker2_arsenal import weapon_presets, weapon_sockets

FIXTURES = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []


def make_rig(donor):
    rig = bpy.data.objects.new('Weapon', bpy.data.armatures.new('Weapon'))
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    root = rig.data.edit_bones.new('Weapon')
    root.head, root.tail = (0, 0, 0), (0, 1, 0)
    clip = rig.data.edit_bones.new('jnt_clip_base')
    clip.head, clip.tail, clip.parent = (5, 10, -3), (5, 11, -3), root
    bpy.ops.object.mode_set(mode='OBJECT')
    rig['arsenal_donor_mesh_name'] = donor
    return rig


class WeaponImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon.register()

    @classmethod
    def tearDownClass(cls):
        addon.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.folder = tempfile.TemporaryDirectory(prefix='arsenal-weapon-import-')
        self.addCleanup(self.folder.cleanup)

    def test_attachment_discovery_is_scoped_to_donor_in_shared_export(self):
        root = Path(self.folder.name)
        expected = {}
        for key in ('TemplateDnipro', 'TemplateG37'):
            expected[key] = set()
            for entry in weapon_presets.PRESETS[key]['attachment_mounts']:
                path = root.joinpath(*entry['mesh'].split('/')[2:]).with_suffix('.fbx')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                expected[key].add(str(path))
        stale = root / '_Stalker_2' / 'weapons' / 'old' / 'SM_old_mag_full.fbx'
        stale.parent.mkdir(parents=True)
        stale.touch()
        for key, paths in expected.items():
            donor = weapon_presets.PRESETS[key]['mesh']
            self.assertEqual(set(weapon.find_attachment_files(str(root), donor)), paths)
        missing = Path(next(iter(expected['TemplateDnipro'])))
        missing.unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'Regenerate and run'):
            weapon.find_attachment_files(str(root), 'dnipro')
        with patch.object(weapon, 'find_donor_files', return_value=('unused.fbx', [])), \
                patch.object(weapon, '_import_skeleton') as create_rig:
            with self.assertRaisesRegex(FileNotFoundError, 'Regenerate and run'):
                weapon.import_rigged_weapon(bpy.context, str(root), 'dnipro')
        create_rig.assert_not_called()

    def test_magazines_use_clip_base_instead_of_weapon_root(self):
        rig = make_rig('dnipro')
        mesh = bpy.data.meshes.new('magazine')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new('magazine', mesh)
        bpy.context.scene.collection.objects.link(obj)
        with patch.object(weapon, '_import', return_value=[obj]):
            weapon._import_attachments(bpy.context, rig, ['SM_ar_dni_mag_full.fbx'], self.folder.name)
        self.assertEqual([group.name for group in obj.vertex_groups], ['jnt_clip_base'])
        self.assertLess((obj.data.vertices[0].co - rig.data.bones['jnt_clip_base'].head_local).length, 0.00001)
        self.assertEqual(obj.modifiers['Armature'].object, rig)

    def test_lasers_use_their_own_rotated_socket_and_reference_frame(self):
        rig = make_rig('dnipro')
        records = []
        for name, location, roll in [('LaserSocket', [10, 2, 4], 90),
                                     ('LaserSocket2', [20, 3, 5], -90)]:
            records.append({
                'name': name, 'bone': 'jnt_offset', 'owner': '/Game/SKEL_dnipro',
                'effective': True, 'location': location, 'rotation': [roll, 0, 0],
                'scale': [1, 1, 1],
                'bone_transform': {'location': [3, 4, 5], 'quaternion': [0, 0, 0, 1],
                                   'scale': [1, 1, 1]}})
        catalogue = {'version': 1, 'units': 'cm', 'meshes': [
            {'mesh': '/Game/SK_dnipro', 'sockets': records}]}
        (Path(self.folder.name) / weapon.SOCKET_FILE).write_text(json.dumps(catalogue), encoding='utf-8')
        for filename, record in zip(('SM_ls01_ru_laser_1.fbx', 'SM_ls02_en_laser_right.fbx'), records):
            mesh = bpy.data.meshes.new(filename)
            mesh.from_pydata([(0, 0, 0), (0, 1, 0)], [], [])
            obj = bpy.data.objects.new(filename, mesh)
            bpy.context.scene.collection.objects.link(obj)
            with patch.object(weapon, '_import', return_value=[obj]):
                weapon._import_attachments(bpy.context, rig, [filename], self.folder.name)
            expected = weapon_sockets.reference_matrix(record) @ weapon_sockets.socket_matrix(record)
            for vertex, source in zip(obj.data.vertices, ((0, 0, 0, 1), (0, 1, 0, 1))):
                target = (expected @ Vector(source)).to_3d()
                self.assertLess((vertex.co - target).length, 0.00001)

    def test_missing_named_socket_is_an_explicit_error(self):
        rig = make_rig('dnipro')
        catalogue = {'version': 1, 'units': 'cm', 'meshes': [{'mesh': '/Game/SK_dnipro', 'sockets': []}]}
        (Path(self.folder.name) / weapon.SOCKET_FILE).write_text(json.dumps(catalogue), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'LaserSocket2'):
            weapon._socket_offset(rig, self.folder.name, 'SM_ls02_en_laser_right.fbx')

    def test_attachment_follows_socket_edits_and_bone_animation_once(self):
        rig = make_rig('dnipro')
        marker = bpy.data.objects.new('LaserSocket2', None)
        bpy.context.scene.collection.objects.link(marker)
        marker.parent, marker.parent_type, marker.parent_bone = rig, 'BONE', 'jnt_clip_base'
        marker.location = (1, 2, 3)
        entry = bpy.context.scene.arsenal_sockets.entries.add()
        entry.socket_name, entry.marker = 'LaserSocket2', marker
        marker.arsenal_socket_id = 'socket-preview-test'
        mesh = bpy.data.meshes.new('Laser')
        mesh.from_pydata([(0, 0, 0), (0, 1, 0)], [], [])
        obj = bpy.data.objects.new('Laser', mesh)
        bpy.context.scene.collection.objects.link(obj)
        placement = Matrix.Translation((3, 5, 7))
        with patch.object(weapon, '_import', return_value=[obj]), \
                patch.object(weapon, '_attachment_placement',
                             return_value=(rig.data.bones['jnt_clip_base'], placement)):
            weapon._import_attachments(bpy.context, rig, ['SM_ls02_en_laser_right.fbx'], self.folder.name)
        bpy.context.view_layer.update()
        self.assertEqual(obj.parent, marker)
        self.assertFalse(obj.modifiers['Armature'].show_viewport)
        before = obj.matrix_world @ obj.data.vertices[0].co
        self.assertLess((before - placement.translation).length, 0.00001)
        from stalker2_arsenal import export_static_mesh
        original, _materials = export_static_mesh.extract_whole(rig, rig, obj, 'jnt_clip_base')
        try:
            local_before = [vertex.co.copy() for vertex in original.verts]
        finally:
            original.free()
        marker.location.x += 4
        marker.rotation_euler.z += 0.4
        bpy.context.view_layer.update()
        moved = obj.matrix_world @ obj.data.vertices[0].co
        self.assertGreater((moved - before).length, 1)
        after, _materials = export_static_mesh.extract_whole(rig, rig, obj, 'jnt_clip_base')
        try:
            for expected, vertex in zip(local_before, after.verts):
                self.assertLess((vertex.co - expected).length, 0.00001)
        finally:
            after.free()
        world_before, _materials = export_static_mesh.extract_whole(
            rig, rig, obj, 'Weapon', {'Weapon': 'jnt_offset'})
        try:
            world_points = [vertex.co.copy() for vertex in world_before.verts]
        finally:
            world_before.free()
        rig.pose.bones['jnt_clip_base'].location.z += 2
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        self.assertLess((evaluated.matrix_world @ evaluated.data.vertices[0].co
                         - moved - Vector((0, 0, 2))).length, 0.00001)
        world_after, _materials = export_static_mesh.extract_whole(
            rig, rig, obj, 'Weapon', {'Weapon': 'jnt_offset'})
        try:
            for expected, vertex in zip(world_points, world_after.verts):
                self.assertLess((vertex.co - expected).length, 0.00001)
        finally:
            world_after.free()
        cfg = bpy.context.scene.arsenal_cfg
        item = cfg.attachments.add()
        item.mesh_object, item.use_existing = obj, True
        self.assertNotIn(obj, export_static_mesh.weapon_meshes(rig, bpy.context.scene))
        item.use_existing = False
        self.assertIn(obj, export_static_mesh.weapon_meshes(rig, bpy.context.scene))

    def test_control_shapes_match_family_without_using_base_for_clip_base(self):
        names = ['customboneshape_base_pistol', 'customboneshape_base_shotgun',
                 'customboneshape_pistol_magazine', 'customboneshape_shotgun_magazine',
                 'customboneshape_pistol_slide', 'customboneshape_trigger']
        self.assertEqual(weapon.shape_for_bone('Weapon', names, weapon_class='shotgun'),
                         'customboneshape_base_shotgun')
        self.assertEqual(weapon.shape_for_bone('jnt_clip_base', names, weapon_class='shotgun'),
                         'customboneshape_shotgun_magazine')
        self.assertIsNone(weapon.shape_for_bone('jnt_shutter', names, weapon_class='rifle'))
        self.assertEqual(weapon.shape_for_bone('jnt_trigger', names, weapon_class='rifle'),
                         'customboneshape_trigger')

    def test_skeletal_launcher_preview_keeps_placement_without_its_source_rig(self):
        rig = make_rig('m160')
        source = bpy.data.objects.new('Launcher source rig', bpy.data.armatures.new('Launcher source rig'))
        bpy.context.scene.collection.objects.link(source)
        source.location = (2, 3, 4)
        mesh = bpy.data.meshes.new('Launcher')
        mesh.from_pydata([(0, 0, 0), (0, 1, 0), (0, 10, 0), (1, 10, 0)], [], [])
        obj = bpy.data.objects.new('Launcher', mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent, obj.location = source, (1, 2, 3)
        group = obj.vertex_groups.new(name='SourceLauncherJoint')
        group.add([0, 1], 1, 'REPLACE')
        group.add([2], 0.4, 'REPLACE')
        # Spare rounds parked beside the M203 must not float next to the preview.
        obj.vertex_groups.new(name='jnt_m406_charge').add([2], 0.6, 'REPLACE')
        obj.vertex_groups.new(name='jnt_vog25_charge').add([3], 1, 'REPLACE')
        obj.modifiers.new('Source armature', 'ARMATURE').object = source
        bpy.context.view_layer.update()
        offset = Matrix.Translation((4, 5, 6))
        expected = offset @ obj.matrix_world @ obj.data.vertices[0].co
        source_name = source.name
        with patch.object(weapon, '_import', return_value=[source, obj]), \
                patch.object(weapon, '_attachment_placement', return_value=(rig.data.bones['Weapon'], offset)):
            weapon._import_attachments(bpy.context, rig, ['SK_gla.fbx'], self.folder.name)
        self.assertNotIn(source_name, bpy.data.objects)
        self.assertEqual([group.name for group in obj.vertex_groups], ['Weapon'])
        self.assertEqual(len(obj.modifiers), 1)
        self.assertEqual(obj.modifiers[0].object, rig)
        self.assertEqual(len(obj.data.vertices), 2)
        self.assertLess((obj.data.vertices[0].co - expected).length, 0.00001)

    def test_aim_to_idle_halves_pair_across_donor_naming_variants(self):
        root = Path(self.folder.name)
        player, weapon_folder = root / 'Animations' / 'Player', root / 'Animations' / 'Weapons'
        player.mkdir(parents=True)
        weapon_folder.mkdir(parents=True)
        for folder, name in ((player, 'AS_fp_m860_idle'), (weapon_folder, 'AS_m860_fp_idle'),
                             (player, 'AS_fp_m860_idle_aim_to_idle'),
                             (weapon_folder, 'AS_m860_fp_aim_to_idle')):
            (folder / (name + '.fbx')).touch()
        pairs, player_only, weapon_only, ambiguous = animation._scan_library(str(root), 'm860')
        self.assertEqual((player_only, weapon_only, ambiguous), ([], [], []))
        transitions = [pair for pair in pairs if pair[0] != 'idle']
        self.assertEqual(len(transitions), 1)
        transition = transitions[0]
        self.assertEqual(transition[0], 'idle_aim_to_idle')
        self.assertEqual(Path(transition[2]).stem, 'AS_m860_fp_aim_to_idle')
        self.assertIsNone(animation.stand_in_half(transition))
        with tempfile.TemporaryDirectory(prefix='arsenal-transition-export-') as output:
            outputs, _status = export_animation.plan_export(
                transition[0], '', '', pairs, 'm860', 'newgun', output, str(root))
        self.assertTrue(all(target for _kind, _source, target in outputs))
        self.assertEqual({Path(target).name for _kind, _source, target in outputs},
                         {'AS_fp_newgun_idle_aim_to_idle.fbx', 'AS_newgun_fp_aim_to_idle.fbx'})
        (weapon_folder / 'AS_m860_fp_idle_aim_to_idle.fbx').touch()
        pairs, _player, _weapon, ambiguous = animation._scan_library(str(root), 'm860')
        self.assertEqual([pair[0] for pair in pairs], ['idle'])
        self.assertEqual(ambiguous, ['aim_to_idle'])

    def test_differently_numbered_halves_pair_and_stale_stand_in_bakes_are_skipped(self):
        root = Path(self.folder.name)
        player, weapon_folder = root / 'Animations' / 'Player', root / 'Animations' / 'Weapons'
        player.mkdir(parents=True)
        weapon_folder.mkdir(parents=True)
        for folder, name in ((player, 'AS_fp_m16_idle'), (weapon_folder, 'AS_m16_fp_idle'),
                             (player, 'AS_fp_m16_sight_attach_BuckGrenLaunch2'),
                             (weapon_folder, 'AS_m16_fp_sight_attach_BuckGrenLaunch'),
                             (player, 'AS_FP_Player_M16_IdleToOffsetAim_01')):
            (folder / (name + '.fbx')).touch()
        pairs, player_only, weapon_only, _ambiguous = animation._scan_library(str(root), 'm16')
        self.assertEqual((player_only, weapon_only), ([], []))
        by_name = {pair[0]: pair for pair in pairs}
        self.assertEqual(set(by_name), {'idle', 'sight_attach_BuckGrenLaunch2', 'IdleToOffsetAim_01'})
        variant = by_name['sight_attach_BuckGrenLaunch2']
        self.assertEqual(Path(variant[2]).stem, 'AS_m16_fp_sight_attach_BuckGrenLaunch')
        self.assertIsNone(animation.stand_in_half(variant))
        self.assertTrue(animation.is_variant_pair(variant))
        self.assertEqual(animation.stand_in_half(by_name['IdleToOffsetAim_01']), 'weapon')
        self.assertFalse(animation.is_variant_pair(by_name['IdleToOffsetAim_01']))
        with tempfile.TemporaryDirectory(prefix='arsenal-variant-export-') as output:
            outputs, status = export_animation.plan_export(
                variant[0], '', '', pairs, 'm16', 'newgun', output, str(root))
            self.assertEqual({Path(target).name for _kind, _source, target in outputs},
                             {'AS_fp_newgun_sight_attach_BuckGrenLaunch2.fbx',
                              'AS_newgun_fp_sight_attach_BuckGrenLaunch.fbx'})
            self.assertEqual(status, 'Matches an original animation')
            export = bpy.context.scene.arsenal_export
            basics = (export, SimpleNamespace(weapon_name='m16'), None, None, 'newgun', output, str(root))
            for record, skipped in ((None, True), (animation.pair_record(variant), False)):
                action = bpy.data.actions.new('sight_attach_BuckGrenLaunch2')
                action[animation.ACTION_MARKER] = True
                if record:
                    action[animation.PAIR_RECORD] = record
                with patch.object(export_animation, '_export_basics', return_value=basics), \
                        patch.object(export_animation, 'exportable_actions', return_value=[action]), \
                        patch.object(export_animation, 'rig_action_slot'), \
                        patch.object(export_animation.importer, '_scan_library',
                                     return_value=(pairs, [], [], [])):
                    _rig, _backup, plans, problems = export_animation._build_plans(bpy.context)
                self.assertEqual(problems, 0)
                self.assertEqual(len(plans), 0 if skipped else 1)
                self.assertEqual(export.actions[0].status.startswith('Skipped'), skipped)
                bpy.data.actions.remove(action)

    @unittest.skipUnless(FIXTURES, 'Supply an external ZoneKit Export folder for real mesh checks.')
    def test_real_donor_magazines_are_scoped_weighted_and_offset(self):
        root = FIXTURES[0]
        for donor in ('dnipro', 'gp37'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            skeleton, _parts = weapon.find_donor_files(root, donor)
            rig = weapon._import_skeleton(bpy.context, skeleton, donor)
            preset = next(row for row in weapon_presets.PRESETS.values() if row['mesh'] == donor)
            paths = [Path(root).joinpath(*entry['mesh'].split('/')[2:]).with_suffix('.fbx')
                     for entry in preset['attachment_mounts']]
            paths = [str(path) for path in paths if path.is_file() and 'mag' in path.stem.lower()]
            self.assertTrue(paths, donor)
            for path in paths:
                self.assertNotIn('gp3' if donor == 'dnipro' else 'dni', Path(path).stem.lower())
                raw = weapon._import(path)
                source = next(obj for obj in raw if obj.type == 'MESH')
                first = source.matrix_world @ source.data.vertices[0].co
                weapon.importer._remove_imported(raw, [])
                objects = weapon._import_attachments(bpy.context, rig, [path], root)
                self.assertTrue(objects, path)
                for obj in objects:
                    self.assertEqual([group.name for group in obj.vertex_groups], ['jnt_clip_base'])
                expected = first + rig.data.bones['jnt_clip_base'].head_local
                self.assertLess((objects[0].data.vertices[0].co - expected).length, 0.0001)

    @unittest.skipUnless(len(FIXTURES) > 1, 'Supply a matching multi-donor native socket catalogue.')
    def test_real_accessories_match_native_socket_rotation_and_location(self):
        root, catalogue = Path(FIXTURES[0]), Path(FIXTURES[1])
        for donor in ('dnipro', 'gp37'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            skeleton, _parts = weapon.find_donor_files(str(root), donor)
            rig = weapon._import_skeleton(bpy.context, skeleton, donor)
            sockets = weapon_sockets.catalogue_mesh(str(catalogue), donor_name=donor)['sockets']
            preset = next(row for row in weapon_presets.PRESETS.values() if row['mesh'] == donor)
            checked = set()
            for entry in preset['attachment_mounts']:
                if entry['socket'] not in ('LaserSocket', 'LaserSocket2', 'SilencerMuzzleSocket'):
                    continue
                path = root.joinpath(*entry['mesh'].split('/')[2:]).with_suffix('.fbx')
                self.assertTrue(path.is_file(), path)
                record, = [socket for socket in sockets
                           if socket['effective'] and socket['name'] == entry['socket']]
                expected = weapon_sockets.reference_matrix(record) @ weapon_sockets.socket_matrix(record)
                raw = weapon._import(str(path))
                source = next(obj for obj in raw if obj.type == 'MESH'
                              and not obj.name.upper().startswith(('UCX_', 'UBX_', 'USP_', 'UCP_'))
                              and not weapon.importer._is_lower_lod(obj.name))
                indices = (0, len(source.data.vertices) // 2, len(source.data.vertices) - 1)
                points = [expected @ source.matrix_world @ source.data.vertices[index].co for index in indices]
                weapon.importer._remove_imported(raw, [])
                objects = weapon._import_attachments(bpy.context, rig, [str(path)], str(catalogue.parent))
                self.assertTrue(objects, path)
                target = objects[0]
                for index, point in zip(indices, points):
                    self.assertLess((target.data.vertices[index].co - point).length, 0.0001)
                bone = weapon_sockets.bone_name(record['bone'], rig)
                self.assertEqual([group.name for group in target.vertex_groups], [bone])
                checked.add(entry['socket'])
            self.assertEqual(checked, {'LaserSocket', 'LaserSocket2', 'SilencerMuzzleSocket'})

    def test_body_materials_use_colour_alpha_and_recover_a_missing_albedo(self):
        root = Path(self.folder.name)
        (root / 'Textures').mkdir()
        for name in ('T_thr_D', 'T_han_R_D', 'T_han_R_N'):
            image = bpy.data.images.new(name, 4, 4, alpha=True)
            image.filepath_raw = str(root / 'Textures' / f'{name}.png')
            image.file_format = 'PNG'
            image.save()
        (root / 'materials.json').write_text(json.dumps({
            'MI_thr': {'Diffuse_VT': 'Textures/T_thr_D.png'},
            # The right hand's albedo was exported but missing from older material tables.
            'MI_han_R': {'SRC': 'Textures/T_han_R_SRC.png', 'Normal': 'Textures/T_han_R_N.png'},
        }), encoding='utf-8')

        def textured(names, use_alpha):
            mesh = bpy.data.meshes.new('body')
            for name in names:
                mesh.materials.append(bpy.data.materials.new(name))
            obj = bpy.data.objects.new('body', mesh)
            self.assertEqual(weapon.apply_materials(str(root), [obj], use_alpha=use_alpha), len(names))
            return [next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
                    for material in mesh.materials]

        threads, hand = textured(['MI_thr', 'MI_han_R'], True)
        self.assertEqual(threads.inputs['Alpha'].links[0].from_socket.name, 'Alpha')
        self.assertEqual(Path(hand.inputs['Base Color'].links[0].from_node.image.filepath).name, 'T_han_R_D.png')
        weapon_threads, = textured(['MI_thr'], False)
        self.assertFalse(weapon_threads.inputs['Alpha'].is_linked)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
