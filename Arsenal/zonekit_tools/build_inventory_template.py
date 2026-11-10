"""Extract an asset-free inventory scene from an artist-authored Blender template.

blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
    --python build_inventory_template.py -- SOURCE.blend DESTINATION.blend
"""
import os
import sys

import bpy


def build(source, destination):
    bpy.ops.wm.open_mainfile(filepath=source, load_ui=False, use_scripts=False)
    scene = bpy.data.scenes['Scene_ArsenalInventory']
    cameras = [scene.objects[f'Camera_ArsenalInventory_{role}']
               for role in ('Upgrade', 'MagazineStandalone', 'Standard')]
    if any(camera.type != 'CAMERA' for camera in cameras):
        raise RuntimeError('Expected upgrade, standalone magazine and standard cameras')
    suns = sorted((obj for obj in scene.objects if obj.type == 'LIGHT' and obj.data.type == 'SUN'),
                  key=lambda obj: obj.name)
    if len(suns) != 4 or scene.world is None or scene.compositing_node_group is None:
        raise RuntimeError('Expected four suns, a world and a compositor in the inventory template')
    keep = {*cameras, *suns}
    for obj in keep:
        if obj.parent or obj.constraints or obj.animation_data:
            raise RuntimeError(f'Template object must be independent: {obj.name}')
        for key in list(obj.keys()):
            del obj[key]
    for index, sun in enumerate(suns, 1):
        sun.name = f'Sun_Arsenal{index}'
        sun.data.name = sun.name
    for obj in list(bpy.data.objects):
        if obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(scene.collection.children):
        scene.collection.children.unlink(collection)
    for obj in keep:
        if obj.name not in scene.collection.objects:
            scene.collection.objects.link(obj)
    for other in list(bpy.data.scenes):
        if other != scene:
            bpy.data.scenes.remove(other)
    layer = scene.view_layers['ViewLayer_ArsenalInventory']
    for other in list(scene.view_layers):
        if other != layer:
            scene.view_layers.remove(other)
    for node in scene.compositing_node_group.nodes:
        if node.type == 'R_LAYERS':
            node.scene = scene
            node.layer = layer.name
    for key in list(scene.keys()):
        del scene[key]
    scene.camera = cameras[2]
    for camera in cameras:
        camera.data.background_images.clear()
        print(f'{camera.name}: location={tuple(camera.location)}, '
              f'rotation={tuple(camera.rotation_euler)}, lens={camera.data.lens}, '
              f'clip_start={camera.data.clip_start}, clip_end={camera.data.clip_end}')
    scene.render.filepath = '//'
    # Preview images must retain alpha even though the artist's viewport uses a sky background.
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.armatures,
                       bpy.data.actions, bpy.data.texts, bpy.data.collections):
        for block in datablocks:
            block.use_fake_user = False
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    for image in list(bpy.data.images):
        if image.type in ('RENDER_RESULT', 'COMPOSITING'):
            bpy.data.images.remove(image)
    if bpy.data.meshes or bpy.data.materials or bpy.data.images or bpy.data.armatures:
        raise RuntimeError('Template still contains model, material or image dependencies: '
                           + str([(blocks.bl_rna.identifier, [(b.name, b.users) for b in blocks])
                                  for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                                                 bpy.data.armatures) if blocks]))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    bpy.data.libraries.write(destination, {scene}, fake_user=True, compress=True)
    print(f'Inventory template saved: {destination}')


if __name__ == '__main__':
    source, destination = sys.argv[sys.argv.index('--') + 1:]
    build(source, destination)
