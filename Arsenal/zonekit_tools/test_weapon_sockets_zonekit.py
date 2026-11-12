"""Headless socket integration check; never targets a user's weapon or /Game writes.

Create a disposable mod with CreatePlainMod.bat ArsenalSocketProbe, then run in ZoneKit:
    py "<path>/test_weapon_sockets_zonekit.py" --report "<external folder>/socket_proof.json"
Run again in a FRESH process with the same --report and --verify-saved to check persistence.
Add --fbx <external Arsenal-exported SK_weapon.FBX> to test fresh import and mesh reimport
with a new, mod-owned skeleton rather than a duplicate using the shared donor skeleton.
The first run also exports the socket catalogue beside the report for Blender tests.
Pair it with an existing ZoneKit-exported SK_udp.FBX; no weapon project is bundled.
No asset editor is opened. Generated test content stays in the disposable mod.
"""
import argparse
import json
from pathlib import Path
import tempfile
import uuid

import unreal


def source_module(name):
    path = Path(__file__).resolve().parents[1] / 'stalker2_arsenal' / (name + '.py')
    source = path.read_text(encoding='utf-8')
    if name in ('unreal_import', 'unreal_setup'):
        source = source.rsplit('\nif unreal is not None or __name__', 1)[0]
    namespace = {'__name__': 'arsenal_socket_integration_' + name, '__file__': str(path)}
    exec(compile(source, str(path), 'exec'), namespace)
    return namespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default=str(Path(tempfile.gettempdir()) / 'arsenal_socket_proof.json'))
    parser.add_argument('--verify-saved', action='store_true')
    parser.add_argument('--fbx')
    args, _unknown = parser.parse_known_args()
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    runtime = source_module('unreal_import')
    library = unreal.EditorAssetLibrary
    unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(
        ['/ArsenalSocketProbe'], force_rescan=True)
    donor_path = '/Game/_STALKER2/SkeletalMeshes/weapons/pt/udp/SK_udp'
    donor = library.load_asset(donor_path)
    original = {str(donor.get_socket_by_index(i).get_editor_property('socket_name')):
                runtime['socket_transform'](donor.get_socket_by_index(i)) for i in range(donor.num_sockets())}
    if args.verify_saved:
        proof = json.loads(report.read_text(encoding='utf-8'))
        runtime['socket_mod_path'](proof['mesh'], '/ArsenalSocketProbe')
        mesh = library.load_asset(proof['mesh'])
        assert mesh.get_editor_property('skeleton').get_path_name().split('.')[0] == proof['skeleton']
        for name, expected in proof['expected'].items():
            socket = mesh.find_socket(name)
            assert socket.get_outer() == mesh
            assert runtime['socket_transforms_equal'](runtime['socket_transform'](socket), expected), name
        assert original == proof['source'], 'Shared donor socket values changed'
        proof['fresh_process_verified'] = True
        report.write_text(json.dumps(proof, indent=2), encoding='utf-8')
        unreal.log('PASS: socket owners and transforms persisted; shared donor is unchanged')
        return
    if not library.does_directory_exist('/ArsenalSocketProbe'):
        raise RuntimeError('Create the disposable ArsenalSocketProbe mod first.')
    report.write_text(json.dumps({'stage': 'copying_disposable_mesh'}), encoding='utf-8')
    folder = '/ArsenalSocketProbe/Test_' + uuid.uuid4().hex[:8]
    mesh_path = folder + '/SK_weapon'
    source_skeleton = donor.get_editor_property('skeleton')
    skeleton_path = source_skeleton.get_path_name().split('.')[0]
    importer = runtime['Importer'].__new__(runtime['Importer'])
    importer.library, importer.counts = library, {}
    importer.manifest = {'game_root': '/ArsenalSocketProbe', 'weapon_skeleton': mesh_path}
    if args.fbx:
        fbx = Path(args.fbx).resolve(strict=True)
        importer.tools = unreal.AssetToolsHelpers.get_asset_tools()
        importer.overwrite = True
        importer.plan = {'skeletal_mesh': [(str(fbx), folder, 'SK_weapon')]}
        importer.import_skeletal_mesh()
        mesh = library.load_asset(mesh_path)
        skeleton_path = mesh.get_editor_property('skeleton').get_path_name().split('.')[0]
        runtime['socket_mod_path'](skeleton_path, '/ArsenalSocketProbe')
    else:
        mesh = library.duplicate_asset(donor_path, mesh_path)
    assert mesh is not None
    assert library.save_loaded_asset(mesh), 'Cannot save disposable mesh'
    report.write_text(json.dumps({'stage': 'applying_mesh_only_sockets', 'mesh': mesh_path}), encoding='utf-8')
    setup = source_module('unreal_setup')
    assert mesh.get_editor_property('skeleton').get_path_name().split('.')[0] == skeleton_path
    entries = []
    edited = ('CameraSocket', 'SilencerMuzzleSocket', 'Muzzle')
    for name in original if args.fbx else edited:
        source = donor.find_socket(name)
        assert source is not None
        baseline = runtime['socket_transform'](source)
        desired = json.loads(json.dumps(baseline))
        if name in edited:
            desired['location'][2] += 1
            desired['rotation'][2] += 15
        entries.append({'name': name, 'bone': str(source.get_editor_property('bone_name')),
                        'baseline': baseline, 'transform': desired, 'enabled': name in edited})
    importer.manifest['weapon_sockets'] = {
        'version': 1, 'units': 'cm', 'mesh': mesh_path, 'source_mesh': donor_path, 'entries': entries}
    importer.apply_weapon_sockets()
    for entry in entries:
        assert runtime['socket_transforms_equal'](
            runtime['socket_transform'](mesh.find_socket(entry['name'])), entry['transform'])
    first_counts = dict(importer.counts)
    importer.apply_weapon_sockets()
    assert importer.counts == first_counts, 'Repeat import should not save'
    for entry in entries:
        entry['enabled'] = False
    importer.apply_weapon_sockets()
    for entry in entries:
        assert runtime['socket_transforms_equal'](
            runtime['socket_transform'](mesh.find_socket(entry['name'])), entry['baseline'])
        entry['enabled'] = entry['name'] in edited
    importer.apply_weapon_sockets()
    if args.fbx:
        importer.import_skeletal_mesh()
        mesh = library.load_asset(mesh_path)
        assert mesh.get_editor_property('skeleton').get_path_name().split('.')[0] == skeleton_path
        importer.apply_weapon_sockets()
        for entry in entries:
            assert runtime['socket_transforms_equal'](
                runtime['socket_transform'](mesh.find_socket(entry['name'])), entry['transform'])
    assert original == {str(donor.get_socket_by_index(i).get_editor_property('socket_name')):
                        runtime['socket_transform'](donor.get_socket_by_index(i)) for i in range(donor.num_sockets())}
    proof = {'mesh': mesh_path, 'skeleton': skeleton_path, 'source': original,
             'expected': {entry['name']: entry['transform'] for entry in entries},
             'fresh_process_verified': False, 'mesh_reimport_verified': bool(args.fbx)}
    report.write_text(json.dumps(proof, indent=2), encoding='utf-8')
    unreal.log('Socket writer checks passed; exporting reference-bone catalogue')
    sequences = [str(data.package_name) for data in unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path(
        '/Game/_STALKER2/Animations/Weapons/pt/udp', recursive=True)
        if str(data.asset_name).casefold() == 'as_udp_fp_idle']
    setup['export_sockets']({'selection': {'skeletal_meshes': [donor_path], 'sequences': sequences}},
                            {'export_dir': str(report.parent)})
    unreal.log('PASS: mesh-only socket update/repeat/reset; now verify in a fresh process')


if __name__ == '__main__':
    main()
