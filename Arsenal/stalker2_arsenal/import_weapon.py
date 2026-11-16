import json
import os
import re

import bpy
from mathutils import Matrix, Vector

from . import stalker2_animation_importer as importer
from .notifications import completion, report

RIG_MARKER = 'arsenal_weapon_rig'
SOCKET_FILE = 'weapon_sockets.json'
ROOT_BONE = 'Weapon'
ROOT_JOINT = 'jnt_offset'
# The character skeleton owns the hands; the weapon rig must not duplicate them.
CHARACTER_JOINTS = {'jnt_r_hand', 'jnt_l_hand'}
SHAPE_LIBRARY = os.path.join(os.path.dirname(__file__), 'shapes', 'weapon_bone_shapes.blend')
SHAPE_COLLECTION = 'Weapon Bone Shapes'

# Words that shape names are built from; used to split run-together names such as "magazinerelease".
SHAPE_VOCABULARY = {
    'magazine', 'release', 'slide', 'barrel', 'trigger', 'shell', 'bullet', 'base', 'safety', 'hammer',
    'lock', 'sight', 'stock', 'grip', 'bolt', 'rail', 'handle', 'lever', 'selector', 'charging', 'muzzle',
}
# Weapon class words select the donor family, not words in the bone name.
SHAPE_CLASS_WORDS = {'pistol', 'rifle', 'smg', 'shotgun', 'sniper'}
SHAPE_PREFIX = 'customboneshape_'
# Extra spellings of the same part, applied to bone names only (see mapping_editor for the shared ones).
SHAPE_BONE_SYNONYMS = {'tab': 'release', 'catch': 'release', 'button': 'release', 'hummer': 'hammer',
                       'cocking': 'charging'}
_shape_names = None
# Spare rounds that skeletal attachments store parked beside the launcher; the attachment's own
# animation brings one into the tube. Verified against native reference poses: only SK_gla parks
# rounds (10 cm sideways). Other launchers keep the round in the tube and belt boxes show bullets.
PARKED_ROUND_BONES = {'sk_gla': {'jnt_m406_charge', 'jnt_m406_shell', 'jnt_vog25_charge'}}


def rig_bone_name(joint):
    return ROOT_BONE if joint == ROOT_JOINT else joint


def available_shapes():
    """Names of every custom bone shape in the library (new shapes are picked up automatically)."""
    global _shape_names
    if _shape_names is None:
        with bpy.data.libraries.load(SHAPE_LIBRARY, link=False) as (source, _destination):
            _shape_names = sorted(name for name in source.objects if name.startswith(SHAPE_PREFIX))
    return _shape_names


def _split_word(word):
    if word in SHAPE_VOCABULARY or len(word) < 6:
        return [word]
    for index in range(3, len(word) - 2):
        if word[:index] in SHAPE_VOCABULARY and word[index:] in SHAPE_VOCABULARY:
            return [word[:index], word[index:]]
    return [word]


def shape_tokens(shape_name):
    """Meaningful words in a shape's name, as a set of normalised tokens."""
    from .mapping_editor import WEAPON_TOKEN_SYNONYMS
    tokens = set()
    for word in shape_name[len(SHAPE_PREFIX):].lower().split('_'):
        for part in _split_word(word):
            part = WEAPON_TOKEN_SYNONYMS.get(part, part)
            if part:
                tokens.add(part)
    return tokens


def bone_shape_tokens(bone_name):
    """Normalised words of a bone name, in order."""
    from .mapping_editor import WEAPON_IGNORED_TOKENS, WEAPON_TOKEN_SYNONYMS
    if bone_name == ROOT_BONE:
        return ['weapon', 'base']
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', bone_name)
    ordered = []
    for token in re.findall(r'[a-z]+|\d+', name.lower()):
        if token in WEAPON_IGNORED_TOKENS:
            continue
        token = WEAPON_TOKEN_SYNONYMS.get(token, token)
        token = SHAPE_BONE_SYNONYMS.get(token, token)
        if token and token not in ordered:
            ordered.append(token)
    return ordered


def shape_for_bone(bone_name, shape_names=None, *, weapon_class=None):
    """Pick the library shape whose name words are all found in the bone name.

    The shape needing the most words wins, so "magazine_tab" (magazine + release) gets the magazine
    release shape rather than the plain magazine. On a tie the word later in the bone name wins
    ("bullet_shell" is a shell). Returns None when nothing fits.
    """
    ordered = bone_shape_tokens(bone_name)
    tokens = set(ordered)
    best, best_score = None, (0, 0, -1)
    for shape in (available_shapes() if shape_names is None else shape_names):
        words = shape_tokens(shape)
        classes = words & SHAPE_CLASS_WORDS
        if weapon_class is not None and classes and weapon_class not in classes:
            continue
        required = words - SHAPE_CLASS_WORDS
        if required == {'base'} and bone_name != ROOT_BONE:
            continue
        if required and required <= tokens:
            score = (len(required), bool(classes), max(ordered.index(token) for token in required))
            if score > best_score:
                best, best_score = shape, score
    return best


def _walk_find(root, matcher):
    for directory, _folders, filenames in os.walk(root):
        for filename in sorted(filenames):
            if matcher(directory, filename):
                yield os.path.join(directory, filename)


def find_donor_files(root, weapon_name):
    """Locate the donor skeletal mesh and AnimMesh parts below the exported-files folder."""
    name = (weapon_name or '').strip()
    if not name:
        raise ValueError('Enter the weapon name (for example UDP) first')
    if not root or not os.path.isdir(root):
        raise FileNotFoundError('Choose the Exported Files folder (containing _STALKER2 and _Stalker_2) first')
    skeleton_name = f'sk_{name}.fbx'.casefold()
    from .weapon_presets import PRESETS
    tokens = next((preset['part_tokens'] for preset in PRESETS.values()
                   if preset['mesh'].casefold() == name.casefold()), [name])
    part_names = '|'.join(re.escape(token) for token in {name, *tokens})
    part_pattern = re.compile(
        rf'sm_(?!amm_)(?:wpn_)?(?:[a-z0-9]+_)*?(?:{part_names})_sm_(.+)\.fbx', re.IGNORECASE)

    skeletons = list(_walk_find(root, lambda _d, f: f.casefold() == skeleton_name))
    if not skeletons:
        raise FileNotFoundError(f'Could not find SK_{name}.FBX below {root}')
    parts = list(_walk_find(
        root,
        lambda d, f: os.path.basename(d).casefold() == 'animmesh' and part_pattern.fullmatch(f)))
    if not parts:
        raise FileNotFoundError(f'Could not find any AnimMesh/SM_*_{name}_SM_*.FBX files below {root}')
    return skeletons[0], [(path, part_pattern.fullmatch(os.path.basename(path)).group(1)) for path in parts]


def _uv_island_edges(mesh):
    """Indices of the edges that lie on a UV island boundary."""
    layer = mesh.uv_layers.active
    if layer is None:
        return []
    corners = {}
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            loop = mesh.loops[loop_index]
            corners.setdefault((loop.edge_index, loop.vertex_index), set()).add(
                tuple(round(c, 5) for c in layer.data[loop_index].uv))
    edges = []
    for edge in mesh.edges:
        a = corners.get((edge.index, edge.vertices[0]), ())
        b = corners.get((edge.index, edge.vertices[1]), ())
        if len(a) > 1 or len(b) > 1:
            edges.append(edge.index)
    return edges


def fix_smoothing(obj):
    """Smooth shading with the original hard edges.

    The FBX's custom normals are only used to find the hard edges (kept as Sharp Edge marks) and are then
    dropped so the mesh stays editable. Without any, the edges on UV island boundaries are marked sharp."""
    mesh = obj.data
    has_sharp = False
    attribute = mesh.attributes.get('sharp_edge')
    if attribute is not None:
        has_sharp = any(item.value for item in attribute.data)
    if mesh.has_custom_normals:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    if not has_sharp:
        for index in _uv_island_edges(mesh):
            mesh.edges[index].use_edge_sharp = True


def _import(filepath):
    existing = {obj.as_pointer() for obj in bpy.data.objects}
    units = bpy.context.scene.unit_settings
    saved_scale = units.scale_length
    units.scale_length = 1.0
    try:
        bpy.ops.import_scene.fbx(filepath=filepath, global_scale=100.0, use_custom_normals=True)
    finally:
        units.scale_length = saved_scale
    created = [obj for obj in bpy.data.objects if obj.as_pointer() not in existing]
    for obj in created:
        if obj.type == 'MESH':
            fix_smoothing(obj)
    return created


def _select_only(context, objects, active):
    context.view_layer.update()
    for obj in list(context.view_layer.objects):
        if obj is not None:
            obj.select_set(False)
    for obj in objects:
        if obj is not None:
            obj.select_set(True)
    context.view_layer.objects.active = active


def _import_skeleton(context, path, display_name):
    objects = _import(path)
    rig = next((obj for obj in objects if obj.type == 'ARMATURE'), None)
    if rig is None:
        importer._remove_imported(objects, [])
        raise RuntimeError(f'{os.path.basename(path)} contains no armature')
    world = rig.matrix_world.copy()
    rig.parent = None
    rig.matrix_world = world
    importer._remove_imported([obj for obj in objects if obj != rig], [])

    _select_only(context, [rig], rig)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    rig['arsenal_component_root'] = re.sub(r'\.\d{3,}$', '', rig.name)
    rig.name = ROOT_BONE
    rig.data.name = f'{display_name} Weapon Rig'
    rig[RIG_MARKER] = True
    rig['arsenal_donor_mesh_name'] = display_name

    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit_bones = rig.data.edit_bones
        for joint in CHARACTER_JOINTS:
            bone = edit_bones.get(joint)
            if bone:
                edit_bones.remove(bone)
        root = edit_bones.get(ROOT_JOINT)
        if root is None:
            raise RuntimeError(f'{os.path.basename(path)} has no {ROOT_JOINT} bone')
        root.name = ROOT_BONE
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def _import_parts(context, rig, parts, weapon_name):
    """Import every AnimMesh part, move it from bone space to rig space and weight it to its bone."""
    imported = []
    skipped = []
    for path, part in parts:
        bone_name = rig_bone_name(f'jnt_{part}')
        bone = rig.data.bones.get(bone_name)
        objects = _import(path)
        meshes = [obj for obj in objects if obj.type == 'MESH']
        importer._remove_imported([obj for obj in objects if obj.type != 'MESH'], [])
        if bone is None or not meshes:
            importer._remove_imported(meshes, [])
            skipped.append(part)
            continue
        offset = Matrix.Translation(rig.matrix_world @ bone.head_local)
        for obj in meshes:
            for slot in obj.material_slots:
                material = slot.material
                base = bpy.data.materials.get(re.sub(r'\.\d{3}$', '', material.name)) if material else None
                if base is not None and base is not material:
                    slot.material = base
            obj.data.transform(offset @ obj.matrix_world)
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            group = obj.vertex_groups.new(name=bone_name)
            group.add([vertex.index for vertex in obj.data.vertices], 1.0, 'REPLACE')
            obj[RIG_MARKER] = bone_name
            imported.append(obj)

    if not imported:
        return None, {}, skipped
    bounds = {}
    for obj in imported:
        coords = [vertex.co for vertex in obj.data.vertices]
        if coords:
            bounds[obj[RIG_MARKER]] = (
                Vector([min(c[i] for c in coords) for i in range(3)]),
                Vector([max(c[i] for c in coords) for i in range(3)]))
        del obj[RIG_MARKER]

    main = max(imported, key=lambda obj: len(obj.data.vertices))
    _select_only(context, imported, main)
    if len(imported) > 1:
        bpy.ops.object.join()
    main.name = weapon_name
    main.data.name = weapon_name
    main.parent = rig
    main.matrix_parent_inverse = rig.matrix_world.inverted()
    modifier = main.modifiers.new('Armature', 'ARMATURE')
    modifier.object = rig
    return main, bounds, skipped


def _load_shapes(names):
    missing = [name for name in names if name not in bpy.data.objects]
    if missing:
        with bpy.data.libraries.load(SHAPE_LIBRARY, link=False) as (source, destination):
            destination.objects = [name for name in missing if name in source.objects]
    collection = bpy.data.collections.get(SHAPE_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(SHAPE_COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    collection.hide_viewport = True
    collection.hide_render = True
    shapes = {}
    for name in names:
        shape = bpy.data.objects.get(name)
        if shape is None:
            continue
        if shape.name not in collection.objects:
            collection.objects.link(shape)
        shapes[name] = shape
    return shapes


def _mesh_bounds(shape):
    coords = [vertex.co for vertex in shape.data.vertices]
    return (Vector([min(c[i] for c in coords) for i in range(3)]),
            Vector([max(c[i] for c in coords) for i in range(3)]))


def apply_bone_shapes(rig, bounds):
    """Fit a library shape to each bone's geometry (translation, rotation and scale)."""
    from .weapon_presets import PRESETS
    category = next((preset['category'] for preset in PRESETS.values()
                     if preset['mesh'].casefold() == rig.get('arsenal_donor_mesh_name', '').casefold()), '')
    weapon_class = {'pistol_mashine_gun': 'smg', 'sturm_riffle': 'rifle',
                    'sniper_riffle': 'sniper', 'DMR': 'sniper'}.get(category, category)
    wanted = {bone.name: shape_for_bone(bone.name, weapon_class=weapon_class) for bone in rig.data.bones}
    shapes = _load_shapes(sorted({name for name in wanted.values() if name}))
    collection = rig.data.collections.get(ROOT_BONE) or rig.data.collections.new(ROOT_BONE)
    for pose_bone in rig.pose.bones:
        pose_bone.color.palette = 'THEME01'
        pose_bone.bone.color.palette = 'THEME01'
        collection.assign(pose_bone.bone)
        shape = shapes.get(wanted.get(pose_bone.name))
        if shape is None:
            continue
        shape_min, shape_max = _mesh_bounds(shape)
        shape_size = shape_max - shape_min
        shape_center = (shape_min + shape_max) / 2
        if pose_bone.name in bounds:
            low, high = bounds[pose_bone.name]
            center = (low + high) / 2
            size = high - low
            scale = Vector([
                size[i] / shape_size[i] if shape_size[i] > 1e-6 and size[i] > 1e-4 else 1.0
                for i in range(3)])
        else:
            center = rig.matrix_world @ pose_bone.bone.head_local
            scale = Vector((1.0, 1.0, 1.0))
        fit = (Matrix.Translation(center)
               @ Matrix.Diagonal(scale.to_4d())
               @ Matrix.Translation(-shape_center))
        local = (rig.matrix_world @ pose_bone.bone.matrix_local).inverted() @ fit
        location, rotation, scale = local.decompose()
        pose_bone.custom_shape = shape
        pose_bone.use_custom_shape_bone_size = False
        pose_bone.custom_shape_translation = location
        pose_bone.custom_shape_rotation_euler = rotation.to_euler()
        pose_bone.custom_shape_scale_xyz = scale


def add_missing_weapon_bones(context, master):
    """Give the character skeleton a static bone for every weapon-rig bone it lacks (for example
    jnt_bullet_shell, which no animation drives) so the whole rig can be mapped one to one."""
    rigs = [obj for obj in context.scene.objects if obj.type == 'ARMATURE' and obj.get(RIG_MARKER) is True]
    if not rigs or master.data.bones.get(ROOT_JOINT) is None:
        return []
    rig = rigs[0]
    missing = [bone for bone in rig.data.bones if bone.name != ROOT_BONE and bone.name not in master.data.bones]
    if not missing:
        return []
    root_head = rig.matrix_world @ rig.data.bones[ROOT_BONE].head_local
    socket_head = master.matrix_world @ master.data.bones[ROOT_JOINT].head_local
    shift = socket_head - root_head
    to_master = master.matrix_world.inverted()

    _select_only(context, [master], master)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit_bones = master.data.edit_bones
        for bone in missing:
            new = edit_bones.new(bone.name)
            new.head = to_master @ (rig.matrix_world @ bone.head_local + shift)
            new.tail = to_master @ (rig.matrix_world @ bone.tail_local + shift)
            new.use_deform = False
        for bone in missing:
            parent = bone.parent.name if bone.parent else ROOT_BONE
            edit_bones[bone.name].parent = edit_bones.get(rig_joint_name(parent))
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return [bone.name for bone in missing]


def rig_joint_name(bone_name):
    return ROOT_JOINT if bone_name == ROOT_BONE else bone_name


def donor_mesh_name(settings):
    """The name in the template's skeletal and static mesh files (SK_<name>); usually the animation name."""
    return (settings.mesh_name or settings.weapon_name or '').strip()


def find_attachment_files(root, weapon_name):
    """Only the current donor's configured magazines and compatible attachments."""
    from .weapon_presets import PRESETS
    preset = next((preset for preset in PRESETS.values()
                   if preset['mesh'].casefold() == weapon_name.casefold()), None)
    if preset is None:
        raise ValueError(f'No attachment catalogue for donor {weapon_name}; choose a supported weapon template.')
    paths = [os.path.join(root, *entry['mesh'].split('/')[2:]) + '.fbx'
             for entry in preset['attachment_mounts']]
    missing = [os.path.basename(path) for path in paths if not os.path.isfile(path)]
    if missing:
        raise FileNotFoundError(f'Missing configured attachments for {weapon_name}: {", ".join(missing)}. '
                                'Regenerate and run the ZoneKit setup script for this template.')
    return sorted(paths)


def _attachment_bone(rig, filename):
    """Fallback bone for legacy exports without a named attachment mount."""
    if 'mag' in filename.casefold():
        for name in ('jnt_magazine', 'jnt_clip_base'):
            bone = rig.data.bones.get(name)
            if bone:
                return bone
    return rig.data.bones.get(ROOT_BONE)


def _attachment_placement(rig, root, filename):
    """Resolve the CFG mount and its full donor reference transform, not the FBX bone display axes."""
    from . import weapon_sockets
    from .weapon_presets import PRESETS

    lowered = os.path.splitext(filename)[0].casefold()
    preset = next((preset for preset in PRESETS.values()
                   if preset['mesh'].casefold() == rig.get('arsenal_donor_mesh_name', '').casefold()), None)
    if preset is not None:
        mount = next((entry for entry in preset['attachment_mounts']
                      if entry['mesh'].rsplit('/', 1)[-1].casefold() == lowered), None)
        if mount is None:
            raise RuntimeError(f'{filename} is not an attachment of the imported donor.')
        socket_name = mount['socket']
        bone = rig.data.bones.get(rig_bone_name(socket_name))
        if bone is not None:
            return bone, Matrix.Translation(rig.matrix_world @ bone.head_local)
    else:
        socket_name = ('LaserSocket' if 'laser' in lowered else
                       'SilencerMuzzleSocket' if 'silen' in lowered else '')

    bone = _attachment_bone(rig, filename)
    path = os.path.join(root, SOCKET_FILE)
    if not socket_name:
        if bone is None:
            raise RuntimeError(f'Cannot identify an attachment bone for {filename}.')
        return bone, Matrix.Translation(rig.matrix_world @ bone.head_local)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Missing {SOCKET_FILE} for {socket_name}. Regenerate and run the ZoneKit setup script.')
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        mesh = weapon_sockets.catalogue_mesh(path, donor_name=rig.get('arsenal_donor_mesh_name', ''))
        records = [entry for entry in mesh['sockets'] if entry['effective']]
    else:
        records = data
    matches = [entry for entry in records if entry['name'].casefold() == socket_name.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'Cannot identify socket {socket_name} for {filename}. '
                           'Regenerate and run the ZoneKit setup script for this donor.')
    record = matches[0]
    bone = rig.data.bones.get(weapon_sockets.bone_name(record['bone'], rig))
    if bone is None:
        raise RuntimeError(f'Socket {socket_name} has no imported bone {record["bone"]}.')
    if isinstance(data, dict):
        transform = rig.matrix_world @ weapon_sockets.reference_matrix(record) @ weapon_sockets.socket_matrix(record)
    else:
        x, y, z = record['location']
        transform = Matrix.Translation(rig.matrix_world @ bone.head_local + Vector((x, -y, z)))
    return bone, transform


def _socket_offset(rig, root, filename):
    return _attachment_placement(rig, root, filename)[1].translation


def _remove_parked_rounds(obj, filename):
    """Delete vertices mainly weighted to a parked spare-round bone, before weights are flattened."""
    parked = PARKED_ROUND_BONES.get(os.path.splitext(filename)[0].casefold())
    if not parked:
        return 0
    groups = {group.index for group in obj.vertex_groups if group.name.casefold() in parked}
    doomed = [vertex.index for vertex in obj.data.vertices
              if vertex.groups and max(vertex.groups, key=lambda entry: entry.weight).group in groups]
    if doomed:
        import bmesh
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        mesh.verts.ensure_lookup_table()
        bmesh.ops.delete(mesh, geom=[mesh.verts[index] for index in doomed], context='VERTS')
        mesh.to_mesh(obj.data)
        mesh.free()
        obj.data.update()
    return len(doomed)


def _import_attachments(context, rig, paths, root=''):
    """Import each attachment mesh weighted to one bone with an Armature modifier, like the weapon mesh."""
    from . import weapon_presets
    preset = next((value for value in weapon_presets.PRESETS.values()
                   if value['mesh'] == rig.get('arsenal_donor_mesh_name')), None)
    imported = []
    for path in paths:
        filename = os.path.basename(path)
        bone, offset = _attachment_placement(rig, root, filename)
        objects = _import(path)
        # Collision hulls (UCX_) and lower LODs come along in the FBX but are not part of the visible mesh.
        meshes = [obj for obj in objects if obj.type == 'MESH'
                  and not obj.name.upper().startswith(('UCX_', 'UBX_', 'USP_', 'UCP_'))
                  and not importer._is_lower_lod(obj.name)]
        context.view_layer.update()
        worlds = {obj: obj.matrix_world.copy() for obj in meshes}
        for obj in meshes:
            _remove_parked_rounds(obj, filename)
            obj.parent = None
            obj.vertex_groups.clear()
            for modifier in list(obj.modifiers):
                if modifier.type == 'ARMATURE':
                    obj.modifiers.remove(modifier)
        importer._remove_imported([obj for obj in objects if obj not in meshes], [])
        for obj in meshes:
            obj.data.transform(offset @ worlds[obj])
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            obj.name = obj.data.name = os.path.splitext(filename)[0]
            if bone is not None:
                group = obj.vertex_groups.new(name=bone.name)
                group.add([vertex.index for vertex in obj.data.vertices], 1.0, 'REPLACE')
            obj.parent = rig
            obj.matrix_parent_inverse = rig.matrix_world.inverted()
            modifier = obj.modifiers.new('Armature', 'ARMATURE')
            modifier.object = rig
            mount = next((item for item in preset['attachment_mounts']
                          if item['mesh'].rsplit('/', 1)[-1].casefold()
                          == os.path.splitext(filename)[0].casefold()), None) if preset else None
            marker = next((entry.marker for entry in context.scene.arsenal_sockets.entries
                           if mount and entry.socket_name == mount['socket']), None)
            if marker is not None:
                context.view_layer.update()
                from .weapon_sockets import parent_preview
                parent_preview(obj, marker, rig)
            imported.append(obj)
    return imported


def _is_rain_texture(parameter, relative):
    text = f'{parameter} {relative}'.casefold()
    return 'rain' in text


def _with_colour_fallback(root, textures):
    """Older setup exports can miss an inherited albedo; use the `_D` texture beside the `_N` one."""
    if any(word in f'{parameter} {relative}'.casefold() and 'rma' not in f'{parameter} {relative}'.casefold()
           for parameter, relative in textures.items()
           for word in ('basecolor', 'base_color', 'albedo', 'diffuse', 'color')):
        return textures
    for relative in textures.values():
        stem, extension = os.path.splitext(relative)
        if re.search(r'_N$', stem, re.IGNORECASE):
            candidate = stem[:-2] + '_D' + extension
            if os.path.isfile(os.path.join(root, *candidate.split('/'))):
                return dict(textures, Albedo=candidate)
    return textures


def apply_materials(root, objects, use_alpha=False):
    """Give the weapon's materials (named after the Unreal instances) their exported textures.

    use_alpha links the colour texture's alpha (the body's thread cards); weapon colour alphas can hold other data."""
    path = os.path.join(root, 'materials.json')
    if not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding='utf-8') as handle:
            table = json.load(handle)
    except (OSError, ValueError):
        return 0
    built = 0
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            textures = table.get(re.sub(r'\.\d{3}$', '', material.name)) if material else None
            if not textures or material.get('arsenal_textured'):
                continue
            textures = _with_colour_fallback(root, textures)
            material.use_nodes = True
            nodes, links = material.node_tree.nodes, material.node_tree.links
            bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is None:
                continue
            # The FBX importer adds a Normal Map node to every material; reuse it for the normal texture.
            normal = next((n for n in nodes if n.type == 'NORMAL_MAP'), None)
            row = 0
            for parameter, relative in sorted(textures.items()):
                image_path = os.path.join(root, *relative.split('/'))
                if _is_rain_texture(parameter, relative) or not os.path.isfile(image_path):
                    continue
                lowered = f'{parameter} {relative}'.casefold()
                is_normal = 'normal' in lowered or re.search(r'_n(\.|$)', relative.casefold()) is not None
                is_rma = 'rma' in lowered
                is_color = any(word in lowered for word in ('basecolor', 'base_color', 'albedo', 'diffuse', 'color'))
                if is_normal and normal is not None and normal.inputs['Color'].is_linked:
                    continue
                if is_color and not is_rma and bsdf.inputs['Base Color'].is_linked:
                    continue
                if not (is_normal or is_rma or is_color):
                    continue
                node = nodes.new('ShaderNodeTexImage')
                node.label = parameter
                node.location = (-700, -300 * row)
                row += 1
                node.image = bpy.data.images.load(image_path, check_existing=True)
                if is_normal:
                    node.image.colorspace_settings.name = 'Non-Color'
                    if normal is None:
                        normal = nodes.new('ShaderNodeNormalMap')
                    normal.convention = 'DIRECTX'
                    normal.location = (-350, node.location.y)
                    links.new(node.outputs['Color'], normal.inputs['Color'])
                    links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
                elif is_rma:
                    # Unreal packs Roughness / Metallic / AO into R / G / B; B is unused.
                    node.image.colorspace_settings.name = 'Non-Color'
                    split = nodes.new('ShaderNodeSeparateColor')
                    split.label = 'Split Colour'
                    split.location = (-400, node.location.y)
                    links.new(node.outputs['Color'], split.inputs['Color'])
                    links.new(split.outputs['Red'], bsdf.inputs['Roughness'])
                    links.new(split.outputs['Green'], bsdf.inputs['Metallic'])
                else:
                    links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
                    if use_alpha:
                        links.new(node.outputs['Alpha'], bsdf.inputs['Alpha'])
            # Drop the importer's Normal Map node when no normal texture used it.
            for node in [n for n in nodes if n.type == 'NORMAL_MAP']:
                if not node.outputs['Normal'].is_linked:
                    nodes.remove(node)
            material['arsenal_textured'] = True
            built += 1
    return built


def import_rigged_weapon(context, root, weapon_name):
    """Build the editable weapon rig and mesh from the donor weapon's exported files."""
    if any(obj.get(RIG_MARKER) is True for obj in context.scene.objects):
        raise RuntimeError('A weapon rig has already been imported; delete it first to import again')
    skeleton_path, parts = find_donor_files(root, weapon_name)
    name = weapon_name.strip()
    attachment_paths = find_attachment_files(root, name)

    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    rig = _import_skeleton(context, skeleton_path, name)
    main, bounds, skipped = _import_parts(context, rig, parts, name)
    apply_bone_shapes(rig, bounds)
    from . import weapon_sockets
    weapon_sockets.import_markers(context.scene, rig, root)
    attachments = _import_attachments(context, rig, attachment_paths, root)
    apply_materials(root, ([main] if main else []) + attachments)
    from . import weapon_cfg
    weapon_cfg.fill_magazine_list(context.scene.arsenal_cfg, [(obj, None) for obj in attachments])
    weapon_cfg.fill_attachment_list(context.scene.arsenal_cfg, rig, attachments)

    _select_only(context, [rig], rig)
    context.scene.arsenal_ui.weapon_rig = rig
    from . import inventory_images
    inventory_images.ensure_scene(context, context.scene)
    return rig, main, skipped


class STALKER2_OT_import_rigged_weapon(bpy.types.Operator):
    bl_idname = 'stalker2.import_rigged_weapon'
    bl_label = 'Import Rigged Weapon'
    bl_description = ('Build an editable weapon rig and mesh from the exported skeleton and AnimMesh files '
                      'of the weapon named above')
    bl_options = {'REGISTER', 'UNDO'}

    @completion('Weapon rig import')
    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            rig, main, skipped = import_rigged_weapon(context, root, donor_mesh_name(settings))
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        for part in skipped:
            report(self, {'WARNING'}, f'No bone for the part "{part}"; it was not imported')
        report(self, {'INFO'}, f'Imported weapon rig "{rig.name}" with {len(rig.data.bones)} bones'
                    + (f' and mesh "{main.name}"' if main else ''))
        return {'FINISHED'}


CLASSES = (STALKER2_OT_import_rigged_weapon,)
