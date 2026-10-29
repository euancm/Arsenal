"""Compare a saved Rigify action with exported/reimported FBX poses in Blender.

blender --background --factory-startup --python-exit-code 1 --python test_animation_export.py -- <blend> [action]
The blend must contain an Arsenal rig, backup, and an accessible template library.
"""
import importlib
import math
import os
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector


def angular_error(a, b):
    dot = abs(math.fsum(x * y for x, y in zip(a, b))) / math.sqrt(
        math.fsum(x * x for x in a) * math.fsum(x * x for x in b))
    return 2 * math.acos(min(1.0, dot))


def engine_worlds(armature):
    """FBX local TRS composed as FTransform, not Blender's shearing matrix hierarchy."""
    worlds = {}
    pending = list(armature.pose.bones)
    while pending:
        ready = [bone for bone in pending if not bone.parent or bone.parent.name in worlds]
        assert ready, 'Invalid bone hierarchy'
        for bone in ready:
            local = bone.parent.matrix.inverted() @ bone.matrix if bone.parent else bone.matrix
            lt, lr, ls = local.decompose()
            if bone.parent:
                pt, pr, ps = worlds[bone.parent.name].decompose()
                lt = pt + pr @ Vector(tuple(a * b for a, b in zip(ps, lt)))
                lr = pr @ lr
                ls = Vector(tuple(a * b for a, b in zip(ps, ls)))
            worlds[bone.name] = Matrix.LocRotScale(lt, lr, ls)
            pending.remove(bone)
    return worlds


def skin_bindings(rig, backup):
    sources = [
        obj for obj in bpy.context.scene.objects if obj.type == 'MESH'
        and any(mod.type == 'ARMATURE' and mod.object == backup for mod in obj.modifiers)
    ]
    assert len(sources) == 1, 'Expected the original character mesh in the retarget backup'
    source = sources[0]
    targets = [
        obj for obj in bpy.context.scene.objects if obj.type == 'MESH'
        and len(obj.data.vertices) == len(source.data.vertices)
        and len(obj.vertex_groups) == len(source.vertex_groups)
        and any(mod.type == 'ARMATURE' and mod.object == rig for mod in obj.modifiers)
    ]
    assert len(targets) == 1, 'Cannot identify the original mesh after vertex-group renaming'
    target = targets[0]
    # Conversion renames groups, without changing their indices, vertices or weights.
    for original, converted in zip(source.data.vertices, target.data.vertices):
        assert [(g.group, g.weight) for g in original.groups] == [(g.group, g.weight) for g in converted.groups]
    bindings = [
        (old.name, new.name)
        for old, new in zip(source.vertex_groups, target.vertex_groups)
        if old.name in backup.data.bones
    ]
    assert all(name in rig.data.bones and rig.data.bones[name].use_deform for _, name in bindings), 'Unbound viewport vertex group'
    return source, target, bindings


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    addon = importlib.import_module('stalker2_arsenal')
    addon.register()
    ex = importlib.import_module('stalker2_arsenal.export_animation')
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args[0]))
    rig, backup = ex.find_export_rig(bpy.context)
    assert rig and backup, 'No Arsenal export rig/backup'
    if ex.deformation_preview_issues(rig):
        try:
            ex.run_exports(bpy.context, rig, backup, [])
        except RuntimeError as error:
            assert 'Repair Deformation Preview' in str(error), error
        else:
            raise AssertionError('Export silently accepted a mismatching viewport')
    conversion = importlib.import_module('stalker2_arsenal.convert_to_rigify')
    assert bpy.ops.object.arsenal_repair_deformation_preview() == {'FINISHED'}
    bone_count = len(rig.data.bones)
    conversion.tidy_generated_rig(bpy.context, rig)
    assert len(rig.data.bones) == bone_count, 'Wrist helper repair is not idempotent'
    mesh, viewport_mesh, bindings = skin_bindings(rig, backup)
    sm = importlib.import_module('stalker2_arsenal.export_static_mesh')
    settings = bpy.context.scene.stalker2_animation_importer
    name_owner = type('MeshName', (), {'name': settings.weapon_name})()
    custom_name = ex.weapon_name(bpy.context.scene)
    assert sm.weapon_mesh_name(name_owner, bpy.context.scene) == custom_name
    name_owner.name = 'ArtistCustomMesh'
    assert sm.weapon_mesh_name(name_owner, bpy.context.scene) == 'ArtistCustomMesh'
    action = bpy.data.actions[args[1] if len(args) > 1 else 'reload']
    slot = ex.rig_action_slot(action, rig)
    rig.animation_data.action = action
    rig.animation_data.action_slot = slot
    mapping, missing = ex.resolve_animation_mapping(backup, rig)
    assert not missing, missing
    settings = bpy.context.scene.stalker2_animation_importer
    library = bpy.path.abspath(settings.animation_root)
    pairs, _player, _weapon, _ambiguous = ex.importer._scan_library(library, settings.weapon_name)
    first, last = math.floor(action.frame_range[0]), math.ceil(action.frame_range[1])
    frames = list(range(first, last + 1))
    arm_names = {
        source for source, _target in bindings
        if source.startswith(('jnt_l_', 'jnt_r_'))
        and any(token in source for token in ('arm', 'hand', 'elbow', 'shoulder'))
    }
    checked_names = arm_names | {'jnt_spine_03'}
    camera = rig.pose.bones.get('Camera')
    camera_source = backup.data.bones.get('jnt_camera')
    assert camera is not None and camera_source is not None, 'Camera bone mapping is missing'
    checked_names.add('jnt_camera')
    vertices = []
    for vertex in mesh.data.vertices:
        weights = [(mesh.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
        # Export deliberately gives these bones the donor's twist (and, on the spine, length), not Rigify's.
        if any(name in ex.TWIST_LOCKED_CHAIN for name, weight in weights if weight > 0):
            continue
        if any(name in arm_names for name, weight in weights if weight > 0):
            vertices.append((vertex.index, vertex.co.copy(), weights))
    assert vertices, 'No weighted arm/hand vertices tested'
    parent = rig.pose.bones['upper_arm_parent.L']
    saved_ik = parent['IK_FK']
    ik_path = 'pose.bones["upper_arm_parent.L"]["IK_FK"]'
    ik_curves = [curve for curve in ex.action_slot_curves(action, slot) if curve.data_path == ik_path]
    saved_mutes = [(curve, curve.mute) for curve in ik_curves]
    for curve in ik_curves:
        curve.mute = True
    try:
        with tempfile.TemporaryDirectory(prefix='arsenal-animation-test-') as folder:
            outputs, _status = ex.plan_export(
                action.name, '', '', pairs, settings.weapon_name, 'test', folder, library)
            assert not ({source for _target, source in ex.deformation_entries(rig, backup, mapping)}
                        & set(ex.TEMPLATE_SOCKETS)), 'Unmapped runtime sockets were taken from Rigify'
            objects, actions, donor, donor_clip = ex.importer._import_fbx(outputs[0][1])
            try:
                weapon_objects, weapon_actions, _weapon_donor, weapon_clip = ex.importer._import_fbx(outputs[1][1])
                try:
                    template_first = math.floor(min(donor_clip.frame_range[0], weapon_clip.frame_range[0]))
                    template_last = math.ceil(max(donor_clip.frame_range[1], weapon_clip.frame_range[1]))
                    if outputs[0][2] is None or outputs[1][2] is None:
                        real_clip = weapon_clip if outputs[0][2] is None else donor_clip
                        template_first = math.floor(real_clip.frame_range[0])
                        template_last = math.ceil(real_clip.frame_range[1])
                    template_frames = [
                        min(max(frame - first + template_first, template_first), template_last)
                        for frame in frames
                    ]
                    socket_poses = {}
                    for frame, template_frame in zip(frames, template_frames):
                        bpy.context.scene.frame_set(template_frame)
                        bpy.context.view_layer.update()
                        socket_poses[frame] = {
                            name: world for name, world in engine_worlds(donor).items()
                            if name in ex.TEMPLATE_SOCKETS
                        }
                finally:
                    ex.importer._remove_imported(weapon_objects, weapon_actions)
            finally:
                ex.importer._remove_imported(objects, actions)
            for mode in (0.0, 0.5, 1.0):
                parent['IK_FK'] = mode
                rig.update_tag()
                expected = {}
                expected_vertices = {}
                with ex.b_fun.forced_pose_position(rig, backup):
                    for frame in frames:
                        bpy.context.scene.frame_set(frame)
                        bpy.context.view_layer.update()
                        assert abs(parent['IK_FK'] - mode) < 0.00001, 'Action overrode the tested IK/FK mode'
                        row = {}
                        for source, name in bindings:
                            world = rig.matrix_world @ rig.pose.bones[name].matrix
                            rest = rig.matrix_world @ rig.data.bones[name].matrix_local
                            source_rest = backup.matrix_world @ backup.data.bones[source].matrix_local
                            row[source] = backup.matrix_world.inverted_safe() @ world @ rest.inverted_safe() @ source_rest
                        world = rig.matrix_world @ rig.pose.bones['Weapon'].matrix
                        rest = rig.matrix_world @ rig.data.bones['Weapon'].matrix_local
                        row['jnt_offset'] = backup.matrix_world.inverted_safe() @ world @ rest.inverted_safe() @ backup.matrix_world @ backup.data.bones['jnt_offset'].matrix_local
                        camera_world = rig.matrix_world @ camera.matrix
                        camera_rest = rig.data.bones['Camera'].matrix_local
                        row['jnt_camera'] = (
                            backup.matrix_world.inverted_safe() @ camera_world @ camera_rest.inverted_safe()
                            @ backup.matrix_world @ camera_source.matrix_local
                        )
                        expected[frame] = row
                        evaluated = viewport_mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
                        to_source = backup.matrix_world.inverted() @ evaluated.matrix_world
                        expected_vertices[frame] = [
                            to_source @ evaluated.data.vertices[index].co for index, _co, _weights in vertices
                        ]
                    bpy.context.scene.frame_set(last, subframe=.375)
                    _written, failures = ex.run_exports(
                        bpy.context, rig, backup, [(action, slot, outputs)])
                    assert bpy.context.scene.frame_current == last and bpy.context.scene.frame_subframe == .375
                assert not failures, failures
                objects, actions, player, _clip = ex.importer._import_fbx(outputs[0][2])
                try:
                    max_position = max_angle = key_angle = max_vertex = 0.0
                    for frame in frames:
                        bpy.context.scene.frame_set(frame - first + 1)
                        bpy.context.view_layer.update()
                        worlds = engine_worlds(player)
                        for name, desired in socket_poses[frame].items():
                            actual = worlds[name]
                            assert (actual.translation - desired.translation).length < 0.001, (frame, name)
                            angle = angular_error(actual.to_quaternion(), desired.to_quaternion())
                            assert angle < 0.002, (frame, name, math.degrees(angle))
                        for name, desired in expected[frame].items():
                            if name not in checked_names:
                                continue
                            actual = worlds[name]
                            position = (actual.translation - desired.translation).length
                            max_position = max(max_position, position)
                            if name in ex.TWIST_LOCKED_CHAIN:
                                continue
                            angle = angular_error(actual.to_quaternion(), desired.to_quaternion())
                            max_angle = max(max_angle, angle)
                            if name in ('jnt_l_hand', 'jnt_r_hand') or name.startswith(
                                    ('jnt_l_hand_index_', 'jnt_r_hand_index_')):
                                key_angle = max(key_angle, angle)
                        skin = {
                            name: worlds[name] @ backup.data.bones[name].matrix_local.inverted()
                            for name in expected[frame] if name in worlds
                        }
                        for (_index, vertex, weights), desired_vertex in zip(vertices, expected_vertices[frame]):
                            actual_vertex = Vector((0, 0, 0))
                            total = 0.0
                            for name, weight in weights:
                                assert name in skin, name
                                actual_vertex += weight * (skin[name] @ vertex)
                                total += weight
                            if total:
                                error = (desired_vertex - actual_vertex / total).length
                                if error > max_vertex:
                                    max_vertex = error
                                    worst = (frame, _index, tuple(desired_vertex), tuple(actual_vertex / total), weights)
                    print(f'IK_FK={mode}: position={max_position:.6f} cm, '
                          f'angle={math.degrees(max_angle):.6f} deg, '
                          f'wrist/index angle={math.degrees(key_angle):.6f} deg, '
                          f'{len(vertices)} weighted vertices={max_vertex:.6f} cm', flush=True)
                    print('WORST', worst, flush=True)
                    assert max_position < 0.001, max_position
                    assert key_angle < 0.002, key_angle
                    # Nonuniform inherited scale can create shear that FBX TRS cannot represent exactly.
                    assert max_angle < 0.01, max_angle
                    assert max_vertex < 0.05, max_vertex
                    max_socket = 0.0
                    for step in range((last - first) * ex.BAKE_SUBSTEPS + 1):
                        frame = first + step / ex.BAKE_SUBSTEPS
                        exported_frame = frame - first + 1
                        bpy.context.scene.frame_set(math.floor(exported_frame),
                                                    subframe=exported_frame - math.floor(exported_frame))
                        bpy.context.view_layer.update()
                        worlds = engine_worlds(player)
                        lower, upper = math.floor(frame), math.ceil(frame)
                        for name, a in socket_poses[lower].items():
                            b = socket_poses[upper][name]
                            desired = a.translation.lerp(b.translation, frame - lower)
                            max_socket = max(max_socket, (worlds[name].translation - desired).length)
                    print(f'  subframe runtime sockets: {max_socket:.6f} cm', flush=True)
                    assert max_socket < 0.003, max_socket
                finally:
                    ex.importer._remove_imported(objects, actions)
                objects, actions, weapon, _clip = ex.importer._import_fbx(outputs[1][2])
                try:
                    weapon_position = weapon_angle = 0.0
                    for frame in frames:
                        bpy.context.scene.frame_set(frame - first + 1)
                        bpy.context.view_layer.update()
                        worlds = engine_worlds(weapon)
                        for name in ('jnt_offset', 'jnt_l_hand'):
                            desired = expected[frame][name]
                            actual = weapon.matrix_world @ worlds[name]
                            weapon_position = max(weapon_position, (actual.translation - desired.translation).length)
                            weapon_angle = max(weapon_angle, angular_error(actual.to_quaternion(), desired.to_quaternion()))
                    print(f'  weapon root/wrist: {weapon_position:.6f} cm, '
                          f'{math.degrees(weapon_angle):.6f} deg', flush=True)
                    assert weapon_position < 0.001, weapon_position
                    assert weapon_angle < 0.002, weapon_angle
                finally:
                    ex.importer._remove_imported(objects, actions)
    finally:
        for curve, muted in saved_mutes:
            curve.mute = muted
        parent['IK_FK'] = saved_ik
    print('PASS: all frames, FK / blended / IK hand and finger FBX round-trips')


if __name__ == '__main__':
    main()
