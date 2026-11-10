"""Project-owned inventory preview scenes and packed image renders."""
import math
import os
import tempfile
from array import array

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from .notifications import report

TEMPLATE = os.path.join(os.path.dirname(__file__), 'resources', 'inventory_scene.blend')
SCENE_NAME = 'Scene_ArsenalInventory'
LAYER_NAME = 'ViewLayer_ArsenalInventory'
FAMILIES = (
    ('inventory', 'Inventory image', '', 1),
    ('upgrade', 'Upgrade image', '', 2),
    ('standalone', 'Standalone inventory image', '', 3),
)
SIZES = {'inventory': (258, 128), 'upgrade': (1940, 800), 'standalone': (258, 128)}
CAMERAS = {'inventory': 'Standard', 'upgrade': 'Upgrade', 'standalone': 'MagazineStandalone'}
CAMERA_LAYOUT = 2


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
    attachment_objects = {item.mesh_object for item in source.arsenal_cfg.attachments if item.mesh_object}
    objects += [obj for obj in magazine_objects | attachment_objects
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
    return scene


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

    targets = [(info['cfg'], 'body', info['sid'])]
    targets += [(item['settings'], f'Mag{item["name"]}', f'Gun{info["weapon_id"]}_Mag{item["name"]}')
                for item in info['magazines'] if item.get('settings')]
    targets += [(item['settings'], f'Attach{item["name"]}', item['sid'])
                for item in info.get('attachments', [])]
    entries = []
    for settings, token, sid in targets:
        for family in ('inventory', 'upgrade', 'standalone'):
            image = getattr(settings, f'{family}_image', None)
            if image is None or (family == 'standalone' and (
                    token == 'body' or getattr(settings, 'preinstalled', False))):
                continue
            if tuple(image.size) != SIZES[family] or image.channels != 4:
                raise RuntimeError(f'Re-render {token} {family}: expected {SIZES[family]} RGBA pixels, '
                                   f'got {tuple(image.size)} with {image.channels} channels.')
            asset = image_asset(info, token, family)
            path = os.path.join(info['output_root'], 'UI', 'Arsenal', info['weapon_id'],
                                asset.rsplit('/', 1)[-1] + '.png')
            write_texture(image, path)
            entries.append({'file': relative(path, info['output_root']), 'sid': sid,
                            'family': family, 'asset': asset})
    return entries


def sync_geometry(context, source, *, objects=None, joints=None):
    from . import export_static_mesh

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
            clone.matrix_world = obj.matrix_world.copy()
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
    attachments = {item.mesh_object for item in source.arsenal_cfg.attachments if item.mesh_object}
    body = [obj for obj in state.geometry.objects
            if obj.get('arsenal_inventory_source') not in magazines | attachments]
    full_magazines = {item.full_object for item in source.arsenal_cfg.magazines if item.full_object}
    assembled = body + [obj for obj in state.geometry.objects
                        if obj.get('arsenal_inventory_source') in full_magazines | attachments]
    for family in ('inventory', 'upgrade'):
        fit_camera(scene, getattr(state, f'{family}_camera'), assembled, SIZES[family])
    standalone = [obj for obj in state.geometry.objects
                  if obj.get('arsenal_inventory_source') in full_magazines]
    if standalone:
        fit_camera(scene, state.standalone_camera, standalone, SIZES['standalone'])
    default_view(scene)


def default_view(scene):
    state = scene.arsenal_inventory
    source = state.source_scene
    magazines = {obj for item in source.arsenal_cfg.magazines
                 for obj in (item.full_object, item.empty_object) if obj}
    attachments = {item.mesh_object for item in source.arsenal_cfg.attachments if item.mesh_object}
    default = next((item.full_object for item in source.arsenal_cfg.magazines if item.preinstalled), None)
    scene.camera = state.inventory_camera
    scene.render.resolution_x, scene.render.resolution_y = SIZES['inventory']
    for obj in state.geometry.objects:
        original = obj.get('arsenal_inventory_source')
        obj.hide_render = original in attachments or (original in magazines and original != default)
    scene.view_layers[LAYER_NAME].update()


def image_target(source, magazine_index, family, attachment_index=-1):
    if attachment_index >= 0:
        if attachment_index >= len(source.arsenal_cfg.attachments):
            raise RuntimeError('Select an attachment first.')
        return source.arsenal_cfg.attachments[attachment_index], f'{family}_image'
    if magazine_index < 0:
        if family == 'standalone':
            raise RuntimeError('Standalone previews are only available for secondary magazines.')
        return source.arsenal_cfg, f'{family}_image'
    if not 0 <= magazine_index < len(source.arsenal_cfg.magazines):
        raise RuntimeError('Select a magazine first.')
    item = source.arsenal_cfg.magazines[magazine_index]
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


def render_preview(context, source, family, magazine_index=-1, attachment_index=-1):
    target, prop = image_target(source, magazine_index, family, attachment_index)
    scene = ensure_scene(context, source)
    sync_geometry(context, source)
    state = scene.arsenal_inventory
    objects = list(state.geometry.objects)
    magazines = {obj for item in source.arsenal_cfg.magazines
                 for obj in (item.full_object, item.empty_object) if obj}
    attachments = {item.mesh_object for item in source.arsenal_cfg.attachments if item.mesh_object}
    selected = None
    if magazine_index >= 0:
        selected = source.arsenal_cfg.magazines[magazine_index].full_object
        if selected is None or selected.name not in source.objects:
            raise RuntimeError('The selected magazine needs a full mesh in the weapon scene.')
    if attachment_index >= 0:
        selected = target.mesh_object
        if selected is None or selected.name not in source.objects:
            raise RuntimeError('The selected attachment needs a mesh in the weapon scene.')
    shown = [obj for obj in objects if (obj.get('arsenal_inventory_source') == selected
             if selected else obj.get('arsenal_inventory_source') not in magazines | attachments)]
    if not shown:
        raise RuntimeError('No geometry is available for this preview.')
    camera_family = 'standalone' if family == 'standalone' and magazine_index >= 0 else (
        'upgrade' if family == 'upgrade' else 'inventory')
    camera = getattr(state, f'{camera_family}_camera')
    if camera is None or camera.name not in scene.objects:
        raise RuntimeError('The preview camera was deleted; restore it before rendering.')
    hidden = [(obj, obj.hide_render) for obj in objects]
    body = [obj for obj in objects if obj.get('arsenal_inventory_source') not in magazines | attachments]
    default = next((item.full_object for item in source.arsenal_cfg.magazines if item.preinstalled), None)
    occluders = body if selected and family != 'standalone' else []
    if attachment_index >= 0 and family != 'standalone':
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
        scene.render.resolution_x, scene.render.resolution_y = SIZES[family]
        scene.render.resolution_percentage = 100
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
    clear: bpy.props.BoolProperty()

    @classmethod
    def description(cls, context, properties):
        if properties.clear:
            return 'Clear this image assignment; the next export will omit it, but old exported PNGs are not deleted'
        camera = ('Upgrade' if properties.family == 'upgrade' else
                  'MagazineStandalone' if properties.family == 'standalone' and properties.magazine_index >= 0
                  else 'Standard')
        return (f'Render this image using shared camera {camera} and pack it into the blend, replacing the preview; '
                'save the blend to keep it and use Export All to write the PNG')

    def execute(self, context):
        source = source_scene(context.scene)
        try:
            target, prop = image_target(source, self.magazine_index, self.family, self.attachment_index)
            if self.clear:
                assign_image(target, prop, None)
            else:
                render_preview(context, source, self.family, self.magazine_index, self.attachment_index)
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


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
                target, prop = image_target(source, self.magazine_index, self.family, self.attachment_index)
                size = SIZES[self.family]
            image = load_packed_image(bpy.path.abspath(self.filepath), size)
            assign_image(target, prop, image)
        except (OSError, RuntimeError, ValueError) as error:
            report(self, {'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_images(layout, context, magazine_index=-1, attachment_index=-1):
    source = source_scene(context.scene)
    row = layout.row()
    families = ('inventory', 'upgrade')
    if attachment_index >= 0 or (
            magazine_index >= 0 and not source.arsenal_cfg.magazines[magazine_index].preinstalled):
        families += ('standalone',)
    for family in families:
        target, prop = image_target(source, magazine_index, family, attachment_index)
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
        select = controls.operator('arsenal.inventory_image_file', text='Select Image', icon='FILE_FOLDER')
        select.family, select.magazine_index = family, magazine_index
        select.attachment_index, select.upgrade_index = attachment_index, -1
        clear = controls.operator('arsenal.inventory_image', text='', icon='X')
        clear.family, clear.magazine_index, clear.clear = family, magazine_index, True
        clear.attachment_index = attachment_index


CLASSES = (ARSENAL_InventoryProps, ARSENAL_OT_InventoryImage, ARSENAL_OT_InventoryImageFile)
