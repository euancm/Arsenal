"""Probe 4: can a montage's .uasset be patched on disk and reloaded in the editor? (headless or interactive)

Loads a mod montage that still references a /Game sequence, records its slot, length, sections, notifies and first
animation, patches the file with uasset_patch.patch_file, reloads the package and records everything again.
Set MODE through the ARSENAL_PROBE_MODE environment variable: 'patch' (default) does the patch and reload test;
'verify' only reports the current state (run it in a fresh process to prove the patched file loads cold).
Only the mod's own file is changed, and a .bak is kept next to it.
"""

import importlib.util
import os

import unreal

MOD_CONTENT = r'X:\STALKER2ZoneKit\Stalker2\Mods\HyenaMod\Content'
MONTAGE = '/HyenaMod/_STALKER2/Animations/Player/AnimSequences/pt/hyenagun/EmptyClick/MG_fp_hyenagun_empty_click'
OLD = '/Game/_STALKER2/Animations/Player/AnimSequences/pt/udp/EmptyClick/AS_fp_udp_empty_click'
NEW = '/HyenaMod/_STALKER2/Animations/Player/AnimSequences/pt/hyenagun/EmptyClick/AS_fp_hyenagun_empty_click'
PATCHER = r'X:\STALKER2ZoneKit\Stalker2\Mods\Glock\Arsenal\stalker2_arsenal\uasset_patch.py'
OUTPUT = os.path.join(os.environ.get('TEMP', '.'), 'zk_probe4.txt')
LINES = []


def out(message):
    LINES.append(str(message))
    unreal.log(f'[Arsenal probe4] {message}')


def stats(label, montage):
    out(f'--- {label}')
    ref = montage.get_first_anim_reference()
    out(f'first reference: {ref.get_path_name() if ref else None}')
    out(f'slots: {[str(s) for s in unreal.AnimationLibrary.get_montage_slot_names(montage)]}')
    out(f'length: {montage.sequence_length}')
    out(f'sections: {[str(montage.get_section_name(i)) for i in range(montage.get_num_sections())]}')
    try:
        events = unreal.AnimationLibrary.get_animation_notify_events(montage)
        out(f'notify events: {len(events)} {[str(e.get_editor_property("notify_name")) for e in events][:12]}')
    except Exception as error:
        out(f'notify events: unavailable ({error})')
    out(f'skeleton: {montage.get_skeleton().get_path_name() if montage.get_skeleton() else None}')


def on_disk_path(package):
    return os.path.join(MOD_CONTENT, package.replace('/HyenaMod/', '').replace('/', os.sep) + '.uasset')


def release(montage):
    """A loaded package keeps its file open; saving it first lets the file be rewritten."""
    return unreal.EditorAssetLibrary.save_loaded_asset(montage, False)


def reload_package(montage):
    mode = unreal.ReloadPackagesInteractionMode
    out(f'ReloadPackagesInteractionMode members: {[n for n in dir(mode) if n.isupper()]}')
    choice = getattr(mode, 'ASSUME_POSITIVE', None)
    return unreal.EditorLoadingAndSavingUtils.reload_packages([montage.get_package()], choice)


def main():
    out('mode ' + os.environ.get('ARSENAL_PROBE_MODE', 'reload'))
    spec = importlib.util.spec_from_file_location('uasset_patch', PATCHER)
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    path = on_disk_path(MONTAGE)
    mapping = {OLD: NEW, OLD.rsplit('/', 1)[1]: NEW.rsplit('/', 1)[1]}
    original = os.path.join(os.environ.get('TEMP', '.'), 'MG_empty_click_original.uasset')
    with open(original, 'rb') as source, open(path, 'wb') as target:
        target.write(source.read())
    out(f'patched BEFORE the editor loads the package: {patcher.patch_file(path, mapping)} names')
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous(['/HyenaMod'], True)
    montage = unreal.EditorAssetLibrary.load_asset(MONTAGE)
    if montage is None:
        out('montage did not load')
        with open(OUTPUT, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(LINES))
        return
    stats('1. cold load of a file patched before first load (expect mod reference)', montage)
    out(f'release: {release(montage)}')
    with open(original, 'rb') as source, open(path, 'wb') as target:
        target.write(source.read())
    out('restored the unpatched file on disk')
    try:
        out(f'reload_packages: {reload_package(montage)!r}')
    except Exception as error:
        out(f'reload_packages FAILED: {type(error).__name__}: {error}')
    montage = unreal.EditorAssetLibrary.load_asset(MONTAGE)
    stats('2. after restoring the original and reloading (expect /Game reference)', montage)
    out(f'release: {release(montage)}')
    out(f'patched {patcher.patch_file(path, mapping, backup_dir=os.path.join(os.environ.get("TEMP", "."), "arsenal_backups"))} names')
    try:
        out(f'reload_packages: {reload_package(montage)!r}')
    except Exception as error:
        out(f'reload_packages FAILED: {type(error).__name__}: {error}')
    montage = unreal.EditorAssetLibrary.load_asset(MONTAGE)
    stats('3. after patching and reloading (expect mod reference)', montage)
    reference = montage.get_first_anim_reference()
    out(f'save after reload leaves the patch in place: {unreal.EditorAssetLibrary.save_loaded_asset(montage, False)}')
    stats('4. after a forced editor save', unreal.EditorAssetLibrary.load_asset(MONTAGE))
    with open(OUTPUT, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(LINES))


main()