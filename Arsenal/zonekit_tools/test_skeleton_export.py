"""Blender regression test using a ZoneKit-exported donor SK_*.fbx.

blender --background --factory-startup --python-exit-code 1 --python test_skeleton_export.py -- <donor.fbx>
"""
import importlib
import os
import sys
import tempfile
import types

import bpy


def main():
    donor = os.path.abspath(sys.argv[sys.argv.index('--') + 1])
    package = types.ModuleType('arsenal_export_test')
    package.__path__ = [os.path.join(os.path.dirname(__file__), '..', 'stalker2_arsenal')]
    sys.modules[package.__name__] = package
    exporter = importlib.import_module(package.__name__ + '.export_skeleton')

    bpy.ops.wm.read_factory_settings(use_empty=True)
    objects = exporter.import_weapon._import(donor)
    rig = next(obj for obj in objects if obj.type == 'ARMATURE')
    root_name = rig.name
    hierarchy = {bone.name: bone.parent.name if bone.parent else None for bone in rig.data.bones}
    heads = {bone.name: bone.head_local.copy() for bone in rig.data.bones}
    world = rig.matrix_world.copy()
    exporter.import_weapon.importer._remove_imported(objects, [])

    clash = bpy.data.objects.new(root_name, None)
    bpy.context.scene.collection.objects.link(clash)
    clash.select_set(True)
    bpy.context.view_layer.objects.active = clash
    original_objects = set(bpy.data.objects)
    original_scale = bpy.context.scene.unit_settings.scale_length
    with tempfile.TemporaryDirectory(prefix='arsenal-skeleton-test-') as folder:
        target = os.path.join(folder, 'SK_regression.FBX')
        exporter.plan_skeleton = lambda context: (donor, target, 'regression')
        exporter.export_weapon_skeleton(bpy.context)
        assert set(bpy.data.objects) == original_objects
        assert clash.name == root_name
        assert clash.select_get()
        assert bpy.context.view_layer.objects.active == clash
        assert bpy.context.scene.unit_settings.scale_length == original_scale

        bpy.data.objects.remove(clash, do_unlink=True)
        objects = exporter.import_weapon._import(target)
        rigs = [obj for obj in objects if obj.type == 'ARMATURE']
        assert len(rigs) == 1
        rig = rigs[0]
        assert rig.name == root_name, rig.name
        assert rig.parent is None, rig.parent
        assert not any(obj.type == 'EMPTY' for obj in objects)
        actual = {bone.name: bone.parent.name if bone.parent else None for bone in rig.data.bones}
        assert actual == hierarchy, (actual, hierarchy)
        for bone in rig.data.bones:
            assert (bone.head_local - heads[bone.name]).length < 0.001, bone.name
        for row, expected in zip(rig.matrix_world, world):
            assert (row - expected).length < 0.001
        exporter.import_weapon.importer._remove_imported(objects, [])
    print(f'PASS: root {root_name}, {len(hierarchy)} bones, no wrapper; transforms and scene restored')


main()
