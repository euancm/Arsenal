"""Probe whether a montage can be rebuilt around a new sequence with AnimMontageFactory (run inside ZoneKit).

Paste this file's path into the ZoneKit Python bar. For one real montage it records what the montage has
(slot name, notifies, sections, blend settings, skeleton, length), builds a replacement from a different
sequence with the factory, and reports which of those survive and which can be copied across from Python.
It also tries creating a dynamic montage with a chosen slot name and saving it as an asset.

Works only on scratch copies under /<MOD>/ZZ_ArsenalProbe2 (deleted at the end); real assets are not edited.
Set MOD to a mod that holds the imported montages and sequences. Set MONTAGE_HINT / SEQUENCE_HINT to pick
which montage and sequence are used (substring of the package path); the first match wins.
The result is written to montage_rebuild_output.txt next to this script and to the Output Log.
"""

import os

import unreal

MOD = 'MouseMod'
MONTAGE_HINT = 'MG_fp_mousegun_reload'  # a montage with notifies and several sections if possible
SEQUENCE_HINT = 'AS_fp_mousegun_shoot'  # any sequence to play instead
SCRATCH = f'/{MOD}/ZZ_ArsenalProbe2'
LINES = []


def out(message):
    LINES.append(message)
    unreal.log(f'[Arsenal probe2] {message}')


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


def describe(label, montage):
    """What the montage exposes to Python; returns a dict for comparing two montages."""
    out(f'-- {label}: {montage.get_path_name()}')
    lib = unreal.AnimationLibrary
    info = {}
    info['slots'] = attempt('slot names', lambda: [str(s) for s in lib.get_montage_slot_names(montage)])
    info['sections'] = attempt('sections', lambda: [str(montage.get_section_name(i)) for i in range(montage.get_num_sections())])
    info['length'] = attempt('sequence_length', lambda: montage.get_editor_property('sequence_length'))
    info['skeleton'] = attempt('skeleton', lambda: montage.get_editor_property('skeleton').get_path_name())
    info['rate'] = attempt('rate_scale', lambda: montage.get_editor_property('rate_scale'))
    info['blend_in'] = attempt('blend_in', lambda: str(montage.get_editor_property('blend_in')))
    info['blend_out'] = attempt('blend_out', lambda: str(montage.get_editor_property('blend_out')))
    info['first'] = attempt('first anim reference', lambda: montage.get_first_anim_reference().get_path_name())
    info['tracks'] = attempt('notify track names', lambda: [str(t) for t in lib.get_animation_notify_track_names(montage)])
    events = attempt('notify events', lambda: list(lib.get_animation_notify_events(montage)))
    info['events'] = len(events) if events is not None else None
    if events:
        out('  event attributes: ' + ', '.join(n for n in dir(events[0]) if not n.startswith('_')))
        for event in events[:12]:
            attempt('event', lambda e=event: (str(e.get_editor_property('notify_name')),
                                              e.get_editor_property('display_time') if hasattr(e, 'get_editor_property') else None))
    out('  montage attributes: ' + ', '.join(n for n in dir(montage) if not n.startswith('_') and n.startswith(('set_', 'add_', 'get_'))))
    return info


def compare(before, after):
    out('-- compare original vs rebuilt')
    for key in before:
        same = before[key] == after.get(key)
        out(f'  {"same   " if same else "DIFFERS"} {key}: original {before[key]!r} | rebuilt {after.get(key)!r}'[:400])


def main():
    montage_path = find('AnimMontage', MONTAGE_HINT)
    sequence_path = find('AnimSequence', SEQUENCE_HINT)
    out(f'montage {montage_path}; replacement sequence {sequence_path}')
    if not montage_path or not sequence_path:
        out('Nothing matched the hints; edit MONTAGE_HINT / SEQUENCE_HINT.')
        flush()
        return
    library = unreal.EditorAssetLibrary
    library.make_directory(SCRATCH)
    original = library.load_asset(montage_path)
    sequence = library.load_asset(sequence_path)
    before = describe('original (mod copy)', original)
    template = original.get_first_anim_reference()
    out(f'original plays {template.get_path_name() if template else None}')

    out('A. Factory rebuild')
    factory = unreal.AnimMontageFactory()
    factory.set_editor_property('source_animation', sequence)
    attempt('set target_skeleton', lambda: factory.set_editor_property('target_skeleton', original.get_editor_property('skeleton')))
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    rebuilt = attempt('create_asset', lambda: tools.create_asset('ZZ_Rebuilt', SCRATCH, unreal.AnimMontage, factory))
    if rebuilt is not None:
        after = describe('rebuilt', rebuilt)
        compare(before, after)
        lib = unreal.AnimationLibrary
        out('B. Copying what the factory dropped')
        for track in (before['tracks'] or []):
            attempt(f'add notify track {track}', lambda t=track: lib.add_animation_notify_track(rebuilt, t))
        source_events = list(lib.get_animation_notify_events(original))
        for event in source_events[:3]:
            attempt('add_animation_notify_event_object', lambda e=event: lib.add_animation_notify_event_object(
                rebuilt, e.get_editor_property('display_time'), e.get_editor_property('notify'), e.get_editor_property('notify_name')))
        attempt('copy_anim_notifies_from_sequence(original, rebuilt)', lambda: lib.copy_anim_notifies_from_sequence(original, rebuilt))
        attempt('events after copy', lambda: len(list(lib.get_animation_notify_events(rebuilt))))
        attempt('set blend_in', lambda: rebuilt.set_editor_property('blend_in', original.get_editor_property('blend_in')))
        attempt('set blend_out', lambda: rebuilt.set_editor_property('blend_out', original.get_editor_property('blend_out')))
        attempt('set rate_scale', lambda: rebuilt.set_editor_property('rate_scale', original.get_editor_property('rate_scale')))
        for name in ('slot_name', 'slot_names', 'composite_sections', 'sections'):
            attempt(f'set {name}', lambda n=name: rebuilt.set_editor_property(n, original.get_editor_property(n)))
        attempt('save rebuilt', lambda: library.save_loaded_asset(rebuilt))

    out('C. Dynamic montage with the original slot name, saved as an asset')
    slot = (before['slots'] or ['DefaultSlot'])[0]
    dynamic = attempt('create_slot_animation_as_dynamic_montage_with_blend_settings', lambda: sequence.create_slot_animation_as_dynamic_montage_with_blend_settings(
        slot, unreal.MontageBlendSettings(), unreal.MontageBlendSettings(), 1.0, 1, -1.0, 0.0))
    if dynamic is not None:
        attempt('dynamic slot names', lambda: [str(s) for s in unreal.AnimationLibrary.get_montage_slot_names(dynamic)])
        package = attempt('create_package', lambda: unreal.create_package(f'{SCRATCH}/ZZ_Dynamic'))
        if package is not None:
            attempt('rename into package', lambda: dynamic.rename('ZZ_Dynamic', package))
            attempt('save dynamic', lambda: library.save_loaded_asset(dynamic))
            attempt('dynamic exists on disk', lambda: library.does_asset_exist(f'{SCRATCH}/ZZ_Dynamic'))

    out('D. Duplicate then replace_anim notifies helpers and slot setters')
    out('  AnimationLibrary set_/replace_ names: ' + ', '.join(n for n in dir(unreal.AnimationLibrary) if n.startswith(('set_', 'replace_'))))
    out('  unreal classes mentioning slot: ' + ', '.join(sorted(n for n in dir(unreal) if 'slot' in n.lower())[:40]))

    out('Cleaning up scratch assets')
    attempt('delete scratch folder', lambda: library.delete_directory(SCRATCH))
    flush()


def flush():
    folder = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else ''
    path = os.path.join(folder or os.getcwd(), 'montage_rebuild_output.txt')
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(LINES) + '\n')
        unreal.log(f'[Arsenal probe2] Output written to {path}')
    except OSError as error:
        unreal.log_warning(f'[Arsenal probe2] Could not write the output file: {error}')


main()
