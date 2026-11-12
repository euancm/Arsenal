"""Native struct/map persistence regression, on disposable assets only.

CreatePlainMod.bat ArsenalSocketProbe, then run in ZoneKit:
    py "<path>/test_collection_sids_zonekit.py" --report "<external folder>/collection_proof.json"
Repeat in a FRESH process with the same --report and --verify-saved.
For commandlets, enable the disposable mount with -EnablePlugins=ArsenalSocketProbe.
Never use a real weapon mod as the test destination.
"""
import argparse
import json
from pathlib import Path
import uuid

import unreal


def runtime_module():
    path = Path(__file__).resolve().parents[1] / 'stalker2_arsenal' / 'unreal_import.py'
    source = path.read_text(encoding='utf-8').rsplit('\nif unreal is not None or __name__', 1)[0]
    namespace = {'__name__': 'arsenal_collection_integration', '__file__': str(path)}
    exec(compile(source, str(path), 'exec'), namespace)
    return namespace


def snapshot(collection, fields):
    internal = collection.get_editor_property('internal_animations')
    return {field: {str(key): value.export_text()
                    for key, value in internal.get_editor_property(field).items()} for field in fields}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--verify-saved', action='store_true')
    args, _unknown = parser.parse_known_args()
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    runtime = runtime_module()
    fields = runtime['COLLECTION_SID_MAPS']
    library = unreal.EditorAssetLibrary
    unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(
        ['/ArsenalSocketProbe'], force_rescan=True)
    donor_path = '/Game/_STALKER2/Animations/Weapons/pt/udp/AnimCollections/AnimCollection_fp_udp'
    donor = library.load_asset(donor_path)
    if donor is None:
        raise RuntimeError('Cannot load the UDP collection donor.')
    if args.verify_saved:
        proof = json.loads(report.read_text(encoding='utf-8'))
        runtime['socket_mod_path'](proof['asset'], '/ArsenalSocketProbe')
        collection = library.load_asset(proof['asset'])
        assert snapshot(collection, fields) == proof['expected'], 'SID maps changed after restart'
        assert snapshot(donor, fields) == proof['donor'], 'Shared donor changed'
        proof['fresh_process_verified'] = True
        report.write_text(json.dumps(proof, indent=2), encoding='utf-8')
        unreal.log('PASS: collection SID maps persisted; shared donor is unchanged')
        return
    if not library.does_directory_exist('/ArsenalSocketProbe'):
        raise RuntimeError('Create the disposable ArsenalSocketProbe mod first.')
    target = '/ArsenalSocketProbe/ZZ_Collections_' + uuid.uuid4().hex[:8] + '/AnimCollection_fp_probe'
    collection = library.duplicate_asset(donor_path, target)
    assert collection is not None and library.save_loaded_asset(collection, False)
    original = collection.get_editor_property('internal_animations').copy()
    before = original.export_text()
    donor_before = snapshot(donor, fields)
    importer = runtime['Importer'].__new__(runtime['Importer'])
    importer.library = library
    importer.manifest = {
        'game_root': '/ArsenalSocketProbe', 'weapon': 'probe',
        'magazines': [{'sid': 'GunProbe_MagDefault', 'name': 'Default', 'preinstalled': True},
                      {'sid': 'GunProbe_MagExtended', 'name': 'Extended', 'preinstalled': False}],
        'attachments': [{'sid': 'EN_Silen_2', 'kind': 'silencer'}]}
    assert importer.sync_collection_sids(collection, {'lines': []}), 'SID update failed'
    assert original.export_text() == before, 'Native rollback snapshot was aliased'
    expected = snapshot(collection, fields)
    assert not importer.sync_collection_sids(collection, {'lines': []}), 'Repeat update was not a no-op'
    assert snapshot(donor, fields) == donor_before, 'Shared donor changed'
    report.write_text(json.dumps({
        'asset': target, 'expected': expected, 'donor': donor_before,
        'fresh_process_verified': False}, indent=2), encoding='utf-8')
    unreal.log('PASS: detached collection update/repeat; now verify in a fresh process')


if __name__ == '__main__':
    main()
