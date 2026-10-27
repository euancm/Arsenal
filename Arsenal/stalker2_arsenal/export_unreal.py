import json
import os
import re
import shutil

import bpy

from . import export_animation as animation_export
from . import export_skeleton
from . import export_static_mesh as static_mesh

PARENT_MATERIAL = '/Game/_Stalker_2/Materials/Instance/MI_PBR_Weapons'
PHYSICAL_MATERIAL = '/Game/_Stalker_2/Materials/PhysMat/Common/PM_MetalSolid'
MANIFEST_VERSION = 1
TEMPLATE_NAME = 'unreal_import.py'
TEXTURE_PARAMETERS = {'D': 'Diffuse_VT', 'N': 'Normal_VT', 'RMA': 'RMAE_VT'}
KIND_SUFFIX = re.compile(r'_(D|N|RMA)$', re.IGNORECASE)
GAME_TEXTURE_PREFIX = 'T_'
UNREAL_PATH = re.compile(r'^/[A-Za-z0-9_\-/]+$')


def clean_material_name(name):
    return re.sub(r'\.\d{3}$', '', name)


def image_kind(node):
    """Return 'D', 'N' or 'RMA' for an image texture node, or None."""
    stem = os.path.splitext(node.image.name)[0]
    match = KIND_SUFFIX.search(stem)
    if match:
        return match.group(1).upper()
    for output in node.outputs:
        for link in output.links:
            if link.to_socket.name == 'Base Color':
                return 'D'
            if link.to_node.type == 'NORMAL_MAP':
                return 'N'
    return None


def material_images(material):
    images = {}
    if material and material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                kind = image_kind(node)
                if kind and kind not in images:
                    images[kind] = node.image
    return images


def collect_materials(objects):
    """Return ({material name: (material, {kind: image})}, [names left to the game's own materials])."""
    managed = {}
    game = []
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            name = clean_material_name(material.name)
            if name in managed or name in game:
                continue
            images = material_images(material)
            stem = os.path.splitext(images['D'].name)[0] if 'D' in images else ''
            if 'D' not in images or stem.startswith(GAME_TEXTURE_PREFIX):
                game.append(name)
            else:
                managed[name] = (material, images)
    return managed, game


def write_texture(image, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    source = bpy.path.abspath(image.filepath) if image.source == 'FILE' and not image.packed_file else ''
    if source and os.path.isfile(source) and source.lower().endswith('.png'):
        shutil.copyfile(source, path)
        return
    if image.size[0] == 0 or image.size[1] == 0:
        raise RuntimeError(f'Image "{image.name}" has no pixel data (missing file?).')
    previous = image.file_format
    image.file_format = 'PNG'
    try:
        image.save(filepath=path)
    finally:
        image.file_format = previous


def relative(path, root):
    return os.path.relpath(path, root).replace(os.sep, '/')


def find_animation_files(output_root, weapon_name):
    found = {'player': [], 'weapon': []}
    wanted = weapon_name.casefold()
    for folder, _dirs, files in os.walk(output_root):
        parts = [part.casefold() for part in os.path.relpath(folder, output_root).split(os.sep)]
        if wanted not in parts or 'animations' not in parts:
            continue
        index = parts.index('animations')
        kind = {'player': 'player', 'weapons': 'weapon'}.get(parts[index + 1] if index + 1 < len(parts) else '')
        if not kind:
            continue
        for name in sorted(files):
            if name.lower().endswith('.fbx') and not name.lower().endswith('.partial.fbx'):
                found[kind].append(relative(os.path.join(folder, name), output_root))
    return found


def validated_unreal_path(value, label):
    if not UNREAL_PATH.match(value):
        if label == 'Mod Name':
            raise RuntimeError('Set the Mod Name (Export panel) to the name of your mod in ZoneKit, e.g. MonkeyMod.')
        raise RuntimeError(f'{label} must be an Unreal path such as /Game/..., not "{value}".')
    return value.rstrip('/')


def write_unreal_import(context):
    export = context.scene.arsenal_export
    rig, backup, bone_joints, plan = animation_export._build_static_plan(context)
    output_root = bpy.path.abspath(export.output_folder).strip()
    category = static_mesh.validate_names('x', export.static_category.strip())
    mesh_name, _plan = static_mesh.plan_static_meshes(rig, bone_joints, export.static_category.strip(), output_root, context.scene)
    animation_name = animation_export.weapon_name(context.scene)
    mount = validated_unreal_path(animation_export.mod_mount(export), 'Mod Name')

    static_files = [relative(path, output_root) for _label, _stem, path in plan if os.path.isfile(path)]
    if not static_files:
        raise RuntimeError('No static meshes found in the output folder; export them first.')
    animation_files = find_animation_files(output_root, animation_name)

    main, _bones, others = static_mesh.classify_meshes(rig, context.scene, bone_joints)
    managed, game = collect_materials([main] + [obj for obj, _bones in others])

    weapon_folder = os.path.join(output_root, '_Stalker_2', 'weapons', category, f'p_{mesh_name}')
    textures = []
    materials = []
    for name, (_material, images) in managed.items():
        entry = {'name': name, 'textures': {}}
        for kind, image in images.items():
            stem = os.path.splitext(image.name)[0]
            path = os.path.join(weapon_folder, 'Textures', stem + '.png')
            write_texture(image, path)
            if not any(texture['file'] == relative(path, output_root) for texture in textures):
                textures.append({'file': relative(path, output_root), 'kind': kind})
            entry['textures'][kind] = stem
        materials.append(entry)

    player_skeleton = f'{mount}/_STALKER2/SkeletalMeshes/SK_Stalker'
    skeletal_file = ''
    try:
        _donor, skeleton_path, _name = export_skeleton.plan_skeleton(context)
        if os.path.isfile(skeleton_path):
            skeletal_file = relative(skeleton_path, output_root)
    except (OSError, ValueError):
        pass
    if skeletal_file:
        weapon_skeleton = f'{mount}/{os.path.splitext(skeletal_file)[0]}'.replace('\\', '/')
    else:
        weapon_skeleton = f'{mount}/_STALKER2/SkeletalMeshes/weapons/pt/{animation_name}/SK_{animation_name}'

    localization = []
    magazines = []
    try:
        from . import weapon_cfg
        info = weapon_cfg.build_context(context)
        localization = weapon_cfg.localization_entries(info)
        magazines = [{'sid': f'Gun{info["weapon_id"]}_Mag{magazine["name"]}', 'name': magazine['name'],
                      'preinstalled': bool(magazine['preinstalled'])} for magazine in info['magazines']]
    except Exception as error:
        print(f'[Arsenal export] No localisation or magazines in the import script: {error}')

    manifest = {
        'version': MANIFEST_VERSION,
        'localization': localization,
        'magazines': magazines,
        'weapon': animation_name,
        'template_weapon': context.scene.stalker2_animation_importer.weapon_name.strip(),
        'replace_existing_assets': True,
        'mesh_name': mesh_name,
        'game_root': mount,
        'player_skeleton': validated_unreal_path(player_skeleton, 'Player Skeleton'),
        'weapon_skeleton': validated_unreal_path(weapon_skeleton, 'Weapon Skeleton'),
        'parent_material': PARENT_MATERIAL,
        'phys_material': PHYSICAL_MATERIAL,
        'material_folder': f'{mount}/_Stalker_2/weapons/{category.replace(os.sep, "/")}/p_{mesh_name}/Materials',
        'texture_parameters': TEXTURE_PARAMETERS,
        'animations': animation_files,
        'skeletal_mesh': skeletal_file,
        'static_meshes': static_files,
        'textures': textures,
        'materials': materials,
        'game_materials': game,
    }

    base = f'import_{animation_name}'
    manifest_path = os.path.join(output_root, base + '.json')
    script_path = os.path.join(output_root, base + '.py')
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2)
    template = os.path.join(os.path.dirname(__file__), TEMPLATE_NAME)
    with open(template, encoding='utf-8') as handle:
        script = handle.read()
    script = script.replace('BAKED_MANIFEST = None', f'BAKED_MANIFEST = {manifest_path!r}', 1)
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(script)
    return script_path, manifest


CLASSES = ()
