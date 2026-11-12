"""Asset-free regression tests: python -m unittest Arsenal.zonekit_tools.test_weapon_distribution."""
import copy
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1] / 'stalker2_arsenal'
PACKAGE = '_arsenal_distribution_tests'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(f'{PACKAGE}.weapon_distribution',
                                             ROOT / 'weapon_distribution.py')
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)
from .build_distribution_defaults import build, parse


def apply(text, original):
    """Interpret the subset emitted here, independently of the exporter's tree builder."""
    root = []
    stack = [root]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        begin = re.fullmatch(r'(.+?) : struct.begin(?: \{(.*)\})?', line)
        if begin:
            child = []
            stack[-1].append((begin[1], child, begin[2] == 'bpatch'))
            stack.append(child)
        elif line == 'struct.end':
            stack.pop()
        elif line.endswith(' : removenode'):
            stack[-1].append((line.split(' : ')[0], None, False))
        else:
            key, value = line.split(' = ', 1)
            stack[-1].append((key, value, False))
    if len(stack) != 1:
        raise AssertionError('Unbalanced generated CFG')

    def merge(target, rows):
        for key, value, bpatch in rows:
            if key == '[*]':
                indices = [int(k[1:-1]) for k in target if re.fullmatch(r'\[\d+\]', k)]
                key = f'[{max(indices, default=-1) + 1}]'
            if value is None:
                del target[key]
            elif isinstance(value, list):
                if bpatch and key not in target:
                    raise AssertionError(f'Patch target does not exist: {key}')
                child = target[key] if bpatch else {}
                merge(child, value)
                target[key] = child
            else:
                target[key] = value
    result = copy.deepcopy(original)
    merge(result, root)
    return result


def faction(name='Neutral', role='CloseCombat', rank='Veteran', role_percent=20, rank_percent=15):
    return SimpleNamespace(
        name=name,
        roles={key: SimpleNamespace(enabled=key == role, percent=role_percent)
               for key, _label in distribution.ROLES},
        ranks={key: SimpleNamespace(enabled=key == rank, percent=rank_percent)
               for key in distribution.RANKS})


def trader(sid='RostokTraderSoviet_TradeItemGenerator', **kwargs):
    values = dict(name=sid, enabled=True, chance=40, min_quantity=1, max_quantity=5,
                  min_condition=10, max_condition=100, sell_unloaded=True)
    values.update(kwargs)
    return SimpleNamespace(**values)


class DistributionTests(unittest.TestCase):
    def info(self, template='TemplatePistol', factions=(), traders=()):
        return {'cfg': SimpleNamespace(setup_template=template, npc_factions=list(factions),
                                       traders=list(traders), stock_custom_attachments=True),
                'sid': 'GunTest_HG', 'weapon_id': 'Test', 'mod': 'TestMod',
                'magazines': [], 'attachments': []}

    def source(self, sid):
        return {sid: {'SID': sid, 'RefreshTime': '1d',
                      'ItemGenerator': copy.deepcopy(distribution.DEFAULTS['npc'][sid]['groups'])}}

    def test_disabled_rules_emit_empty_persistent_file(self):
        info = self.info()
        enabled = distribution.files(self.info(traders=[trader()]))
        disabled = distribution.files(info)
        self.assertEqual(enabled.keys(), disabled.keys())
        text = next(iter(disabled.values()))
        self.assertNotIn('struct.begin', text)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / next(iter(enabled))
            path.parent.mkdir(parents=True)
            path.write_text(next(iter(enabled.values())))
            path.write_text(text)
            self.assertNotIn('GunTest_HG', path.read_text())

    def test_base_patches_and_private_generators_share_base_namespace(self):
        info = self.info(factions=[faction()], traders=[trader('IkarTrader_TradeItemGenerator')])
        files = distribution.files(info)
        path = str(Path('GameLite') / 'GameData' / 'ItemGeneratorPrototypes'
                   / 'TestMod_TestDistribution.cfg')
        legacy = str(Path('GameLite') / 'ModGameData' / 'TestMod'
                     / 'ItemGeneratorPrototypes' / 'TestDistribution.cfg')
        self.assertEqual(set(files), {path, legacy})
        text = distribution.distribution_compose.compose([distribution.payload(info)])
        self.assertIn('struct.begin {bpatch}', text)
        self.assertNotIn('struct.begin', files[path])
        self.assertNotIn('struct.begin', files[legacy])
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'distribution.cfg'
            cfg.write_text(text, encoding='utf-8')
            definitions = parse(cfg)
        references = re.findall(r'ItemGeneratorPrototypeSID = (Arsenal_\w+)', text)
        self.assertTrue(references)
        for sid in references:
            self.assertIn(sid, definitions)
            self.assertEqual(definitions[sid]['SID'], sid)
        self.assertIn('SID = Arsenal_TestMod_Combined_', text)

    def test_role_rank_multiplication(self):
        self.assertEqual(distribution.shares(faction(), 'CloseCombat')['Veteran'], 0.03)
        self.assertEqual(distribution.shares(faction(), 'Recon')['Veteran'], 0)
        self.assertEqual(distribution.shares(faction(), 'CloseCombat')['Master'], 0)

    def test_slot_uses_weapon_template_not_animation_or_sound_donor(self):
        for template in distribution.PRESETS:
            cfg = self.info(template)['cfg']
            cfg.firing_sound_donor = 'APB'
            self.assertEqual(distribution.slot(cfg),
                             'WeaponPistol' if distribution.PRESETS[template]['base_weapon'].endswith('_HG')
                             else 'WeaponPrimary')

    def test_trader_selector_has_unique_stable_enum_numbers(self):
        ids = [row[3] for row in distribution.TRADER_ITEMS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(next(row[3] for row in distribution.TRADER_ITEMS
                              if row[0] == 'RostokTraderSoviet_TradeItemGenerator'), 12)

    def test_trader_defaults_match_selected_template_stock(self):
        defaults = distribution.trader_defaults('TemplatePistol', 'RostokTraderNato_TradeItemGenerator')
        self.assertEqual(defaults, {'enabled': True, 'chance': 100, 'min_quantity': 1, 'max_quantity': 1,
                                    'min_condition': 100, 'max_condition': 100, 'sell_unloaded': False})
        absent = distribution.trader_defaults('TemplatePistol', 'RostokTraderSoviet_TradeItemGenerator')
        self.assertFalse(absent['enabled'])
        self.assertEqual(absent['chance'], 0)
        omitted = distribution.trader_defaults('TemplateShotgun', 'TraderTerikon_TradeItemGenerator')
        self.assertTrue(omitted['enabled'])
        self.assertEqual(omitted['min_quantity'], int(distribution.DEFAULTS['item_defaults']['MinCount']))
        self.assertEqual(omitted['max_quantity'], int(distribution.DEFAULTS['item_defaults']['MaxCount']))

    def test_stock_defaults_find_template_pool_even_when_it_is_not_always_active(self):
        cfg = self.info('TemplateShotgun')['cfg']
        _targets, route = distribution.trader_route(cfg, 'YanovTrader_TradeItemGenerator')
        self.assertEqual(route[0], 'Trader_T2_Guns_ItemGenerator')
        self.assertEqual(route[3], 0.3)
        self.assertTrue(distribution.trader_defaults(
            'TemplateShotgun', 'YanovTrader_TradeItemGenerator')['enabled'])

    def test_approximate_npc_defaults_average_difficulty_then_factor_role_and_rank(self):
        def pool(rank, donor_weight, difficulty=None):
            row = {
                'Category': 'EItemGenerationCategory::WeaponPrimary', 'PlayerRank': f'ERank::{rank}',
                'PossibleItems': {
                    '[0]': {'ItemPrototypeSID': 'GunAK74_ST', 'Weight': str(donor_weight)},
                    '[1]': {'ItemPrototypeSID': 'OtherGun', 'Weight': str(100 - donor_weight)},
                },
            }
            if difficulty:
                row['Diff'] = difficulty
            return row
        references = {
            'GeneralNPC_Neutral_CloseCombat_ItemGenerator': {'groups': {
                '[0]': pool('Newbie', 20),
                '[1]': pool('Veteran', 10, 'EGameDifficulty::Easy, EGameDifficulty::Medium, EGameDifficulty::Hard'),
                '[2]': pool('Veteran', 50, 'EGameDifficulty::Stalker'),
            }},
            'GeneralNPC_Neutral_Recon_ItemGenerator': {'groups': {
                '[0]': pool('Newbie', 40), '[1]': pool('Veteran', 10),
            }},
        }
        distribution.faction_defaults.cache_clear()
        self.addCleanup(distribution.faction_defaults.cache_clear)
        with patch.dict(distribution.DEFAULTS, npc=references):
            defaults = distribution.faction_defaults('TemplateRifle', 'Neutral')
        # Role maxima: Close Combat max(20, (10+10+10+50)/4)=20%; Recon max(40,10)=40%.
        self.assertEqual(defaults['roles']['CloseCombat'], (True, 20))
        self.assertEqual(defaults['roles']['Recon'], (True, 40))
        self.assertEqual(defaults['roles']['Heavy'], (False, 0))
        self.assertEqual(defaults['ranks']['Newbie'], (True, 100))
        self.assertEqual(defaults['ranks']['Veteran'], (True, 62.5))
        self.assertEqual(defaults['ranks']['Experienced'], (False, 0))
        self.assertEqual(defaults['ranks']['Master'], (False, 0))

    def test_npc_template_absence_disables_all_roles_and_ranks(self):
        distribution.faction_defaults.cache_clear()
        self.addCleanup(distribution.faction_defaults.cache_clear)
        with patch.dict(distribution.DEFAULTS, npc={}):
            defaults = distribution.faction_defaults('TemplateRifle', 'Neutral')
        self.assertTrue(all(value == (False, 0) for value in defaults['roles'].values()))
        self.assertTrue(all(value == (False, 0) for value in defaults['ranks'].values()))

    def test_all_template_defaults_are_finite_in_range_and_do_not_mutate_catalogue(self):
        before = copy.deepcopy(distribution.DEFAULTS)
        for template in distribution.PRESETS:
            for sid in distribution.DEFAULTS['traders']:
                row = distribution.trader_defaults(template, sid)
                self.assertLessEqual(row['min_quantity'], row['max_quantity'])
                for field in ('chance', 'min_condition', 'max_condition'):
                    self.assertGreaterEqual(row[field], 0)
                    self.assertLessEqual(row[field], 100)
            for faction_sid, _label in distribution.FACTIONS:
                row = distribution.faction_defaults(template, faction_sid)
                for collection in ('roles', 'ranks'):
                    for enabled, percent in row[collection].values():
                        self.assertGreaterEqual(percent, 0)
                        self.assertLessEqual(percent, 100)
                        self.assertEqual(enabled, percent > 0)
        self.assertEqual(distribution.DEFAULTS, before)

    def test_primary_addition_has_exact_three_percent_share_and_preserves_gear(self):
        info = self.info('TemplateRifle', [faction()])
        sid = 'GeneralNPC_Neutral_CloseCombat_ItemGenerator'
        original = self.source(sid)
        original[sid]['ItemGenerator']['[999]'] = {'Category': 'Armor', 'Unrelated': 'keep'}
        result = apply('\n'.join(distribution.npc_lines(info)), original)
        self.assertEqual(result[sid]['RefreshTime'], '1d')
        self.assertEqual(result[sid]['ItemGenerator']['[999]'], {'Category': 'Armor', 'Unrelated': 'keep'})
        changed = 0
        for key, source in distribution.DEFAULTS['npc'][sid]['groups'].items():
            group = result[sid]['ItemGenerator'][key]
            ours = [row for row in group['PossibleItems'].values()
                    if row.get('ItemPrototypeSID') == info['sid']]
            if 'ERank::Veteran' == source.get('PlayerRank') and source['Category'].endswith('WeaponPrimary'):
                changed += 1
                self.assertEqual(len(ours), 1)
                total = sum(distribution.number(row.get('Weight', '4.f'))
                            for row in group['PossibleItems'].values())
                self.assertAlmostEqual(float(ours[0]['Weight']) / total, 0.03, places=10)
                for index, row in source['PossibleItems'].items():
                    self.assertEqual(group['PossibleItems'][index], row)
            else:
                self.assertFalse(ours)
                self.assertEqual(group, source)
        self.assertGreater(changed, 0)

    def test_pistol_route_is_role_owned_and_retains_activation_chance(self):
        sid = 'GeneralNPC_Neutral_CloseCombat_ItemGenerator'
        info = self.info(factions=[faction()])
        original = self.source(sid)
        original['GeneralNPC_Neutral_Recon_ItemGenerator'] = {'Unrelated': 'keep'}
        original['GeneralNPC_Neutral_WeaponPistol'] = {'ItemGenerator': distribution.DEFAULTS['pistols'][
            'GeneralNPC_Neutral_WeaponPistol']}
        result = apply('\n'.join(distribution.npc_lines(info)), original)
        self.assertEqual(result['GeneralNPC_Neutral_WeaponPistol'], original['GeneralNPC_Neutral_WeaponPistol'])
        self.assertEqual(result['GeneralNPC_Neutral_Recon_ItemGenerator'],
                         original['GeneralNPC_Neutral_Recon_ItemGenerator'])
        custom = [key for key in result if key.startswith('Arsenal_')]
        self.assertEqual(len(custom), 1)
        changed = 0
        for key, source in original[sid]['ItemGenerator'].items():
            target = result[sid]['ItemGenerator'][key]
            for index, entry in source['PossibleItems'].items():
                if entry.get('ItemGeneratorPrototypeSID') == 'GeneralNPC_Neutral_WeaponPistol':
                    changed += 1
                    self.assertEqual(target['PossibleItems'][index],
                                     dict(entry, ItemGeneratorPrototypeSID=custom[0]))
        self.assertEqual(changed, 1)
        for group in result[custom[0]]['ItemGenerator'].values():
            ours = [row for row in group['PossibleItems'].values() if row['ItemPrototypeSID'] == info['sid']]
            self.assertEqual(len(ours), int(group['PlayerRank'] == 'ERank::Veteran'))
            if ours:
                total = sum(float(row['Weight']) for row in group['PossibleItems'].values())
                self.assertAlmostEqual(float(ours[0]['Weight']) / total, 0.03, places=10)

    def test_combined_primary_ranks_are_split_without_leaking_to_master(self):
        sid = 'GeneralNPC_Bandit_CloseCombat_ItemGenerator'
        info = self.info('TemplateShotgun', [faction('Bandit')])
        original = self.source(sid)
        result = apply('\n'.join(distribution.npc_lines(info)), original)
        combined = [key for key, group in original[sid]['ItemGenerator'].items()
                    if 'Veteran' in group.get('PlayerRank', '') and 'Master' in group.get('PlayerRank', '')]
        self.assertTrue(combined)
        for key in combined:
            self.assertNotIn(key, result[sid]['ItemGenerator'])
        for group in result[sid]['ItemGenerator'].values():
            if group.get('PlayerRank') == 'ERank::Master':
                self.assertFalse(any(row.get('ItemPrototypeSID') == info['sid']
                                     for row in group['PossibleItems'].values()))
        self.assertIn(info['sid'], str(result))

    def test_combined_pistol_ranks_are_split_without_leaking(self):
        sid = 'GeneralNPC_Scientists_Recon_ItemGenerator'
        info = self.info(factions=[faction('Scientists', 'Recon')])
        result = apply('\n'.join(distribution.npc_lines(info)), self.source(sid))
        clone = next(value for key, value in result.items() if key.startswith('Arsenal_'))
        self.assertEqual(len(clone['ItemGenerator']), 4)
        for group in clone['ItemGenerator'].values():
            self.assertEqual(any(row['ItemPrototypeSID'] == info['sid']
                                 for row in group['PossibleItems'].values()),
                             group['PlayerRank'] == 'ERank::Veteran')

    def test_hundred_percent_replaces_only_selected_slot_rank_candidates(self):
        sid = 'GeneralNPC_Neutral_CloseCombat_ItemGenerator'
        info = self.info('TemplateRifle', [faction(role_percent=100, rank_percent=100)])
        original = self.source(sid)
        result = apply('\n'.join(distribution.npc_lines(info)), original)
        for key, source in original[sid]['ItemGenerator'].items():
            group = result[sid]['ItemGenerator'][key]
            if group.get('PlayerRank') == 'ERank::Veteran' and group['Category'].endswith('WeaponPrimary'):
                self.assertEqual(len(group['PossibleItems']), 1)
                self.assertEqual(next(iter(group['PossibleItems'].values()))['ItemPrototypeSID'], info['sid'])
            else:
                self.assertEqual(group, source)

    def test_trader_patch_uses_existing_group_and_mockup_values(self):
        rule = trader()
        info = self.info(traders=[rule])
        groups = copy.deepcopy(distribution.DEFAULTS['traders'][rule.name]['groups'])
        result = apply('\n'.join(distribution.trader_lines(info)),
                       {rule.name: {'ItemGenerator': groups, 'RefreshTime': '8h'}})
        self.assertEqual(result[rule.name]['RefreshTime'], '8h')
        self.assertEqual(result[rule.name]['ItemGenerator'].keys(), groups.keys())
        target = result[rule.name]['ItemGenerator']['[3]']['PossibleItems']
        ours = next(row for row in target.values() if row['ItemPrototypeSID'] == info['sid'])
        self.assertEqual(ours, {'ItemPrototypeSID': info['sid'], 'Chance': '0.4',
                               'MinCount': '1', 'MaxCount': '5', 'MinDurability': '0.1',
                               'MaxDurability': '1', 'bUnloadedWeapon': 'true'})

    def test_shared_trader_pool_is_cloned_only_for_selected_trader_and_rolled_once(self):
        rule = trader('NewbeeVillageTrader_TradeItemGenerator')
        info = self.info(traders=[rule])
        groups = distribution.DEFAULTS['traders'][rule.name]['groups']
        original = {rule.name: {'ItemGenerator': groups}, 'AnotherTrader': {'Unrelated': 'keep'}}
        result = apply('\n'.join(distribution.trader_lines(info)), original)
        self.assertEqual(result['AnotherTrader'], original['AnotherTrader'])
        clones = [value for key, value in result.items() if key.startswith('Arsenal_')]
        self.assertEqual(len(clones), 1)
        self.assertEqual(sum(row.get('ItemPrototypeSID') == info['sid']
                             for group in clones[0]['ItemGenerator'].values()
                             for row in group['PossibleItems'].values()), 1)
        for key in result:
            self.assertFalse(key.startswith('Trader_T'))

    def test_trader_stock_gate_is_preserved_and_effective_chance_is_twenty_percent(self):
        rule = trader('IkarTrader_TradeItemGenerator')
        info = self.info(traders=[rule])
        info['cfg'].distribution_trader = rule.name
        self.assertEqual(distribution.trader_activation(info['cfg']), 0.5)
        self.assertEqual(rule.chance * distribution.trader_activation(info['cfg']), 20)
        original = {rule.name: {'ItemGenerator': distribution.DEFAULTS['traders'][rule.name]['groups']}}
        result = apply('\n'.join(distribution.trader_lines(info)), original)
        self.assertEqual(result[rule.name]['ItemGenerator']['[0]']['PossibleItems']['[0]']['Chance'], '0.5')
        clone = next(row for key, row in result.items() if key.startswith('Arsenal_'))
        ours = [item for group in clone['ItemGenerator'].values()
                for item in group['PossibleItems'].values() if item.get('ItemPrototypeSID') == info['sid']]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0]['Chance'], '0.4')
        for sid in distribution.DEFAULTS['traders']:
            info['cfg'].distribution_trader = sid
            self.assertEqual(distribution.trader_activation(info['cfg']),
                             0.5 if sid == 'IkarTrader_TradeItemGenerator' else 1)

    def test_template_fallback_preserves_difficulty_specific_ammo_defaults(self):
        def group(diff, ammo, donor):
            return {'Category': 'EItemGenerationCategory::WeaponPrimary', 'PlayerRank': 'ERank::Veteran',
                    'Diff': diff, 'PossibleItems': {'[0]': {
                        'ItemPrototypeSID': donor, 'Weight': '10', 'MinDurability': '0.25',
                        'MaxDurability': '0.5', 'AmmoMinCount': '0', 'AmmoMaxCount': ammo}}}
        target = group('unused', '1', 'GunAK74_ST')
        del target['Diff']
        donors = {
            'EasyReference': {'faction': 'Neutral', 'groups': {'[0]': group(
                'EGameDifficulty::Easy, EGameDifficulty::Medium, EGameDifficulty::Hard', '2', 'GunViper_PP')}},
            'StalkerReference': {'faction': 'Neutral', 'groups': {'[0]': group(
                'EGameDifficulty::Stalker', '9', 'GunViper_PP')}},
        }
        with patch.dict(distribution.DEFAULTS, npc=donors, pistols={}):
            variants = distribution.split_group(target, self.info('TemplateSMG'), 'Neutral', {'Veteran': 0.03})
        self.assertEqual(len(variants), 2)
        for row in variants:
            ours = next(item for item in row['PossibleItems'].values() if item['ItemPrototypeSID'] == 'GunTest_HG')
            self.assertEqual(ours['AmmoMaxCount'], '9' if row['Diff'] == 'EGameDifficulty::Stalker' else '2')

    def test_template_donor_defaults_are_copied_exactly(self):
        group = distribution.DEFAULTS['pistols']['GeneralNPC_Neutral_WeaponPistol']['[1]']
        udp = next(row for row in group['PossibleItems'].values()
                   if row['ItemPrototypeSID'] == 'GunUDP_HG')
        item = distribution.weapon_item(self.info(), group, 'Experienced', 'Neutral', 0.03)
        for key in distribution.INHERITED_FIELDS[:4]:
            self.assertEqual(item[key], udp[key])

    def test_missing_local_donor_uses_same_template_rank_reference_not_an_arbitrary_gun(self):
        group = distribution.DEFAULTS['pistols']['GeneralNPC_Neutral_WeaponPistol']['[0]']
        defaults = distribution.inherited_defaults('TemplatePistol', group, 'Newbie', 'Neutral')
        self.assertEqual(defaults, {'MinDurability': '0.25', 'MaxDurability': '0.5',
                                    'AmmoMinCount': '0', 'AmmoMaxCount': '3'})

    def test_missing_template_defaults_fail_explicitly(self):
        with patch.dict(distribution.DEFAULTS, npc={}, pistols={}):
            with self.assertRaisesRegex(RuntimeError, 'No GunUDP_HG condition/ammo defaults'):
                distribution.inherited_defaults('TemplatePistol', {'PossibleItems': {}}, 'Newbie', 'Neutral')

    def test_invalid_ranges_and_unknown_rules_fail_explicitly(self):
        for settings in ({'min_quantity': 6}, {'min_condition': 101}, {'min_condition': 90, 'max_condition': 80},
                         {'name': 'Missing'}, {'chance': float('nan')}):
            with self.subTest(settings=settings), self.assertRaises(RuntimeError):
                distribution.files(self.info(traders=[trader(**settings)]))
        with self.assertRaisesRegex(RuntimeError, 'has no Heavy loadout'):
            distribution.files(self.info(factions=[faction('Scientists', 'Heavy')]))

    def test_legacy_templates_support_all_factions_roles_ranks_without_mutating_catalogue(self):
        before = copy.deepcopy(distribution.DEFAULTS)
        for template in ('TemplatePistol', 'TemplateSMG', 'TemplateRifle', 'TemplateShotgun', 'TemplateSniper'):
            rules = []
            for name, _label in distribution.FACTIONS:
                row = faction(name)
                for role, value in row.roles.items():
                    value.enabled = role in distribution.available_roles(name)
                    value.percent = 20
                for value in row.ranks.values():
                    value.enabled, value.percent = True, 15
                rules.append(row)
            text = distribution.distribution_compose.compose([distribution.payload(self.info(template, rules))])
            self.assertIn('ItemPrototypeSID = GunTest_HG', text)
            original = {sid: {'ItemGenerator': row['groups']}
                        for sid, row in distribution.DEFAULTS['npc'].items()}
            result = apply(text, original)
            self.assertGreater(len(result), 0)
        for sid in distribution.DEFAULTS['traders']:
            for template in distribution.PRESETS:
                self.assertIn('GunTest_HG', distribution.distribution_compose.compose([
                    distribution.payload(self.info(template, traders=[trader(sid)]))]))
        self.assertEqual(distribution.DEFAULTS, before)

    def test_all_weapon_templates_support_their_actual_distribution_defaults(self):
        for template in distribution.PRESETS:
            with self.subTest(template=template):
                rules = []
                for name, _label in distribution.FACTIONS:
                    row = faction(name)
                    defaults = distribution.faction_defaults(template, name)
                    for collection in ('roles', 'ranks'):
                        for key, values in defaults[collection].items():
                            item = getattr(row, collection)[key]
                            item.enabled, item.percent = values
                    rules.append(row)
                distribution.distribution_compose.compose([distribution.payload(self.info(template, rules))])

    def test_new_template_without_rank_donor_fails_explicitly(self):
        with self.assertRaisesRegex(RuntimeError, 'No GunRhino_HG condition/ammo defaults'):
            distribution.inherited_defaults('TemplateRhino', {'PossibleItems': {}}, 'Newbie', 'Neutral')


class CatalogueBuilderTests(unittest.TestCase):
    def test_wildcards_explicit_indices_and_duplicate_indices_match_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.cfg'
            path.write_text('Root : struct.begin\n[*] : struct.begin\nV = 1\nstruct.end\n'
                            '[3] : struct.begin\nV = 2\nstruct.end\n'
                            '[*] : struct.begin\nV = 3\nstruct.end\n'
                            '[3] : struct.begin\nV = 4\nstruct.end\nstruct.end\n')
            self.assertEqual(parse(path), {'Root': {'[0]': {'V': '1'}, '[3]': {'V': '4'}, '[4]': {'V': '3'}}})

    @unittest.skipUnless(Path(r'X:\STALKER2ZoneKit\Stalker2\Content\GameLite\GameData').is_dir(),
                         'Installed ZoneKit data is optional')
    def test_bundled_catalogue_matches_installed_generator_paths_and_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogue.json'
            build(Path(r'X:\STALKER2ZoneKit\Stalker2\Content\GameLite\GameData'), path)
            self.assertEqual(path.read_bytes(), (ROOT / 'resources' / 'distribution_defaults.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
