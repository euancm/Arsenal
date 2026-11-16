"""Project-owned inventory preview scenes and packed image renders."""
import functools
import json
import math
import os
import struct
import tempfile
from array import array

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from .notifications import report

RESOURCES = os.path.join(os.path.dirname(__file__), 'resources')
TEMPLATE = os.path.join(RESOURCES, 'inventory_scene.blend')
TEMPLATE_IMAGES = os.path.join(RESOURCES, 'inventory_templates')
GRIDS = os.path.join(RESOURCES, 'attachment_grids.json')
SCENE_NAME = 'Scene_ArsenalInventory'
LAYER_NAME = 'ViewLayer_ArsenalInventory'
FAMILIES = (
    ('inventory', 'Inventory image', '', 1),
    ('upgrade', 'Upgrade image', '', 2),
    ('standalone', 'Standalone inventory image', '', 3),
)
SIZES = {'inventory': (258, 128), 'upgrade': (1940, 800), 'standalone': (128, 128)}
CAMERAS = {'inventory': 'Standard', 'upgrade': 'Upgrade', 'standalone': 'MagazineStandalone'}
CAMERA_LAYOUT = 2
STOCK_ATTACHMENTS = [('NONE', 'None', ''), ('silencer', 'Stock Silencer', ''), ('laser', 'Stock Laser', '')]
DEFAULT_ATTACHMENT_TEMPLATES = {'silencer': 'EN_Silen_2', 'laser': 'EN_Laser_1'}
# Retail standalone icon pixels for an item 1, 2 and 3 inventory cells long.
ICON_SPANS = (128, 262, 388)
TEMPLATE_STYLES = {'pistol': 'pistol', 'pistol_mashine_gun': 'smg', 'sturm_riffle': 'rifle',
                   'shotgun': 'shotgun', 'sniper_riffle': 'sniper', 'DMR': 'sniper'}
TEMPLATE_MARKER = 'arsenal_inventory_template'
FRAME_MARGIN = 1.15


def stock_attachments(cfg):
    custom_kinds = {item.kind for item in cfg.attachments}
    return [(kind, sid, getattr(cfg, f'stock_{kind}_images'))
            for kind, sid in (('silencer', 'EN_Silen_2'), ('laser', 'EN_Laser_1'))
            if getattr(cfg, f'allow_{kind}') and kind not in custom_kinds]


def attachment_objects(source):
    settings = list(source.arsenal_cfg.attachments)
    settings += [item for _kind, _sid, item in stock_attachments(source.arsenal_cfg)]
    return {obj for item in settings
            for obj in (item.mesh_object, getattr(item, 'front_object', None)) if obj}


class ARSENAL_InventoryProps(bpy.types.PropertyGroup):
    camera_layout: bpy.props.IntProperty(default=0)
    source_scene: bpy.props.PointerProperty(type=bpy.types.Scene)
    render_scene: bpy.props.PointerProperty(type=bpy.types.Scene)
    geometry: bpy.props.PointerProperty(type=bpy.types.Collection)
    inventory_camera: bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda self, obj: obj.type == 'CAMERA')
    upgrade_camera: bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda self, obj: obj.type == 'CAMERA')
    standalone_camera: bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda self, obj: obj.type == 'CAMERA')


def source_scene(scene):
    return scene.arsenal_inventory.source_scene or scene


def canvas_size(cfg, family, settings=None):
    """Pixel size of an image layer: the weapon's template, the item grid, or the fixed upgrade canvas."""
    if family == 'inventory':
        path = template_image(cfg, 'inventory')
        if path:
            return png_size(path)
        from .weapon_presets import PRESETS
        return tuple(PRESETS[cfg.setup_template]['inventory_size'])
    if family == 'standalone':
        width, height = attachment_grids().get(standalone_sid(settings), (1, 1))
        return icon_span(width), icon_span(height)
    return SIZES[family]


def template_style(cfg):
    from .weapon_presets import PRESETS
    if cfg.setup_template == 'TemplateGauss':
        return 'gauss'
    return TEMPLATE_STYLES.get(PRESETS[cfg.setup_template]['category'])


def template_image(cfg, family):
    """Bundled camera guide for this weapon type; its size is the inventory canvas."""
    style = template_style(cfg)
    return os.path.join(TEMPLATE_IMAGES, f'{style}_{family}.png') if style else None


@functools.cache
def png_size(path):
    with open(path, 'rb') as file:
        header = file.read(24)
    if not header.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError(f'Inventory template is not a PNG image: {path}')
    return struct.unpack('>II', header[16:24])


@functools.cache
def attachment_grids():
    with open(GRIDS, encoding='utf-8') as file:
        return {sid: tuple(size) for sid, size in json.load(file).items()}


def standalone_sid(settings):
    """Game item whose inventory grid a standalone icon fills; custom magazines inherit a 1x1 template."""
    kind = getattr(settings, 'kind', None)
    if kind is None:
        return ''
    if settings.use_existing:
        return settings.existing_sid.strip()
    return settings.template_sid.strip() or DEFAULT_ATTACHMENT_TEMPLATES.get(kind, '')


def icon_span(cells):
    if cells <= len(ICON_SPANS):
        return ICON_SPANS[max(cells, 1) - 1]
    return ICON_SPANS[-1] + 130 * (cells - len(ICON_SPANS))


def weapon_sources(context, source):
    from . import export_animation, export_static_mesh, import_weapon, weapon_cfg

    with context.temp_override(scene=source, view_layer=source.view_layers[0]):
        rig, backup = export_animation.find_export_rig(context)
    if rig:
        mapping, _missing = export_animation.resolve_animation_mapping(backup, rig)
        joints = export_static_mesh.weapon_bone_joints(rig, mapping)
    else:
        rig = next((obj for obj in source.objects
                    if obj.type == 'ARMATURE' and obj.get(import_weapon.RIG_MARKER) is True), None)
        if rig is None:
            raise RuntimeError('No imported weapon rig found in the weapon scene.')
        joints = {bone.name: bone.name for bone in rig.data.bones}
    main, bones, others = export_static_mesh.classify_meshes(rig, source, joints)
    if main is None:
        raise RuntimeError('No meshes weighted to weapon bones were found.')
    objects = export_static_mesh.world_meshes(main, bones, others, joints)
    objects = [obj for obj in objects if obj == main or not weapon_cfg.ACCESSORY_WORDS.search(obj.name)]
    magazine_objects = {obj for item in source.arsenal_cfg.magazines
                        for obj in (item.full_object, item.empty_object) if obj}
    # Explicitly selected magazine meshes may not be bound to the rig yet.
    objects += [obj for obj in magazine_objects | attachment_objects(source)
                if obj.name in source.objects and obj not in objects]
    return objects, joints


def ensure_scene(context, source):
    source = source_scene(source)
    existing = source.arsenal_inventory.render_scene
    if existing:
        if existing.arsenal_inventory.source_scene != source:
            raise RuntimeError('The inventory render scene belongs to another weapon scene.')
        if existing.arsenal_inventory.camera_layout < CAMERA_LAYOUT:
            migrate_cameras(existing)
        apply_template_backgrounds(existing)
        return existing
    if not os.path.isfile(TEMPLATE):
        raise RuntimeError(f'Bundled inventory template is missing: {TEMPLATE}')
    objects, joints = weapon_sources(context, source)
    with bpy.data.libraries.load(TEMPLATE, link=False) as (available, loaded):
        if SCENE_NAME not in available.scenes:
            raise RuntimeError('The inventory template has no inventory scene.')
        loaded.scenes = [SCENE_NAME]
    scene = loaded.scenes[0]
    state = scene.arsenal_inventory
    state.source_scene = source
    source.arsenal_inventory.render_scene = scene
    for family, role in CAMERAS.items():
        setattr(state, f'{family}_camera', template_camera(scene, role))
    state.camera_layout = CAMERA_LAYOUT
    state.geometry = bpy.data.collections.new('Arsenal Inventory Geometry')
    scene.collection.children.link(state.geometry)
    for node in scene.compositing_node_group.nodes:
        if node.type == 'R_LAYERS':
            node.scene = scene
            node.layer = LAYER_NAME
    sync_geometry(context, source, objects=objects, joints=joints)
    default_view(scene)
    apply_template_backgrounds(scene)
    return scene


def apply_template_backgrounds(scene):
    """Show the bundled guide for this weapon type behind the Standard and Upgrade cameras.

    Guides are viewport-only. A camera that already has a user-chosen background keeps it unchanged.
    """
    cfg = source_scene(scene).arsenal_cfg
    for family in ('inventory', 'upgrade'):
        camera = getattr(scene.arsenal_inventory, f'{family}_camera')
        if camera is None:
            continue
        path = template_image(cfg, family)
        wanted = os.path.basename(path) if path and os.path.isfile(path) else None
        backgrounds = camera.data.background_images
        custom = any(bg.image is None or not bg.image.get(TEMPLATE_MARKER) for bg in backgrounds)
        for background in [bg for bg in backgrounds if bg.image and bg.image.get(TEMPLATE_MARKER)]:
            if custom or background.image[TEMPLATE_MARKER] != wanted:
                image = background.image
                backgrounds.remove(background)
                # Removing a background does not release its image user, so check references directly.
                if not any(bg.image == image for data in bpy.data.cameras for bg in data.background_images):
                    bpy.data.images.remove(image)
        if custom or wanted is None or len(backgrounds):
            continue
        image = next((image for image in bpy.data.images if image.get(TEMPLATE_MARKER) == wanted), None)
        if image is None:
            image = bpy.data.images.load(path, check_existing=False)
            image.name = f'Arsenal template {wanted}'
            image.pack()
            image[TEMPLATE_MARKER] = wanted
        background = backgrounds.new()
        background.image = image
        background.alpha = 0.5
        background.display_depth = 'BACK'
        background.frame_method = 'FIT'
        camera.data.show_background_images = True


def template_camera(scene, role):
    camera = next((obj for obj in scene.objects if obj.type == 'CAMERA'
                   and obj.name.split('.')[0] == f'Camera_ArsenalInventory_{role}'), None)
    if camera is None:
        raise RuntimeError(f'The inventory template has no {role} camera.')
    return camera


def migrate_cameras(scene):
    """Adopt the three authored cameras, preserving scene edits and former camera objects."""
    state = scene.arsenal_inventory
    cameras = {family: next((obj for obj in scene.objects if obj.type == 'CAMERA'
                            and obj.name.split('.')[0] == f'Camera_ArsenalInventory_{role}'), None)
               for family, role in CAMERAS.items()}
    missing_families = [family for family, camera in cameras.items() if camera is None]
    if missing_families:
        names = [f'Camera_ArsenalInventory_{CAMERAS[family]}' for family in missing_families]
        with bpy.data.libraries.load(TEMPLATE, link=False) as (available, loaded):
            if any(name not in available.objects for name in names):
                raise RuntimeError('The inventory template is missing one of the three authored cameras.')
            loaded.objects = names
        for family, camera in zip(missing_families, loaded.objects):
            scene.collection.objects.link(camera)
            cameras[family] = camera
    for family, camera in cameras.items():
        setattr(state, f'{family}_camera', camera)
    scene.camera = state.inventory_camera
    state.camera_layout = CAMERA_LAYOUT


def image_asset(info, token, family):
    prefix = 'T_inv_icon' if family == 'standalone' else 'T_inv_w'
    suffix = '_upgrade' if family == 'upgrade' else ''
    return f'{info["mount"]}/UI/Arsenal/{info["weapon_id"]}/{prefix}_{info["weapon_id"]}_{token}{suffix}'


def export_images(info):
    from .export_unreal import relative, write_texture

    every = ('inventory', 'upgrade', 'standalone')
    targets = [(info['cfg'], 'body', info['sid'], every)]
    targets += [(item['settings'], f'Mag{item["name"]}', f'Gun{info["weapon_id"]}_Mag{item["name"]}', every)
                for item in info['magazines'] if item.get('settings') and not item.get('existing_sid')]
    # Referenced attachments still need weapon-specific layers; their owner supplies the standalone icon.
    targets += [(item['settings'], f'Attach{item["name"]}', item['sid'],
                 every[:2] if item.get('existing_sid') else every)
                for item in info.get('attachments', []) if item.get('settings')]
    targets += [(settings, f'Stock{kind.title()}', sid, every[:2])
                for kind, sid, settings in stock_attachments(info['cfg'])]
    entries = []
    for settings, token, sid, families in targets:
        for family in families:
            image = getattr(settings, f'{family}_image', None)
            if image is None or (family == 'standalone' and (
                    token == 'body' or getattr(settings, 'preinstalled', False))):
                continue
            size = canvas_size(info['cfg'], family, settings)
            if tuple(image.size) != size or image.channels != 4:
                raise RuntimeError(f'Re-render {token} {family}: expected {size} RGBA pixels, '
                                   f'got {tuple(image.size)} with {image.channels} channels.')
            asset = image_asset(info, token, family)
            path = os.path.join(info['output_root'], 'UI', 'Arsenal', info['weapon_id'],
                                asset.rsplit('/', 1)[-1] + '.png')
            write_texture(image, path)
            entries.append({'file': relative(path, info['output_root']), 'sid': sid,
                            'family': family, 'asset': asset})
    return entries


def sync_geometry(context, source, *, objects=None, joints=None):
    from . import export_static_mesh, weapon_sockets

    scene = source.arsenal_inventory.render_scene
    if scene is None or scene.arsenal_inventory.geometry is None:
        raise RuntimeError('Create the inventory scene before synchronising geometry.')
    if objects is None:
        objects, joints = weapon_sources(context, source)
    collection = scene.arsenal_inventory.geometry
    fresh = []
    try:
        for obj in objects:
            clone = obj.copy()
            clone.data = obj.data.copy()
            fresh.append(clone)
            clone.name = f'{obj.name}_ArsenalInventory'
            clone.animation_data_clear()
            clone.parent = None
            clone.constraints.clear()
            clone.matrix_world = weapon_sockets.preview_rest_matrix(obj)
            for modifier in list(clone.modifiers):
                if modifier.type == 'ARMATURE':
                    clone.modifiers.remove(modifier)
            clone.hide_render = False
            clone.hide_viewport = False
            clone['arsenal_inventory_source'] = obj
            mesh = bmesh.new()
            try:
                mesh.from_mesh(clone.data)
                owners = export_static_mesh.face_bones(mesh, obj, joints)
                bmesh.ops.delete(mesh, geom=[
                    face for face in mesh.faces if face.index in owners
                    and export_static_mesh.ammunition_joint(joints[owners[face.index]])], context='FACES')
                mesh.to_mesh(clone.data)
            finally:
                mesh.free()
    except Exception:
        for clone in fresh:
            data = clone.data
            bpy.data.objects.remove(clone, do_unlink=True)
            bpy.data.meshes.remove(data)
        raise
    for obj in list(collection.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    for clone in fresh:
        collection.objects.link(clone)
    # Materials remain shared; geometry and visibility are independent of the production rig.
    scene.view_layers[LAYER_NAME].update()


def fit_camera(scene, camera, objects, size):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError('No render geometry to fit the camera around.')
    rotation = camera.rotation_euler.to_quaternion()
    inverse = rotation.inverted()
    local = [inverse @ point for point in points]
    low = Vector(tuple(min(point[i] for point in local) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in local) for i in range(3)))
    center = (low + high) / 2
    width, height = size
    aspect = width / height
    if camera.data.type == 'ORTHO':
        camera.data.ortho_scale = max(high.x - low.x, (high.y - low.y) * aspect, 0.01) * 1.15
        distance = max((high - low).length * 2, 1)
    else:
        slope = math.tan(camera.data.angle_x / 2)
        distance = max(max(abs(p.x - center.x) / slope,
                           abs(p.y - center.y) * aspect / slope) * 1.15 + p.z - center.z
                       for p in local)
        distance = max(distance, 0.1)
    distance = max(distance, camera.data.clip_start + high.z - center.z + 0.1)
    if distance + center.z - low.z >= camera.data.clip_end:
        raise RuntimeError(f'Camera {camera.name} clipping range is too short for this geometry; '
                           'increase Clip End before fitting.')
    camera.location = rotation @ (center + Vector((0, 0, distance)))


def fit_cameras(scene):
    state = scene.arsenal_inventory
    source = state.source_scene
    magazines = {obj for item in source.arsenal_cfg.magazines
                 for obj in (item.full_object, item.empty_object) if obj}
    attachments = attachment_objects(source)
    body = [obj for obj in state.geometry.objects
            if obj.get('arsenal_inventory_source') not in magazines | attachments]
    full_magazines = {item.full_object for item in source.arsenal_cfg.magazines if item.full_object}
    assembled = body + [obj for obj in state.geometry.objects
                        if obj.get('arsenal_inventory_source') in full_magazines | attachments]
    for family in ('inventory', 'upgrade'):
        fit_camera(scene, getattr(state, f'{family}_camera'), assembled, canvas_size(source.arsenal_cfg, family))
    standalone = [obj for obj in state.geometry.objects
                  if obj.get('arsenal_inventory_source') in full_magazines]
    if standalone:
        fit_camera(scene, state.standalone_camera, standalone, SIZES['standalone'])
    default_view(scene)


def frame_camera(scene, camera, objects, margin=FRAME_MARGIN):
    """Centre the objects in the camera and fill 1/margin of the frame, keeping the camera rotation.

    Uses evaluated vertices and the camera's own frame at the current render size, so the aspect,
    sensor fit, lens shift and perspective of a long lens are all honoured.
    """
    import numpy

    scene.view_layers[LAYER_NAME].update()
    depsgraph = scene.view_layers[LAYER_NAME].depsgraph
    chunks = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            count = len(mesh.vertices)
            if count:
                co = numpy.empty(count * 3, dtype=numpy.float64)
                mesh.vertices.foreach_get('co', co)
                matrix = numpy.array(evaluated.matrix_world)
                chunks.append(co.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])
        finally:
            evaluated.to_mesh_clear()
    if not chunks:
        raise RuntimeError('No render geometry to frame the standalone camera around.')
    rotation = camera.matrix_world.to_quaternion()
    # Row-vector points expressed along the camera axes (the camera looks down its -Z axis).
    local = numpy.concatenate(chunks) @ numpy.array(rotation.to_matrix())
    low, high = local.min(axis=0), local.max(axis=0)
    centre = (low + high) / 2
    frame = [Vector(corner) for corner in camera.data.view_frame(scene=scene)]
    data = camera.data
    if data.type == 'ORTHO':
        width = max(v.x for v in frame) - min(v.x for v in frame)
        height = max(v.y for v in frame) - min(v.y for v in frame)
        scale = max((high[0] - low[0]) / width, (high[1] - low[1]) / height, 1e-6) * margin
        data.ortho_scale *= scale
        offset = numpy.array([(max(v.x for v in frame) + min(v.x for v in frame)) / 2,
                              (max(v.y for v in frame) + min(v.y for v in frame)) / 2]) * scale
        position = numpy.array([centre[0] - offset[0], centre[1] - offset[1],
                                high[2] + data.clip_start + (high[2] - low[2]) / 2 + 0.01])
    else:
        depth = -frame[0].z
        u_range = (min(v.x for v in frame) / depth, max(v.x for v in frame) / depth)
        v_range = (min(v.y for v in frame) / depth, max(v.y for v in frame) / depth)
        frame_width, frame_height = u_range[1] - u_range[0], v_range[1] - v_range[0]
        span = max((high[0] - low[0]) / frame_width, (high[1] - low[1]) / frame_height, 1e-6) * margin
        position = numpy.array([centre[0], centre[1], high[2] + span])
        for _step in range(50):
            relative = local - position
            distance = -relative[:, 2]
            if distance.min() <= 0:
                position[2] = high[2] + span
                continue
            u, v = relative[:, 0] / distance, relative[:, 1] / distance
            scale = max((u.max() - u.min()) / frame_width, (v.max() - v.min()) / frame_height, 1e-6) * margin
            shift_u = (u.max() + u.min() - u_range[0] - u_range[1]) / 2
            shift_v = (v.max() + v.min() - v_range[0] - v_range[1]) / 2
            mean = distance.mean()
            position[0] += shift_u * mean
            position[1] += shift_v * mean
            position[2] = centre[2] + (position[2] - centre[2]) * scale
            if abs(scale - 1) < 1e-5 and abs(shift_u) < 1e-6 * frame_width and abs(shift_v) < 1e-6 * frame_height:
                break
    distance = position[2] - local[:, 2]
    if distance.min() < data.clip_start or distance.max() > data.clip_end:
        raise RuntimeError(f'Camera {camera.name} clipping range ({data.clip_start:g} to {data.clip_end:g}) '
                           'cannot contain this item once framed; adjust Clip Start/End and render again.')
    matrix = camera.matrix_world.copy()
    matrix.translation = rotation @ Vector(position.tolist())
    camera.matrix_world = matrix
    scene.view_layers[LAYER_NAME].update()


def default_view(scene):
    state = scene.arsenal_inventory
    source = state.source_scene
    magazines = {obj for item in source.arsenal_cfg.magazines
                 for obj in (item.full_object, item.empty_object) if obj}
    attachments = attachment_objects(source)
    default = next((item.full_object for item in source.arsenal_cfg.magazines if item.preinstalled), None)
    scene.camera = state.inventory_camera
    scene.render.resolution_x, scene.render.resolution_y = canvas_size(source_scene(scene).arsenal_cfg, 'inventory')
    for obj in state.geometry.objects:
        original = obj.get('arsenal_inventory_source')
        obj.hide_render = original in attachments or (original in magazines and original != default)
    scene.view_layers[LAYER_NAME].update()


def image_target(source, magazine_index, family, attachment_index=-1, stock_attachment='NONE'):
    if stock_attachment != 'NONE':
        settings = next((item for kind, _sid, item in stock_attachments(source.arsenal_cfg)
                         if kind == stock_attachment), None)
        if settings is None or family == 'standalone':
            raise RuntimeError('Enable this stock attachment and select an inventory or upgrade layer first.')
        return settings, f'{family}_image'
    if attachment_index >= 0:
        if attachment_index >= len(source.arsenal_cfg.attachments):
            raise RuntimeError('Select an attachment first.')
        item = source.arsenal_cfg.attachments[attachment_index]
        if item.use_existing and family == 'standalone':
            raise RuntimeError('Referenced attachments use the standalone image of their owning item.')
        return item, f'{family}_image'
    if magazine_index < 0:
        if family == 'standalone':
            raise RuntimeError('Standalone previews are only available for secondary magazines.')
        return source.arsenal_cfg, f'{family}_image'
    if not 0 <= magazine_index < len(source.arsenal_cfg.magazines):
        raise RuntimeError('Select a magazine first.')
    item = source.arsenal_cfg.magazines[magazine_index]
    if item.use_existing:
        raise RuntimeError('Existing magazine images are supplied by the owning mod.')
    if family == 'standalone' and item.preinstalled:
        raise RuntimeError('Preinstalled magazines do not need a standalone inventory image.')
    return item, f'{family}_image'


def update_thumbnail(image):
    thumbnail = image.copy()
    try:
        width, height = image.size
        scale = min(128 / width, 128 / height, 1)
        thumbnail.scale(max(1, round(width * scale)), max(1, round(height * scale)))
        preview = image.preview_ensure()
        preview.image_size = thumbnail.size
        preview.image_pixels_float = thumbnail.pixels[:]
    finally:
        bpy.data.images.remove(thumbnail)


def assign_image(target, prop, image):
    previous = getattr(target, prop)
    setattr(target, prop, image)
    if previous and previous.get('arsenal_inventory_preview') and previous.users == 0:
        bpy.data.images.remove(previous)


def load_packed_image(filepath, size=None):
    """Make an independent RGBA image so resizing never edits another image or the source file."""
    loaded = bpy.data.images.load(filepath, check_existing=False)
    image = None
    try:
        if not all(loaded.size):
            raise RuntimeError('The selected image has no readable pixels.')
        if size and tuple(loaded.size) != size:
            loaded.scale(*size)
        image = bpy.data.images.new(os.path.basename(filepath), width=loaded.size[0],
                                    height=loaded.size[1], alpha=True)
        image.colorspace_settings.name = loaded.colorspace_settings.name
        pixels = array('f', [0]) * (loaded.size[0] * loaded.size[1] * 4)
        loaded.pixels.foreach_get(pixels)
        image.pixels.foreach_set(pixels)
        image.pack()
        image['arsenal_inventory_preview'] = True
        update_thumbnail(image)
        return image
    except Exception:
        if image is not None:
            bpy.data.images.remove(image)
        raise
    finally:
        bpy.data.images.remove(loaded)


def render_preview(context, source, family, magazine_index=-1, attachment_index=-1, stock_attachment='NONE'):
    target, prop = image_target(source, magazine_index, family, attachment_index, stock_attachment)
    scene = ensure_scene(context, source)
    sync_geometry(context, source)
    state = scene.arsenal_inventory
    objects = list(state.geometry.objects)
    magazines = {obj for item in source.arsenal_cfg.magazines
                 for obj in (item.full_object, item.empty_object) if obj}
    attachments = attachment_objects(source)
    selected = set()
    if magazine_index >= 0:
        full = source.arsenal_cfg.magazines[magazine_index].full_object
        if full is None or full.name not in source.objects:
            raise RuntimeError('The selected magazine needs a full mesh in the weapon scene.')
        selected.add(full)
    if attachment_index >= 0 or stock_attachment != 'NONE':
        if target.mesh_object is None or target.mesh_object.name not in source.objects:
            raise RuntimeError('The selected attachment needs a mesh in the weapon scene.')
        selected.add(target.mesh_object)
        front = getattr(target, 'front_object', None)
        if front is not None:
            if front.name not in source.objects:
                raise RuntimeError('The selected front sight needs a mesh in the weapon scene.')
            selected.add(front)
    shown = [obj for obj in objects if (obj.get('arsenal_inventory_source') in selected
             if selected else obj.get('arsenal_inventory_source') not in magazines | attachments)]
    if not shown:
        raise RuntimeError('No geometry is available for this preview.')
    camera_family = 'standalone' if family == 'standalone' else (
        'upgrade' if family == 'upgrade' else 'inventory')
    camera = getattr(state, f'{camera_family}_camera')
    if camera is None or camera.name not in scene.objects:
        raise RuntimeError('The preview camera was deleted; restore it before rendering.')
    hidden = [(obj, obj.hide_render) for obj in objects]
    body = [obj for obj in objects if obj.get('arsenal_inventory_source') not in magazines | attachments]
    default = next((item.full_object for item in source.arsenal_cfg.magazines if item.preinstalled), None)
    occluders = body if selected and family != 'standalone' else []
    if (attachment_index >= 0 or stock_attachment != 'NONE') and family != 'standalone':
        occluders += [obj for obj in objects if obj.get('arsenal_inventory_source') == default]
    materials = [(obj, list(obj.data.materials), [(slot.link, slot.material) for slot in obj.material_slots])
                 for obj in occluders]
    holdout = None
    settings = (scene.camera, scene.render.resolution_x, scene.render.resolution_y,
                scene.render.resolution_percentage, scene.render.filepath,
                scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
                scene.render.film_transparent, scene.render.image_settings.color_depth)
    image = None
    try:
        if occluders:
            holdout = bpy.data.materials.new('Arsenal Render Holdout')
            holdout.use_nodes = True
            nodes = holdout.node_tree.nodes
            nodes.clear()
            output = nodes.new('ShaderNodeOutputMaterial')
            shader = nodes.new('ShaderNodeHoldout')
            holdout.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
            for obj in occluders:
                # Only snapshot mesh slots change; production materials stay untouched.
                for slot in obj.material_slots:
                    slot.link = 'DATA'
                for index in range(len(obj.data.materials)):
                    obj.data.materials[index] = holdout
                if not obj.data.materials:
                    obj.data.materials.append(holdout)
        for obj in objects:
            obj.hide_render = obj not in shown and obj not in occluders
        scene.camera = camera
        size = canvas_size(source.arsenal_cfg, family, target)
        scene.render.resolution_x, scene.render.resolution_y = size
        scene.render.resolution_percentage = 100
        if family == 'standalone':
            # Standalone icons are centred and filled like retail icons; the camera keeps this placement.
            frame_camera(scene, camera, shown)
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '8'
        scene.render.film_transparent = True
        with tempfile.TemporaryDirectory(prefix='arsenal_inventory_') as folder:
            scene.render.filepath = os.path.join(folder, 'preview.png')
            result = bpy.ops.render.render(scene=scene.name, layer=LAYER_NAME, write_still=True)
            if 'FINISHED' not in result:
                raise RuntimeError('Inventory render was cancelled.')
            image = bpy.data.images.load(scene.render.filepath, check_existing=False)
            image.name = f'Arsenal {target.name or source.name} {family}'
            image.pack()
            image.filepath_raw = f'//{image.name}.png'
            image['arsenal_inventory_preview'] = True
            update_thumbnail(image)
        assign_image(target, prop, image)
        return image
    except Exception:
        if image is not None and image.users == 0:
            bpy.data.images.remove(image)
        raise
    finally:
        (scene.camera, scene.render.resolution_x, scene.render.resolution_y,
         scene.render.resolution_percentage, scene.render.filepath,
         scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
         scene.render.film_transparent, scene.render.image_settings.color_depth) = settings
        for obj, value in hidden:
            obj.hide_render = value
        for obj, slots, overrides in materials:
            obj.data.materials.clear()
            for material in slots:
                obj.data.materials.append(material)
            for slot, (link, material) in zip(obj.material_slots, overrides):
                slot.link = link
                if link == 'OBJECT':
                    slot.material = material
        if holdout is not None:
            bpy.data.materials.remove(holdout)


class ARSENAL_OT_InventoryImage(bpy.types.Operator):
    bl_idname = 'arsenal.inventory_image'
    bl_label = 'Inventory Preview'
    bl_description = 'Render or clear the selected packed image; does not save your blend or export files'
    family: bpy.props.EnumProperty(items=FAMILIES)
    magazine_index: bpy.props.IntProperty(default=-1)
    attachment_index: bpy.props.IntProperty(default=-1)
    stock_attachment: bpy.props.EnumProperty(items=STOCK_ATTACHMENTS, default='NONE')
    clear: bpy.props.BoolProperty()

    @classmethod
    def description(cls, context, properties):
        if properties.clear:
            return 'Clear this image assignment; the next export will omit it, but old exported PNGs are not deleted'
        return ('Render an inventory image. Edit the Scene_ArsenalInventory scene if you prefer different lighting. '
                'Save your blend to keep the image; Export All writes the PNG')

    def execute(self, context):
        source = source_scene(context.scene)
        try:
            target, prop = image_target(
                source, self.magazine_index, self.family, self.attachment_index, self.stock_attachment)
            if self.clear:
                assign_image(target, prop, None)
            else:
                render_preview(
                    context, source, self.family, self.magazine_index, self.attachment_index, self.stock_attachment)
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def render_attachment_images(context, source):
    """Render inventory and upgrade layers for every listed attachment; returns (rendered, skipped)."""
    rendered, skipped = [], []
    for index, item in enumerate(source.arsenal_cfg.attachments):
        label = item.name or f'Attachment {index + 1}'
        if item.mesh_object is None or item.mesh_object.name not in source.objects:
            skipped.append(f'{label}: no mesh in the weapon scene')
            continue
        for family in ('inventory', 'upgrade'):
            try:
                render_preview(context, source, family, attachment_index=index)
            except RuntimeError as error:
                if 'cancelled' in str(error):
                    raise
                skipped.append(f'{label} {family}: {error}')
            else:
                rendered.append(f'{label} {family}')
    return rendered, skipped


class ARSENAL_OT_InventoryRenderAttachments(bpy.types.Operator):
    bl_idname = 'arsenal.inventory_render_attachments'
    bl_label = 'Render All Attachment Images'
    bl_description = ('Render the inventory and upgrade layers of every listed attachment with the shared '
                      'cameras. Replaces their current images; does not save your blend or export files')

    def execute(self, context):
        source = source_scene(context.scene)
        if not len(source.arsenal_cfg.attachments):
            report(self, {'ERROR'}, 'There are no attachments to render.')
            return {'CANCELLED'}
        try:
            rendered, skipped = render_attachment_images(context, source)
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, f'{error} Images rendered before cancelling were kept.')
            return {'CANCELLED'}
        for message in skipped:
            report(self, {'WARNING'}, f'Skipped {message}')
        report(self, {'INFO'}, f'Rendered {len(rendered)} attachment image(s), skipped {len(skipped)}.')
        return {'FINISHED'} if rendered else {'CANCELLED'}


class ARSENAL_OT_InventoryImageFile(bpy.types.Operator, ImportHelper):
    bl_idname = 'arsenal.inventory_image_file'
    bl_label = 'Select Image'
    bl_description = ('Choose an image from your computer, resize it to this inventory canvas and pack it '
                      'into the blend without changing the source file')
    bl_options = {'UNDO'}
    filter_glob: bpy.props.StringProperty(default='*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.tiff;*.webp', options={'HIDDEN'})
    family: bpy.props.EnumProperty(items=FAMILIES)
    magazine_index: bpy.props.IntProperty(default=-1)
    attachment_index: bpy.props.IntProperty(default=-1)
    stock_attachment: bpy.props.EnumProperty(items=STOCK_ATTACHMENTS, default='NONE')
    upgrade_index: bpy.props.IntProperty(default=-1)

    @classmethod
    def description(cls, context, properties):
        if properties.upgrade_index >= 0:
            return 'Choose and pack a custom upgrade illustration at its original size; replaces only this upgrade image'
        return cls.bl_description

    def execute(self, context):
        source = source_scene(context.scene)
        try:
            if self.upgrade_index >= 0:
                if not 0 <= self.upgrade_index < len(source.arsenal_cfg.upgrades):
                    raise RuntimeError('Select an upgrade first.')
                target, prop = source.arsenal_cfg.upgrades[self.upgrade_index], 'image'
                size = None
            else:
                target, prop = image_target(
                    source, self.magazine_index, self.family, self.attachment_index, self.stock_attachment)
                size = canvas_size(source.arsenal_cfg, self.family, target)
            image = load_packed_image(bpy.path.abspath(self.filepath), size)
            assign_image(target, prop, image)
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_images(layout, context, magazine_index=-1, attachment_index=-1, stock_attachment='NONE'):
    source = source_scene(context.scene)
    row = layout.row()
    families = ('inventory', 'upgrade')
    attachment = source.arsenal_cfg.attachments[attachment_index] if attachment_index >= 0 else None
    if (attachment is not None and not attachment.use_existing) or (
            magazine_index >= 0 and not source.arsenal_cfg.magazines[magazine_index].preinstalled):
        families += ('standalone',)
    for family in families:
        target, prop = image_target(source, magazine_index, family, attachment_index, stock_attachment)
        box = row.box() if family != 'standalone' else layout.box()
        box.label(text=dict((item[0], item[1]) for item in FAMILIES)[family])
        image = getattr(target, prop)
        if image:
            preview = image.preview_ensure()
            box.template_icon(icon_value=preview.icon_id, scale=6)
            box.label(text=f'{image.size[0]} x {image.size[1]}')
        else:
            box.label(text='Not rendered', icon='IMAGE_DATA')
        controls = box.row(align=True)
        render = controls.operator('arsenal.inventory_image', text='Render', icon='RENDER_STILL')
        render.family, render.magazine_index = family, magazine_index
        render.attachment_index, render.clear = attachment_index, False
        render.stock_attachment = stock_attachment
        select = controls.operator('arsenal.inventory_image_file', text='Select Image', icon='FILE_FOLDER')
        select.family, select.magazine_index = family, magazine_index
        select.attachment_index, select.upgrade_index = attachment_index, -1
        select.stock_attachment = stock_attachment
        clear = controls.operator('arsenal.inventory_image', text='', icon='X')
        clear.family, clear.magazine_index, clear.clear = family, magazine_index, True
        clear.attachment_index = attachment_index
        clear.stock_attachment = stock_attachment


CLASSES = (ARSENAL_InventoryProps, ARSENAL_OT_InventoryImage, ARSENAL_OT_InventoryRenderAttachments,
           ARSENAL_OT_InventoryImageFile)
