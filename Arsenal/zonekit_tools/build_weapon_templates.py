"""Extract standard firearm donor defaults and asset identifiers, not game assets.

python build_weapon_templates.py GAME_DATA_FOLDER OUTPUT.json
Enum numbers are saved in blends: never renumber or reuse them.
"""
import json
from pathlib import Path
import re
import sys

from build_upgrade_defaults import parse, resolve


WEAPONS = (
    ('TemplatePistol', 'GunUDP_HG', 'UDP', 0),
    ('TemplateSMG', 'GunViper_PP', 'Viper-5', 1),
    ('TemplateRifle', 'GunAK74_ST', 'AKM-74S', 2),
    ('TemplateShotgun', 'GunM860_SG', 'M860 Cracker', 3),
    ('TemplateSniper', 'GunThreeLine_SP', 'Three-Line', 4),
    ('TemplatePM', 'GunPM_HG', 'PTM', 5),
    ('TemplateAPB', 'GunAPB_HG', 'APSB', 6),
    ('TemplateM10', 'GunM10_HG', 'MAC-10', 7),
    ('TemplateRhino', 'GunRhino_HG', 'Rhino', 8),
    ('TemplateKora', 'GunKora_HG', 'Kora', 9),
    ('TemplateAKU', 'GunAKU_PP', 'AKM-74U', 10),
    ('TemplateBucket', 'GunBucket_PP', 'Bucket S-2', 11),
    ('TemplateIntegral', 'GunIntegral_PP', 'Integral-A', 12),
    ('TemplateZubr', 'GunZubr_PP', 'Zubr-19', 13),
    ('TemplateFora230', 'GunFora230_PP', 'Fora-230', 14),
    ('TemplateM16', 'GunM16_ST', 'AR416', 15),
    ('TemplateG37', 'GunG37_ST', 'GP37', 16),
    ('TemplateFora', 'GunFora_ST', 'Fora-221', 17),
    ('TemplateGrim', 'GunGrim_ST', 'Grom S-14', 18),
    ('TemplateGvintar', 'GunGvintar_ST', 'VS Vintar', 19),
    ('TemplateKharod', 'GunKharod_ST', 'Kharod', 20),
    ('TemplateLavina', 'GunLavina_ST', 'AS Lavina', 21),
    ('TemplateDnipro', 'GunDnipro_ST', 'Dnipro', 22),
    ('TemplateArev', 'GunArev_ST', 'Arev', 23),
    ('TemplatePKP', 'GunPKP_MG', 'RPM-74', 24),
    ('TemplateObrez', 'GunObrez_SG', 'Boomstick', 25),
    ('TemplateTOZ', 'GunTOZ_SG', 'TOZ-34', 26),
    ('TemplateSPSA', 'GunSPSA_SG', 'SPSA-14', 27),
    ('TemplateD12', 'GunD12_SG', 'Saiga D-12', 28),
    ('TemplateRam2', 'GunRam2_SG', 'RAM-2', 29),
    ('TemplateSKP', 'GunSKP_DMR', 'SKP', 30),
    ('TemplateMark', 'GunMark_SP', 'Mark I EMR', 31),
    ('TemplateGP3A', 'GunGP3A_DMR', 'GP3A', 32),
    ('TemplateSVD', 'GunSVDM_SP', 'SVDM-2', 33),
    ('TemplateM701', 'GunM701_SP', 'M701 Super', 34),
    ('TemplateSVU', 'GunSVU_SP', 'SVU-MK S-3', 35),
    ('TemplateGauss', 'GunGauss_SP', 'Gauss Gun', 36),
    ('TemplateRPG7', 'GunRpg7_GL', 'RPG-7U', 37),
)
ITEM_FIELDS = {'cost': 'Cost', 'weight': 'Weight', 'durability': 'BaseDurability'}
PLAYER_FIELDS = {
    'durability_per_shot': 'DurabilityDamagePerShot', 'base_damage': 'BaseDamage',
    'armor_damage': 'ArmorDamage', 'armor_piercing': 'ArmorPiercing',
    'cover_piercing': 'CoverPiercing', 'base_bleeding': 'BaseBleeding',
    'bleeding_chance': 'ChanceBleedingPerShot', 'effective_distance': 'EffectiveFireDistanceMin',
    'drop_off_distance': 'FireDistanceDropOff', 'min_distance_modifier': 'MinBulletDistanceDamageModifier',
    'projectile_drop_length': 'DistanceDropOffLength', 'fire_loudness': 'FireLoudness',
    'base_comfort': 'BaseComfort', 'ui_accuracy': 'AccuracyUI', 'ui_rate_of_fire': 'RateOfFireUI',
    'ui_handling': 'HandlingUI', 'ui_damage': 'DamageUI', 'ui_range': 'RangeUI',
    'dispersion_radius': 'DispersionRadius',
}
GENERAL_FIELDS = {
    'fire_interval': 'FireInterval', 'aiming_time': 'AimingTime',
    'offset_aiming_time': 'OffsetAimingTime', 'lean_aiming_time': 'LeanAimingTime',
    'lean_restore_time': 'LeanAimingRestoreTime', 'max_jam_chance': 'MaxJamChance',
}
AUDIO_FIELDS = (
    'OffsetAimingOffSound', 'OffsetAimingOnSound', 'FireEventOneShot', 'FireEventLoop',
    'FireEventBreak', 'WeaponTypeSoundSwitch', 'WeaponInWorldUnloadSound',
)


def numeric(value):
    return float(value.rstrip('%f'))


def asset_path(value):
    match = re.fullmatch(r"[^']*'([^']+)'", value)
    if not match:
        raise ValueError(f'Expected a nonempty asset path: {value}')
    return match[1].split('.', 1)[0]


def build(folder, destination):
    items = parse(folder / 'ItemPrototypes.cfg')
    items.update(parse(folder / 'ItemPrototypes' / 'WeaponPrototypes.cfg'))
    general = parse(folder / 'WeaponData' / 'WeaponGeneralSetupPrototypes.cfg')
    attributes = parse(folder / 'WeaponData' / 'WeaponAttributesPrototypes.cfg')
    attributes.update(parse(folder / 'WeaponData' / 'WeaponAttributesPrototypes'
                            / 'PlayerWeaponAttributesPrototypes.cfg'))
    players = parse(folder / 'WeaponData' / 'CharacterWeaponSettingsPrototypes.cfg')
    players.update(parse(folder / 'WeaponData' / 'CharacterWeaponSettingsPrototypes'
                         / 'PlayerWeaponSettingsPrototypes.cfg'))
    meshes = parse(folder / 'MeshPrototypes.cfg')
    mesh_by_sid = {row['SID']: resolve(meshes, key) for key, row in meshes.items()}
    attachments = parse(folder / 'ItemPrototypes.cfg')
    attachments.update(parse(folder / 'ItemPrototypes' / 'AttachPrototypes.cfg'))
    standard = {sid for sid, row in items.items()
                if re.fullmatch(r'Gun[A-Za-z0-9]+_(HG|PP|ST|MG|SG|DMR|SP|GL)', sid)
                and row.get('_ref', '').startswith('Template')}
    listed = {row[1] for row in WEAPONS}
    if standard != listed:
        raise ValueError(f'Update WEAPONS for installed standard firearms: '
                         f'missing={sorted(standard - listed)}, unexpected={sorted(listed - standard)}')
    result = {}
    for key, sid, label, enum_id in WEAPONS:
        item = resolve(items, sid)
        settings_ref = resolve(attributes, item['PlayerWeaponAttributes'])['DefaultWeaponSettingsSID']
        player = resolve(players, settings_ref)
        setup = resolve(general, item['GeneralWeaponSetup'])
        animation_path = asset_path(resolve(attributes, item['PlayerWeaponAttributes'])['AnimBlueprint'])
        animation = re.fullmatch(r'AnimBP_(.+)_fp', animation_path.rsplit('/', 1)[1], re.I)[1]
        mesh_path = asset_path(mesh_by_sid[item['MeshPrototypeSID']]['MeshPath'])
        mesh = re.fullmatch(r'SK_(.+)', mesh_path.rsplit('/', 1)[1], re.I)[1]
        world_path = asset_path(mesh_by_sid[item['MeshInWorldPrototypeSID']]['MeshPath'])
        category = re.search(r'/weapons/([^/]+)/', world_path, re.I)[1]
        part_tokens = set()
        for row in setup['WeaponStaticMeshParts'].values():
            if not isinstance(row, dict):
                continue
            stem = asset_path(row['MeshPath']).rsplit('/', 1)[1]
            match = re.fullmatch(r'SM_(?!amm_)(?:wpn_)?(.+?)_SM_.+', stem, re.I)
            if match:
                part_tokens.add(match[1].lower())
        attachment_meshes = []
        for row in setup['CompatibleAttachments'].values():
            if not isinstance(row, dict):
                continue
            attach_sid = row['AttachPrototypeSID']
            if not re.search(r'Silen|Laser', attach_sid, re.I):
                continue
            attach = resolve(attachments, attach_sid)
            attachment_meshes.append(asset_path(mesh_by_sid[attach['MeshPrototypeSID']]['MeshPath']))
        preset = {
            'base_weapon': sid, 'label': label, 'enum_id': enum_id,
            'category': category, 'animation': animation.lower(), 'mesh': mesh.lower(),
            'part_tokens': sorted(part_tokens),
            'ammo_types': [row['AmmoType'].split('::')[-1] for row in setup['AmmoTypeProjectiles'].values()],
            'attachments': attachment_meshes, 'general_ref': item['GeneralWeaponSetup'],
            'settings_ref': settings_ref,
            'slot': 'WeaponPistol' if item['ItemSlotType'].endswith('::Pistol') else 'WeaponPrimary',
        }
        for source, fields in ((item, ITEM_FIELDS), (player, PLAYER_FIELDS), (setup, GENERAL_FIELDS)):
            preset.update({target: numeric(source[field]) for target, field in fields.items()})
        preset.update(
            max_ammo=int(setup['MaxAmmo']), caliber=setup['AmmoCaliber'].split('::')[-1],
            fire_modes=[mode.split('::')[-1] for mode in setup['FireTypes'].values()],
            default_fire_mode=setup['DefaultFireType'].split('::')[-1],
            burst_length=max(2, int(setup['FireQueueCount'])),
            recoil_radius=numeric(setup['RecoilParams']['RecoilRadius']),
            recoil_pattern=setup['CameraRecoilPatternPath'], recoil_blend=setup['CameraRecoilPatternBlendCurve'],
            camera_shake=setup['ShootCameraShakePrototypeSID'],
            aim_loop_start=setup['RecoilParams']['CameraAimRecoilPatternLoopStartKeyIndex'],
            hip_loop_start=setup['RecoilParams']['CameraHipRecoilPatternLoopStartKeyIndex'],
            jam_chance_coef=numeric(setup['WeaponJamParams']['[0]']['JamChanceCoef']),
            jam_time=numeric(setup['WeaponJamParams']['[0]']['FullJamTime']),
            dead_ammo_min=int(setup['MinDeadNPCLoadedAmmoCount']),
            dead_ammo_max=int(setup['MaxDeadNPCLoadedAmmoCount']),
            audio=[f'{field} = {setup[field]}' for field in AUDIO_FIELDS if field in setup],
            upgrades=[value for value in setup['UpgradePrototypeSIDs'].values() if value != 'empty'],
        )
        result[key] = preset
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Extracted {len(result)} weapon templates')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
