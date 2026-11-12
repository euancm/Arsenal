"""Extract distribution targets/defaults from installed ZoneKit CFGs.

python build_distribution_defaults.py GAME_DATA_FOLDER OUTPUT.json
Only structured prototype identifiers, generator fields and numerical defaults are retained.
"""
import json
from pathlib import Path
import re
import sys


def parse(path):
    """Keep ordered children until wildcard indices can be assigned within each list."""
    root = []
    stack = [root]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.split('//', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'(.+?)\s*:\s*struct.begin(?:\s+(.*))?', line)
        if match:
            child = []
            stack[-1].append((match[1].strip(), child))
            stack.append(child)
        elif line == 'struct.end':
            if len(stack) == 1:
                raise ValueError(f'Unexpected struct.end in {path}')
            stack.pop()
        elif '=' in line:
            key, value = line.split('=', 1)
            stack[-1].append((key.strip(), re.sub(r'\s*\{bskipref\}', '', value).strip()))
        else:
            raise ValueError(f'Unsupported CFG line in {path}: {line}')
    if len(stack) != 1:
        raise ValueError(f'Unclosed CFG block in {path}')

    def indexed(rows):
        result = {}
        next_index = 0
        for key, value in rows:
            if key == '[*]':
                key = f'[{next_index}]'
            match = re.fullmatch(r'\[(\d+)\]', key)
            if match:
                next_index = max(next_index, int(match[1]) + 1)
            result[key] = indexed(value) if isinstance(value, list) else value
        return result
    return indexed(root)


def build(folder, destination):
    dynamic_path = folder / 'ItemGeneratorPrototypes' / 'DynamicItemGenerator.cfg'
    dynamic = parse(dynamic_path)
    item_defaults = parse(folder / 'ItemGeneratorPrototypes.cfg')['[0]']['ItemGenerator']['[0]']['PossibleItems']['[0]']
    trade = parse(folder / 'TradePrototypes.cfg')
    npc = {}
    pattern = re.compile(r'GeneralNPC_(\w+)_(CloseCombat|Recon|Stormtrooper|Sniper|Heavy)_ItemGenerator')
    for sid, value in dynamic.items():
        match = pattern.fullmatch(sid)
        if match and match[1] in ('Neutral', 'Bandit', 'Corpus', 'Duty', 'Freedom', 'Mercenaries',
                                  'Militaries', 'Monolith', 'Noon', 'Scientists', 'Spark', 'Varta'):
            npc[sid] = {'faction': match[1], 'role': match[2], 'groups': value['ItemGenerator']}
    pistols = {sid: value['ItemGenerator'] for sid, value in dynamic.items()
               if re.fullmatch(r'GeneralNPC_\w+_WeaponPistol', sid)}
    # Enum numbers are saved in blends: never renumber or reuse existing IDs.
    labels = {
        'TraderZalesie_TradeItemGenerator': (1, 'Hamster - Zalissya'),
        'TraderChemicalPlant_TradeItemGenerator': (2, 'Trader - Chemical Plant'),
        'TraderTerikon_TradeItemGenerator': (3, 'Huron - Slag Heap'),
        'AsylumTrader_TradeItemGenerator': (4, 'Trader - Quiet settlement'),
        'IkarTrader_TradeItemGenerator': (5, 'Trader - Icarus'),
        'SultanskTrader_TradeItemGenerator': (6, 'Trader - Sultansk'),
        'ShevchenkoTrader_TradeItemGenerator': (7, 'Beard - Shevchenko'),
        'NewbeeVillageTrader_TradeItemGenerator': (8, 'Sidorovich - Rookie Village'),
        'MalakhitTrader_TradeItemGenerator': (9, 'Trader - Malachite'),
        'CementPlantTrader_TradeItemGenerator': (10, 'Trader - Cement Factory'),
        'RostokTraderNato_TradeItemGenerator': (11, 'Yevhen - Rostok'),
        'RostokTraderSoviet_TradeItemGenerator': (12, 'Ragman - Rostok'),
        'YanovTrader_TradeItemGenerator': (13, 'Trader - Yaniv'),
        'PripyatTrader_TradeItemGenerator': (14, 'Trader - Prypiat'),
        'RedForestTrader_TradeItemGenerator': (15, 'Trader - Red Forest'),
        'TraderSuska_TradeItemGenerator': (16, 'Trader - Suska'),
        'VartaTrader_TradeItemGenerator': (17, 'Trader - Ward'),
        'SelmaTrader_TradeItemGenerator': (18, 'Rascal - Kazkovy'),
    }
    traders = {}
    live_trades = set()
    for path in (folder / 'ObjPrototypes').glob('*.cfg'):
        live_trades.update(re.findall(r'^\s*TradePrototypeSID\s*=\s*(\w+)',
                                      path.read_text(encoding='utf-8-sig'), re.MULTILINE))
    for trade_sid, definition in trade.items():
        for group in definition.get('TradeGenerators', {}).values():
            if not isinstance(group, dict):
                continue
            sid = group.get('ItemGeneratorPrototypeSID')
            if sid in labels:
                if trade_sid not in live_trades:
                    raise ValueError(f'Trade prototype is not used by an NPC: {trade_sid}')
                if sid not in dynamic:
                    raise ValueError(f'Missing live trader generator: {sid}')
                traders[sid] = {'enum_id': labels[sid][0], 'label': labels[sid][1], 'trade_sid': trade_sid,
                                'groups': dynamic[sid]['ItemGenerator']}
    missing = set(labels) - set(traders)
    if missing:
        raise ValueError(f'Traders are not linked by TradePrototypes: {sorted(missing)}')
    # Keep only paths needed for a weapon patch, not unrelated stock/equipment.
    for row in npc.values():
        row['groups'] = {
            key: group for key, group in row['groups'].items()
            if group.get('Category') == 'EItemGenerationCategory::WeaponPrimary'
            or any(item.get('ItemGeneratorPrototypeSID') in pistols
                   for item in group.get('PossibleItems', {}).values())
        }
    pools = {}
    for row in traders.values():
        row['attachment_groups'] = {
            key: group for key, group in row['groups'].items()
            if group.get('Category') == 'EItemGenerationCategory::Attach'
        }
        for group in row['groups'].values():
            for item in group.get('PossibleItems', {}).values():
                sid = item.get('ItemGeneratorPrototypeSID')
                if sid in dynamic and any(
                        value.get('Category') in ('EItemGenerationCategory::WeaponPrimary',
                                                  'EItemGenerationCategory::WeaponPistol')
                        for value in dynamic[sid].get('ItemGenerator', {}).values()):
                    pools[sid] = dynamic[sid]['ItemGenerator']
        row['groups'] = {
            key: group for key, group in row['groups'].items()
            if group.get('Category') in ('EItemGenerationCategory::WeaponPrimary',
                                        'EItemGenerationCategory::WeaponPistol')
            or any(item.get('ItemGeneratorPrototypeSID') in pools
                   for item in group.get('PossibleItems', {}).values())
        }
        if not row['groups']:
            raise ValueError(f'No weapon stock route: {row["label"]}')
    result = {'source': 'Installed ZoneKit GameLite/GameData; regenerate after game data updates',
              'npc': npc, 'pistols': pistols, 'traders': traders, 'trade_pools': pools,
              'item_defaults': item_defaults}
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Extracted {len(npc)} role loadouts, {len(pistols)} pistol generators, {len(traders)} traders')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
