import os
import re

import bmesh
import bpy

WEAPON_COLLECTION = 'Weapon'
WORLD_PREFIX = 'world:'
UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\s]')


def weapon_bone_joints(rig, mapping):
    """Return {rig weapon bone: game joint name} for every mapped weapon bone."""
    collection = rig.data.collections.get(WEAPON_COLLECTION)
    weapon_bones = {bone.name for bone in collection.bones} if collection else set()
    weapon_bones.add('Weapon')
    return {
        target: source
        for target, source, _kind in mapping
        if target in weapon_bones and target in rig.data.bones
    }


def static_mesh_stem(weapon_name, joint_name):
    part = joint_name[4:] if joint_name.startswith('jnt_') else joint_name
    return f'SM_wpn_{weapon_name}_SM_{part}'


def static_mesh_folder(output_root, category, weapon_name):
    return os.path.join(output_root, '_Stalker_2', 'weapons', category, f'p_{weapon_name}', 'AnimMesh')


def validate_names(weapon_name, category):
    if not weapon_name or UNSAFE_NAME.search(weapon_name):
        raise ValueError(
            f'"{weapon_name}" is not a usable weapon name; rename the main weapon mesh object '
            '(it supplies the weapon name in the static mesh file names).')
    parts = [part for part in re.split(r'[\\/]+', category) if part]
    if not parts or any(UNSAFE_NAME.search(part) for part in parts):
        raise ValueError('Enter a valid weapon category folder, for example "pistol".')
    return os.path.join(*parts)


def weapon_meshes(rig, scene):
    result = []
    for obj in scene.objects:
        if obj.type != 'MESH' or not obj.vertex_groups:
            continue
        bound = obj.parent == rig or any(
            modifier.type == 'ARMATURE' and modifier.object == rig for modifier in obj.modifiers)
        if bound:
            result.append(obj)
    return result


def split_by_bone(rig, backup, obj, bone_joints):
    """Split obj into one rest-pose mesh per weapon bone, positioned relative to the
    bone head in the game skeleton's units. Returns {bone name: (bmesh, materials)}."""
    group_bone = {group.index: group.name for group in obj.vertex_groups if group.name in bone_joints}
    if not group_bone:
        return {}

    source = bmesh.new()
    source.from_mesh(obj.data)
    deform = source.verts.layers.deform.active
    if deform is None:
        source.free()
        return {}

    owner = {}
    for face in source.faces:
        totals = {}
        for vert in face.verts:
            for group_index, weight in vert[deform].items():
                name = group_bone.get(group_index)
                if name:
                    totals[name] = totals.get(name, 0.0) + weight
        if totals:
            owner[face.index] = max(totals, key=totals.get)

    to_source_units = backup.matrix_world.to_3x3().inverted_safe()
    object_matrix = obj.matrix_world
    parts = {}
    for bone_name in sorted(set(owner.values())):
        part = source.copy()
        part.faces.ensure_lookup_table()
        unwanted = [face for face in part.faces if owner.get(face.index) != bone_name]
        bmesh.ops.delete(part, geom=unwanted, context='FACES')

        head_world = rig.matrix_world @ rig.data.bones[bone_name].head_local
        for vert in part.verts:
            vert.co = to_source_units @ (object_matrix @ vert.co - head_world)

        deform_layer = part.verts.layers.deform.active
        if deform_layer is not None:
            part.verts.layers.deform.remove(deform_layer)

        used = sorted({face.material_index for face in part.faces})
        remap = {index: new for new, index in enumerate(used)}
        for face in part.faces:
            face.material_index = remap[face.material_index]
        materials = [
            obj.material_slots[index].material if index < len(obj.material_slots) else None
            for index in used
        ]
        parts[bone_name] = (part, materials)
    source.free()
    return parts


def weighted_bones(obj, bone_joints):
    """Return {mapped weapon bone: summed vertex weight} for a mesh object."""
    names = {group.index: group.name for group in obj.vertex_groups if group.name in bone_joints}
    totals = {}
    for vert in obj.data.vertices:
        for assignment in vert.groups:
            name = names.get(assignment.group)
            if name and assignment.weight > 0:
                totals[name] = totals.get(name, 0.0) + assignment.weight
    return totals


def classify_meshes(rig, scene, bone_joints):
    """Return (main object, {bone: weight} of main, [(other object, {bone: weight})]).

    The main weapon mesh is the one weighted to the most weapon bones (ties: most faces);
    it is split per bone. Every other bound mesh is exported whole."""
    weighted = [(obj, weighted_bones(obj, bone_joints)) for obj in weapon_meshes(rig, scene)]
    weighted = [item for item in weighted if item[1]]
    if not weighted:
        return None, {}, []
    weighted.sort(key=lambda item: (len(item[1]), len(item[0].data.polygons)), reverse=True)
    main, main_bones = weighted[0]
    return main, main_bones, weighted[1:]


def extract_whole(rig, backup, obj, bone_name):
    """Return (bmesh, materials) of the entire mesh, positioned relative to bone_name's head."""
    part = bmesh.new()
    part.from_mesh(obj.data)
    head_world = rig.matrix_world @ rig.data.bones[bone_name].head_local
    to_source_units = backup.matrix_world.to_3x3().inverted_safe()
    for vert in part.verts:
        vert.co = to_source_units @ (obj.matrix_world @ vert.co - head_world)
    deform_layer = part.verts.layers.deform.active
    if deform_layer is not None:
        part.verts.layers.deform.remove(deform_layer)
    return part, [slot.material for slot in obj.material_slots]


def plan_static_meshes(rig, bone_joints, category, output_root, scene):
    """Return (weapon name, [(label, stem, path)]) for the meshes that would be written."""
    main, main_bones, others = classify_meshes(rig, scene, bone_joints)
    if main is None:
        raise ValueError('No weapon mesh is weighted to the mapped weapon bones.')
    weapon_name = main.name
    folder = static_mesh_folder(output_root, validate_names(weapon_name, category), weapon_name)
    plan = []
    for bone_name in sorted(main_bones, key=lambda name: bone_joints[name]):
        stem = static_mesh_stem(weapon_name, bone_joints[bone_name])
        plan.append((bone_name, stem, os.path.join(folder, stem + '.FBX')))
    for obj, _bones in sorted(others, key=lambda item: item[0].name):
        if UNSAFE_NAME.search(obj.name):
            raise ValueError(f'Mesh object name "{obj.name}" contains characters that are not allowed in a file name.')
        stem = f'SM_wpn_{weapon_name}_SM_{obj.name}'
        plan.append((obj.name, stem, os.path.join(folder, stem + '.FBX')))
    world_folder = os.path.dirname(folder)
    for obj in [main] + [obj for obj, _bones in sorted(others, key=lambda item: item[0].name)]:
        stem = f'SM_{weapon_name}' if obj is main else f'SM_{weapon_name}_{obj.name}'
        plan.append((WORLD_PREFIX + obj.name, stem, os.path.join(world_folder, stem + '.FBX')))
    stems = [stem for _label, stem, _path in plan]
    duplicates = sorted({stem for stem in stems if stems.count(stem) > 1})
    if duplicates:
        raise ValueError(f'These static mesh names would collide: {", ".join(duplicates)}.')
    return weapon_name, plan


def export_static_meshes(context, rig, backup, bone_joints, category, output_root):
    """Write the weapon static meshes. Returns (written paths, labels skipped for lack of geometry)."""
    scene = context.scene
    _name, plan = plan_static_meshes(rig, bone_joints, category, output_root, scene)
    targets = {label: (stem, path) for label, stem, path in plan}
    main, main_bones, others = classify_meshes(rig, scene, bone_joints)

    saved_scale = scene.unit_settings.scale_length
    active = context.view_layer.objects.active
    selected = [obj for obj in scene.objects if obj.select_get()]
    jobs = []
    for bone_name, (part, materials) in split_by_bone(rig, backup, main, bone_joints).items():
        jobs.append((bone_name, [(part, materials, main)]))
    for obj, bones in others:
        dominant = max(bones, key=bones.get)
        part, materials = extract_whole(rig, backup, obj, dominant)
        jobs.append((obj.name, [(part, materials, obj)]))
    root_bone = 'Weapon' if 'Weapon' in rig.data.bones else max(main_bones, key=main_bones.get)
    for obj in [main] + [obj for obj, _bones in others]:
        part, materials = extract_whole(rig, backup, obj, root_bone)
        jobs.append((WORLD_PREFIX + obj.name, [(part, materials, obj)]))

    written = []
    temporaries = []
    try:
        scene.unit_settings.scale_length = 1.0
        for label, pieces in jobs:
            stem, path = targets[label]
            temp = create_part_object(context, stem, pieces)
            temporaries.append(temp)
            write_static_mesh(context, temp, path)
            written.append(path)
    finally:
        for _label, pieces in jobs:
            for piece, _materials, _obj in pieces:
                piece.free()
        for temp in temporaries:
            mesh = temp.data
            bpy.data.objects.remove(temp)
            bpy.data.meshes.remove(mesh)
        scene.unit_settings.scale_length = saved_scale
        for obj in scene.objects:
            obj.select_set(obj in selected)
        context.view_layer.objects.active = active
    skipped = sorted(set(targets) - {label for label, _pieces in jobs})
    return written, skipped


def create_part_object(context, stem, pieces):
    """Build a temporary object from the pieces of one bone, linked into the scene."""
    mesh = bpy.data.meshes.new(stem)
    merged = bmesh.new()
    materials = []
    for piece, piece_materials, _obj in pieces:
        offset = len(materials)
        materials.extend(piece_materials)
        piece_mesh = bpy.data.meshes.new(stem + '_piece')
        piece.to_mesh(piece_mesh)
        for face in piece_mesh.polygons:
            face.material_index += offset
        merged.from_mesh(piece_mesh)
        bpy.data.meshes.remove(piece_mesh)
    merged.to_mesh(mesh)
    merged.free()
    for material in materials:
        mesh.materials.append(material)

    obj = bpy.data.objects.new(stem, mesh)
    context.scene.collection.objects.link(obj)
    for modifier in pieces[0][2].modifiers:
        if modifier.type == 'EDGE_SPLIT':
            copy = obj.modifiers.new(modifier.name, 'EDGE_SPLIT')
            copy.use_edge_angle = modifier.use_edge_angle
            copy.split_angle = modifier.split_angle
            copy.use_edge_sharp = modifier.use_edge_sharp
    return obj


def write_static_mesh(context, obj, filepath):
    for other in context.scene.objects:
        other.select_set(other == obj)
    context.view_layer.objects.active = obj
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    partial = os.path.splitext(filepath)[0] + '.partial.fbx'
    try:
        bpy.ops.export_scene.fbx(
            filepath=partial,
            use_selection=True,
            object_types={'MESH'},
            use_mesh_modifiers=True,
            mesh_smooth_type='FACE',
            add_leaf_bones=False,
            bake_anim=False,
            axis_forward='Y',
            axis_up='Z',
            global_scale=0.01,
            apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_NONE',
            path_mode='AUTO',
        )
        os.replace(partial, filepath)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
