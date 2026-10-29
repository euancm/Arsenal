"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stalker2_arsenal import map_bones
import stalker2_arsenal as addon


class MappingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bundled = root / 'bundled'
        self.bundled.mkdir()
        self.user = root / 'user'
        self.reference = [['hand_l', 'hand.L']]
        (self.bundled / 'reference.json').write_text(json.dumps(self.reference), encoding='utf-8')
        self.enterContext(patch.object(map_bones, 'mappings_folder', str(self.bundled)))
        self.enterContext(patch.object(map_bones, 'anim_mappings_folder', str(self.bundled)))
        self.resource = self.enterContext(patch.object(bpy.utils, 'user_resource', self.user_resource))

    def user_resource(self, resource_type, *, path, create=False):
        self.assertEqual(resource_type, 'DATAFILES')
        self.assertEqual(os.path.dirname(path), 'stalker2_arsenal')
        folder = self.user / os.path.basename(path)
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        return str(folder)

    def test_reads_bundled_without_creating_user_directory(self):
        self.assertEqual(map_bones.load_mapping('reference'), self.reference)
        self.assertEqual(map_bones.get_mappings(None, None), [('reference',) * 3])
        self.assertFalse(map_bones.has_mapping('missing'))
        self.assertFalse(self.user.exists())

    def test_save_reload_list_and_remove_user_mapping(self):
        for anim in (False, True):
            with self.subTest(anim=anim):
                map_bones.save_mapping('generated', self.reference, anim=anim)
                folder = self.user / ('animation_mappings' if anim else 'mappings')
                self.assertTrue((folder / 'generated.json').is_file())
                self.assertFalse((self.bundled / 'generated.json').exists())
                self.assertTrue(map_bones.has_mapping('generated', anim=anim))
                self.assertEqual(map_bones.load_mapping('generated', anim=anim), self.reference)
                listing = map_bones.get_anim_mappings if anim else map_bones.get_mappings
                self.assertEqual(listing(None, None), [('generated',) * 3, ('reference',) * 3])
                map_bones.remove_mapping('generated', anim=anim)
                self.assertFalse(map_bones.has_mapping('generated', anim=anim))
                self.assertTrue(map_bones.has_mapping('reference', anim=anim))

    def test_bundled_references_are_read_only_and_take_precedence(self):
        for anim in (False, True):
            with self.subTest(anim=anim):
                folder = Path(map_bones.user_mappings_folder(anim=anim, create=True))
                (folder / 'reference.json').write_text('[]', encoding='utf-8')
                self.assertEqual(map_bones.load_mapping('reference', anim=anim), self.reference)
                with self.assertRaisesRegex(ValueError, 'read-only'):
                    map_bones.save_mapping('reference', [], anim=anim)
                with self.assertRaisesRegex(ValueError, 'read-only'):
                    map_bones.remove_mapping('reference', anim=anim)
                self.assertEqual(json.loads((self.bundled / 'reference.json').read_text()), self.reference)

    def test_invalid_names_cannot_escape_user_directory(self):
        for name in ('', '..', '../outside', r'..\outside', r'C:\outside', 'bad:name'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                map_bones.save_mapping(name, [])
        self.assertFalse(self.user.exists())

    def test_unavailable_directory_and_write_errors_are_reported(self):
        with patch.object(bpy.utils, 'user_resource', return_value=''):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                map_bones.save_mapping('generated', [])
        with patch('builtins.open', side_effect=PermissionError('Not writable')):
            with self.assertRaises(PermissionError):
                map_bones.save_mapping('generated', [])

    def test_guess_and_autosave_use_user_directory(self):
        addon.register()
        try:
            (self.bundled / 'uemannequin_rigify.json').write_text(
                json.dumps(self.reference), encoding='utf-8')
            bpy.ops.object.armature_add()
            armature = bpy.context.object
            armature.name = 'Storage Test'
            try:
                bpy.ops.object.mode_set(mode='EDIT')
                armature.data.edit_bones[0].name = 'jnt_l_hand'
                bpy.ops.object.mode_set(mode='OBJECT')
                ui = bpy.context.scene.arsenal_ui
                ui.active_mapping = 'uemannequin_rigify'
                area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
                with bpy.context.temp_override(area=area):
                    self.assertEqual(bpy.ops.object.arsenal_generate_mapping_guess(), {'FINISHED'})
                    self.assertEqual(ui.active_mapping, 'storage_test_to_rigify')
                    self.assertEqual(map_bones.load_mapping(ui.active_mapping), [['jnt_l_hand', 'hand.L']])
                    self.assertEqual(bpy.ops.object.arsenal_generate_mapping_guess(), {'FINISHED'})
                    self.assertEqual(ui.active_mapping, 'storage_test_to_rigify')
                ui.mapping_entries[0].bone_from = 'edited_hand'
                self.assertEqual(map_bones.load_mapping(ui.active_mapping), [['edited_hand', 'hand.L']])
                self.assertEqual(
                    sorted(path.name for path in self.bundled.iterdir()),
                    ['reference.json', 'uemannequin_rigify.json'],
                )
                self.assertEqual(
                    [path.name for path in (self.user / 'mappings').iterdir()],
                    ['storage_test_to_rigify.json'],
                )
            finally:
                data = armature.data
                bpy.data.objects.remove(armature, do_unlink=True)
                bpy.data.armatures.remove(data)
        finally:
            addon.unregister()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
