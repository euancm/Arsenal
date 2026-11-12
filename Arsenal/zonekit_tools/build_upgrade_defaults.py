"""Extract structured upgrade defaults from ZoneKit CFGs; no game assets are copied.

python build_upgrade_defaults.py GAME_DATA_FOLDER OUTPUT.json [PREVIOUS.json]
Reuse the previous catalogue's enum numbers, including when writing to a new path.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys


def parse(path):
    root, stack = {}, []
    current = root
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.split('//', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'(.+?)\s*:\s*struct.begin(?:\s+(.*))?', line)
        if match:
            child = {}
            ref = re.search(r'refkey=([^}]+)', match[2] or '')
            if ref:
                child['_ref'] = ref[1]
            current[match[1].strip()] = child
            stack.append(current)
            current = child
        elif line == 'struct.end':
            current = stack.pop()
        elif '=' in line:
            key, value = line.split('=', 1)
            current[key.strip()] = re.sub(r'\s*\{bskipref\}', '', value).strip()
        else:
            raise ValueError(f'Unsupported CFG line in {path}: {line}')
    if stack:
        raise ValueError(f'Unclosed CFG block in {path}')
    return root


def resolve(blocks, sid, seen=()):
    if sid in seen:
        raise ValueError(f'Circular CFG reference: {sid}')
    block = blocks[sid]
    result = resolve(blocks, block['_ref'], (*seen, sid)) if '_ref' in block else {}
    result.update({key: value for key, value in block.items() if key != '_ref'})
    return result


def build(folder, destination, previous=None):
    spec = importlib.util.spec_from_file_location(
        'weapon_presets', Path(__file__).parents[1] / 'stalker2_arsenal' / 'weapon_presets.py')
    presets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(presets)
    upgrades = parse(folder / 'UpgradePrototypes.cfg')
    effects = parse(folder / 'EffectPrototypes.cfg')
    result = {'templates': {}, 'effects': {}}
    previous = previous or destination
    old_effects = json.loads(previous.read_text(encoding='utf-8-sig'))['effects'] if previous.exists() else {}
    effect_ids = {sid: row.get('enum_id', index) for index, (sid, row) in enumerate(old_effects.items())}
    next_id = max(effect_ids.values(), default=-1) + 1
    effect_sids = {'DamagePos20Effect', 'RecoilDown20Effect'}
    for template, preset in presets.PRESETS.items():
        rows = []
        for sid in preset['upgrades']:
            block = resolve(upgrades, sid)
            row = {'sid': sid}
            for key in ('Text', 'Hint', 'Image', 'Icon', 'BaseCost', 'HorizontalPosition',
                        'VerticalPosition', 'UpgradeTargetPart', 'IsModification', 'HiddenWihoutItem',
                        'DiscountCoefficient', 'RepairCostModifier'):
                row[key] = block[key]
            for key in ('EffectPrototypeSIDs', 'AttachPrototypeSIDs', 'RequiredUpgradePrototypeSIDs',
                        'BlockingUpgradePrototypeSIDs', 'InterchangeableUpgradePrototypeSIDs',
                        'RequiredItemPrototypeSIDs', 'Skills', 'ConnectionLines'):
                row[key] = [value for name, value in block[key].items()
                            if name != '_ref' and value not in ('empty', 'EConnectionLineState::None')]
            effect_sids.update(row['EffectPrototypeSIDs'])
            rows.append(row)
        result['templates'][template] = rows
    types = {resolve(effects, sid)['Type'] for sid in effect_sids}
    for sid in effects:
        block = resolve(effects, sid)
        if block.get('Type') in types and block.get('bIsPermanent') == 'true':
            if re.fullmatch(r'-?\d+(?:\.\d+)?%?', block.get('ValueMin', '')):
                effect_sids.add(sid)
    for sid in sorted(effect_sids):
        block = resolve(effects, sid)
        result['effects'][sid] = {key: block[key] for key in ('Type', 'ValueMin', 'ValueMax', 'Positive')}
        if sid not in effect_ids:
            effect_ids[sid] = next_id
            next_id += 1
        result['effects'][sid]['enum_id'] = effect_ids[sid]
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Extracted', sum(map(len, result['templates'].values())), 'upgrades and',
          len(result['effects']), 'effect defaults')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
