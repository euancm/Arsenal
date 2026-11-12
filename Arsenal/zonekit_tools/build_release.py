"""Build a ready-to-install Blender add-on zip, never Python bytecode.

python build_release.py OUTPUT_FOLDER [--tag v1.0.0]
The output folder must be outside the repository. No Blender installation is needed.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ADDON = Path('Arsenal') / 'stalker2_arsenal'
RESOURCES = (
    'animation_mappings/rigify_uemannequin.json',
    'mappings/uemannequin_rigify.json',
    'resources/distribution_defaults.json',
    'resources/upgrade_defaults.json',
    'resources/weapon_templates.json',
    'resources/inventory_scene.blend',
    'shapes/weapon_bone_shapes.blend',
)


def build(root, output_folder, tag=None):
    root, output_folder = Path(root).resolve(), Path(output_folder).resolve()
    if output_folder == root or root in output_folder.parents:
        raise ValueError('Release packages must be written outside the repository.')
    source = root / ADDON
    tree = ast.parse((source / '__init__.py').read_text(encoding='utf-8'))
    info = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'bl_info' for target in node.targets))
    version = '.'.join(map(str, info['version']))
    if tag is not None and tag != f'v{version}':
        raise ValueError(f'Tag {tag!r} does not match add-on version v{version}.')
    files = [(path, Path('stalker2_arsenal') / path.name) for path in sorted(source.glob('*.py'))]
    files.extend((source / name, Path('stalker2_arsenal') / name) for name in RESOURCES)
    files.extend((root / name, Path('stalker2_arsenal') / name) for name in ('LICENSE', 'NOTICE.md'))
    for path, _archive_path in files:
        if not path.is_file() or path.is_symlink() or source.is_symlink():
            raise ValueError(f'Missing or linked package input: {path}')
        data = path.read_bytes()
        if path.suffix == '.py':
            compile(data, str(path), 'exec')
        elif path.suffix == '.json':
            json.loads(data)
        elif path.suffix == '.blend':
            if not data.startswith((b'BLENDER', b'\x28\xb5\x2f\xfd', b'\x1f\x8b')):
                raise ValueError(f'{path} is not Blender data. Run git lfs pull before packaging.')
    output_folder.mkdir(parents=True, exist_ok=True)
    archive = output_folder / f'stalker2_arsenal-{version}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path, archive_path in files:
            entry = zipfile.ZipInfo(archive_path.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, path.read_bytes(), compresslevel=9)
    with zipfile.ZipFile(archive) as package:
        failed = package.testzip()
        if failed:
            raise ValueError(f'Corrupt package entry: {failed}')
    checksum = archive.with_suffix('.zip.sha256')
    checksum.write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n', encoding='ascii')
    print(f'{archive} ({archive.stat().st_size:,} bytes, {len(files)} files)')
    print(checksum)
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_folder', type=Path)
    parser.add_argument('--tag')
    args = parser.parse_args()
    build(ROOT, args.output_folder, args.tag)
