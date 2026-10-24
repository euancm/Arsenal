import os
import re

import bpy

from . import import_weapon

SKELETON_FOLDER = '_STALKER2'


def skeleton_target(donor_path, donor_name, new_name, output_root):
    """Where SK_<new>.FBX goes: the donor's folders below _STALKER2 with the weapon name swapped."""
    parts = os.path.normpath(donor_path).split(os.sep)
    anchor = next((i for i, part in enumerate(parts) if part.casefold() == SKELETON_FOLDER.casefold()), None)
    if anchor is None:
        raise ValueError(f'{donor_path} is not inside a {SKELETON_FOLDER} folder')
    from .export_animation import rename_weapon_folders
    folders = rename_weapon_folders(parts[anchor:-1], donor_name, new_name)
    return os.path.join(output_root, *folders, f'SK_{new_name}.FBX')


def plan_skeleton(context):
    from . import export_animation as animation_export
    export = context.scene.arsenal_export
    settings = context.scene.stalker2_animation_importer
    donor_name = import_weapon.donor_mesh_name(settings)
    new_name = animation_export.weapon_name(context.scene)
    root = bpy.path.abspath(settings.animation_root).strip()
    output_root = bpy.path.abspath(export.output_folder).strip()
    donor_path, _parts = import_weapon.find_donor_files(root, donor_name)
    return donor_path, skeleton_target(donor_path, donor_name, new_name, output_root), new_name


def export_weapon_skeleton(context):
    """Write SK_<new weapon>.FBX: the donor skeleton and its placeholder mesh under the new name."""
    donor_path, target, new_name = plan_skeleton(context)
    scene = context.scene
    saved_scale = scene.unit_settings.scale_length
    active = context.view_layer.objects.active
    selected = [obj for obj in scene.objects if obj.select_get()]
    objects = import_weapon._import(donor_path)
    try:
        rigs = [obj for obj in objects if obj.type == 'ARMATURE']
        if len(rigs) != 1:
            raise RuntimeError(f'Expected one armature in {os.path.basename(donor_path)}')
        for obj in objects:
            if obj.type == 'ARMATURE':
                obj.name = obj.data.name = re.sub(r'(?i)^(jnt_wpn_).+$', lambda m: m.group(1) + new_name, obj.name)
            elif obj.type == 'MESH':
                obj.name = obj.data.name = f'SK_{new_name}_mesh'
            else:
                obj.name = f'SK_{new_name}'

        os.makedirs(os.path.dirname(target), exist_ok=True)
        partial = os.path.splitext(target)[0] + '.partial.fbx'
        for obj in scene.objects:
            obj.select_set(obj in objects)
        context.view_layer.objects.active = rigs[0]
        scene.unit_settings.scale_length = 1.0
        try:
            bpy.ops.export_scene.fbx(
                filepath=partial,
                use_selection=True,
                object_types={'EMPTY', 'ARMATURE', 'MESH'},
                mesh_smooth_type='FACE',
                bake_anim=False,
                add_leaf_bones=False,
                armature_nodetype='ROOT',
                primary_bone_axis='Y',
                secondary_bone_axis='X',
                axis_forward='Y',
                axis_up='Z',
                global_scale=0.01,
                apply_unit_scale=True,
                apply_scale_options='FBX_SCALE_NONE',
                path_mode='AUTO',
            )
            os.replace(partial, target)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    finally:
        scene.unit_settings.scale_length = saved_scale
        from . import stalker2_animation_importer as importer
        importer._remove_imported(objects, [])
        for obj in scene.objects:
            obj.select_set(obj in selected)
        context.view_layer.objects.active = active
    return target
