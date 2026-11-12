"""Asset-free packaging regressions: python -m unittest Arsenal.zonekit_tools.test_build_release."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from . import build_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.root = self.folder / 'source'
        self.addon = self.root / build_release.ADDON
        self.addon.mkdir(parents=True)
        (self.addon / '__init__.py').write_text("bl_info = {'version': (1, 0, 0)}\n", encoding='ascii')
        for name in build_release.RESOURCES:
            path = self.addon / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'BLENDER-v test' if path.suffix == '.blend' else b'{}')
        for name in ('LICENSE', 'NOTICE.md'):
            (self.root / name).write_text(name, encoding='ascii')

    def test_package_contains_only_installable_code_resources_and_legal_files(self):
        for name in ('__pycache__/junk.pyc', 'shapes/weapon_bone_shapes.blend1',
                     'resources/export.fbx', 'resources/extracted.png', 'project.blend'):
            path = self.addon / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'not for distribution')
        output = self.folder / 'packages'
        archive = build_release.build(self.root, output, 'v1.0.0')
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(set(package.namelist()), {'stalker2_arsenal/' + name for name in (
                '__init__.py', *build_release.RESOURCES, 'LICENSE', 'NOTICE.md')})
        data = archive.read_bytes()
        checksum = archive.with_suffix('.zip.sha256').read_text(encoding='ascii')
        self.assertIn(hashlib.sha256(data).hexdigest(), checksum)
        self.assertEqual(build_release.build(self.root, output).read_bytes(), data)

    def test_lfs_pointer_missing_resource_wrong_tag_and_in_checkout_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside the repository'):
            build_release.build(self.root, self.root / 'dist')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            build_release.build(self.root, self.folder / 'packages', 'v9.0.0')
        resource = self.addon / 'resources' / 'inventory_scene.blend'
        resource.write_text('version https://git-lfs.github.com/spec/v1\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'git lfs pull'):
            build_release.build(self.root, self.folder / 'packages')
        resource.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            build_release.build(self.root, self.folder / 'packages')


if __name__ == '__main__':
    unittest.main()
