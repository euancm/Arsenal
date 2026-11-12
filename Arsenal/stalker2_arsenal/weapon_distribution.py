"""Trader stock and scoped, weighted NPC weapon additions."""
import copy
import json
import math
import os
from functools import lru_cache
from types import SimpleNamespace

from .weapon_presets import PRESETS
from . import distribution_compose

with open(os.path.join(os.path.dirname(__file__), 'resources', 'distribution_defaults.json'),
          encoding='utf-8') as handle:
    DEFAULTS = json.load(handle)

ROLES = (('CloseCombat', 'Close Combat'), ('Recon', 'Recon'), ('Stormtrooper', 'Stormtrooper'),
         ('Sniper', 'Sniper'), ('Heavy', 'Heavy'))
RANKS = ('Newbie', 'Experienced', 'Veteran', 'Master')
DIFFICULTIES = ('Easy', 'Medium', 'Hard', 'Stalker')
FACTIONS = (
    ('Neutral', 'Loners'), ('Bandit', 'Bandits'), ('Corpus', 'Corps'), ('Duty', 'Duty'),
    ('Freedom', 'Freedom'), ('Mercenaries', 'Mercenaries'), ('Militaries', 'ISPF'),
    ('Monolith', 'Monolith'), ('Noon', 'Noon'), ('Scientists', 'Scientists'),
    ('Spark', 'Spark'), ('Varta', 'Ward'),
)
TRADER_ITEMS = tuple((sid, row['label'], row['trade_sid'], row['enum_id'])
                     for sid, row in sorted(DEFAULTS['traders'].items(),
                                            key=lambda pair: pair[1]['label']))
FACTION_ITEMS = tuple((sid, label, f'Generic {label} NPC loadouts') for sid, label in FACTIONS)
INHERITED_FIELDS = ('MinDurability', 'MaxDurability', 'AmmoMinCount', 'AmmoMaxCount')


def slot(cfg):
    return PRESETS[cfg.setup_template]['slot']


def available_roles(faction):
    return {row['role'] for row in DEFAULTS['npc'].values() if row['faction'] == faction}


def selected_rule(cfg, collection, sid):
    rows = getattr(cfg, collection)
    if sid not in rows:
        row = rows.add()
        row.name = sid
        if collection == 'traders':
            for key, value in trader_defaults(cfg.setup_template, sid).items():
                setattr(row, key, value)
        else:
            defaults = faction_defaults(cfg.setup_template, sid)
            for name in ('roles', 'ranks'):
                for key, values in defaults[name].items():
                    item = getattr(row, name).add()
                    item.name = key
                    item.enabled, item.percent = values
    return rows[sid]


def faction_rule(cfg):
    return selected_rule(cfg, 'npc_factions', cfg.distribution_faction)


def load_defaults(cfg, reset=False):
    if reset:
        cfg.traders.clear()
        cfg.npc_factions.clear()
    for sid in DEFAULTS['traders']:
        selected_rule(cfg, 'traders', sid)
    for sid, _label in FACTIONS:
        selected_rule(cfg, 'npc_factions', sid)


def percentage(value, label):
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise RuntimeError(f'{label} must be between 0 and 100%.')
    return value / 100


def shares(rule, role):
    role_rule = rule.roles.get(role)
    role_share = percentage(role_rule.percent, role) if role_rule and role_rule.enabled else 0
    return {rank: role_share * percentage(row.percent, rank) if row.enabled else 0
            for rank in RANKS if (row := rule.ranks.get(rank)) is not None}


def ranks(group):
    values = group.get('PlayerRank', ','.join(f'ERank::{rank}' for rank in RANKS))
    result = [value.strip().split('::')[-1] for value in values.split(',')]
    if not result or any(value not in RANKS for value in result):
        raise RuntimeError(f'Unsupported NPC rank filter: {values}')
    return result


def number(value):
    return float(value.rstrip('f'))


def difficulties(group):
    value = group.get('Diff', ','.join(f'EGameDifficulty::{name}' for name in DIFFICULTIES))
    result = [name.strip().split('::')[-1] for name in value.split(',')]
    if not result or any(name not in DIFFICULTIES for name in result):
        raise RuntimeError(f'Unsupported NPC difficulty filter: {value}')
    return result


@lru_cache(maxsize=None)
def faction_defaults(template, faction):
    donor = PRESETS[template]['base_weapon']
    category = f'EItemGenerationCategory::{slot(SimpleNamespace(setup_template=template))}'
    matrix = {}
    for role, _label in ROLES:
        definition = DEFAULTS['npc'].get(f'GeneralNPC_{faction}_{role}_ItemGenerator')
        groups = []
        if definition:
            for source in definition['groups'].values():
                if source['Category'] == category:
                    groups.append(source)
                elif category.endswith('WeaponPistol'):
                    for entry in source['PossibleItems'].values():
                        for group in DEFAULTS['pistols'].get(
                                entry.get('ItemGeneratorPrototypeSID'), {}).values():
                            # Keep caller filters as well as the shared pistol pool's filters.
                            row = dict(group)
                            row['PlayerRank'] = ', '.join(
                                f'ERank::{rank}' for rank in ranks(group) if rank in ranks(source))
                            row['Diff'] = ', '.join(
                                f'EGameDifficulty::{diff}' for diff in difficulties(group)
                                if diff in difficulties(source))
                            if row['PlayerRank'] and row['Diff'] and number(entry.get('Chance', '1')) > 0:
                                groups.append(row)
        matrix[role] = {}
        for rank in RANKS:
            shares_by_difficulty = []
            for difficulty in DIFFICULTIES:
                matching = [group for group in groups
                            if rank in ranks(group) and difficulty in difficulties(group)]
                values = []
                for group in matching:
                    items = group['PossibleItems'].values()
                    total = sum(number(item.get('Weight', DEFAULTS['item_defaults']['Weight']))
                                for item in items)
                    if total <= 0 or not math.isfinite(total):
                        raise RuntimeError(f'Invalid template weapon pool: {faction} {role} {rank}')
                    weight = sum(number(item.get('Weight', DEFAULTS['item_defaults']['Weight']))
                                 for item in items if item.get('ItemPrototypeSID') == donor)
                    values.append(weight / total)
                shares_by_difficulty.append(sum(values) / len(values) if values else 0)
            matrix[role][rank] = sum(shares_by_difficulty) / len(DIFFICULTIES)
    peaks = {role: max(values.values()) for role, values in matrix.items()}
    active = [role for role in peaks if peaks[role] > 0]
    return {
        'roles': {role: (peak > 0, peak * 100) for role, peak in peaks.items()},
        'ranks': {rank: (any(matrix[role][rank] > 0 for role in active),
                         sum(matrix[role][rank] / peaks[role] for role in active) / len(active) * 100
                         if active else 0)
                  for rank in RANKS},
    }


@lru_cache(maxsize=None)
def trader_defaults(template, sid):
    cfg = SimpleNamespace(setup_template=template)
    donor = PRESETS[template]['base_weapon']
    targets, _route = trader_route(cfg, sid)
    candidates = [item for group in targets.values() for item in group['PossibleItems'].values()
                  if item.get('ItemPrototypeSID') == donor]
    item = dict(DEFAULTS['item_defaults'])
    if candidates:
        if any(row != candidates[0] for row in candidates[1:]):
            raise RuntimeError(f'Template stock has conflicting defaults in {sid}: {donor}')
        item.update(candidates[0])
    return {
        'enabled': bool(candidates) and number(item['Chance']) > 0,
        'chance': number(item['Chance']) * 100,
        'min_quantity': int(item['MinCount']), 'max_quantity': int(item['MaxCount']),
        'min_condition': number(item['MinDurability']) * 100,
        'max_condition': number(item['MaxDurability']) * 100,
        'sell_unloaded': item.get('bUnloadedWeapon', 'false').lower() == 'true',
    }


def inherited_defaults(template, group, rank, faction, sources=None):
    """Prefer a local donor; otherwise use the same donor/rank/difficulty elsewhere."""
    donor = PRESETS[template]['base_weapon']
    candidates = []

    def collect(source, same_faction, sid, key):
        if rank not in ranks(source):
            return
        if not set(difficulties(source)).issuperset(difficulties(group)):
            return
        for item in source.get('PossibleItems', {}).values():
            if item.get('ItemPrototypeSID') == donor:
                candidates.append((not same_faction, sid, key, item))

    collect(group, True, '', '')
    if not candidates:
        for sid, row in DEFAULTS['npc'].items():
            for key, source in row['groups'].items():
                collect(source, row['faction'] == faction, sid, key)
        for sid, groups in DEFAULTS['pistols'].items():
            for key, source in groups.items():
                collect(source, sid == f'GeneralNPC_{faction}_WeaponPistol', sid, key)
    if not candidates:
        raise RuntimeError(f'No {donor} condition/ammo defaults for {faction} {rank}. '
                           'Disable this rank or choose another weapon template.')
    _other_faction, sid, key, item = sorted(candidates, key=lambda row: row[:3])[0]
    if any(field not in item for field in INHERITED_FIELDS):
        raise RuntimeError(f'Incomplete condition/ammo defaults for {donor}, {faction} {rank}.')
    if sid and sources is not None:
        sources.add(f'{faction} {rank}: {donor} from {sid} {key}')
    return {field: item[field] for field in INHERITED_FIELDS}


def weapon_item(info, group, rank, faction, share):
    items = group['PossibleItems']
    if any('Chance' in row for row in items.values()):
        raise RuntimeError('NPC weapon pool uses Chance rather than Weight; cannot calculate its share.')
    total = sum(number(row.get('Weight', '4.f')) for row in items.values())
    if not math.isfinite(total) or total <= 0:
        raise RuntimeError('NPC weapon pool must have positive finite total weight.')
    weight = 1 if share == 1 else total * share / (1 - share)
    item = {'ItemPrototypeSID': info['sid'], 'Weight': format(weight, '.12g')}
    item.update(inherited_defaults(info['cfg'].setup_template, group, rank, faction,
                                   info.setdefault('distribution_sources', set())))
    return item


def emit(name, fields, option='', depth=0):
    indent = '   ' * depth
    lines = [f'{indent}{name} : struct.begin' + (f' {{{option}}}' if option else '')]
    for key, value in fields.items():
        if isinstance(value, dict):
            lines.extend(emit(key, value, depth=depth + 1))
        else:
            lines.append(f'{indent}   {key} = {value}')
    lines.append(f'{indent}struct.end')
    return lines


def patch_groups(sid, groups):
    lines = [f'{sid} : struct.begin {{bpatch}}', '   ItemGenerator : struct.begin {bpatch}']
    lines.extend(groups)
    lines.extend(['   struct.end', 'struct.end', ''])
    return lines


def pool_patch(key, group, item, share):
    lines = [f'      {key} : struct.begin {{bpatch}}',
             '         PossibleItems : struct.begin {bpatch}']
    if share == 1:
        lines.extend(f'            {index} : removenode' for index in group['PossibleItems'])
    lines.extend(emit('[*]', item, depth=4))
    lines.extend(['         struct.end', '      struct.end'])
    return lines


def split_group(group, info, faction, by_rank):
    """New groups have no inherited tail; keep unselected ranks exactly as in the source."""
    result = []
    for rank in ranks(group):
        share = by_rank.get(rank, 0)
        variants = {}
        if share:
            for difficulty in difficulties(group):
                source = dict(group, Diff=f'EGameDifficulty::{difficulty}')
                item = weapon_item(info, source, rank, faction, share)
                marker = tuple(item.items())
                if marker not in variants:
                    variants[marker] = ([], item)
                variants[marker][0].append(difficulty)
        else:
            variants[None] = (difficulties(group), None)
        for selected_difficulties, item in variants.values():
            row = copy.deepcopy(group)
            row['PlayerRank'] = f'ERank::{rank}'
            if len(variants) > 1:
                row['Diff'] = ', '.join(f'EGameDifficulty::{name}' for name in selected_difficulties)
            if item is None:
                result.append(row)
                continue
            if share == 1:
                row['PossibleItems'] = {'[0]': item}
            else:
                index = max((int(key[1:-1]) for key in row['PossibleItems']), default=-1) + 1
                row['PossibleItems'][f'[{index}]'] = item
            result.append(row)
    return result


def npc_lines(info):
    lines = []
    cfg = info['cfg']
    for rule in cfg.npc_factions:
        if rule.name not in dict(FACTIONS):
            raise RuntimeError(f'Unknown NPC faction: {rule.name}')
        for role, _label in ROLES:
            by_rank = shares(rule, role)
            if not any(by_rank.values()):
                continue
            sid = f'GeneralNPC_{rule.name}_{role}_ItemGenerator'
            if sid not in DEFAULTS['npc']:
                raise RuntimeError(f'{rule.name} has no {role} loadout.')
            groups = DEFAULTS['npc'][sid]['groups']
            patches = []
            if slot(cfg) == 'WeaponPrimary':
                for key, group in groups.items():
                    if group['Category'] != 'EItemGenerationCategory::WeaponPrimary':
                        continue
                    selected = [rank for rank in ranks(group) if by_rank.get(rank, 0)]
                    if not selected:
                        continue
                    variants = split_group(group, info, rule.name, by_rank)
                    if len(ranks(group)) == 1 and len(variants) == 1:
                        share = by_rank[selected[0]]
                        item = next(row for row in variants[0]['PossibleItems'].values()
                                    if row.get('ItemPrototypeSID') == info['sid'])
                        patches.extend(pool_patch(key, group, item, share))
                    else:
                        patches.append(f'      {key} : removenode')
                        for row in variants:
                            patches.extend(emit('[*]', row, depth=2))
            else:
                for key, group in groups.items():
                    for index, item in group['PossibleItems'].items():
                        donor = item.get('ItemGeneratorPrototypeSID')
                        if donor not in DEFAULTS['pistols']:
                            continue
                        custom = (f'Arsenal_{info["mod"]}_{info["weapon_id"]}_{rule.name}_{role}_'
                                  f'{key[1:-1]}_{index[1:-1]}Pistol')
                        new_groups = {}
                        for source in DEFAULTS['pistols'][donor].values():
                            for row in split_group(source, info, rule.name, by_rank):
                                new_groups[f'[{len(new_groups)}]'] = row
                        lines.extend(emit(custom, {'SID': custom, 'ItemGenerator': new_groups},
                                          'refurl=@BaseGame/ItemGeneratorPrototypes.cfg;refkey=[0]'))
                        lines.append('')
                        patches.extend([
                            f'      {key} : struct.begin {{bpatch}}',
                            '         PossibleItems : struct.begin {bpatch}',
                            f'            {index} : struct.begin {{bpatch}}',
                            f'               ItemGeneratorPrototypeSID = {custom}',
                            '            struct.end', '         struct.end', '      struct.end',
                        ])
            if not patches:
                raise RuntimeError(f'No {slot(cfg)} route in {sid}.')
            lines.extend(patch_groups(sid, patches))
    return lines


def trader_route(cfg, trader_sid):
    groups = DEFAULTS['traders'][trader_sid]['groups']
    category = f'EItemGenerationCategory::{slot(cfg)}'
    targets = {key: group for key, group in groups.items() if group['Category'] == category}
    # Some traders sell pistols in their existing mixed primary-weapon group.
    if not targets and slot(cfg) == 'WeaponPistol':
        targets = {key: group for key, group in groups.items()
                   if group['Category'] == 'EItemGenerationCategory::WeaponPrimary'}
    if targets:
        return targets, None
    routes = []
    donor_weapon = PRESETS[cfg.setup_template]['base_weapon']
    for key, group in groups.items():
        for index, entry in group['PossibleItems'].items():
            donor = entry.get('ItemGeneratorPrototypeSID')
            pool = DEFAULTS['trade_pools'].get(donor, {})
            if not any(row['Category'] == category for row in pool.values()):
                continue
            if 'Chance' not in entry:
                raise RuntimeError(f'Trader stock route has no independent activation chance: {trader_sid}')
            activation = number(entry['Chance'])
            if not math.isfinite(activation) or not 0 < activation <= 1:
                raise RuntimeError(f'Invalid trader stock activation chance: {trader_sid}')
            contains_donor = any(value.get('ItemPrototypeSID') == donor_weapon
                                 for row in pool.values() for value in row['PossibleItems'].values())
            routes.append((not contains_donor, activation != 1, donor, key, index, activation))
    if not routes:
        raise RuntimeError(f'{DEFAULTS["traders"][trader_sid]["label"]} has no weapon stock route.')
    _other_donor, _gated, donor, key, index, activation = min(routes)
    return {key: group for key, group in DEFAULTS['trade_pools'][donor].items()
            if group['Category'] == category}, (donor, key, index, activation)


def trader_activation(cfg):
    _targets, route = trader_route(cfg, cfg.distribution_trader)
    return route[3] if route else 1


def trader_lines(info):
    lines = []
    for rule in info['cfg'].traders:
        if not rule.enabled:
            continue
        if rule.name not in DEFAULTS['traders']:
            raise RuntimeError(f'Unknown trader: {rule.name}')
        chance = percentage(rule.chance, 'Stock chance')
        minimum = percentage(rule.min_condition, 'Minimum condition')
        maximum = percentage(rule.max_condition, 'Maximum condition')
        if rule.min_quantity > rule.max_quantity or rule.min_quantity < 0:
            raise RuntimeError('Trader quantity must satisfy 0 <= minimum <= maximum.')
        if minimum > maximum:
            raise RuntimeError('Trader minimum condition exceeds maximum condition.')
        if not chance:
            continue
        targets, route = trader_route(info['cfg'], rule.name)
        item = {'ItemPrototypeSID': info['sid'], 'Chance': format(chance, '.12g'),
                'MinCount': str(rule.min_quantity), 'MaxCount': str(rule.max_quantity),
                'MinDurability': format(minimum, '.12g'), 'MaxDurability': format(maximum, '.12g'),
                'bUnloadedWeapon': str(rule.sell_unloaded).lower()}
        patches = []
        if route is None:
            for key, group in targets.items():
                patches.extend(pool_patch(key, group, item, 0))
        else:
            donor, key, index, _activation = route
            custom = f'Arsenal_{info["mod"]}_{info["weapon_id"]}_{rule.name}_Stock'
            new_groups = copy.deepcopy(DEFAULTS['trade_pools'][donor])
            for group_key in targets:
                group = new_groups[group_key]
                next_index = max(int(value[1:-1]) for value in group['PossibleItems']) + 1
                group['PossibleItems'][f'[{next_index}]'] = item
            lines.extend(emit(custom, {'SID': custom, 'ItemGenerator': new_groups},
                              'refurl=@BaseGame/ItemGeneratorPrototypes.cfg;refkey=[0]'))
            lines.append('')
            patches.extend([
                f'      {key} : struct.begin {{bpatch}}',
                '         PossibleItems : struct.begin {bpatch}',
                f'            {index} : struct.begin {{bpatch}}',
                f'               ItemGeneratorPrototypeSID = {custom}',
                '            struct.end', '         struct.end', '      struct.end',
            ])
        lines.extend(patch_groups(rule.name, patches))
    return lines


def payload(info):
    text = '\n'.join(trader_lines(info) + npc_lines(info))
    record = distribution_compose.record_from_text(
        info['mod'], info['weapon_id'], text, DEFAULTS, info['sid'])
    if not info['cfg'].stock_custom_attachments:
        return record
    sids = [f'Gun{info["weapon_id"]}_Mag{magazine["name"]}'
            for magazine in info['magazines']
            if not magazine['preinstalled'] and not magazine.get('existing_sid')]
    sids.extend(item['sid'] for item in info['attachments'])
    for sid in sids:
        distribution_compose.identifier(sid)
    if len(set(sids)) != len(sids):
        raise RuntimeError('Duplicate custom attachment distribution SID.')
    if not sids:
        return record
    additions = []
    for rule in info['cfg'].traders:
        if not rule.enabled:
            continue
        chance = percentage(rule.chance, 'Stock chance')
        if not chance:
            continue
        _targets, route = trader_route(info['cfg'], rule.name)
        activation = route[3] if route else 1
        groups = DEFAULTS['traders'][rule.name]['attachment_groups']
        if len(groups) > 1:
            raise RuntimeError(f'Multiple direct attachment stock groups: {rule.name}')
        group = next(iter(groups), None)
        additions.append({
            'root': rule.name, 'group': group,
            'base': copy.deepcopy(groups[group]) if group else None,
            'items': [{'ItemPrototypeSID': sid, 'Chance': format(chance * activation / 2, '.12g'),
                       'MinCount': '1', 'MaxCount': '1'} for sid in sids],
        })
    record['trader_attachments'] = additions
    return record


def files(info):
    payload(info)
    # Patches and their private subgenerators must share the base generators' namespace.
    path = os.path.join('GameLite', 'GameData', 'ItemGeneratorPrototypes',
                        f'{info["mod"]}_{info["weapon_id"]}Distribution.cfg')
    legacy = os.path.join('GameLite', 'ModGameData', info['mod'], 'ItemGeneratorPrototypes',
                          f'{info["weapon_id"]}Distribution.cfg')
    return {
        path: '// Generated by Arsenal. Distribution is composed automatically by the import script.\n',
        legacy: '// Generated by Arsenal. Distribution moved to GameData/ItemGeneratorPrototypes.\n',
    }
