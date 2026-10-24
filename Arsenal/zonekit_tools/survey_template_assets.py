"""Survey the base-game assets of the Arsenal template weapons (run inside the ZoneKit editor).

Paste this file's path into the ZoneKit Python bar. For every template weapon below it lists the
animation sequences, montages, anim collections, anim blueprints, skeletons, skeletal and static
meshes (and anything else whose name or folder contains the weapon's name tokens), and marks what the
Arsenal add-on does with each one:

  IMPORTED      the add-on exports a replacement that the import script creates in the mod
  STAYS         stays in ZoneKit as a copy/rename of the template and needs editing by hand or script
  NOT IMPORTED  nothing in the add-on produces or handles it yet (the reason is given)

It also lists the shared base-game assets that the montages, anim collections and anim blueprints
depend on, and what else references them. The report is written as .txt and .json files and
summarised in the Output Log.

Edit TEMPLATES to survey other weapons, or set ONLY to a list of template names to run just those.
"""

import json
import os
import re
import time

import unreal

TEMPLATES = {
    'TemplatePistol': {'weapon': 'udp', 'tokens': ['udp', 'fp_udp', 'udp_fp']},
    'TemplateSMG': {'weapon': 'viper', 'tokens': ['viper', 'fp_viper', 'viper_fp', 'vip']},
    'TemplateRifle': {'weapon': 'ak74', 'tokens': ['ak74', 'fp_ak74', 'ak74_fp']},
    'TemplateShotgun': {'weapon': 'm860', 'tokens': ['m860', 'fp_m860', 'm860_fp', 'm86000']},
    'TemplateSniper': {'weapon': 'threeline',
                       'tokens': ['threeline', 'three_line', 'fp_threeline', 'threeline_fp']},
}
ONLY = []  # for example ['TemplatePistol', 'TemplateSMG']
OUTPUT_FOLDER = ''  # empty: a survey_output folder next to this script (or the project's Saved folder)
LISTED_LIMIT = 12  # referencing assets listed per asset (the full count is always shown)


def log(message):
    unreal.log(f'[Arsenal survey] {message}')


def warn(message):
    unreal.log_warning(f'[Arsenal survey] {message}')


def output_folder():
    if OUTPUT_FOLDER:
        folder = OUTPUT_FOLDER
    else:
        try:
            folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'survey_output')
        except NameError:
            folder = os.path.join(unreal.Paths.project_saved_dir(), 'ArsenalSurvey')
    os.makedirs(folder, exist_ok=True)
    return folder


def class_name_of(data):
    path = getattr(data, 'asset_class_path', None)
    if path is not None:
        return str(path.asset_name)
    return str(data.get_editor_property('asset_class'))


def safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def prop(asset, name, default=None):
    return safe(lambda: asset.get_editor_property(name), default)


def whole_token(token):
    # A token is a match when it is not part of a longer word; an optional "Gun" prefix covers GunUDP_HG
    return re.compile(r'(?<![a-z0-9])(?:gun)?' + re.escape(token.lower()) + r'(?![a-z0-9])')


class Survey:
    def __init__(self, name, info, assets, registry):
        self.name = name
        self.weapon = info['weapon'].lower()
        self.tokens = info['tokens']
        self.patterns = {token: whole_token(token) for token in self.tokens}
        self.assets = assets
        self.registry = registry
        self.records = []
        self.loose = []
        self.by_package = {}
        self.options = self.dependency_options()
        self.class_cache = {}

    @staticmethod
    def dependency_options():
        options = unreal.AssetRegistryDependencyOptions()
        for name in ('include_soft_package_references', 'include_hard_package_references'):
            safe(lambda name=name: options.set_editor_property(name, True))
        return options

    # --- matching -------------------------------------------------------------------------

    def collect(self):
        for package, name, class_name in self.assets:
            lowered = package.lower()
            if not any(token.lower() in lowered for token in self.tokens):
                continue
            matched = [token for token, pattern in self.patterns.items() if pattern.search(lowered)]
            record = {'package': package, 'name': name, 'class': class_name, 'matched_by': matched}
            if matched:
                self.records.append(record)
                self.by_package[package] = record
            else:
                self.loose.append(record)
        for record in self.records:
            record['role'] = self.role(record)
        for record in self.records:
            record['status'], record['reason'] = self.status(record)
        self.records.sort(key=lambda item: (item['role'], item['package'].lower()))

    def role(self, record):
        class_name, path = record['class'], record['package'].lower()
        side = 'player' if '/animations/player/' in path else 'weapon' if '/animations/weapons/' in path else ''
        if class_name == 'AnimSequence':
            return f'AnimSequence ({side or "other folder"})'
        if class_name == 'AnimMontage':
            return f'AnimMontage ({side or "other folder"})'
        if 'AnimCollection' in class_name:
            return 'AnimCollection'
        if class_name in ('AnimBlueprint', 'AnimBlueprintGeneratedClass'):
            return 'AnimBlueprint'
        if class_name == 'Skeleton':
            return 'Skeleton'
        if class_name == 'SkeletalMesh':
            return 'SkeletalMesh'
        if class_name == 'StaticMesh':
            return 'StaticMesh'
        return class_name

    def status(self, record):
        name, path = record['name'].lower(), record['package'].lower()
        role, weapon = record['role'], self.weapon
        if role.startswith('AnimSequence'):
            side = 'player' if 'player' in role else 'weapon' if 'weapon' in role else ''
            if not side:
                return 'NOT IMPORTED', 'sequence outside Animations/Player and Animations/Weapons'
            if 'additive' not in record:
                self.load_sequence_details(record)
            additive = record.get('additive')
            if additive and additive not in ('AAT_NONE', 'unknown'):
                return 'NOT IMPORTED', f'additive sequence ({additive}); the add-on only exports full-body animation'
            pattern = rf'as_fp_{re.escape(weapon)}_(.+)' if side == 'player' else rf'as_{re.escape(weapon)}_fp_(.+)'
            if not re.fullmatch(pattern, name):
                expected = f'AS_fp_{weapon}_*' if side == 'player' else f'AS_{weapon}_fp_*'
                return 'NOT IMPORTED', f'name does not follow {expected}, so the add-on never pairs or exports it'
            if f'/pt/{weapon}/' not in path:
                return 'NOT IMPORTED', f'folder is not .../pt/{weapon}/...'
            return 'IMPORTED', 'retargeted by the add-on and imported by the import script'
        if role.startswith('AnimMontage'):
            return 'STAYS', ('montage stays in ZoneKit: copy/rename it, then its sequence slots, '
                             'skeleton and notifies must point at the new animations')
        if role == 'AnimCollection':
            return 'STAYS', 'collection stays in ZoneKit: montage/sequence references and magazine SIDs need replacing'
        if role == 'AnimBlueprint':
            return 'STAYS', 'AnimBP stays in ZoneKit: copy/rename by hand; skeleton and collection references change'
        if role == 'Skeleton':
            return 'IMPORTED', 'created when SK_<weapon> is imported from the add-on skeletal mesh export'
        if role == 'SkeletalMesh':
            return 'IMPORTED', 'SK_<weapon> is exported from the rig and imported'
        if role == 'StaticMesh':
            return self.static_mesh_status(name, path)
        if role in ('MaterialInstanceConstant', 'Material', 'Texture2D'):
            return 'NOT IMPORTED', 'materials and textures are not exported; the import reuses base-game materials'
        if role == 'PhysicsAsset':
            return 'NOT IMPORTED', 'physics asset is not created (create_physics_asset is off)'
        if role in ('AkAudioEvent', 'AkSwitchValue', 'AkAudioBank'):
            return 'NOT IMPORTED', 'audio stays on the base game; the CFG files reference the template events'
        if role in ('BlendSpace', 'BlendSpace1D', 'AimOffsetBlendSpace', 'AimOffsetBlendSpace1D'):
            return 'NOT IMPORTED', 'blend space is not exported or copied'
        return 'NOT IMPORTED', 'asset type is not handled by the add-on'

    def static_mesh_status(self, name, path):
        weapon = self.weapon
        if '/skins/' in path:
            return 'NOT IMPORTED', 'skin/variant mesh (for example Deadeye); the add-on exports no skins'
        if name.startswith(f'sm_wpn_{weapon}_sm_'):
            return 'IMPORTED', 'animated weapon part (AnimMesh), split per bone by the add-on'
        if name == f'sm_{weapon}':
            return 'IMPORTED', 'in-world mesh of the whole weapon'
        if re.search(r'(mag|magazine)', name):
            return 'NOT IMPORTED', 'magazine mesh with a template-specific name; the add-on names its own SM_wpn_<w>_SM_*'
        return 'NOT IMPORTED', 'static mesh not part of the add-on naming scheme (LODs, upgrades or attachments?)'

    # --- details --------------------------------------------------------------------------

    def load(self, package):
        return safe(lambda: unreal.EditorAssetLibrary.load_asset(package))

    def load_sequence_details(self, record):
        details = record.setdefault('details', {})
        asset = self.load(record['package'])
        if asset is None:
            details['load'] = 'failed'
            record['additive'] = 'unknown'
            return
        additive = prop(asset, 'additive_anim_type')
        found = re.search(r'AAT_\w+', str(additive)) if additive is not None else None
        record['additive'] = found.group(0) if found else 'unknown'
        details['additive'] = record['additive']
        base_pose = prop(asset, 'ref_pose_seq')
        if base_pose is not None and record['additive'] not in ('AAT_NONE', 'unknown'):
            details['additive_base_pose'] = base_pose.get_path_name()
            details['ref_pose_type'] = str(prop(asset, 'ref_pose_type')).split('.')[-1]
        skeleton = prop(asset, 'skeleton')
        details['skeleton'] = skeleton.get_path_name() if skeleton else None
        details['length_seconds'] = safe(lambda: round(asset.get_play_length(), 4))
        details['frames'] = safe(lambda: unreal.AnimationLibrary.get_num_frames(asset))
        details['rate_scale'] = prop(asset, 'rate_scale')
        details['root_motion'] = prop(asset, 'enable_root_motion')
        notifies = prop(asset, 'notifies')
        details['notifies'] = len(notifies) if notifies is not None else None

    def describe_assets(self):
        for index, record in enumerate(self.records):
            role = record['role']
            if role.startswith('AnimMontage'):
                self.load_montage_details(record)
            elif role == 'AnimCollection':
                self.load_collection_details(record)
            elif role == 'AnimBlueprint':
                self.load_blueprint_details(record)
            if index % 50 == 49:
                log(f'{self.name}: described {index + 1}/{len(self.records)} assets')

    def load_montage_details(self, record):
        details = record.setdefault('details', {})
        asset = self.load(record['package'])
        if asset is None:
            details['load'] = 'failed'
            return
        skeleton = prop(asset, 'skeleton')
        details['skeleton'] = skeleton.get_path_name() if skeleton else None
        details['length_seconds'] = safe(lambda: round(asset.get_play_length(), 4))
        for label, name in (('sections', 'composite_sections'), ('notifies', 'notifies'),
                            ('slot_tracks', 'slot_anim_tracks')):
            value = prop(asset, name)
            details[label] = len(value) if value is not None else 'inaccessible from Python'
        slots = []
        for track in prop(asset, 'slot_anim_tracks') or []:
            slots.append(safe(lambda track=track: str(track.get_editor_property('slot_name'))))
        if slots:
            details['slot_names'] = slots

    def load_collection_details(self, record):
        details = record.setdefault('details', {})
        asset = self.load(record['package'])
        if asset is None:
            details['load'] = 'failed'
            return
        properties, magazine_sids = {}, set()
        for name in dir(asset):
            if name.startswith('_'):
                continue
            value = prop(asset, name)
            if value is None:
                continue
            text = safe(lambda value=value: value.export_text()) if hasattr(value, 'export_text') else None
            text = text if isinstance(text, str) else str(value)
            magazine_sids.update(re.findall(r'Gun\w+?_Mag\w+', text))
            properties[name] = text[:300]
        details['properties'] = properties
        details['magazine_sids'] = sorted(magazine_sids)
        if not properties:
            details['note'] = 'no properties are exposed to Python; the dependency list below is the only view'

    def load_blueprint_details(self, record):
        details = record.setdefault('details', {})
        asset = self.load(record['package'])
        if asset is None:
            details['load'] = 'failed'
            return
        skeleton = prop(asset, 'target_skeleton')
        details['target_skeleton'] = skeleton.get_path_name() if skeleton else None

    # --- references -----------------------------------------------------------------------

    def class_of_package(self, package):
        if package not in self.class_cache:
            datas = safe(lambda: self.registry.get_assets_by_package_name(package), []) or []
            self.class_cache[package] = class_name_of(datas[0]) if datas else 'unknown'
        return self.class_cache[package]

    def dependencies(self, package):
        found = safe(lambda: self.registry.get_dependencies(package, self.options), []) or []
        return [str(item) for item in found if not str(item).startswith('/Script/')]

    def referencers(self, package):
        found = safe(lambda: self.registry.get_referencers(package, self.options), []) or []
        return [str(item) for item in found if not str(item).startswith('/Script/')]

    def trace_references(self):
        """Dependencies of montages/collections/AnimBPs, and what references them (and the skeletons)."""
        for record in self.records:
            role = record['role']
            package = record['package']
            if role.startswith('AnimMontage') or role in ('AnimCollection', 'AnimBlueprint'):
                shared, template = {}, []
                for dependency in self.dependencies(package):
                    if dependency == package:
                        continue
                    if dependency in self.by_package:
                        template.append(dependency)
                    else:
                        shared.setdefault(self.class_of_package(dependency), []).append(dependency)
                record['depends_on_template'] = sorted(template)
                record['depends_on_shared'] = {key: sorted(value) for key, value in sorted(shared.items())}
            if role in ('AnimCollection', 'AnimBlueprint', 'Skeleton', 'SkeletalMesh'):
                outside = [item for item in self.referencers(package) if item not in self.by_package]
                record['referenced_by_outside'] = sorted(outside)

    # --- report ---------------------------------------------------------------------------

    def summary(self):
        counts = {}
        for record in self.records:
            key = (record['role'], record['status'])
            counts[key] = counts.get(key, 0) + 1
        return counts

    def gaps(self):
        reasons = {}
        for record in self.records:
            if record['status'] == 'NOT IMPORTED':
                reasons.setdefault(record['reason'], []).append(record)
        return reasons

    def text_report(self):
        out = []
        add = out.append
        add('=' * 100)
        add(f'{self.name}: weapon "{self.weapon}", tokens {self.tokens}')
        add(f'{len(self.records)} matched assets, {len(self.loose)} loose (substring only) matches')
        add('=' * 100)
        add('')
        add('SUMMARY (asset type / add-on status / count)')
        for (role, status), count in sorted(self.summary().items()):
            add(f'  {role:36} {status:13} {count}')
        add('')
        add('NOT IMPORTED YET (grouped by reason)')
        gaps = self.gaps()
        if not gaps:
            add('  (none)')
        for reason, records in sorted(gaps.items(), key=lambda item: -len(item[1])):
            add(f'  [{len(records)}] {reason}')
            for record in records:
                note = ''
                base_pose = record.get('details', {}).get('additive_base_pose')
                if base_pose:
                    note = f'   (additive on {base_pose})'
                add(f'      {record["package"]}{note}')
        add('')
        add('ALL MATCHED ASSETS')
        current = None
        for record in self.records:
            if record['role'] != current:
                current = record['role']
                add('')
                add(f'--- {current} ---')
            add(f'{record["status"]:13} {record["package"]}  [{record["class"]}; matched {record["matched_by"]}]')
            if record['status'] != 'IMPORTED':
                add(f'              {record["reason"]}')
            for key, value in record.get('details', {}).items():
                if key == 'properties':
                    for prop_name, text in value.items():
                        add(f'              property {prop_name}: {text}')
                else:
                    add(f'              {key}: {value}')
            if 'depends_on_template' in record:
                add(f'              uses {len(record["depends_on_template"])} template assets (same weapon):')
                for dependency in record['depends_on_template']:
                    add(f'                  {dependency}')
                shared = record['depends_on_shared']
                add(f'              uses {sum(len(v) for v in shared.values())} shared base-game assets '
                    '(they stay as they are):')
                for class_name, packages in shared.items():
                    add(f'                  {class_name} ({len(packages)})')
                    for dependency in packages:
                        add(f'                      {dependency}')
            if 'referenced_by_outside' in record:
                refs = record['referenced_by_outside']
                add(f'              referenced by {len(refs)} assets outside the matched set'
                    + (':' if refs else ''))
                for reference in refs[:LISTED_LIMIT]:
                    add(f'                  {reference}')
                if len(refs) > LISTED_LIMIT:
                    add(f'                  ... and {len(refs) - LISTED_LIMIT} more')
        add('')
        add('LOOSE MATCHES (the name contains the token only as part of a longer word; check by hand)')
        for record in sorted(self.loose, key=lambda item: item['package'].lower()):
            add(f'  {record["class"]:28} {record["package"]}')
        add('')
        return '\n'.join(out)


def gather_assets(registry):
    if registry.is_loading_assets():
        warn('The asset registry is still loading; results may be incomplete. Run the script again when it finishes.')
    assets = []
    for data in registry.get_all_assets():
        package = str(data.get_editor_property('package_name'))
        if package.startswith('/Game/'):
            assets.append((package, str(data.get_editor_property('asset_name')), class_name_of(data)))
    return assets


def main():
    started = time.time()
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = gather_assets(registry)
    log(f'{len(assets)} base game assets in the registry')
    folder = output_folder()
    combined, data = [], {}
    for name, info in TEMPLATES.items():
        if ONLY and name not in ONLY:
            continue
        log(f'{name}: surveying "{info["weapon"]}"')
        survey = Survey(name, info, assets, registry)
        survey.collect()
        survey.describe_assets()
        survey.trace_references()
        text = survey.text_report()
        combined.append(text)
        data[name] = {'weapon': survey.weapon, 'tokens': survey.tokens,
                      'assets': survey.records, 'loose': survey.loose}
        with open(os.path.join(folder, f'{name}_assets.txt'), 'w', encoding='utf-8') as handle:
            handle.write(text)
        for (role, status), count in sorted(survey.summary().items()):
            log(f'  {name}: {role} / {status}: {count}')
        for reason, records in sorted(survey.gaps().items(), key=lambda item: -len(item[1])):
            log(f'  {name}: NOT IMPORTED [{len(records)}] {reason}')
    with open(os.path.join(folder, 'all_templates_assets.txt'), 'w', encoding='utf-8') as handle:
        handle.write('\n\n'.join(combined))
    with open(os.path.join(folder, 'all_templates_assets.json'), 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=1, default=str)
    log(f'Done in {time.time() - started:.0f}s. Reports written to {folder}')


main()
