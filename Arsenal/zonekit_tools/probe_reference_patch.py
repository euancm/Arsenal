"""Headless probe: do mod assets whose references were patched on disk load, and what do they reference now?

Run with the Stalker2ModEditor Cmd exe (-run=pythonscript -script=<this file> -unattended -nullrhi -stdout).
Set ARSENAL_PROBE_MOD (default JellyfishMod) and ARSENAL_PROBE_WEAPON (default jellyfishgun)."""
import os

import unreal

MOD = os.environ.get('ARSENAL_PROBE_MOD', 'JellyfishMod')
WEAPON = os.environ.get('ARSENAL_PROBE_WEAPON', 'jellyfishgun')
OUTPUT = os.path.join(os.environ.get('TEMP', '.'), 'zk_probe_refs.txt')
LINES = []


def out(text):
    LINES.append(text)
    unreal.log('PROBE ' + text)


def main():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([f'/{MOD}'], True)
    library = unreal.EditorAssetLibrary
    options = unreal.AssetRegistryDependencyOptions()
    for name in ('include_soft_package_references', 'include_hard_package_references'):
        options.set_editor_property(name, True)
    wanted = ('AnimBP_', 'AnimCollection_', 'SK_', 'MG_fp_', 'AS_fp_', 'MG_', 'AS_')
    paths = library.list_assets(f'/{MOD}/_STALKER2', recursive=True, include_folder=False)
    sample = {}
    for path in paths:
        leaf = path.rsplit('/', 1)[-1].split('.')[0]
        for prefix in wanted:
            if leaf.startswith(prefix):
                sample.setdefault(prefix, []).append(path)
                break
    picks = []
    for prefix in wanted[:5]:
        picks += sample.get(prefix, [])[:3]
    for path in picks:
        package = path.split('.')[0]
        asset = library.load_asset(path)
        out(f'{package}: loaded={asset is not None} class={type(asset).__name__}')
        template = [str(d) for d in (registry.get_dependencies(package, options) or []) if str(d).startswith('/Game/')
                    and ('udp' in str(d).lower())]
        mod_deps = [str(d) for d in (registry.get_dependencies(package, options) or []) if str(d).startswith(f'/{MOD}/')]
        out(f'   deps: {len(mod_deps)} in mod, template /Game refs: {template[:4]}')
        if asset is not None and isinstance(asset, unreal.AnimMontage):
            reference = asset.get_first_anim_reference()
            out(f'   montage first reference: {reference.get_path_name() if reference else None}; '
                f'slots={[str(s) for s in asset.get_editor_property("slot_anim_tracks")][:1]}')
    with open(OUTPUT, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(LINES))


main()
