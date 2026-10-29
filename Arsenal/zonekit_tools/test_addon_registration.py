"""Check registration, reload and bundled workflow resources in a disposable Blender scene.

blender --background --factory-startup --python-exit-code 1 --python test_addon_registration.py
"""
import ast
import importlib
from pathlib import Path
import sys
import unittest

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stalker2_arsenal as addon
from stalker2_arsenal import import_weapon, map_bones, mapping_editor, retarget_animation


class AddonRegistrationTests(unittest.TestCase):
    def test_registration_reload_and_unregister(self):
        properties = (
            'stalker2_animation_importer', 'arsenal_export', 'arsenal_cfg',
            'arsenal_setup', 'arsenal_ui',
        )
        for _ in range(2):
            addon.register()
            try:
                for name in properties:
                    self.assertTrue(hasattr(bpy.types.Scene, name), name)
                self.assertIn(
                    'object.arsenal_convert_to_rigify_by_mapping',
                    {cls.bl_idname for cls in addon.classes if issubclass(cls, bpy.types.Operator)},
                )
                self.assertNotIn('active_template', bpy.context.scene.arsenal_ui.bl_rna.properties)
            finally:
                addon.unregister()
            for name in properties:
                self.assertFalse(hasattr(bpy.types.Scene, name), name)
            importlib.reload(addon)

    def test_relative_imports_exist(self):
        package = Path(addon.__file__).parent
        for source in package.glob('*.py'):
            tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    names = [node.module.split('.')[0]] if node.module else [
                        alias.name for alias in node.names if alias.name != 'bl_info'
                    ]
                    for name in names:
                        self.assertTrue((package / (name + '.py')).is_file(), (source.name, name))

    def test_required_mapping_resources(self):
        reference = dict(map_bones.load_mapping('uemannequin_rigify'))
        self.assertEqual(reference['hand_l'], 'hand.L')
        self.assertTrue(map_bones.load_mapping('rigify_uemannequin', anim=True))
        self.assertEqual(
            mapping_editor.build_mapping_guesses(['jnt_l_hand', 'jnt_r_hand'], ['hand.L', 'hand.R']),
            {'jnt_l_hand': 'hand.L', 'jnt_r_hand': 'hand.R'},
        )
        bpy.ops.object.armature_add()
        source = bpy.context.object
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            source.data.edit_bones[0].name = 'jnt_l_hand'
            bpy.ops.object.mode_set(mode='OBJECT')
            rig = bpy.data.objects.new('Test rig', bpy.data.armatures.new('Test rig'))
            bpy.context.scene.collection.objects.link(rig)
            try:
                bpy.context.view_layer.objects.active = rig
                bpy.ops.object.mode_set(mode='EDIT')
                bone = rig.data.edit_bones.new('hand_fk.L')
                bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
                bpy.ops.object.mode_set(mode='OBJECT')
                resolved, _missing = retarget_animation.resolve_animation_mapping(source, rig)
                self.assertIn(('hand_fk.L', 'jnt_l_hand', 'rot'), resolved)
            finally:
                data = rig.data
                bpy.data.objects.remove(rig, do_unlink=True)
                bpy.data.armatures.remove(data)
        finally:
            data = source.data
            bpy.data.objects.remove(source, do_unlink=True)
            bpy.data.armatures.remove(data)

    def test_shape_library_exists(self):
        with bpy.data.libraries.load(import_weapon.SHAPE_LIBRARY, link=False) as (source, _destination):
            self.assertTrue(source.objects)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
