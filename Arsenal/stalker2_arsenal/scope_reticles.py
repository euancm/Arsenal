"""Custom scope reticles: pack a user image into a mod-owned copy of the game's reticle atlas.

Red-dot marks (M_PBR_WeaponMark_01) read the SightMask atlas, a 2 x 2 grid of 256-pixel cells
(red: sharp reticle, green: glow). SightMaskID 0 selects the top-left cell, the one EN_GoloScope_1
uses. The importer creates a mod-owned child of the scope's mark material with SightMask replaced
and, optionally, the colour and brightness parameters overridden.
"""
import os

import bpy
import numpy as np

from . import export_static_mesh as static_mesh
from . import weapon_sockets

ATLAS_SIZE = 512
CELL_SIZE = 256
GLOW_RADIUS = 6
GLOW_PASSES = 3
TEXTURE_PARAMETER = 'SightMask'
# Game parameter names, including their original spelling.
COLOUR_PARAMETER = 'SightColor(RGB)Int(A)'
GLOW_PARAMETER = 'SighAddColor(RGB)Int(A)'
BRIGHTNESS_PARAMETER = 'SightBrightnes'
NVG_BRIGHTNESS_PARAMETER = 'NVGSightBrightnes'


def mark_slot(obj):
    """Name of the mesh's reticle material slot (named after a game *_mark material), or None."""
    from .export_unreal import clean_material_name
    names = [clean_material_name(slot.material.name) for slot in obj.material_slots
             if slot.material and weapon_sockets.RETICLE_MATERIAL in slot.material.name.casefold()]
    return names[0] if len(set(names)) == 1 else None


def reticle_items(info):
    return [item for item in info.get('attachments', [])
            if not item.get('existing_sid') and item['kind'] == 'scope'
            and (getattr(item['settings'], 'reticle_image', None) is not None
                 or getattr(item['settings'], 'reticle_custom_colours', False))]


def reticle_parameters(settings):
    """Material parameter overrides for a scope's reticle, or empty dicts to keep the game values."""
    if not settings.reticle_custom_colours:
        return {'scalars': {}, 'vectors': {}}
    return {
        'scalars': {BRIGHTNESS_PARAMETER: settings.reticle_brightness,
                    NVG_BRIGHTNESS_PARAMETER: settings.reticle_nvg_brightness},
        'vectors': {COLOUR_PARAMETER: [*settings.reticle_colour, settings.reticle_colour_intensity],
                    GLOW_PARAMETER: [*settings.reticle_glow_colour, settings.reticle_glow_intensity]}}


def check_reticles(info):
    """Raise before any file is written if a selected reticle cannot be exported."""
    from .export_unreal import collect_materials
    for item in reticle_items(info):
        image = item['settings'].reticle_image
        if image is not None and (image.size[0] == 0 or image.size[1] == 0):
            raise RuntimeError(f'Reticle image "{image.name}" for {item["name"]} has no pixels (missing file?).')
        obj = item['object']
        slot = mark_slot(obj)
        if slot is None:
            raise RuntimeError(
                f'{item["name"]}: a custom reticle image or colour needs exactly one reticle material on '
                f'"{obj.name}" named after the game mark material it replaces, e.g. MI_rds02_en_goloscope_1_mark.')
        _managed, game = collect_materials([obj])
        if slot not in game:
            raise RuntimeError(f'{item["name"]}: reticle material "{slot}" has its own textures; '
                               'name it after the game mark material instead.')


def _blur(values, radius, axis):
    padded = np.pad(values, [(radius + 1, radius) if index == axis else (0, 0) for index in range(2)])
    total = np.cumsum(padded, axis=axis)
    upper = np.take(total, range(2 * radius + 1, total.shape[axis]), axis=axis)
    lower = np.take(total, range(0, total.shape[axis] - 2 * radius - 1), axis=axis)
    return (upper - lower) / (2 * radius + 1)


def _resample(pixels, size):
    """Bilinear resample of an (h, w, c) array to size x size."""
    height, width = pixels.shape[:2]
    ys = np.clip((np.arange(size) + 0.5) * height / size - 0.5, 0, height - 1)
    xs = np.clip((np.arange(size) + 0.5) * width / size - 0.5, 0, width - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, height - 1), np.minimum(x0 + 1, width - 1)
    fy, fx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    top = pixels[y0][:, x0] * (1 - fx) + pixels[y0][:, x1] * fx
    bottom = pixels[y1][:, x0] * (1 - fx) + pixels[y1][:, x1] * fx
    return top * (1 - fy) + bottom * fy


def build_atlas(image):
    """Return RGBA float pixels (Blender order, bottom row first) for a 512 x 512 reticle atlas."""
    width, height = image.size
    channels = image.channels
    pixels = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, channels)
    if channels < 4:
        pixels = np.concatenate([pixels[..., :1].repeat(3, axis=2) if channels < 3 else pixels[..., :3],
                                 np.ones((height, width, 1), dtype=np.float32)], axis=2)
    pixels = _resample(pixels, CELL_SIZE)
    mask = np.clip(pixels[..., :3].max(axis=2) * pixels[..., 3], 0.0, 1.0)
    glow = mask
    for _index in range(GLOW_PASSES):
        glow = _blur(_blur(glow, GLOW_RADIUS, 0), GLOW_RADIUS, 1)
    if glow.max() > 0:
        glow = glow / glow.max()
    atlas = np.zeros((ATLAS_SIZE, ATLAS_SIZE, 4), dtype=np.float32)
    atlas[..., 3] = 1.0
    top = slice(ATLAS_SIZE - CELL_SIZE, ATLAS_SIZE)
    atlas[top, :CELL_SIZE, 0] = mask
    atlas[top, :CELL_SIZE, 1] = np.maximum(mask, glow)
    return atlas


def asset_names(info, item):
    token = f'{info["mesh_name"]}_{item["name"]}'.replace('-', '_')
    return f'T_{token}_Reticle', f'MI_{token}_Reticle'


def export_reticles(info, weapon_folder, relative):
    """Write each selected reticle atlas as PNG and return the import manifest entries.

    A scope with custom colours but no image gets an entry without a file; the importer then keeps the
    game's reticle texture and only overrides the colour parameters.
    """
    entries = []
    for item in reticle_items(info):
        texture, material = asset_names(info, item)
        image = item['settings'].reticle_image
        file = None
        if image is not None:
            path = os.path.join(weapon_folder, 'Textures', texture + '.png')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atlas = bpy.data.images.new(texture, ATLAS_SIZE, ATLAS_SIZE, alpha=False)
            try:
                atlas.colorspace_settings.name = 'sRGB'
                atlas.pixels.foreach_set(build_atlas(image).ravel())
                atlas.filepath_raw = path
                atlas.file_format = 'PNG'
                atlas.save()
            finally:
                bpy.data.images.remove(atlas)
            file = relative(path, info['output_root'])
        obj = item['object']
        template = info['template']
        entries.append({
            'file': file, 'texture': texture if file else None, 'material': material,
            'slot': mark_slot(obj), 'parameters': reticle_parameters(item['settings']), 'meshes': [
                static_mesh.attachment_stem(info['mesh_name'], obj.name, template),
                static_mesh.world_attachment_stem(info['mesh_name'], obj.name, template)]})
    return entries
