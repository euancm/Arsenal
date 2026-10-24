"""Probe how a montage's animation slots can be repointed from Python (run inside the ZoneKit editor).

Paste this file's path into the ZoneKit Python bar. It works only on scratch copies under
/<MOD>/ZZ_ArsenalProbe (deleted at the end) and never edits your real assets. It reports which of
these routes work, so the setup script can use one:

  1  Reading/writing the montage's slot_anim_tracks property directly
  2  export_text()/import_text() on the montage object
  3  Creating a fresh montage from a sequence with AnimMontageFactory.source_animation
  4  EditorAssetLibrary.consolidate_asset_duplicates (swaps references to one sequence for another)
  5  Anything else in the unreal module whose name suggests it edits montages or replaces references

Set MOD to a mod that already holds imported sequences and montages (the import script's output).
The result is written to montage_probe_output.txt next to this script and to the Output Log.
"""

import os

import unreal

MOD = 'MouseMod'

SCRATCH = f'/{MOD}/ZZ_ArsenalProbe'
LINES = []


def out(message):
    LINES.append(message)
    unreal.log(f'[Arsenal probe] {message}')


def attempt(label, function):
    try:
        result = function()
        out(f'  OK    {label}: {result!r}'[:400])
        return result
    except Exception as error:
        out(f'  FAIL  {label}: {type(error).__name__}: {error}'[:400])
        return None


def mod_assets(class_name):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = []
    for data in registry.get_assets_by_path(f'/{MOD}', recursive=True):
        if class_name in str(data.get_editor_property('asset_class_path')):
            found.append(str(data.get_editor_property('package_name')))
    return sorted(found)


def names(obj, words):
    return sorted(n for n in dir(obj) if any(w in n.lower() for w in words))


def probe_properties(montage):
    out('1. Montage properties')
    out(f'  class {montage.get_class().get_name()}; attributes: ' + ', '.join(names(montage, ('slot', 'segment', 'track', 'anim', 'section', 'notif', 'blend', 'text'))))
    tracks = attempt('get_editor_property("slot_anim_tracks")', lambda: montage.get_editor_property('slot_anim_tracks'))
    for name in ('composite_sections', 'notifies', 'blend_in', 'blend_out', 'sequence_length', 'rate_scale'):
        attempt(f'get_editor_property("{name}")', lambda n=name: montage.get_editor_property(n))
    attempt('get_first_anim_reference()', montage.get_first_anim_reference)
    if tracks:
        track = tracks[0]
        out('  slot track attributes: ' + ', '.join(n for n in dir(track) if not n.startswith('_')))
        segments = attempt('anim_track.anim_segments', lambda: list(track.get_editor_property('anim_track').get_editor_property('anim_segments')))
        if segments:
            out('  segment attributes: ' + ', '.join(n for n in dir(segments[0]) if not n.startswith('_')))


def probe_text(montage):
    out('2. export_text / import_text on the montage')
    for name in ('export_text', 'import_text', 'copy_properties_for_unrelated_objects'):
        out(f'  montage has {name}: {hasattr(montage, name)}')
    if hasattr(montage, 'export_text'):
        text = attempt('montage.export_text()', lambda: montage.export_text())
        if isinstance(text, str):
            out(f'  text length {len(text)}; first 300 characters: {text[:300]!r}')
            out(f'  mentions SlotAnimTracks: {"SlotAnimTracks" in text}')
    out(f'  unreal.EditorAssetLibrary text-like functions: ' + ', '.join(names(unreal.EditorAssetLibrary, ('text', 'export', 'import'))))
    out(f'  unreal.ObjectTools-like classes: ' + ', '.join(names(unreal, ('objecttools', 'exporttext', 'importtext'))))


def probe_factory(sequence_a):
    out('3. AnimMontageFactory')
    factory_class = getattr(unreal, 'AnimMontageFactory', None)
    out(f'  unreal.AnimMontageFactory exists: {factory_class is not None}')
    if factory_class is None:
        return None
    factory = factory_class()
    out('  factory attributes: ' + ', '.join(n for n in dir(factory) if not n.startswith('_') and ('source' in n or 'skeleton' in n or 'anim' in n)))
    attempt('factory.set_editor_property("source_animation")', lambda: factory.set_editor_property('source_animation', sequence_a))
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    created = attempt('create_asset(ZZ_ProbeFromFactory)', lambda: tools.create_asset('ZZ_ProbeFromFactory', SCRATCH, unreal.AnimMontage, factory))
    if created:
        attempt('new montage first anim reference', created.get_first_anim_reference)
        attempt('new montage slot_anim_tracks readable', lambda: len(created.get_editor_property('slot_anim_tracks')))
    return created


def probe_consolidate(sequence_a, sequence_b, montage_from_factory):
    out('4. consolidate_asset_duplicates')
    library = unreal.EditorAssetLibrary
    if montage_from_factory is None:
        out('  skipped: no factory montage to test with')
        return
    out(f'  signature help: {unreal.EditorAssetLibrary.consolidate_asset_duplicates.__doc__}')
    before = attempt('montage references before', montage_from_factory.get_first_anim_reference)
    attempt('consolidate_asset_duplicates(new, [old])',
            lambda: library.consolidate_asset_duplicates(sequence_b, [before]))
    after = attempt('montage references after', montage_from_factory.get_first_anim_reference)
    out(f'  reference changed to the new sequence: {after is not None and sequence_b is not None and after.get_name() == sequence_b.get_name()}')


def probe_names():
    out('5. Other candidates in the unreal module')
    out('  ' + ', '.join(names(unreal, ('montage',))))
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    out('  AssetTools: ' + ', '.join(names(tools, ('replace', 'reference', 'consolid', 'migrate', 'redirect', 'fix'))))
    out('  AnimationLibrary-like classes: ' + ', '.join(names(unreal, ('animationlibrary', 'animationblueprintlibrary', 'animmontagelibrary', 'animsequencelibrary'))))
    for class_name in ('AnimationLibrary', 'AnimMontageLibrary'):
        cls = getattr(unreal, class_name, None)
        if cls:
            out(f'  unreal.{class_name}: ' + ', '.join(n for n in dir(cls) if not n.startswith('_')))
    out('  classes mentioning Mod and Anim: ' + ', '.join(names(unreal, ('modanim', 'modmontage', 'modkitanim'))))


def main():
    montages = mod_assets('AnimMontage')
    sequences = mod_assets('AnimSequence')
    out(f'/{MOD}: {len(montages)} montages, {len(sequences)} sequences')
    if len(montages) < 1 or len(sequences) < 2:
        out('Need at least one montage and two sequences in the mod; run the import first or change MOD.')
        flush()
        return
    library = unreal.EditorAssetLibrary
    montage_copy_path = f'{SCRATCH}/ZZ_ProbeMontage'
    library.make_directory(SCRATCH)
    attempt(f'duplicate {montages[0]}', lambda: library.duplicate_asset(montages[0], montage_copy_path))
    montage = library.load_asset(montage_copy_path)
    # consolidate deletes the replaced asset, so only scratch copies of the sequences are used
    for index, name in enumerate(('ZZ_ProbeSeqA', 'ZZ_ProbeSeqB')):
        attempt(f'duplicate {sequences[index]}', lambda i=index, n=name: library.duplicate_asset(sequences[i], f'{SCRATCH}/{n}'))
    sequence_a = library.load_asset(f'{SCRATCH}/ZZ_ProbeSeqA')
    sequence_b = library.load_asset(f'{SCRATCH}/ZZ_ProbeSeqB')
    out(f'scratch montage copy of {montages[0]}; test sequences {sequences[0]} and {sequences[1]}')
    if montage is not None:
        probe_properties(montage)
        probe_text(montage)
    created = probe_factory(sequence_a)
    probe_consolidate(sequence_a, sequence_b, created)
    probe_names()
    out('Cleaning up scratch assets')
    attempt('delete scratch folder', lambda: library.delete_directory(SCRATCH))
    flush()


def flush():
    folder = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else ''
    path = os.path.join(folder or os.getcwd(), 'montage_probe_output.txt')
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(LINES) + '\n')
        unreal.log(f'[Arsenal probe] Output written to {path}')
    except OSError as error:
        unreal.log_warning(f'[Arsenal probe] Could not write the output file: {error}')


main()
