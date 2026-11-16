"""Native custom-attachment alias regression, on disposable assets only.

A custom optic made from a donor that stays configured (EN_GoloScope_1) needs its own
AttachingBySID entry and an attach montage whose AttachItem notifies spawn the custom SID.

CreatePlainMod.bat ArsenalSocketProbe, then run in ZoneKit:
    py "<path>/test_attachment_alias_zonekit.py" --report "<external folder>/alias_proof.json"
Repeat in a FRESH process with the same --report and --verify-saved.
For commandlets, enable the disposable mount with -EnablePlugins=ArsenalSocketProbe.
Never use a real weapon mod as the test destination.
"""
import argparse
import json
from pathlib import Path
import uuid

import unreal

MOUNT = '/ArsenalSocketProbe'
DONOR_COLLECTION = '/Game/_STALKER2/Animations/Weapons/ar/M16/AnimCollections/AnimCollection_fp_M16'
SOURCE = 'EN_GoloScope_1'
CUSTOM = 'GunProbe_AttachDot'


def runtime_module():
    path = Path(__file__).resolve().parents[1] / 'stalker2_arsenal' / 'unreal_import.py'
    source = path.read_text(encoding='utf-8').rsplit('\nif unreal is not None or __name__', 1)[0]
    namespace = {'__name__': 'arsenal_alias_integration', '__file__': str(path)}
    exec(compile(source, str(path), 'exec'), namespace)
    return namespace


def attaching(collection):
    return collection.get_editor_property('internal_animations').get_editor_property('attaching_by_sid')


def snapshot(collection):
    return {str(key): value.export_text() for key, value in attaching(collection).items()}


def notify_sids(montage):
    return [str(event.get_editor_property('notify').get_editor_property('binded_attach_sid'))
            for event in unreal.AnimationLibrary.get_animation_notify_events(montage)
            if event.get_editor_property('notify') is not None
            and event.get_editor_property('notify').get_class().get_name() == 'AnimNotify_AttachItem']


def package(asset):
    return str(asset.get_path_name()).split('.')[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--verify-saved', action='store_true')
    args, _unknown = parser.parse_known_args()
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    runtime = runtime_module()
    library = unreal.EditorAssetLibrary
    unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous([MOUNT], force_rescan=True)
    donor = library.load_asset(DONOR_COLLECTION)
    if donor is None:
        raise RuntimeError('Cannot load the M16 collection donor.')
    if args.verify_saved:
        proof = json.loads(report.read_text(encoding='utf-8'))
        for path in (proof['asset'], proof['copied_montage']):
            runtime['socket_mod_path'](path, MOUNT)
        collection = library.load_asset(proof['asset'])
        assert snapshot(collection) == proof['expected'], 'AttachingBySID changed after restart'
        copied = library.load_asset(proof['copied_montage'])
        assert copied is not None and notify_sids(copied) == proof['copied_sids'], 'Copied notifies changed'
        assert snapshot(donor) == proof['donor'], 'Shared donor changed'
        proof['fresh_process_verified'] = True
        report.write_text(json.dumps(proof, indent=2), encoding='utf-8')
        unreal.log('PASS: alias entry and copied montage persisted; shared donor is unchanged')
        return
    if not library.does_directory_exist(MOUNT):
        raise RuntimeError('Create the disposable ArsenalSocketProbe mod first.')
    donor_before = snapshot(donor)
    donor_entry = next(value for key, value in attaching(donor).items() if str(key) == SOURCE)
    donor_attach = donor_entry.get_editor_property('attach_animation').get_editor_property('character')
    assert SOURCE in notify_sids(donor_attach), 'Donor attach montage does not spawn the donor SID'
    folder = f'{MOUNT}/ZZ_Alias_{uuid.uuid4().hex[:8]}'
    collection = library.duplicate_asset(DONOR_COLLECTION, folder + '/AnimCollection_fp_probe')
    montage_path = f'{folder}/MG_fp_probe_sight_attach'
    montage = library.duplicate_asset(package(donor_attach), montage_path)
    assert collection is not None and montage is not None
    # Make the copied collection's donor entry point at the mod-owned montage, as setup does.
    internal = collection.get_editor_property('internal_animations').copy()
    entries = dict(internal.get_editor_property('attaching_by_sid'))
    key = next(key for key in entries if str(key) == SOURCE)
    entry = entries[key].copy()
    attach = entry.get_editor_property('attach_animation').copy()
    attach.set_editor_property('character', montage)
    entry.set_editor_property('attach_animation', attach)
    entries[key] = entry
    internal.set_editor_property('attaching_by_sid', entries)
    collection.set_editor_property('internal_animations', internal)
    assert library.save_loaded_asset(collection, False) and library.save_loaded_asset(montage, False)
    mod_entry = snapshot(collection)[SOURCE]

    importer = runtime['Importer'].__new__(runtime['Importer'])
    importer.library = library
    importer.manifest = {'game_root': MOUNT, 'weapon': 'probe', 'attachments': [
        {'sid': SOURCE, 'source_sid': SOURCE},
        {'sid': CUSTOM, 'kind': 'scope', 'source_sid': SOURCE}]}
    lines = {'lines': []}
    assert importer.sync_collection_sids(collection, lines), 'Alias update failed'
    expected = snapshot(collection)
    assert expected[SOURCE] == mod_entry, 'Donor entry changed'
    copied_path = f'{montage_path}_{CUSTOM}'
    alias = next(value for key, value in attaching(collection).items() if str(key) == CUSTOM)
    copied = alias.get_editor_property('attach_animation').get_editor_property('character')
    assert package(copied) == copied_path, f'Alias plays {package(copied)}'
    copied_sids = notify_sids(copied)
    assert copied_sids and set(copied_sids) == {CUSTOM}, copied_sids
    assert SOURCE in notify_sids(montage), 'Original montage notifies changed'
    assert not importer.sync_collection_sids(collection, {'lines': []}), 'Repeat update was not a no-op'
    assert snapshot(donor) == donor_before, 'Shared donor changed'
    report.write_text(json.dumps({
        'asset': package(collection), 'copied_montage': copied_path, 'copied_sids': copied_sids,
        'lines': lines['lines'], 'expected': expected, 'donor': donor_before,
        'fresh_process_verified': False}, indent=2), encoding='utf-8')
    unreal.log('PASS: alias entry and copied montage created; now verify in a fresh process')


if __name__ == '__main__':
    main()
