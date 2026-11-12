"""Mod-owned upgrade trees seeded from verified base-game CFG defaults."""
import json
import math
import os
import re

from .weapon_presets import PRESETS

with open(os.path.join(os.path.dirname(__file__), 'resources', 'upgrade_defaults.json'), encoding='utf-8') as handle:
    DEFAULTS = json.load(handle)

EFFECT_ITEMS = tuple((sid, f'{value["Type"].split("::")[-1]}: {sid}',
                      f'Base values: {value["ValueMin"]} to {value["ValueMax"]}', value['enum_id'])
                     for sid, value in DEFAULTS['effects'].items())
NON_NUMERIC = {'FlagEffect', 'ChangeCaliber', 'ChangeAmmoTypes'}


def effect_changed(item, context):
    defaults = DEFAULTS['effects'][item.prototype]
    item.percent = defaults['ValueMin'].endswith('%')
    item.value_min = float(defaults['ValueMin'].rstrip('%f'))
    item.value_max = float(defaults['ValueMax'].rstrip('%f'))
    item.beneficial = defaults['Positive'].split('::')[-1]


def tree_changed(cfg, context):
    if not cfg.keep_upgrades and not cfg.upgrade_template:
        seed_tree(cfg)


def seed_tree(cfg):
    cfg.upgrades.clear()
    rows = DEFAULTS['templates'][cfg.setup_template]
    names = {row['sid']: row['sid'].split('_Upgrade_', 1)[1] for row in rows}
    for row in rows:
        item = cfg.upgrades.add()
        item.name = names[row['sid']]
        item.template_sid = row['sid']
        item.base_cost = float(row['BaseCost'].rstrip('f'))
        item.horizontal = int(row['HorizontalPosition'])
        item.vertical = row['VerticalPosition'].split('::')[-1]
        item.target_part = row['UpgradeTargetPart'].split('::')[-1]
        item.modification = row['IsModification'] == 'true'
        item.hidden_without_item = row['HiddenWihoutItem'] == 'true'
        item.required = ', '.join(names[sid] for sid in row['RequiredUpgradePrototypeSIDs'])
        item.blocking = ', '.join(names[sid] for sid in row['BlockingUpgradePrototypeSIDs'])
        item.interchangeable = ', '.join(names[sid] for sid in row['InterchangeableUpgradePrototypeSIDs'])
        item.attachments = ', '.join(row['AttachPrototypeSIDs'])
        item.required_items = ', '.join(row['RequiredItemPrototypeSIDs'])
        item.skills = ', '.join(row['Skills'])
        item.connection_lines = ', '.join(value.split('::')[-1] for value in row['ConnectionLines'])
        for sid in row['EffectPrototypeSIDs']:
            effect = item.effects.add()
            effect.prototype = sid
            effect_changed(effect, None)
    cfg.upgrade_template = cfg.setup_template
    cfg.active_upgrade = 0


def prototype(item):
    for rows in DEFAULTS['templates'].values():
        for row in rows:
            if row['sid'] == item.template_sid:
                return row
    raise RuntimeError(f'Upgrade "{item.name}" has an unknown template: {item.template_sid}.')


def split_ids(value, label):
    ids = [sid.strip() for sid in value.split(',') if sid.strip()]
    if any(not re.fullmatch(r'[A-Za-z0-9_]+', sid) for sid in ids) or len(set(ids)) != len(ids):
        raise RuntimeError(f'{label} must be a comma-separated list of unique IDs.')
    return ids


def collect(info):
    cfg = info['cfg']
    if getattr(cfg, 'keep_upgrades', True):
        return []
    if not cfg.upgrade_template:
        seed_tree(cfg)
    names = [item.name for item in cfg.upgrades]
    if any(not re.fullmatch(r'[A-Za-z0-9_]+', name) for name in names) \
            or len({name.casefold() for name in names}) != len(names):
        raise RuntimeError('Upgrade IDs must be unique and contain only letters, digits and underscores.')
    mapping = {name: f'Gun{info["weapon_id"]}_Upgrade_{name}' for name in names}
    result, graph = [], {}
    for item in cfg.upgrades:
        base = prototype(item)
        values = {}
        for attr in ('required', 'blocking', 'interchangeable'):
            refs = split_ids(getattr(item, attr), f'{item.name} {attr}')
            if item.name in refs or any(ref not in mapping for ref in refs):
                raise RuntimeError(f'Upgrade "{item.name}" {attr} must refer to other IDs in this custom tree.')
            values[attr] = refs
        if set(values['required']) & set(values['blocking']):
            raise RuntimeError(f'Upgrade "{item.name}" requires an upgrade it also blocks.')
        graph[item.name] = values['required']
        for attr in ('attachments', 'required_items', 'skills'):
            values[attr] = split_ids(getattr(item, attr), f'{item.name} {attr}')
        lines = split_ids(item.connection_lines, f'{item.name} connection lines')
        if any(line not in ('None', 'Top', 'Down') for line in lines):
            raise RuntimeError('Upgrade connection lines must be None, Top or Down.')
        values['connection_lines'] = lines
        for effect in item.effects:
            if effect.prototype not in DEFAULTS['effects']:
                raise RuntimeError(f'Unknown effect for upgrade "{item.name}".')
            if effect.custom:
                if DEFAULTS['effects'][effect.prototype]['Type'].split('::')[-1] in NON_NUMERIC:
                    raise RuntimeError('Caliber, ammo-type and flag effects cannot use numerical overrides.')
                if not all(math.isfinite(value) for value in (effect.value_min, effect.value_max)) \
                        or effect.value_min > effect.value_max:
                    raise RuntimeError(f'Upgrade "{item.name}" needs finite effect values with Min <= Max.')
        result.append({'settings': item, 'sid': mapping[item.name], 'base': base, 'values': values})
    visited = set()

    def visit(name, ancestors):
        if name in ancestors:
            raise RuntimeError('Custom upgrade prerequisites contain a cycle.')
        if name not in visited:
            for other in graph[name]:
                visit(other, {*ancestors, name})
            visited.add(name)

    for name in graph:
        visit(name, set())
    return result


def upgrade_sids(info):
    if info['cfg'].keep_upgrades:
        return PRESETS[info['cfg'].setup_template]['upgrades']
    return [row['sid'] for row in collect(info)]


def laser_upgrade(info):
    if info['cfg'].keep_upgrades:
        return next((sid for sid in upgrade_sids(info) if 'Laser' in sid), None)
    return next((row['sid'] for row in collect(info) if
                 any('Laser' in sid for sid in row['values']['attachments'])), None)


def image_asset(info, item):
    return f'{info["mount"]}/UI/Arsenal/{info["weapon_id"]}/T_upgrade_{info["weapon_id"]}_{item.name}'


def files(info):
    from .weapon_cfg import Writer, number

    rows = collect(info)
    if not rows:
        return {}
    mapping = {row['settings'].name: row['sid'] for row in rows}
    upgrades, effects = Writer(), Writer()

    def array(writer, name, values):
        writer.begin(name, '{bskipref}')
        for index, value in enumerate(values):
            writer.line(f'[{index}] = {value}')
        writer.end()

    for row in rows:
        item, sid, base, values = row['settings'], row['sid'], row['base'], row['values']
        upgrades.begin(sid, f'{{refurl=@BaseGame/UpgradePrototypes.cfg;refkey={item.template_sid}}}')
        upgrades.line(f'SID = {sid}')
        for field, suffix in (('Text', 'name'), ('Hint', 'description')):
            has_text = any(getattr(text, suffix).strip() for text in item.texts)
            upgrades.line(f'{field} = sid_upgrades_{sid}_{suffix}' if has_text else f'{field} = {base[field]}')
        image = image_asset(info, item) if item.image else ''
        upgrades.line(f"Image = Texture2D'{image}.{image.rsplit('/', 1)[-1]}'" if image else f'Image = {base["Image"]}')
        for field, value in (
                ('BaseCost', number(item.base_cost)), ('HorizontalPosition', item.horizontal),
                ('VerticalPosition', f'EUpgradeVerticalPosition::{item.vertical}'),
                ('UpgradeTargetPart', f'EUpgradeTargetPartType::{item.target_part}'),
                ('IsModification', str(item.modification).lower()),
                ('HiddenWihoutItem', str(item.hidden_without_item).lower())):
            upgrades.line(f'{field} = {value}')
        for attr, field in (('required', 'RequiredUpgradePrototypeSIDs'),
                            ('blocking', 'BlockingUpgradePrototypeSIDs'),
                            ('interchangeable', 'InterchangeableUpgradePrototypeSIDs')):
            array(upgrades, field, [mapping[name] for name in values[attr]])
        for attr, field in (('attachments', 'AttachPrototypeSIDs'),
                            ('required_items', 'RequiredItemPrototypeSIDs'), ('skills', 'Skills')):
            refs = values[attr]
            if attr == 'attachments':
                refs = [next((attachment['sid'] for attachment in info.get('attachments', [])
                              if attachment['template'] == ref), ref) for ref in refs]
            array(upgrades, field, refs)
        array(upgrades, 'ConnectionLines', [f'EConnectionLineState::{value}' for value in values['connection_lines']])
        if not item.keep_restrictions:
            array(upgrades, 'RequiredGlobalVariables', [])
            array(upgrades, 'BlockingGlobalVariables', [])
        refs = []
        for index, effect in enumerate(item.effects):
            effect_sid = f'{sid}_Effect{index + 1}' if effect.custom else effect.prototype
            refs.append(effect_sid)
            if effect.custom:
                effects.begin(effect_sid, f'{{refurl=@BaseGame/EffectPrototypes.cfg;refkey={effect.prototype}}}')
                effects.line(f'SID = {effect_sid}')
                suffix = '%' if effect.percent else ''
                effects.line(f'ValueMin = {number(effect.value_min)}{suffix}')
                effects.line(f'ValueMax = {number(effect.value_max)}{suffix}')
                effects.line(f'Positive = EBeneficial::{effect.beneficial}')
                effects.line(f'ShowUpgradeEffect = {str(effect.show_effect).lower()}')
                effects.line(f'ShowUpgradeEffectValue = {str(effect.show_effect).lower()}')
                effects.end()
        array(upgrades, 'EffectPrototypeSIDs', refs)
        upgrades.end()
    base = os.path.join('GameLite', 'ModGameData', info['mod'])
    return {
        os.path.join(base, 'UpgradePrototypes', f'{info["weapon_id"]}UpgradePrototypes.cfg'): upgrades.text(),
        os.path.join(base, 'EffectPrototypes', f'{info["weapon_id"]}UpgradeEffects.cfg'): effects.text(),
    }


def localization_entries(info):
    from .weapon_cfg import LANGUAGE_MEMBERS

    entries = []
    for row in collect(info):
        for suffix in ('name', 'description'):
            texts = {f'ELocalizationLanguage::{LANGUAGE_MEMBERS[text.language]}':
                     getattr(text, suffix).replace('\\n', '\n')
                     for text in row['settings'].texts if text.language in LANGUAGE_MEMBERS
                     and getattr(text, suffix).strip()}
            if texts:
                entries.append({'SID': f'sid_upgrades_{row["sid"]}_{suffix}',
                                'LanguagesToLocalizedStrings': texts})
    return entries


def export_images(info):
    from .export_unreal import relative, write_texture

    entries = []
    for row in collect(info):
        item = row['settings']
        if item.image:
            if not all(item.image.size) or item.image.channels != 4:
                raise RuntimeError(f'Upgrade "{item.name}" needs a readable RGBA image.')
            asset = image_asset(info, item)
            path = os.path.join(info['output_root'], 'UI', 'Arsenal', info['weapon_id'],
                                asset.rsplit('/', 1)[-1] + '.png')
            write_texture(item.image, path)
            entries.append({'file': relative(path, info['output_root']), 'sid': row['sid'],
                            'family': 'upgrade_module', 'asset': asset})
    return entries
