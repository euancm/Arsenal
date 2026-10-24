"""Probe how to point a montage at a different sequence by replacing references (run inside ZoneKit).

Paste this file's path into the ZoneKit Python bar. It lists every function in the unreal module that could
replace references (consolidate / replace / redirect / fix), then tests them on scratch assets only, under
/<MOD>/ZZ_ArsenalProbe3 (deleted at the end):

  1  EditorAssetLibrary.consolidate_assets(keep, [replace]) on a scratch montage built from the replaced sequence
  2  The same through a duplicate of a real montage whose reference is a /Game sequence, using scratch
     duplicates only (the /Game asset is never passed to a function that deletes)
  3  Whether rename_assets leaves the montage pointing at the renamed sequence (the normal fix-up path)
  4  Whether the montage keeps its slot name through each step

Nothing in /Game is modified. Set MOD to a mod that holds the imported montages and sequences.
The result is written to montage_reference_output.txt next to this script and to the Output Log.
"""

import os

import unreal

MOD = 'MouseMod'
MONTAGE_HINT = 'MG_fp_mousegun_reload_increased_one_hand'
SEQUENCE_HINT = 'AS_fp_mousegun_shoot'
SCRATCH = f'/{MOD}/ZZ_ArsenalProbe3'
LINES = []
KEYWORDS = ('consolidat', 'replace_ref', 'replacereference', 'redirect', 'fixup', 'fix_up', 'swap_ref', 'remap')


def out(message):
    LINES.append(message)
    unreal.log(f'[Arsenal probe3] {message}')


def attempt(label, function):
    try:
        result = function()
        out(f'  OK    {label}: {result!r}'[:500])
        return result
    except Exception as error:
        out(f'  FAIL  {label}: {type(error).__name__}: {error}'[:500])
        return None


def find(class_name, hint):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for data in sorted(registry.get_assets_by_path(f'/{MOD}', recursive=True),
                       key=lambda d: str(d.get_editor_property('package_name'))):
        if class_name in str(data.get_editor_property('asset_class_path')) \
                and hint.lower() in str(data.get_editor_property('package_name')).lower():
            return str(data.get_editor_property('package_name'))
    return None


def reference(montage):
    ref = montage.get_first_anim_reference()
    return ref.get_path_name() if ref else None


def slots(montage):
    return [str(s) for s in unreal.AnimationLibrary.get_montage_slot_names(montage)]


def list_candidates():
    out('0. Functions that could replace references')
    for name in sorted(dir(unreal)):
        try:
            owner = getattr(unreal, name)
        except Exception:
            continue
        if not isinstance(owner, type):
            continue
        for attribute in dir(owner):
            if any(word in attribute.lower() for word in KEYWORDS):
                doc = (getattr(getattr(owner, attribute, None), '__doc__', '') or '').replace('\n', ' ')[:160]
                out(f'  unreal.{name}.{attribute}: {doc}')


def main():
    list_candidates()
    montage_path = find('AnimMontage', MONTAGE_HINT)
    sequence_path = find('AnimSequence', SEQUENCE_HINT)
    out(f'montage {montage_path}; replacement sequence {sequence_path}')
    if not montage_path or not sequence_path:
        out('Nothing matched the hints; edit MONTAGE_HINT / SEQUENCE_HINT.')
        flush()
        return
    library = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    library.make_directory(SCRATCH)

    out('1. consolidate_assets on scratch sequences')
    attempt('duplicate old sequence', lambda: library.duplicate_asset(sequence_path, f'{SCRATCH}/ZZ_OldSeq'))
    attempt('duplicate new sequence', lambda: library.duplicate_asset(sequence_path, f'{SCRATCH}/ZZ_NewSeq'))
    old_seq = library.load_asset(f'{SCRATCH}/ZZ_OldSeq')
    new_seq = library.load_asset(f'{SCRATCH}/ZZ_NewSeq')
    attempt('duplicate real montage', lambda: library.duplicate_asset(montage_path, f'{SCRATCH}/ZZ_Montage'))
    real = library.load_asset(f'{SCRATCH}/ZZ_Montage')
    out(f'  original slots {slots(real)}; plays {reference(real)}')

    factory = unreal.AnimMontageFactory()
    factory.set_editor_property('source_animation', old_seq)
    built = attempt('build montage from old sequence', lambda: tools.create_asset('ZZ_Built', SCRATCH, unreal.AnimMontage, factory))
    if built is not None:
        out(f'  built montage plays {reference(built)}')
        consolidate = getattr(library, 'consolidate_assets', None)
        out(f'  EditorAssetLibrary.consolidate_assets exists: {consolidate is not None}')
        if consolidate is not None:
            attempt('consolidate_assets(new, [old])', lambda: consolidate(new_seq, [old_seq]))
            out(f'  built montage now plays {reference(built)}')
            out(f'  old sequence still exists: {library.does_asset_exist(f"{SCRATCH}/ZZ_OldSeq")}')

    out('2. Montage with a /Game reference, replaced through a scratch stand-in')
    game_ref = real.get_first_anim_reference()
    out(f'  real montage copy plays {game_ref.get_path_name() if game_ref else None}')
    if game_ref is not None:
        stand_in_path = f'{SCRATCH}/ZZ_StandIn'
        attempt('duplicate the /Game sequence', lambda: library.duplicate_asset(game_ref.get_path_name().split('.')[0], stand_in_path))
        out('  a duplicate does not take over references to the original, so consolidating it would not change the montage;')
        out('  the real /Game case needs a function that rewrites references without deleting the original (see section 0).')

    out('3. rename_assets fix-up: does a montage follow a renamed sequence?')
    attempt('duplicate sequence', lambda: library.duplicate_asset(sequence_path, f'{SCRATCH}/ZZ_Renameable'))
    renameable = library.load_asset(f'{SCRATCH}/ZZ_Renameable')
    factory2 = unreal.AnimMontageFactory()
    factory2.set_editor_property('source_animation', renameable)
    holder = attempt('build montage on it', lambda: tools.create_asset('ZZ_Holder', SCRATCH, unreal.AnimMontage, factory2))
    if holder is not None and renameable is not None:
        data = unreal.AssetRenameData(renameable, SCRATCH, 'ZZ_Renamed')
        attempt('rename_assets', lambda: tools.rename_assets([data]))
        out(f'  holder plays {reference(holder)}')

    out('4. Slot names')
    out(f'  real montage copy {slots(real)}; factory montage {slots(built) if built else None}')

    out('Cleaning up scratch assets')
    attempt('delete scratch folder', lambda: library.delete_directory(SCRATCH))
    flush()


def flush():
    folder = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else ''
    path = os.path.join(folder or os.getcwd(), 'montage_reference_output.txt')
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(LINES) + '\n')
        unreal.log(f'[Arsenal probe3] Output written to {path}')
    except OSError as error:
        unreal.log_warning(f'[Arsenal probe3] Could not write the output file: {error}')


main()
