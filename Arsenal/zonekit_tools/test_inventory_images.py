"""Inventory preview regression tests, using disposable synthetic weapon geometry.

blender --background --factory-startup --python-exit-code 1 --python test_inventory_images.py
No external weapon project is required or saved. Real Eevee renders run in a temporary directory.
"""
import os
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import inventory_images as inventory, import_weapon, weapon_cfg, export_unreal


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon.register()

    @classmethod
    def tearDownClass(cls):
        addon.unregister()

    def setUp(self):
        self.original_scene = bpy.context.window.scene
        self.existing = {
            name: set(getattr(bpy.data, name)) for name in
            ('scenes', 'objects', 'collections', 'meshes', 'armatures', 'cameras', 'lights',
             'worlds', 'node_groups', 'images', 'materials')
        }
        self.source = bpy.data.scenes.new('Test Weapon Scene')
        bpy.context.window.scene = self.source
        self.source.frame_set(37)
        self.source.render.resolution_x = 333
        self.source.render.resolution_y = 222
        data = bpy.data.armatures.new('Test Weapon Armature')
        self.rig = bpy.data.objects.new('Test Weapon Rig', data)
        self.source.collection.objects.link(self.rig)
        self.rig[import_weapon.RIG_MARKER] = True
        bpy.context.view_layer.objects.active = self.rig
        self.rig.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        for index, name in enumerate(('Weapon', 'jnt_magazine', 'jnt_bullet')):
            bone = data.edit_bones.new(name)
            bone.head = (0, 0, index)
            bone.tail = (0, 1, index)
        bpy.ops.object.mode_set(mode='OBJECT')
        self.body = self.mesh('Weapon Body', 'Weapon', (0, 0, 0))
        self.full = self.mesh('Test_mag_full', 'jnt_magazine', (0, 0, -1))
        self.empty = self.mesh('Test_mag_empty', 'jnt_magazine', (0, 0, -1))
        self.extended = self.mesh('Test_mag_extended_full', 'jnt_magazine', (0, 0, -2))
        self.extended_empty = self.mesh('Test_mag_extended_empty', 'jnt_magazine', (0, 0, -2))
        self.bullet = self.mesh('Bullet', 'jnt_bullet', (0, 0, 1))
        self.player = self.mesh('Player Model', None, (4, 0, 0))
        self.silencer = self.mesh('SM_silen_1', 'Weapon', (0, 3, 0))
        self.laser = self.mesh('SM_laser_1', 'Weapon', (0, 2, 0))
        cfg = self.source.arsenal_cfg
        for name, full, empty, preinstalled in (
                ('Default', self.full, self.empty, True),
                ('Extended', self.extended, self.extended_empty, False)):
            item = cfg.magazines.add()
            item.name = name
            item.full_object = full
            item.empty_object = empty
            item.preinstalled = preinstalled
        self.source.arsenal_ui.weapon_rig = self.rig
        self.addCleanup(self.cleanup)

    def cleanup(self):
        bpy.context.window.scene = self.original_scene
        for name, existing in self.existing.items():
            blocks = getattr(bpy.data, name)
            for block in list(blocks):
                if block not in existing and not (name == 'images' and block.type == 'RENDER_RESULT'):
                    blocks.remove(block, do_unlink=True)

    def mesh(self, name, bone, location):
        data = bpy.data.meshes.new(name)
        mesh = bmesh.new()
        bmesh.ops.create_cube(mesh, size=1)
        mesh.to_mesh(data)
        mesh.free()
        obj = bpy.data.objects.new(name, data)
        self.source.collection.objects.link(obj)
        obj.location = location
        if bone:
            obj.parent = self.rig
            group = obj.vertex_groups.new(name=bone)
            group.add(list(range(len(data.vertices))), 1, 'REPLACE')
            modifier = obj.modifiers.new('Weapon Deform', 'ARMATURE')
            modifier.object = self.rig
        return obj

    def test_template_is_asset_free_and_links_are_correct(self):
        dependencies = {name: set(getattr(bpy.data, name)) for name in
                        ('meshes', 'materials', 'images', 'armatures', 'actions', 'texts')}
        with bpy.data.libraries.load(inventory.TEMPLATE, link=False) as (_available, loaded):
            loaded.scenes = [inventory.SCENE_NAME]
        scene = loaded.scenes[0]
        self.assertEqual(len(scene.objects), 7)
        self.assertEqual({obj.type for obj in scene.objects}, {'CAMERA', 'LIGHT'})
        self.assertEqual(len([o for o in scene.objects if o.name.startswith('Sun_Arsenal')]), 4)
        self.assertTrue(scene.render.film_transparent)
        self.assertEqual(scene.render.image_settings.color_mode, 'RGBA')
        self.assertEqual([layer.name for layer in scene.view_layers], [inventory.LAYER_NAME])
        self.assertIn('ShaderNodeTexSky', {n.bl_idname for n in scene.world.node_tree.nodes})
        for node in scene.compositing_node_group.nodes:
            if node.type == 'R_LAYERS':
                self.assertEqual(node.scene, scene)
                self.assertEqual(node.layer, inventory.LAYER_NAME)
        self.assertFalse(scene.camera.data.background_images)
        self.assertEqual({obj.name for obj in scene.objects if obj.type == 'CAMERA'},
                         {f'Camera_ArsenalInventory_{role}' for role in inventory.CAMERAS.values()})
        for obj in scene.objects:
            if obj.type == 'CAMERA':
                self.assertEqual(obj.data.clip_start, 1.0)
        for name, before in dependencies.items():
            self.assertEqual(set(getattr(bpy.data, name)), before, name)
        trees = [scene.compositing_node_group]
        checked = set()
        while trees:
            tree = trees.pop()
            if tree in checked:
                continue
            checked.add(tree)
            for node in tree.nodes:
                self.assertNotEqual(node.type, 'OUTPUT_FILE')
                if node.type == 'GROUP' and node.node_tree:
                    trees.append(node.node_tree)

    def test_scene_creation_is_isolated_and_idempotent(self):
        before = set(self.source.objects)
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory
        self.assertEqual(state.source_scene, self.source)
        self.assertEqual(self.source.arsenal_inventory.render_scene, scene)
        self.assertEqual(set(self.source.objects), before)
        self.assertEqual(self.source.frame_current, 37)
        self.assertEqual(self.source.render.resolution_x, 333)
        self.assertEqual(bpy.context.scene, self.source)
        self.assertNotIn(self.player, scene.objects.values())
        self.assertNotIn(self.rig, scene.objects.values())
        geometry = list(state.geometry.objects)
        self.assertEqual({o.get('arsenal_inventory_source') for o in geometry},
                         {self.body, self.full, self.empty, self.extended, self.extended_empty})
        for obj in geometry:
            self.assertIsNot(obj.data, obj['arsenal_inventory_source'].data)
            self.assertIsNone(obj.parent)
            self.assertFalse(any(m.type == 'ARMATURE' for m in obj.modifiers))
        camera = scene.camera
        camera.location.x += 3
        position = camera.location.copy()
        self.assertEqual(inventory.ensure_scene(bpy.context, self.source), scene)
        self.assertEqual(camera.location, position)
        visible = {obj['arsenal_inventory_source'] for obj in geometry if not obj.hide_render}
        self.assertEqual(visible, {self.body, self.full})

    def test_creation_preserves_all_authored_camera_settings_without_fitting(self):
        with bpy.data.libraries.load(inventory.TEMPLATE, link=False) as (_available, loaded):
            loaded.scenes = [inventory.SCENE_NAME]
        template = loaded.scenes[0]
        template.view_layers[inventory.LAYER_NAME].update()
        scene = inventory.ensure_scene(bpy.context, self.source)
        for family, role in inventory.CAMERAS.items():
            expected = inventory.template_camera(template, role)
            actual = getattr(scene.arsenal_inventory, f'{family}_camera')
            self.assertEqual(actual.matrix_world, expected.matrix_world)
            for prop in expected.data.bl_rna.properties:
                if prop.identifier == 'show_background_images':
                    continue
                if prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'} \
                        and prop.identifier not in bpy.types.ID.bl_rna.properties:
                    a, b = getattr(actual.data, prop.identifier), getattr(expected.data, prop.identifier)
                    is_array = getattr(prop, 'is_array', False)
                    self.assertEqual(tuple(a) if is_array else a, tuple(b) if is_array else b,
                                     (family, prop.identifier))
        self.assertEqual(scene.arsenal_inventory.camera_layout, inventory.CAMERA_LAYOUT)

    def test_sync_updates_mesh_without_changing_production_pose_or_camera(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        self.body.data.vertices[0].co.x += 2
        self.rig.pose.bones['Weapon'].location.y = 5
        camera_matrix = scene.camera.matrix_world.copy()
        inventory.sync_geometry(bpy.context, self.source)
        clone = next(obj for obj in scene.arsenal_inventory.geometry.objects
                     if obj['arsenal_inventory_source'] == self.body)
        self.assertEqual(clone.data.vertices[0].co, self.body.data.vertices[0].co)
        self.assertEqual(self.rig.pose.bones['Weapon'].location.y, 5)
        self.assertEqual(scene.camera.matrix_world, camera_matrix)
        self.assertEqual(self.source.frame_current, 37)
        self.assertTrue(self.body.modifiers)

    def test_shared_camera_fit_contains_body_and_longest_magazine(self):
        self.extended.location.z = -5
        bpy.context.view_layer.update()
        scene = inventory.ensure_scene(bpy.context, self.source)
        clipping = {family: (getattr(scene.arsenal_inventory, f'{family}_camera').data.clip_start,
                            getattr(scene.arsenal_inventory, f'{family}_camera').data.clip_end)
                    for family in inventory.CAMERAS}
        inventory.fit_cameras(scene)
        for family, expected in clipping.items():
            camera = getattr(scene.arsenal_inventory, f'{family}_camera')
            self.assertEqual((camera.data.clip_start, camera.data.clip_end), expected)
        objects = [obj for obj in scene.arsenal_inventory.geometry.objects
                   if obj['arsenal_inventory_source'] in (self.body, self.full, self.extended)]
        for family in ('inventory', 'upgrade', 'standalone'):
            scene.render.resolution_x, scene.render.resolution_y = inventory.SIZES[family]
            camera = getattr(scene.arsenal_inventory, f'{family}_camera')
            for obj in objects:
                if family == 'standalone' and obj['arsenal_inventory_source'] == self.body:
                    continue
                for corner in obj.bound_box:
                    pixel = world_to_camera_view(scene, camera, obj.matrix_world @ Vector(corner))
                    self.assertGreater(pixel.z, 0)
                    self.assertGreaterEqual(pixel.x, 0)
                    self.assertLessEqual(pixel.x, 1)
                    self.assertGreaterEqual(pixel.y, 0)
                    self.assertLessEqual(pixel.y, 1)

    def test_separate_production_scenes_do_not_share_render_settings(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        other = self.source.copy()
        other.arsenal_inventory.render_scene = None
        second = inventory.ensure_scene(bpy.context, other)
        self.assertNotEqual(second, scene)
        self.assertNotEqual(second.camera.data, scene.camera.data)
        self.assertNotEqual(second.world, scene.world)
        self.assertNotEqual(second.compositing_node_group, scene.compositing_node_group)
        self.assertEqual(second.arsenal_inventory.source_scene, other)

    def test_preview_plan_follows_preinstalled_magazine_and_image_pointers(self):
        with self.assertRaisesRegex(RuntimeError, 'Preinstalled'):
            inventory.image_target(self.source, 0, 'standalone')
        with self.assertRaisesRegex(RuntimeError, 'Select'):
            inventory.image_target(self.source, 4, 'inventory')
        target, prop = inventory.image_target(self.source, 1, 'standalone')
        self.assertEqual(target, self.source.arsenal_cfg.magazines[1])
        self.assertEqual(prop, 'standalone_image')
        image = bpy.data.images.new('Magazine Preview', width=8, height=8)
        target.standalone_image = image
        self.source.arsenal_cfg.magazines.move(1, 0)
        self.assertEqual(self.source.arsenal_cfg.magazines[0].standalone_image, image)

    def test_file_selected_images_resize_pack_and_export_every_inventory_slot(self):
        cfg = self.source.arsenal_cfg
        attachment = cfg.attachments.add()
        attachment.name = 'Quiet'
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'user_icon.jpg')
            original = bpy.data.images.new('Original user image', width=12, height=8, alpha=False)
            original.pixels[:] = [0.8, 0.2, 0.1, 1] * (12 * 8)
            original.file_format = 'JPEG'
            original.save(filepath=path)
            before = Path(path).read_bytes()
            for magazine, custom, families in (
                    (-1, -1, ('inventory', 'upgrade')), (1, -1, ('inventory', 'upgrade', 'standalone')),
                    (-1, 0, ('inventory', 'upgrade', 'standalone'))):
                for family in families:
                    self.assertEqual(bpy.ops.arsenal.inventory_image_file(
                        filepath=path, family=family, magazine_index=magazine, attachment_index=custom,
                        upgrade_index=-1), {'FINISHED'})
                    target, prop = inventory.image_target(self.source, magazine, family, custom)
                    image = getattr(target, prop)
                    self.assertEqual(tuple(image.size), inventory.canvas_size(cfg, family, target))
                    self.assertEqual(image.channels, 4)
                    self.assertIsNotNone(image.packed_file)
                    self.assertGreater(image.preview_ensure().image_size[0], 0)
                    self.assertGreater(max(list(image.pixels)[3::4]), 0.9)
            self.assertEqual(Path(path).read_bytes(), before)
            self.assertEqual(tuple(original.size), (12, 8))
            self.assertIsNone(self.source.arsenal_inventory.render_scene)
            info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'mount': '/TestMod', 'output_root': folder,
                    'magazines': [{'settings': cfg.magazines[1], 'name': 'Extended', 'preinstalled': False}],
                    'attachments': [{'settings': attachment, 'name': 'Quiet', 'sid': 'GunTest_AttachQuiet'}]}
            self.assertEqual(len(inventory.export_images(info)), 8)
            first = cfg.inventory_image
            self.assertEqual(bpy.ops.arsenal.inventory_image_file(
                filepath=path, family='inventory', magazine_index=-1, attachment_index=-1,
                upgrade_index=-1), {'FINISHED'})
            self.assertNotIn(first, bpy.data.images.values())

    def test_rifle_render_and_export_use_native_canvas_not_pistol_size(self):
        cfg = self.source.arsenal_cfg
        cfg.setup_template = 'TemplateM16'
        cfg.inventory_image = bpy.data.images.new('Obsolete rifle image', width=258, height=128, alpha=True)
        with tempfile.TemporaryDirectory() as folder:
            info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'mount': '/TestMod',
                    'output_root': folder, 'magazines': [], 'attachments': []}
            with self.assertRaisesRegex(RuntimeError, r'expected \(648, 258\)'):
                inventory.export_images(info)
            scene = inventory.ensure_scene(bpy.context, self.source)
            camera = scene.arsenal_inventory.inventory_camera
            before = camera.matrix_world.copy()
            image = inventory.render_preview(bpy.context, self.source, 'inventory')
            self.assertEqual(tuple(image.size), (648, 258))
            self.assertEqual(camera.matrix_world, before)
            entries = inventory.export_images(info)
            self.assertEqual(len(entries), 1)
            exported = bpy.data.images.load(os.path.join(folder, entries[0]['file']))
            self.assertEqual(tuple(exported.size), (648, 258))
            selected = bpy.ops.arsenal.inventory_image_file(
                filepath=os.path.join(folder, entries[0]['file']), family='inventory',
                magazine_index=-1, attachment_index=-1, upgrade_index=-1)
            self.assertEqual(selected, {'FINISHED'})
            self.assertEqual(tuple(cfg.inventory_image.size), (648, 258))

    def test_canvas_sizes_follow_weapon_templates_and_attachment_grids(self):
        cfg = self.source.arsenal_cfg
        for template, expected in (('TemplateSMG', (648, 258)), ('TemplateObrez', (648, 258)),
                                   ('TemplateSVU', (908, 258)), ('TemplateGauss', (908, 258)),
                                   ('TemplatePistol', (258, 128)), ('TemplatePKP', (778, 258))):
            cfg.setup_template = template
            self.assertEqual(inventory.canvas_size(cfg, 'inventory'), expected, template)
        item = cfg.attachments.add()
        for kind, template, expected in (('silencer', '', (262, 128)), ('scope', 'EN_GoloScope_1', (128, 128)),
                                         ('scope', 'EN_X8Scope_1', (388, 128)),
                                         ('scope', 'ModOnlyScope', (128, 128))):
            item.kind, item.template_sid = kind, template
            self.assertEqual(inventory.canvas_size(cfg, 'standalone', item), expected, template)
        self.assertEqual(inventory.canvas_size(cfg, 'standalone', cfg.magazines[1]), (128, 128))

    def test_template_guides_back_standard_and_upgrade_cameras_only(self):
        cfg = self.source.arsenal_cfg
        cfg.setup_template = 'TemplateM16'
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory

        def guides(camera):
            return [background.image.get(inventory.TEMPLATE_MARKER) if background.image else None
                    for background in camera.data.background_images]

        self.assertEqual(guides(state.inventory_camera), ['rifle_inventory.png'])
        self.assertEqual(guides(state.upgrade_camera), ['rifle_upgrade.png'])
        self.assertFalse(state.standalone_camera.data.background_images)
        guide = state.inventory_camera.data.background_images[0]
        self.assertEqual((guide.alpha, guide.display_depth, guide.frame_method), (0.5, 'BACK', 'FIT'))
        self.assertTrue(state.inventory_camera.data.show_background_images)
        self.assertEqual(tuple(guide.image.size), inventory.canvas_size(cfg, 'inventory'))
        self.assertIsNotNone(guide.image.packed_file)
        rifle = guide.image.name
        inventory.ensure_scene(bpy.context, self.source)
        self.assertEqual(guides(state.inventory_camera), ['rifle_inventory.png'])
        cfg.setup_template = 'TemplateSVD'
        inventory.ensure_scene(bpy.context, self.source)
        self.assertEqual(guides(state.inventory_camera), ['sniper_inventory.png'])
        self.assertNotIn(rifle, bpy.data.images)
        custom = bpy.data.images.new('My own guide', width=4, height=4)
        state.upgrade_camera.data.background_images.clear()
        state.upgrade_camera.data.background_images.new().image = custom
        cfg.setup_template = 'TemplatePKP'
        inventory.ensure_scene(bpy.context, self.source)
        self.assertEqual(guides(state.inventory_camera), [])
        self.assertEqual([bg.image for bg in state.upgrade_camera.data.background_images], [custom])

    def test_standalone_render_frames_item_in_the_centre_of_its_grid_canvas(self):
        item = self.source.arsenal_cfg.attachments.add()
        item.name, item.kind, item.mesh_object = 'Quiet', 'silencer', self.silencer
        scene = inventory.ensure_scene(bpy.context, self.source)
        camera = scene.arsenal_inventory.standalone_camera
        camera.location += Vector((40, 25, -15))
        image = inventory.render_preview(bpy.context, self.source, 'standalone', attachment_index=0)
        width, height = image.size
        self.assertEqual((width, height), (262, 128))
        alpha = list(image.pixels)[3::4]
        columns = [i % width for i, value in enumerate(alpha) if value > 0.5]
        rows = [i // width for i, value in enumerate(alpha) if value > 0.5]
        self.assertTrue(columns)
        self.assertAlmostEqual((min(columns) + max(columns) + 1) / 2, width / 2, delta=2)
        self.assertAlmostEqual((min(rows) + max(rows) + 1) / 2, height / 2, delta=2)
        fill = max((max(columns) - min(columns) + 1) / width, (max(rows) - min(rows) + 1) / height)
        self.assertGreater(fill, 0.8)
        self.assertLess(fill, 0.92)
        placed = camera.matrix_world.copy()
        inventory.render_preview(bpy.context, self.source, 'standalone', attachment_index=0)
        for a, b in zip(placed, camera.matrix_world):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=3)

    def test_render_all_attachment_images_renders_both_layers_and_skips_meshless_items(self):
        cfg = self.source.arsenal_cfg
        referenced, missing = cfg.attachments.add(), cfg.attachments.add()
        referenced.name, referenced.mesh_object = 'Scope', self.laser
        missing.name = 'NoMesh'
        calls = []

        def fake(context, source, family, attachment_index=-1):
            calls.append((attachment_index, family))
            if family == 'upgrade':
                raise RuntimeError('No geometry is available for this preview.')

        with patch.object(inventory, 'render_preview', fake):
            rendered, skipped = inventory.render_attachment_images(bpy.context, self.source)
        self.assertEqual(calls, [(0, 'inventory'), (0, 'upgrade')])
        self.assertEqual(rendered, ['Scope inventory'])
        self.assertEqual(len(skipped), 2)
        self.assertIn('NoMesh: no mesh', skipped[1])

        def cancel(*args, **kwargs):
            raise RuntimeError('Inventory render was cancelled.')

        with patch.object(inventory, 'render_preview', cancel), self.assertRaisesRegex(RuntimeError, 'cancelled'):
            inventory.render_attachment_images(bpy.context, self.source)

    def test_referenced_attachment_has_weapon_layers_but_no_standalone_image(self):
        cfg = self.source.arsenal_cfg
        item = cfg.attachments.add()
        item.name, item.kind = 'Scope', 'scope'
        item.use_existing, item.existing_sid, item.mesh_object = True, 'EN_X4Scope_1', self.laser
        item.socket = 'ScopeSocket'
        for family in ('inventory', 'upgrade'):
            self.assertEqual(inventory.image_target(self.source, -1, family, 0), (item, f'{family}_image'))
        with self.assertRaisesRegex(RuntimeError, 'owning item'):
            inventory.image_target(self.source, -1, 'standalone', 0)

        class Layout:
            families = []

            def row(self, **kwargs):
                return self

            box = column = row

            def label(self, **kwargs):
                pass

            def template_icon(self, **kwargs):
                pass

            def operator(self, name, **kwargs):
                properties = SimpleNamespace()
                if kwargs.get('text') == 'Render':
                    self.families.append(properties)
                return properties

        layout = Layout()
        inventory.draw_images(layout, bpy.context, attachment_index=0)
        self.assertEqual([props.family for props in layout.families], ['inventory', 'upgrade'])
        item.inventory_image = bpy.data.images.new('Scope layer', width=258, height=128, alpha=True)
        item.upgrade_image = bpy.data.images.new('Scope upgrade', width=1940, height=800, alpha=True)
        item.standalone_image = bpy.data.images.new('Ignored standalone', width=262, height=128, alpha=True)
        with tempfile.TemporaryDirectory() as folder:
            info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'mount': '/TestMod',
                    'output_root': folder, 'magazines': [],
                    'attachments': weapon_cfg.collect_attachments(cfg, [])}
            info['attachments'][0]['sid'] = 'EN_X4Scope_1'
            entries = inventory.export_images(info)
        self.assertEqual([(entry['family'], entry['sid']) for entry in entries],
                         [('inventory', 'EN_X4Scope_1'), ('upgrade', 'EN_X4Scope_1')])
        self.assertTrue(entries[0]['asset'].endswith('/T_inv_w_Test_AttachScope'))

    def test_both_iron_sight_meshes_render_in_one_attachment_layer(self):
        item = self.source.arsenal_cfg.attachments.add()
        item.kind = 'iron_sight'
        item.mesh_object, item.front_object = self.silencer, self.laser
        scene = inventory.ensure_scene(bpy.context, self.source)

        def cancelled(**kwargs):
            shown = {obj['arsenal_inventory_source'] for obj in scene.arsenal_inventory.geometry.objects
                     if not obj.hide_render}
            self.assertEqual(shown, {self.body, self.full, self.silencer, self.laser})
            return {'CANCELLED'}

        stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
        with patch.object(inventory, 'bpy', stub):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                inventory.render_preview(bpy.context, self.source, 'inventory', attachment_index=0)

    def test_socket_previews_stay_in_rest_pose_for_inventory_without_resetting_animation(self):
        from stalker2_arsenal import weapon_sockets
        marker = bpy.data.objects.new('Test socket marker', None)
        self.source.collection.objects.link(marker)
        marker.arsenal_socket_id = 'inventory-socket'
        marker.parent, marker.parent_type, marker.parent_bone = self.rig, 'BONE', 'Weapon'
        marker.location = (1, 2, 3)
        item = self.source.arsenal_cfg.attachments.add()
        item.mesh_object = self.silencer
        bpy.context.view_layer.update()
        weapon_sockets.parent_preview(self.silencer, marker, self.rig)
        bpy.context.view_layer.update()
        rest = self.silencer.matrix_world.copy()
        scene = inventory.ensure_scene(bpy.context, self.source)
        self.rig.pose.bones['Weapon'].location = (3, 5, 7)
        self.rig.pose.bones['Weapon'].rotation_mode = 'XYZ'
        self.rig.pose.bones['Weapon'].rotation_euler.z = 0.4
        bpy.context.view_layer.update()
        posed = self.silencer.matrix_world.copy()
        self.assertGreater((posed.translation - rest.translation).length, 1)
        inventory.sync_geometry(bpy.context, self.source)
        clone = next(obj for obj in scene.arsenal_inventory.geometry.objects
                     if obj.get('arsenal_inventory_source') == self.silencer)
        self.assertLess((clone.matrix_world.translation - rest.translation).length, 0.00001)
        self.assertEqual(self.rig.pose.bones['Weapon'].location, Vector((3, 5, 7)))
        # Original-object matrices cache the last evaluated scene; inspect the source depsgraph.
        self.source.view_layers[0].update()
        self.assertEqual(self.silencer.matrix_world, posed)
        marker.location.x += 2
        bpy.context.view_layer.update()
        inventory.sync_geometry(bpy.context, self.source)
        clone = next(obj for obj in scene.arsenal_inventory.geometry.objects
                     if obj.get('arsenal_inventory_source') == self.silencer)
        self.assertLess((clone.matrix_world.translation - rest.translation - Vector((2, 0, 0))).length, 0.00001)

    def test_invalid_file_selection_preserves_previous_image_and_reports_error(self):
        original = bpy.data.images.new('Keep this preview', width=258, height=128, alpha=True)
        self.source.arsenal_cfg.inventory_image = original
        with self.assertRaisesRegex(RuntimeError, 'Cannot read|could not|Unable|Error'):
            bpy.ops.arsenal.inventory_image_file(
                filepath=r'Z:\ArsenalMissingImage.png', family='inventory',
                magazine_index=-1, attachment_index=-1, upgrade_index=-1)
        self.assertEqual(self.source.arsenal_cfg.inventory_image, original)

    def test_every_preview_button_resets_last_used_image_action_and_target(self):
        class Layout:
            def __init__(self):
                self.buttons = []

            def row(self, **kwargs):
                return self

            box = column = row

            def label(self, **kwargs):
                pass

            def operator(self, name, **kwargs):
                properties = SimpleNamespace(clear=True, upgrade_index=9, magazine_index=9, attachment_index=9)
                self.buttons.append((name, kwargs, properties))
                return properties

        for magazine in (-1, 0, 1):
            layout = Layout()
            inventory.draw_images(layout, bpy.context, magazine_index=magazine)
            selections = [p for name, _kw, p in layout.buttons if name == 'arsenal.inventory_image_file']
            self.assertEqual(len(selections), 3 if magazine == 1 else 2)
            for selection in selections:
                self.assertEqual((selection.upgrade_index, selection.magazine_index, selection.attachment_index),
                                 (-1, magazine, -1))
            for name, kwargs, props in layout.buttons:
                if name == 'arsenal.inventory_image' and kwargs['text'] == 'Render':
                    self.assertFalse(props.clear)

    def test_attachment_add_button_overrides_last_used_remove_action(self):
        class Layout:
            def __init__(self):
                self.operators = []

            def row(self, **kwargs):
                return self

            column = box = row

            def label(self, **kwargs):
                pass

            def prop(self, *args, **kwargs):
                pass

            def template_list(self, *args, **kwargs):
                pass

            def operator(self, name, **kwargs):
                props = SimpleNamespace(remove=True)
                self.operators.append((name, kwargs, props))
                return props

        for icon, count in (('ADD', 1), ('ADD', 2), ('REMOVE', 1), ('ADD', 2),
                            ('REMOVE', 1), ('REMOVE', 0), ('ADD', 1)):
            layout = Layout()
            panel = SimpleNamespace(layout=layout, props=lambda *args: None)
            with patch.object(inventory, 'draw_images'):
                weapon_cfg.ARSENAL_PT_CfgAttachments.draw(panel, bpy.context)
            button = next(props for name, kwargs, props in layout.operators
                          if name == 'object.arsenal_cfg_attachment_edit' and kwargs['icon'] == icon)
            self.assertEqual(button.remove, icon == 'REMOVE')
            self.assertEqual(bpy.ops.object.arsenal_cfg_attachment_edit(remove=button.remove), {'FINISHED'})
            self.assertEqual(len(self.source.arsenal_cfg.attachments), count)

    def test_render_failure_restores_render_settings_and_geometry_visibility(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        hidden = {obj: obj.hide_render for obj in scene.arsenal_inventory.geometry.objects}
        camera = scene.camera
        resolution = (scene.render.resolution_x, scene.render.resolution_y)
        path = scene.render.filepath
        stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(
            render=lambda **kwargs: {'CANCELLED'})))
        with patch.object(inventory, 'sync_geometry'), patch.object(inventory, 'bpy', stub):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                inventory.render_preview(bpy.context, self.source, 'upgrade', 1)
        self.assertEqual(scene.camera, camera)
        self.assertEqual((scene.render.resolution_x, scene.render.resolution_y), resolution)
        self.assertEqual(scene.render.filepath, path)
        self.assertEqual({obj: obj.hide_render for obj in hidden}, hidden)
        self.assertIsNone(self.source.arsenal_cfg.magazines[1].upgrade_image)

    def test_render_visibility_is_body_or_single_selected_full_magazine(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        for family, index, expected in (
                ('inventory', -1, {self.body}), ('inventory', 0, {self.body, self.full}),
                ('upgrade', 1, {self.body, self.extended}), ('standalone', 1, {self.extended})):
            with self.subTest(family=family, magazine=index):
                def cancelled(**kwargs):
                    shown = {obj['arsenal_inventory_source']
                             for obj in scene.arsenal_inventory.geometry.objects if not obj.hide_render}
                    self.assertEqual(shown, expected)
                    expected_camera = getattr(scene.arsenal_inventory, f'{family}_camera')
                    self.assertEqual(scene.camera, expected_camera)
                    if family != 'standalone' and index >= 0:
                        body = next(obj for obj in scene.arsenal_inventory.geometry.objects
                                    if obj['arsenal_inventory_source'] == self.body)
                        self.assertIn('ShaderNodeHoldout', {
                            node.bl_idname for node in body.data.materials[0].node_tree.nodes})
                    return {'CANCELLED'}

                stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(
                    render=SimpleNamespace(render=cancelled)))
                with patch.object(inventory, 'sync_geometry'), patch.object(inventory, 'bpy', stub):
                    with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                        inventory.render_preview(bpy.context, self.source, family, index)
        camera = scene.arsenal_inventory.inventory_camera
        camera.location.x += 3
        location = camera.location.copy()
        with patch.object(inventory, 'sync_geometry'), patch.object(inventory, 'bpy', stub):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                inventory.render_preview(bpy.context, self.source, 'standalone', 1)
        self.assertEqual(camera.location, location)

    def test_existing_named_cameras_are_preserved_during_migration(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory
        camera_b, camera_a = state.inventory_camera, state.upgrade_camera
        state.inventory_camera = camera_a
        state.camera_layout = 0
        before = camera_a.matrix_world.copy()
        inventory.ensure_scene(bpy.context, self.source)
        self.assertEqual(state.inventory_camera, camera_b)
        self.assertEqual(state.upgrade_camera, camera_a)
        self.assertEqual(camera_a.matrix_world, before)
        self.assertEqual(state.camera_layout, inventory.CAMERA_LAYOUT)

    def test_legacy_ab_scene_loads_three_authored_cameras_without_moving_old_ones(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory
        camera_b, camera_a = state.inventory_camera, state.upgrade_camera
        state.inventory_camera = camera_a
        camera_b.name = 'Camera_ArsenalInventoryB'
        camera_a.name = 'Camera_ArsenalInventoryA'
        old = {camera: camera.matrix_world.copy() for camera in (camera_a, camera_b)}
        world, compositor = scene.world, scene.compositing_node_group
        bpy.data.objects.remove(state.standalone_camera, do_unlink=True)
        state.camera_layout = 1
        inventory.ensure_scene(bpy.context, self.source)
        self.assertIsNotNone(state.inventory_camera)
        self.assertNotEqual(state.inventory_camera, state.upgrade_camera)
        self.assertNotEqual(state.upgrade_camera, camera_a)
        self.assertEqual(scene.camera, state.inventory_camera)
        for camera, matrix in old.items():
            self.assertEqual(camera.matrix_world, matrix)
        self.assertEqual(scene.world, world)
        self.assertEqual(scene.compositing_node_group, compositor)
        for family, role in inventory.CAMERAS.items():
            camera = getattr(state, f'{family}_camera')
            self.assertEqual(camera, inventory.template_camera(scene, role))
            self.assertEqual(camera.data.clip_start, 1.0)

    def test_custom_attachment_layers_use_weapon_holdout_but_standalone_does_not(self):
        attachment = self.source.arsenal_cfg.attachments.add()
        attachment.name, attachment.mesh_object, attachment.kind = 'Silencer', self.silencer, 'silencer'
        scene = inventory.ensure_scene(bpy.context, self.source)
        original_material = bpy.data.materials.new('Body Material')
        body = next(obj for obj in scene.arsenal_inventory.geometry.objects
                    if obj['arsenal_inventory_source'] == self.body)
        body.data.materials.append(original_material)
        for family in ('inventory', 'upgrade', 'standalone'):
            def cancelled(**kwargs):
                visible = {obj['arsenal_inventory_source'] for obj in scene.arsenal_inventory.geometry.objects
                           if not obj.hide_render}
                self.assertEqual(visible, {self.silencer} if family == 'standalone'
                                 else {self.body, self.full, self.silencer})
                self.assertEqual(scene.camera, {'upgrade': state.upgrade_camera,
                                                'standalone': state.standalone_camera}.get(
                    family, state.inventory_camera))
                return {'CANCELLED'}
            state = scene.arsenal_inventory
            stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
            with patch.object(inventory, 'sync_geometry'), patch.object(inventory, 'bpy', stub):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    inventory.render_preview(bpy.context, self.source, family, attachment_index=0)
            self.assertEqual(list(body.data.materials), [original_material])
        self.assertNotIn('Arsenal Render Holdout', bpy.data.materials)

    def test_stock_attachment_layers_share_camera_and_holdouts(self):
        cfg = self.source.arsenal_cfg
        cfg.allow_silencer = True
        cfg.stock_silencer_images.mesh_object = self.silencer
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory
        self.assertNotIn(self.silencer, {
            obj['arsenal_inventory_source'] for obj in state.geometry.objects if not obj.hide_render})
        for family in ('inventory', 'upgrade'):
            def cancelled(**kwargs):
                visible = {obj['arsenal_inventory_source'] for obj in state.geometry.objects
                           if not obj.hide_render}
                self.assertEqual(visible, {self.body, self.full, self.silencer})
                self.assertEqual(scene.camera, state.upgrade_camera if family == 'upgrade'
                                 else state.inventory_camera)
                self.assertEqual((scene.render.resolution_x, scene.render.resolution_y), inventory.SIZES[family])
                return {'CANCELLED'}
            stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
            with patch.object(inventory, 'sync_geometry'), patch.object(inventory, 'bpy', stub):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    inventory.render_preview(bpy.context, self.source, family, stock_attachment='silencer')

    def test_stock_layer_selection_export_clearing_and_custom_replacement(self):
        cfg = self.source.arsenal_cfg
        cfg.allow_silencer = True
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'stock.png')
            image = bpy.data.images.new('Stock source', width=10, height=10, alpha=True)
            image.file_format = 'PNG'
            image.save(filepath=path)
            for family in ('inventory', 'upgrade'):
                self.assertEqual(bpy.ops.arsenal.inventory_image_file(
                    filepath=path, family=family, stock_attachment='silencer',
                    magazine_index=-1, attachment_index=-1, upgrade_index=-1), {'FINISHED'})
                target, prop = inventory.image_target(self.source, -1, family, stock_attachment='silencer')
                self.assertEqual(tuple(getattr(target, prop).size), inventory.SIZES[family])
            info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'mount': '/TestMod',
                    'output_root': folder, 'magazines': [], 'attachments': []}
            entries = inventory.export_images(info)
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(entry['sid'] == 'EN_Silen_2' and 'StockSilencer' in entry['asset']
                                for entry in entries))
            self.assertEqual(bpy.ops.arsenal.inventory_image(
                family='inventory', stock_attachment='silencer', clear=True,
                magazine_index=-1, attachment_index=-1), {'FINISHED'})
            self.assertIsNone(cfg.stock_silencer_images.inventory_image)
            self.assertEqual(len(inventory.export_images(info)), 1)
            custom = cfg.attachments.add()
            custom.kind = 'silencer'
            self.assertEqual(inventory.export_images(info), [])
            with self.assertRaisesRegex(RuntimeError, 'Enable this stock attachment'):
                inventory.image_target(self.source, -1, 'inventory', stock_attachment='silencer')

    def test_exported_pngs_and_cfg_references_match_without_using_old_files(self):
        cfg = self.source.arsenal_cfg
        cfg.inventory_image = bpy.data.images.new('Export body', width=258, height=128, alpha=True)
        magazine = cfg.magazines[1]
        magazine.inventory_image = bpy.data.images.new('Export magazine', width=258, height=128, alpha=True)
        magazine.standalone_image = bpy.data.images.new('Export standalone', width=128, height=128, alpha=True)
        info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'Test', 'mount': '/TestMod',
                'player_sid': 'GunTest_Player', 'parts': [],
                'magazines': weapon_cfg.collect_magazines(cfg, [])}
        for item in info['magazines']:
            item['socket'] = 'jnt_magazine'
        with tempfile.TemporaryDirectory() as folder:
            info['output_root'] = folder
            entries = inventory.export_images(info)
            self.assertEqual(len(entries), 3)
            self.assertEqual(inventory.image_asset(info, 'body', 'upgrade'),
                             inventory.image_asset(info, 'body', 'inventory') + '_upgrade')
            for entry, size in zip(entries, ((258, 128), (258, 128), (128, 128))):
                path = os.path.join(folder, entry['file'])
                self.assertTrue(os.path.isfile(path))
                loaded = bpy.data.images.load(path)
                self.assertEqual(tuple(loaded.size), size)
                self.assertEqual(loaded.channels, 4)
                self.assertTrue(entry['asset'].startswith('/TestMod/UI/Arsenal/Test/'))
            reference = weapon_cfg.image_reference(info, magazine, 'inventory', 'MagExtended')
            self.assertIn(entries[1]['asset'], reference)
            self.assertIn(f'Icon = {weapon_cfg.image_reference(info, cfg, "inventory", "body")}',
                          weapon_cfg.weapon_prototypes(info))
            self.assertIn(f'WeaponSpecificIcon = {reference}', weapon_cfg.general_setup(info))
            self.assertIn(f'Icon = {weapon_cfg.image_reference(info, magazine, "standalone", "MagExtended")}',
                          weapon_cfg.attach_prototypes(info))
            magazine.inventory_image = None
            self.assertEqual(weapon_cfg.image_reference(info, magazine, 'inventory', 'MagExtended'), '')
            self.assertEqual(len(inventory.export_images(info)), 2)
            cfg.inventory_image.scale(8, 8)
            with self.assertRaisesRegex(RuntimeError, 'Re-render'):
                inventory.export_images(info)

    def test_holdout_really_masks_hidden_attachment_pixels(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        state = scene.arsenal_inventory
        state.inventory_camera.rotation_euler = (0, 0, 0)
        state.inventory_camera.location = (0, 0, 10)
        state.inventory_camera.data.type = 'ORTHO'
        state.inventory_camera.data.ortho_scale = 4
        scene.render.film_transparent = False
        state.standalone_camera.rotation_euler = (0, 0, 0)
        state.standalone_camera.location = (0, 0, 10)
        state.standalone_camera.data.type = 'ORTHO'
        state.standalone_camera.data.ortho_scale = 4
        # Put the magazine directly behind the weapon body from the Standard camera.
        self.extended.location = (0, 0, -2)
        bpy.context.view_layer.update()
        layer = inventory.render_preview(bpy.context, self.source, 'inventory', 1)
        standalone = inventory.render_preview(bpy.context, self.source, 'standalone', 1)
        self.assertLess(max(list(layer.pixels)[3::4]), 0.01)
        self.assertGreater(max(list(standalone.pixels)[3::4]), 0.9)
        self.assertEqual(state.inventory_camera.location, Vector((0, 0, 10)))
        self.assertFalse(scene.render.film_transparent)

    def test_import_manifest_exports_ui_and_attachment_localization_together(self):
        cfg = self.source.arsenal_cfg
        cfg.inventory_image = bpy.data.images.new('Export body', width=258, height=128, alpha=True)
        item = cfg.attachments.add()
        item.name, item.mesh_object, item.kind = 'Quiet', self.silencer, 'silencer'
        item.text_name = 'Quiet silencer'
        item.upgrade_image = bpy.data.images.new('Upgrade silencer', width=1940, height=800, alpha=True)
        magazine = cfg.magazines[1]
        magazine.use_existing, magazine.existing_sid = True, 'SharedMagazine30'
        magazine.text_name = 'Must not be exported'
        magazine.inventory_image = bpy.data.images.new('Old magazine icon', width=1, height=1, alpha=True)
        magazine.upgrade_image = magazine.inventory_image
        magazine.standalone_image = magazine.inventory_image
        self.source.arsenal_export.unreal_mount = 'TestMod'
        info = {'cfg': cfg, 'sid': 'GunTest', 'weapon_id': 'test', 'mod': 'TestMod', 'mount': '/TestMod',
                'world_mesh': "StaticMesh'/TestMod/SM_test.SM_test'",
                'magazines': [weapon_cfg.collect_magazines(cfg, [])[1]], 'attachments': [
                    {'settings': item, 'sid': 'GunTest_AttachQuiet', 'name': 'Quiet', 'kind': 'silencer'}]}
        with tempfile.TemporaryDirectory() as folder:
            info['output_root'] = folder
            self.source.arsenal_export.output_folder = folder
            static = os.path.join(folder, 'SM_Test.fbx')
            Path(static).touch()
            animations = Path(folder, '_STALKER2', 'Animations', 'Weapons', 'pt', 'test', 'AnimSequences', 'fp')
            animations.mkdir(parents=True)
            fresh = animations / 'AS_test_fp_idle.fbx'
            fresh.touch()
            (animations / 'AS_test_fp_stale_reload.fbx').touch()
            world_sockets = {'version': 1, 'units': 'cm', 'mesh': '/TestMod/SM_test',
                             'entries': [{'name': 'jnt_magazine', 'location': [0, 0, -3],
                                          'rotation': [0, 0, 0], 'scale': [1, 1, 1]}]}
            with patch.object(export_unreal.static_mesh, 'world_mesh_sockets',
                              return_value=world_sockets), \
                    patch.object(export_unreal.animation_export, '_build_static_plan', return_value=(
                    self.rig, None, {}, [('test', 'SM_Test', static)])), \
                    patch.object(export_unreal.animation_export, 'weapon_name', return_value='test'), \
                    patch.object(export_unreal.static_mesh, 'plan_static_meshes', return_value=('test', [])), \
                    patch.object(export_unreal.static_mesh, 'classify_meshes', return_value=(self.body, [], [])), \
                    patch.object(export_unreal.export_skeleton, 'plan_skeleton', side_effect=ValueError('no donor')), \
                    patch.object(weapon_cfg, 'build_context', return_value=info):
                export_unreal.write_unreal_import(bpy.context, animation_paths=[str(fresh)])
                with self.assertRaisesRegex(RuntimeError, 'Fresh animation files are missing'):
                    export_unreal.write_unreal_import(bpy.context, animation_paths=[str(fresh) + '.missing'])
            manifest = json.loads(Path(folder, 'import_test.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['ui_images']), 2)
            self.assertEqual(manifest['animations']['player'], [])
            self.assertEqual(manifest['animations']['weapon'], [fresh.relative_to(folder).as_posix()])
            self.assertEqual(manifest['world_mesh_sockets'], world_sockets)
            self.assertEqual(manifest['magazines'], [
                {'sid': 'SharedMagazine30', 'name': 'Extended', 'preinstalled': False}])
            self.assertEqual(len(manifest['localization']), 1)
            self.assertEqual(manifest['localization'][0]['SID'], 'sid_items_GunTest_AttachQuiet_name')
            self.assertTrue(Path(folder, 'import_test.py').is_file())
            script = Path(folder, 'import_test.py').read_text(encoding='utf-8')
            self.assertIn('def import_ui_images', script)
            self.assertEqual(manifest['setup']['weapon'], 'test')
            self.assertEqual(manifest['setup']['mod'], 'TestMod')
            self.assertFalse(manifest['setup']['export'])
            self.assertFalse(manifest['setup']['dry_run'])
            self.assertEqual(manifest['distribution']['weapon'], 'test')
            self.assertEqual(manifest['distribution']['mod'], 'TestMod')
            parsed = ast.parse(script)
            composer = next(ast.literal_eval(node.value) for node in parsed.body
                            if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == 'DISTRIBUTION_SOURCE'
                                    for target in node.targets))
            compile(composer, 'embedded_distribution', 'exec')
            defaults = next(ast.literal_eval(node.value) for node in parsed.body
                            if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == 'DISTRIBUTION_DEFAULTS'
                                    for target in node.targets))
            self.assertIn('pistols', defaults)
            embedded = next(ast.literal_eval(node.value) for node in parsed.body
                            if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == 'SETUP_SOURCE'
                                    for target in node.targets))
            self.assertIn('def ensure_mod_assets', embedded)
            self.assertNotIn("if unreal is not None or __name__", embedded)
            setup_ast = ast.parse(embedded)
            patcher = next(ast.literal_eval(node.value) for node in setup_ast.body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == 'PATCHER_SOURCE'
                                   for target in node.targets))
            compile(patcher, 'embedded_patcher', 'exec')
        self.assertIsNotNone(magazine.inventory_image)
        for family in ('inventory', 'upgrade', 'standalone'):
            with self.assertRaisesRegex(RuntimeError, 'owning mod'):
                inventory.image_target(self.source, 1, family)

    def test_render_recreates_deleted_scene_without_manual_setup(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        bpy.data.scenes.remove(scene, do_unlink=True)
        self.assertIsNone(self.source.arsenal_inventory.render_scene)

        def cancelled(**kwargs):
            recreated = self.source.arsenal_inventory.render_scene
            self.assertIsNotNone(recreated)
            self.assertEqual(recreated.arsenal_inventory.source_scene, self.source)
            self.assertTrue(recreated.arsenal_inventory.geometry.objects)
            self.assertEqual(recreated.camera, recreated.arsenal_inventory.standalone_camera)
            for family in inventory.CAMERAS:
                self.assertEqual(getattr(recreated.arsenal_inventory, f'{family}_camera').data.clip_start, 1.0)
            return {'CANCELLED'}

        stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
        with patch.object(inventory, 'bpy', stub):
            with self.assertRaisesRegex(RuntimeError, 'Inventory render was cancelled'):
                bpy.ops.arsenal.inventory_image(family='standalone', magazine_index=1)
        self.assertEqual(bpy.context.scene, self.source)
        self.assertEqual(self.source.frame_current, 37)

    def test_render_from_manually_selected_scene_refreshes_geometry_and_preserves_cameras(self):
        scene = inventory.ensure_scene(bpy.context, self.source)
        bpy.context.window.scene = scene
        self.body.data.vertices[0].co.x += 2
        state = scene.arsenal_inventory
        state.inventory_camera.location.x += 7
        scene.view_layers[inventory.LAYER_NAME].update()
        cameras = {family: getattr(state, f'{family}_camera').matrix_world.copy()
                   for family in inventory.CAMERAS}

        def cancelled(**kwargs):
            clone = next(obj for obj in state.geometry.objects if obj['arsenal_inventory_source'] == self.body)
            self.assertEqual(clone.data.vertices[0].co, self.body.data.vertices[0].co)
            self.assertEqual(scene.camera, state.inventory_camera)
            return {'CANCELLED'}

        stub = SimpleNamespace(data=bpy.data, ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
        with patch.object(inventory, 'bpy', stub):
            with self.assertRaisesRegex(RuntimeError, 'Inventory render was cancelled'):
                bpy.ops.arsenal.inventory_image(family='inventory')
        for family, matrix in cameras.items():
            self.assertEqual(getattr(state, f'{family}_camera').matrix_world, matrix)
        self.assertEqual(bpy.context.scene, scene)
        self.assertEqual(self.source.frame_current, 37)

    def test_import_rigged_weapon_creates_render_scene(self):
        del self.rig[import_weapon.RIG_MARKER]
        with patch.object(import_weapon, 'find_donor_files', return_value=('skeleton.fbx', [])), \
                patch.object(import_weapon, '_import_skeleton', return_value=self.rig), \
                patch.object(import_weapon, '_import_parts', return_value=(self.body, {}, [])), \
                patch.object(import_weapon, 'apply_bone_shapes'), \
                patch.object(import_weapon, 'find_attachment_files', return_value=[]), \
                patch.object(import_weapon, '_import_attachments', return_value=[self.full, self.empty]), \
                patch.object(weapon_cfg, 'fill_attachment_list'), \
                patch.object(import_weapon, 'apply_materials'), \
                patch.object(inventory, 'ensure_scene', wraps=inventory.ensure_scene) as ensure:
            # The actual skeleton importer sets this marker; expose it after the duplicate-import guard.
            def mark_rig(*args):
                self.rig[import_weapon.RIG_MARKER] = True
                return self.rig

            with patch.object(import_weapon, '_import_skeleton', side_effect=mark_rig):
                import_weapon.import_rigged_weapon(bpy.context, 'unused', 'Test')
        ensure.assert_called_once_with(bpy.context, self.source)
        self.assertIsNotNone(self.source.arsenal_inventory.render_scene)

    def test_real_render_packs_images_and_survives_blend_reload(self):
        self.source.arsenal_cfg.allow_silencer = True
        self.source.arsenal_cfg.stock_silencer_images.mesh_object = self.silencer
        scene = inventory.ensure_scene(bpy.context, self.source)
        inventory.fit_cameras(scene)
        cameras = {family: (getattr(scene.arsenal_inventory, f'{family}_camera').matrix_world.copy(),
                            getattr(scene.arsenal_inventory, f'{family}_camera').data.clip_start,
                            getattr(scene.arsenal_inventory, f'{family}_camera').data.clip_end)
                   for family in inventory.CAMERAS}
        body = inventory.render_preview(bpy.context, self.source, 'inventory')
        self.assertEqual(tuple(body.size), (258, 128))
        self.assertIsNotNone(body.packed_file)
        self.assertGreater(body.preview_ensure().image_size[0], 0)
        alpha = list(body.pixels)[3::4]
        self.assertGreater(max(alpha), 0.1)
        self.assertLess(min(alpha), 0.01)
        self.assertEqual(self.source.arsenal_cfg.inventory_image, body)
        stock = inventory.render_preview(bpy.context, self.source, 'inventory', stock_attachment='silencer')
        self.assertEqual(tuple(stock.size), (258, 128))
        self.assertIsNotNone(stock.packed_file)
        self.assertEqual(self.source.arsenal_cfg.stock_silencer_images.inventory_image, stock)
        layer = inventory.render_preview(bpy.context, self.source, 'upgrade', 1)
        self.assertEqual(tuple(layer.size), (1940, 800))
        standalone = inventory.render_preview(bpy.context, self.source, 'standalone', 1)
        self.assertEqual(tuple(standalone.size), inventory.SIZES['standalone'])
        self.assertIsNotNone(standalone.packed_file)
        for family, (matrix, near, far) in cameras.items():
            camera = getattr(scene.arsenal_inventory, f'{family}_camera')
            if family != 'standalone':
                self.assertEqual(camera.matrix_world, matrix)
            self.assertEqual((camera.data.clip_start, camera.data.clip_end), (near, far))
        attachment = self.source.arsenal_cfg.attachments.add()
        attachment.name, attachment.mesh_object, attachment.kind = 'Quiet', self.silencer, 'silencer'
        attachment.text_name = 'Quiet silencer'
        attachment.text_language = 'fr'
        attachment.text_name = 'Silencieux'
        self.source.arsenal_cfg.magazines[1].text_name = 'Extended magazine'
        self.assertEqual(self.source.frame_current, 37)
        self.assertEqual(self.source.render.resolution_x, 333)
        self.assertEqual(bpy.context.scene, self.source)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'inventory_round_trip.blend')
            bpy.data.libraries.write(path, {self.source})
            with bpy.data.libraries.load(path, link=False) as (_available, loaded):
                loaded.scenes = [self.source.name]
            restored = loaded.scenes[0]
            self.assertIsNotNone(restored.arsenal_cfg.inventory_image.packed_file)
            self.assertGreater(restored.arsenal_cfg.inventory_image.preview_ensure().image_size[0], 0)
            self.assertIsNotNone(restored.arsenal_cfg.magazines[1].standalone_image.packed_file)
            self.assertIsNotNone(restored.arsenal_cfg.stock_silencer_images.inventory_image.packed_file)
            self.assertEqual(tuple(restored.arsenal_cfg.stock_silencer_images.inventory_image.size), (258, 128))
            self.assertIsNotNone(restored.arsenal_cfg.stock_silencer_images.mesh_object)
            self.assertEqual(restored.arsenal_inventory.render_scene.arsenal_inventory.source_scene, restored)
            self.assertNotEqual(restored.arsenal_inventory.render_scene, scene)
            self.assertEqual(restored.arsenal_cfg.attachments[0].text_name, 'Silencieux')
            self.assertEqual(restored.arsenal_cfg.attachments[0].texts[0].name, 'Quiet silencer')
            self.assertEqual(restored.arsenal_cfg.magazines[1].text_name, 'Extended magazine')
        result = bpy.ops.arsenal.inventory_image(family='inventory', clear=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertIsNone(self.source.arsenal_cfg.inventory_image)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
