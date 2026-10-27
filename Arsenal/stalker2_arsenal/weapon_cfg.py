"""Weapon settings and the CFG files STALKER 2 needs for a working weapon mod.

The six files written mirror the structure of a hand-made mod (see Content/GameLite/ModGameData):
ItemPrototypes (weapon, attachments), MeshPrototypes, and the WeaponData general setup, player
settings and player attributes. Everything the add-on already knows (weapon name, mesh names,
bone sockets, mod name, folders) is filled in automatically; the rest comes from the panel.
"""
import json
import os
import re

import bpy

from . import export_animation as animation_export
from . import export_static_mesh as static_mesh
from .weapon_presets import PRESETS

PISTOL = PRESETS['TemplatePistol']
SAFE_ID = re.compile(r'^[A-Za-z0-9_]+$')
GAME_ICONS = '/Game/GameLite/FPS_Game/UIRemaster/UITextures/Inventory/WeaponAndAttachments'
SETUP_TEMPLATES = (
    ('TemplatePistol', 'Pistol', 'Values from the UDP (GunUDP_HG)'),
    ('TemplateSMG', 'SMG', 'Values from the Viper (GunViper_PP)'),
    ('TemplateRifle', 'Rifle', 'Values from the AK-74 (GunAK74_ST)'),
    ('TemplateShotgun', 'Shotgun', 'Values from the M860 (GunM860_SG)'),
    ('TemplateSniper', 'Sniper', 'Values from the Three-Line (GunThreeLine_SP_GS)'),
)
# Settings that follow the template; everything else in PRESETS is written to the files as-is.
PRESET_PROPERTIES = tuple(key for key, value in PISTOL.items()
                          if isinstance(value, (int, float, str)) and key not in (
                              'recoil_pattern', 'recoil_blend', 'camera_shake', 'aim_loop_start',
                              'hip_loop_start'))
CALIBERS = (
    ('A918', '9x18', ''), ('A919', '9x19', ''), ('A045', '.45 ACP', ''), ('A545', '5.45x39', ''),
    ('A556', '5.56x45', ''), ('A762NATO', '7.62x51 NATO', ''), ('A762Sniper', '7.62x54R', ''),
    ('A939', '9x39', ''), ('A012', '12 gauge', ''),
)
MAG_SUFFIX = re.compile(r'(?i)[_\-. ]*(full|empty)[_\-. ]*')
# Game culture code, ELocalizationLanguage member used in the mod text assets, label.
LANGUAGE_TABLE = (
    ('en', 'English', 'English'), ('uk', 'Ukrainian', 'Ukrainian'), ('de', 'German', 'German'),
    ('fr', 'French', 'French'), ('es', 'SpanishEuropean', 'Spanish (Spain)'), ('it', 'Italian', 'Italian'),
    ('pl', 'Polish', 'Polish'), ('cs', 'Czech', 'Czech'), ('tr', 'Turkish', 'Turkish'),
    ('sr', 'Serbian', 'Serbian'), ('pt-BR', 'PortugalBrazilian', 'Portuguese (Brazil)'),
    ('es-419', 'SpanishLatinoAmerican', 'Spanish (Latin America)'), ('ar', 'Arabic', 'Arabic'),
    ('zh-Hans', 'ChineseSimplified', 'Chinese (Simplified)'), ('zh-Hant', 'ChineseTraditional', 'Chinese (Traditional)'),
    ('ja', 'Japanese', 'Japanese'), ('ko', 'Korean', 'Korean'), ('ru', 'Russian', 'Russian'),
)
LANGUAGES = tuple((code, f'{code} - {label}', '') for code, _member, label in LANGUAGE_TABLE)
LANGUAGE_MEMBERS = {code: member for code, member, _label in LANGUAGE_TABLE}


def apply_preset(cfg, template=None):
    """Copy the template weapon's values into the settings."""
    preset = PRESETS[template or cfg.setup_template]
    for key in PRESET_PROPERTIES:
        if key in preset:
            setattr(cfg, key, preset[key])


def _template_changed(self, context):
    apply_preset(self)
    from . import setup_panel
    setup_panel.apply_template_defaults(context.scene, self.setup_template)


def number(value):
    text = f'{value:.6g}'
    return text if any(c in text for c in '.e') else text + '.0'


class Writer:
    def __init__(self):
        self.lines = []
        self.depth = 0

    def line(self, text=''):
        self.lines.append('   ' * self.depth + text if text else '')

    def begin(self, name, ref=''):
        self.line(f'{name} : struct.begin' + (f' {ref}' if ref else ''))
        self.depth += 1

    def end(self):
        self.depth -= 1
        self.line('struct.end')

    def text(self):
        return '\n'.join(self.lines) + '\n'


class ARSENAL_CfgMagazine(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name', default='Default',
                                   description='Used in the IDs: Gun<ID>_Mag<Name>')
    full_object: bpy.props.PointerProperty(name='Full Mesh', type=bpy.types.Object,
                                           description='Mesh object shown while the magazine has rounds',
                                           poll=lambda self, obj: obj.type == 'MESH')
    empty_object: bpy.props.PointerProperty(name='Empty Mesh', type=bpy.types.Object,
                                            description='Mesh object shown when the magazine is empty',
                                            poll=lambda self, obj: obj.type == 'MESH')
    capacity: bpy.props.IntProperty(name='Capacity', default=15, min=1,
                                    description='Rounds this magazine holds (MaxAmmo)')
    preinstalled: bpy.props.BoolProperty(
        name='Preinstalled', default=True,
        description='Comes with the weapon (free, hidden in the inventory). Otherwise it is a '
                    'purchasable extra magazine')
    cost: bpy.props.FloatProperty(name='Cost', description='Price of this extra magazine', default=2500.0, min=0.0)
    weight: bpy.props.FloatProperty(name='Weight', description='Weight of this extra magazine in kg',
                                    default=0.1, min=0.0)
    tactical_reload: bpy.props.FloatProperty(
        name='Tactical Reload Time x', default=1.0, min=0.0,
        description='Multiplier on the reload time when rounds remain in the chamber. Below 1 is faster')
    full_reload: bpy.props.FloatProperty(
        name='Full Reload Time x', default=1.0, min=0.0,
        description='Multiplier on the reload time from an empty weapon. Below 1 is faster')


class ARSENAL_CfgText(bpy.types.PropertyGroup):
    """The weapon's name and description in one language."""
    language: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    description: bpy.props.StringProperty()


def _current_text(cfg, create=False):
    for entry in cfg.texts:
        if entry.language == cfg.text_language:
            return entry
    if create:
        entry = cfg.texts.add()
        entry.language = cfg.text_language
        return entry
    return None


def _get_text_name(self):
    entry = _current_text(self)
    return entry.name if entry else ''


def _set_text_name(self, value):
    _current_text(self, create=True).name = value


def _get_text_description(self):
    entry = _current_text(self)
    return entry.description if entry else ''


def _set_text_description(self, value):
    _current_text(self, create=True).description = value


class ARSENAL_WeaponCfg(bpy.types.PropertyGroup):
    texts: bpy.props.CollectionProperty(type=ARSENAL_CfgText)
    text_language: bpy.props.EnumProperty(
        name='Language', items=LANGUAGES, default='en',
        description='Language the name and description below are typed in. Switch to enter the next one; '
                    'every language is saved in the .blend')
    text_name: bpy.props.StringProperty(
        name='Name', get=_get_text_name, set=_set_text_name,
        description='Weapon name shown in the inventory and trade screens, in the selected language')
    text_description: bpy.props.StringProperty(
        name='Description', get=_get_text_description, set=_set_text_description,
        description='Weapon description shown in the inventory, in the selected language. Type \\n for a line break')
    setup_template: bpy.props.EnumProperty(
        name='Template', items=SETUP_TEMPLATES, default='TemplatePistol', update=_template_changed,
        description='Weapon type. Choosing one fills every value below from a base game weapon: '
                    'UDP (pistol), Viper (SMG), AK74 (rifle), M860 (shotgun), Three-Line (sniper)')
    localization_sid: bpy.props.StringProperty(
        name='Text Key Override',
        description='Advanced. Normally the name and description are stored under the weapon\'s own SID '
                    '(sid_items_<SID>_name). Set this to make the game read that key instead (LocalizationSID), '
                    'for example to share the text of another weapon. Empty: the weapon\'s own SID')
    cost: bpy.props.FloatProperty(name='Cost', description='Base price in the trade screens',
                                  default=PISTOL['cost'], min=0.0)
    weight: bpy.props.FloatProperty(name='Weight', description="Weight in kg. Adds to the player's carried load",
                                    default=PISTOL['weight'], min=0.0)
    durability: bpy.props.FloatProperty(name='Durability', description='Starting condition. The weapon loses Durability Loss / Shot of this with every trigger pull', default=PISTOL['durability'], min=0.0)
    durability_per_shot: bpy.props.FloatProperty(name='Durability Loss / Shot', description='Condition lost with every trigger pull. Snipers lose it much faster (UDP 3.3, Viper 0.69, Gauss 12.5)',
                                                 default=PISTOL['durability_per_shot'], min=0.0)

    base_damage: bpy.props.FloatProperty(name='Damage', description='Raw health damage per projectile. Shotguns are high (140-160) because a shot is several pellets', default=PISTOL['base_damage'], min=0.0)
    armor_damage: bpy.props.FloatProperty(name='Armor Damage', description="Damage dealt to the target's armor durability. Most base game weapons leave this at 0", default=PISTOL['armor_damage'], min=0.0)
    armor_piercing: bpy.props.FloatProperty(name='Armor Piercing', description='How well the bullet bypasses armor. Pistols are 1.0, armor-piercing weapons are 3.0 or more', default=PISTOL['armor_piercing'], min=0.0)
    cover_piercing: bpy.props.FloatProperty(name='Cover Piercing', description='Like Armor Piercing, but for shooting through objects such as wood or thin metal', default=PISTOL['cover_piercing'], min=0.0)
    base_bleeding: bpy.props.FloatProperty(name='Bleeding', description='Intensity of the bleeding effect applied to the target', default=PISTOL['base_bleeding'], min=0.0)
    bleeding_chance: bpy.props.FloatProperty(name='Bleeding Chance %', description='Percentage chance that a hit causes bleeding', default=PISTOL['bleeding_chance'],
                                             min=0.0, max=100.0)
    effective_distance: bpy.props.FloatProperty(name='Effective Distance', description='Range where the weapon performs as intended. Written to both the min and max values, because keeping them equal avoids buggy recoil. Pistols are about 1000, snipers 5000+', default=PISTOL['effective_distance'],
                                                min=0.0)
    drop_off_distance: bpy.props.FloatProperty(name='Damage Drop-off Distance', description='Distance at which projectiles start losing damage',
                                               default=PISTOL['drop_off_distance'], min=0.0)
    min_distance_modifier: bpy.props.FloatProperty(name='Min Damage at Range', description='Damage floor at long range, as a fraction of Damage. 0.2 means never less than 20%',
                                                   default=PISTOL['min_distance_modifier'], min=0.0, max=1.0)
    projectile_drop_length: bpy.props.FloatProperty(name='Bullet Drop-off Length', description='Distance over which damage fades from full to the minimum (DistanceDropOffLength)',
                                                    default=PISTOL['projectile_drop_length'], min=0.0)
    fire_loudness: bpy.props.FloatProperty(name='Fire Loudness', description='How loud a shot is to AI detection. Suppressed weapons are about 0.1, shotguns 0.8', default=PISTOL['fire_loudness'], min=0.0)
    base_comfort: bpy.props.FloatProperty(name='Comfort', description='How much noise the player makes while moving with this weapon, used by AI detection. Pistols 0.25, rifles 0.55', default=PISTOL['base_comfort'], min=0.0)
    ui_accuracy: bpy.props.FloatProperty(name='Accuracy', description='Fills the Accuracy bar in the inventory and trade screens (0-1). Display only', default=PISTOL['ui_accuracy'], min=0.0, max=1.0)
    ui_rate_of_fire: bpy.props.FloatProperty(name='Rate of Fire', description='Fills the Rate of Fire bar in the inventory and trade screens (0-1). Display only', default=PISTOL['ui_rate_of_fire'],
                                             min=0.0, max=1.0)
    ui_handling: bpy.props.FloatProperty(name='Handling', description='Fills the Handling (ergonomics) bar in the inventory and trade screens (0-1). Display only', default=PISTOL['ui_handling'], min=0.0, max=1.0)
    ui_damage: bpy.props.FloatProperty(name='Damage', description='Fills the Damage bar in the inventory and trade screens (0-1). Display only', default=PISTOL['ui_damage'], min=0.0, max=1.0)
    ui_range: bpy.props.FloatProperty(name='Range', description='Fills the Range bar in the inventory and trade screens (0-1). Display only', default=PISTOL['ui_range'], min=0.0, max=1.0)

    max_ammo: bpy.props.IntProperty(name='Max Ammo', description="Rounds the weapon holds. Each magazine's own Capacity is set in the magazine list", default=PISTOL['max_ammo'], min=1)
    caliber: bpy.props.EnumProperty(name='Caliber', description='Ammo type the weapon accepts. Also selects the projectile used for every ammo type', items=CALIBERS, default=PISTOL['caliber'])
    fire_interval: bpy.props.FloatProperty(name='Fire Interval', default=PISTOL['fire_interval'], min=0.01,
                                           description='Seconds between shots')
    recoil_radius: bpy.props.FloatProperty(name='Recoil Radius', description='Size of the recoil kick. Larger means more camera movement while firing', default=PISTOL['recoil_radius'], min=0.0)
    dispersion_radius: bpy.props.FloatProperty(name='Dispersion Radius', description='Bullet spread (accuracy). Lower is better: Gauss is 83, UDP 152, sawed-off Obrez 758', default=PISTOL['dispersion_radius'],
                                               min=0.0)
    aiming_time: bpy.props.FloatProperty(name='Aiming Time', description='Seconds to raise the sights when aiming down them', default=PISTOL['aiming_time'], min=0.0)
    offset_aiming_time: bpy.props.FloatProperty(name='Offset Aiming Time', description='Seconds to switch to the offset (secondary) sight', default=PISTOL['offset_aiming_time'],
                                                min=0.0)
    lean_aiming_time: bpy.props.FloatProperty(name='Lean Aiming Time', description='Seconds to aim while leaning', default=PISTOL['lean_aiming_time'],
                                              min=0.0)
    lean_restore_time: bpy.props.FloatProperty(name='Lean Restore Time', description='Seconds to return to the normal aim after leaning', default=PISTOL['lean_restore_time'],
                                               min=0.0)
    max_jam_chance: bpy.props.FloatProperty(name='Max Jam Chance', description='Highest chance of a jam, as a percentage, reached as the weapon wears out', default=PISTOL['max_jam_chance'], min=0.0)
    jam_chance_coef: bpy.props.FloatProperty(name='Jam Chance Coefficient', description='Multiplier on how fast the jam chance grows', default=PISTOL['jam_chance_coef'],
                                             min=0.0)
    jam_time: bpy.props.FloatProperty(name='Jam Clear Time', description='Seconds the jam-clearing animation takes', default=PISTOL['jam_time'], min=0.0)
    dead_ammo_min: bpy.props.IntProperty(name='Min Ammo on NPC Corpses', description="Fewest rounds a looted NPC corpse's copy of this weapon holds", default=PISTOL['dead_ammo_min'], min=0)
    dead_ammo_max: bpy.props.IntProperty(name='Max Ammo on NPC Corpses', description="Most rounds a looted NPC corpse's copy of this weapon holds", default=PISTOL['dead_ammo_max'], min=0)

    magazines: bpy.props.CollectionProperty(type=ARSENAL_CfgMagazine)
    active_magazine: bpy.props.IntProperty()
    allow_silencer: bpy.props.BoolProperty(name='Allow Silencer', description="Adds the silencer slot (uses the game's EN_Silen_2 silencer)", default=False)
    allow_laser: bpy.props.BoolProperty(name='Allow Laser', description="Adds the laser sight slot (uses the game's EN_Laser_1 laser)", default=False)
    keep_upgrades: bpy.props.BoolProperty(
        name='Use Base Weapon Upgrade Tree', default=True,
        description='List the upgrades of the template weapon on this weapon (otherwise it has none)')


def mod_name(export):
    """The mod folder name: the first part of the Mod Content Path (ModGameData/<Mod> repeats the mod's name)."""
    parts = [part for part in export.unreal_mount.strip().split('/') if part]
    if not parts:
        raise RuntimeError('Set the Mod Name (for example MonkeyMod) in the Export panel.')
    return parts[0]


def base_weapon(cfg):
    """The base game weapon the chosen template stands for (e.g. GunUDP_HG)."""
    return PRESETS[cfg.setup_template]['base_weapon']


def weapon_names(scene, export, cfg):
    weapon_id = animation_export.weapon_name(scene)
    if not weapon_id:
        raise RuntimeError("Enter the weapon's English Name first.")
    base = base_weapon(cfg)
    suffix = base.rsplit('_', 1)[1] if '_' in base else 'HG'
    return weapon_id, f'Gun{weapon_id}_{suffix}'


ACCESSORY_WORDS = re.compile(r'(?i)silen|suppress|laser|scope|muzzle|sight|grip|rail|flash|brake|holo|colim|goloscope')
MAG_QUALIFIER = re.compile(r'(?i)(increased|big|twin|extended|drum|large|long)mag|mag_?(increased|extended|drum)')
MAG_QUALIFIER_NAMES = {'increased': 'Increased', 'big': 'Increased', 'extended': 'Extended', 'large': 'Increased',
                       'long': 'Increased', 'twin': 'Twin', 'drum': 'Drum'}


def detect_magazines(others):
    """Group the extra weapon meshes by name (magazine_full + magazine_empty) into magazine entries.

    Meshes with "mag" in the name are magazines; if none has, every mesh that is not obviously a
    silencer, laser, scope or similar accessory is taken."""
    candidates = [(obj, bones) for obj, bones in others if 'mag' in obj.name.casefold()
                  and not ACCESSORY_WORDS.search(obj.name)]
    if not candidates:
        candidates = [(obj, bones) for obj, bones in others if not ACCESSORY_WORDS.search(obj.name)]
    groups = {}
    for obj, _bones in candidates:
        match = MAG_SUFFIX.search(obj.name)
        key = MAG_SUFFIX.sub('', obj.name) if match else obj.name
        kind = match.group(1).lower() if match else 'full'
        groups.setdefault(key, {})[kind] = obj
    result = []
    ordered = sorted(groups.items(), key=lambda item: (bool(MAG_QUALIFIER.search(item[0])), item[0]))
    used = set()
    for index, (key, kinds) in enumerate(ordered):
        full = kinds.get('full') or kinds.get('empty')
        empty = kinds.get('empty') or full
        qualifier = MAG_QUALIFIER.search(key)
        if index == 0 and not qualifier:
            name = 'Default'
        elif qualifier:
            word = qualifier.group(1).lower()
            name = MAG_QUALIFIER_NAMES.get(word, word.title())
        else:
            name = re.sub(r'[^A-Za-z0-9]', '', key.title()) or f'Extra{index}'
        while name in used:
            name += 'X'
        used.add(name)
        result.append({'name': name, 'full': full, 'empty': empty, 'preinstalled': index == 0})
    return result


def collect_magazines(cfg, others):
    if not cfg.magazines:
        return [dict(entry, capacity=cfg.max_ammo, cost=2500.0, weight=0.1,
                     tactical=1.0, full_reload=1.0) for entry in detect_magazines(others)]
    result = []
    for entry in cfg.magazines:
        if not SAFE_ID.match(entry.name):
            raise RuntimeError(f'Magazine name "{entry.name}" may only contain letters, digits and underscores.')
        if not entry.full_object or not entry.empty_object:
            raise RuntimeError(f'Magazine "{entry.name}" needs both a full and an empty mesh object.')
        result.append({
            'name': entry.name, 'full': entry.full_object, 'empty': entry.empty_object,
            'preinstalled': entry.preinstalled, 'capacity': entry.capacity, 'cost': entry.cost,
            'weight': entry.weight, 'tactical': entry.tactical_reload, 'full_reload': entry.full_reload})
    return result


def build_context(context):
    """Gather everything the generators need from the scene and the export settings."""
    export = context.scene.arsenal_export
    cfg = context.scene.arsenal_cfg
    rig, _backup, bone_joints, _plan = animation_export._build_static_plan(context)
    main, main_bones, others = static_mesh.classify_meshes(rig, context.scene, bone_joints)
    if main is None:
        raise RuntimeError('No weapon mesh is weighted to the mapped weapon bones.')
    output_root = bpy.path.abspath(export.output_folder).strip()
    mesh_name = static_mesh.weapon_mesh_name(main, context.scene)
    category = static_mesh.validate_names(mesh_name, export.static_category.strip()).replace(os.sep, '/')
    weapon_id, sid = weapon_names(context.scene, export, cfg)
    mod_name(export)
    mount = animation_export.mod_mount(export)
    mesh_folder = f'{mount}/_Stalker_2/weapons/{category}/p_{mesh_name}'

    def mesh_path(folder, stem):
        return f"StaticMesh'{folder}/{stem}.{stem}'"

    parts = []
    for bone in sorted(main_bones, key=lambda name: (bone_joints[name] != 'jnt_offset', bone_joints[name])):
        joint = bone_joints[bone]
        stem = static_mesh.static_mesh_stem(mesh_name, joint)
        parts.append((mesh_path(f'{mesh_folder}/AnimMesh', stem), joint))

    magazines = collect_magazines(cfg, others)
    template = static_mesh.template_token(context.scene)
    for magazine in magazines:
        for key in ('full', 'empty'):
            obj = magazine[key]
            stem = static_mesh.attachment_stem(mesh_name, obj.name, template)
            magazine[key + '_path'] = mesh_path(f'{mesh_folder}/AnimMesh', stem)
        bones = static_mesh.weighted_bones(magazine['full'], bone_joints)
        magazine['socket'] = bone_joints[max(bones, key=bones.get)] if bones else 'jnt_magazine'

    animation_dir = animation_folder(context.scene, export, output_root, mount)
    anim_name = animation_export.weapon_name(context.scene)
    # The weapon class folder ("pt", "ar", ...) is the parent of the weapon's own animation folder.
    weapon_class = animation_dir.rstrip('/').split('/')[-2]
    skeletal_mesh = (f"SkeletalMesh'{mount}/_STALKER2/SkeletalMeshes/weapons/{weapon_class}/{anim_name}/"
                     f"SK_{anim_name}.SK_{anim_name}'")
    return {
        'skeletal_mesh': skeletal_mesh,
        'export': export, 'cfg': cfg, 'mod': mod_name(export), 'mount': mount, 'output_root': output_root,
        'weapon_id': weapon_id, 'sid': sid, 'player_sid': f'{sid}_Player', 'mesh_name': mesh_name,
        'mesh_folder': mesh_folder, 'world_mesh': mesh_path(mesh_folder, f'SM_{mesh_name}'),
        'parts': parts, 'magazines': magazines, 'animation_dir': animation_dir,
        'anim_name': animation_export.weapon_name(context.scene), 'template': template,
    }


def animation_folder(scene, export, output_root, mount):
    """Unreal folder holding the new weapon's animations (where its AnimBP is expected)."""
    from . import export_unreal
    name = animation_export.weapon_name(scene)
    files = export_unreal.find_animation_files(output_root, name)['weapon']
    if files:
        parts = os.path.dirname(files[0]).replace(os.sep, '/').split('/')
        # The AnimBP sits in the weapon's own folder, not in subfolders (AnimSequences/fp/...) holding the sequences.
        lowered = [part.casefold() for part in parts]
        if name.casefold() in lowered:
            parts = parts[:lowered.index(name.casefold()) + 1]
        return f'{mount}/{"/".join(parts)}'
    return f'{mount}/_STALKER2/Animations/Weapons/pt/{name}'


def weapon_prototypes(info):
    cfg = info['cfg']
    writer = Writer()
    writer.begin(info['sid'], f'{{refurl=@BaseGame/ItemPrototypes/WeaponPrototypes.cfg;refkey={base_weapon(cfg)}}}')
    writer.line('//Base info')
    writer.line(f'SID = {info["sid"]}')
    if cfg.localization_sid.strip():
        writer.line(f'LocalizationSID = {cfg.localization_sid.strip()}')
    # Without this the weapon inherits the template's skeletal mesh and the mod's own SK_ asset is never used.
    writer.line(f'MeshPrototypeSID = Gun{info["weapon_id"]}_Skeletal')
    writer.line(f'MeshInWorldPrototypeSID = Gun{info["weapon_id"]}_StaticMesh')
    writer.line()
    writer.line('//Base stats')
    writer.line(f'Cost = {number(cfg.cost)}')
    writer.line(f'Weight = {number(cfg.weight)}')
    writer.line(f'BaseDurability = {number(cfg.durability)}')
    writer.line(f'GeneralWeaponSetup = {info["sid"]}')
    writer.line(f'PlayerWeaponAttributes = {info["player_sid"]}')
    writer.end()
    return writer.text()


def attach_prototypes(info):
    writer = Writer()
    for magazine in info['magazines']:
        mag_sid = f'Gun{info["weapon_id"]}_Mag{magazine["name"]}'
        template = 'MagTemplate' if magazine['preinstalled'] else 'BigMagTemplate'
        writer.begin(mag_sid, f'{{refurl=@BaseGame/ItemPrototypes/AttachPrototypes.cfg;refkey={template}}}')
        writer.line(f'SID = {mag_sid}')
        writer.line(f'MeshPrototypeSID = {mag_sid}Full')
        writer.line(f'Cost = {number(0 if magazine["preinstalled"] else magazine["cost"])}')
        writer.line(f'Weight = {number(0 if magazine["preinstalled"] else magazine["weight"])}')
        writer.begin('Magazine')
        writer.line('PhysicsInteractionPrototypeSID = Magazine_Metal_Small')
        writer.line(f'MaxAmmo = {magazine["capacity"]}')
        writer.begin('MeshArray')
        for index, kind in enumerate(('Full', 'Empty')):
            writer.begin(f'[{index}]')
            writer.line(f'MeshPrototypeSID = {mag_sid}{kind}')
            writer.line(f'MagazineMeshType = EMagazineMeshType::{kind}')
            writer.end()
        writer.end()
        writer.line('IsTwinMagazine = false')
        writer.line('BindBulletsToAttach = false')
        writer.line('HasMultipleMeshes = true')
        writer.end()
        if not magazine['preinstalled']:
            writer.begin('FittingWeaponsSIDs')
            writer.line(f'[0] = {info["sid"]}')
            writer.end()
        writer.end()
        writer.line()
    return writer.text()


def mesh_prototypes(info):
    writer = Writer()

    def entry(sid, path):
        writer.begin(sid, '{refurl=@BaseGame/MeshPrototypes.cfg;refkey=[0]}')
        writer.line(f'SID = {sid}')
        writer.line(f'MeshPath = {path}')
        writer.end()

    for magazine in info['magazines']:
        mag_sid = f'Gun{info["weapon_id"]}_Mag{magazine["name"]}'
        entry(f'{mag_sid}Empty', magazine['empty_path'])
        entry(f'{mag_sid}Full', magazine['full_path'])
    entry(f'Gun{info["weapon_id"]}_StaticMesh', info['world_mesh'])
    skeletal = f'Gun{info["weapon_id"]}_Skeletal'
    writer.begin(skeletal, '{refurl=@BaseGame/MeshPrototypes.cfg;refkey=[0]}')
    writer.line(f'SID = {skeletal}')
    writer.line(f'MeshPath = {info["skeletal_mesh"]}')
    writer.line('MeshType = EMeshSubType::Skeletal')
    writer.end()
    return writer.text()


def player_settings(info):
    cfg = info['cfg']
    writer = Writer()
    writer.begin(info['player_sid'],
                 f'{{refurl=@BaseGame/WeaponData/CharacterWeaponSettingsPrototypes.cfg;refkey={cfg.setup_template}}}')
    writer.line('//Base info')
    writer.line(f'SID = {info["player_sid"]}')
    writer.line('//Durability')
    writer.line(f'DurabilityDamagePerShot = {number(cfg.durability_per_shot)}')
    writer.line('//Damage')
    writer.line(f'ArmorDamage = {number(cfg.armor_damage)}')
    writer.line(f'ArmorPiercing = {number(cfg.armor_piercing)}')
    writer.line(f'CoverPiercing = {number(cfg.cover_piercing)}')
    writer.line(f'BaseDamage = {number(cfg.base_damage)}')
    writer.line(f'BaseBleeding = {number(cfg.base_bleeding)}')
    writer.line(f'ChanceBleedingPerShot = {cfg.bleeding_chance:g}%')
    writer.line('//Effective Distance')
    writer.line(f'EffectiveFireDistanceMin = {number(cfg.effective_distance)}')
    writer.line(f'EffectiveFireDistanceMax = {number(cfg.effective_distance)}')
    writer.line(f'FireDistanceDropOff = {number(cfg.drop_off_distance)}')
    writer.line(f'MinBulletDistanceDamageModifier = {number(cfg.min_distance_modifier)}')
    writer.line('//Shooting')
    writer.line(f'DispersionRadius = {number(cfg.dispersion_radius)}')
    writer.line('//NPC Hearing')
    writer.line(f'BaseComfort = {number(cfg.base_comfort)}')
    writer.line(f'FireLoudness = {number(cfg.fire_loudness)}')
    writer.line('//UI')
    writer.line(f'AccuracyUI = {number(cfg.ui_accuracy)}')
    writer.line(f'RateOfFireUI = {number(cfg.ui_rate_of_fire)}')
    writer.line(f'HandlingUI = {number(cfg.ui_handling)}')
    writer.line(f'DamageUI = {number(cfg.ui_damage)}')
    writer.line(f'RangeUI = {number(cfg.ui_range)}')
    writer.line('//Projectile settings')
    writer.line(f'DistanceDropOffLength = {number(cfg.projectile_drop_length)}')
    writer.end()
    return writer.text()


def player_attributes(info):
    writer = Writer()
    writer.begin(info['player_sid'],
                 '{refurl=@BaseGame/WeaponData/WeaponAttributesPrototypes/PlayerWeaponAttributesPrototypes.cfg;'
                 f'refkey={base_weapon(info["cfg"])}_Player}}')
    writer.line('//Base info')
    writer.line(f'SID = {info["player_sid"]}')
    writer.line(f'DefaultWeaponSettingsSID = {info["player_sid"]}')
    writer.line('//AnimBP')
    anim = info['anim_name']
    writer.line(f"AnimBlueprint = AnimBlueprint'{info['animation_dir']}/AnimBP_{anim}_fp.AnimBP_{anim}_fp'")
    writer.end()
    return writer.text()


def general_setup(info):
    cfg = info['cfg']
    preset = PRESETS[cfg.setup_template]
    projectile = 'P' + cfg.caliber[1:]
    writer = Writer()
    writer.begin(info['sid'], f'{{refurl=@BaseGame/WeaponData/WeaponGeneralSetupPrototypes.cfg;refkey={cfg.setup_template}}}')
    writer.line('//Base info')
    writer.line(f'SID = {info["sid"]}')
    writer.line()
    writer.line('//Ammo')
    writer.line(f'MaxAmmo = {cfg.max_ammo}')
    writer.line(f'AmmoCaliber = EAmmoCaliber::{cfg.caliber}')
    writer.begin('AmmoTypeProjectiles')
    for index, ammo_type in enumerate(('Default', 'ArmorPiercing', 'Expanding')):
        writer.begin(f'[{index}]')
        writer.line(f'AmmoType = EAmmoType::{ammo_type}')
        writer.line(f'ProjectilePrototypeSID = {projectile}')
        writer.end()
    writer.end()
    writer.line()
    writer.line('//Aiming')
    writer.line(f'AimingTime = {number(cfg.aiming_time)}')
    writer.line(f'OffsetAimingTime = {number(cfg.offset_aiming_time)}')
    writer.line(f'LeanAimingTime = {number(cfg.lean_aiming_time)}')
    writer.line(f'LeanAimingRestoreTime = {number(cfg.lean_restore_time)}')
    writer.line()
    writer.line('//Shooting')
    writer.line(f'FireInterval = {number(cfg.fire_interval)}')
    writer.line(f'RecoilInterval = {number(cfg.fire_interval)}')
    writer.line(f'CameraRecoilPatternPath = {preset["recoil_pattern"]}')
    writer.line(f'CameraRecoilPatternBlendCurve = {preset["recoil_blend"]}')
    writer.begin('RecoilParams')
    writer.line(f'RecoilRadius = {number(cfg.recoil_radius)}')
    writer.line(f'CameraAimRecoilPatternLoopStartKeyIndex = {preset["aim_loop_start"]}')
    writer.line(f'CameraHipRecoilPatternLoopStartKeyIndex = {preset["hip_loop_start"]}')
    writer.begin('ShootingStateParams')
    writer.begin('RadiusNormalizationModifiers')
    writer.line('RadiusNormalizationDelay = 0.0')
    writer.line('RadiusNormalizationInterval = 0.06')
    writer.end()
    writer.end()
    writer.end()
    writer.begin('DispersionParams')
    writer.line(f'FirstShotDispersionRadius = {number(cfg.dispersion_radius)}')
    writer.begin('ShootingStateParams')
    writer.begin('RadiusExtensionModifiers')
    writer.line('PerIterationRadiusExtensionModifier = 0.25')
    writer.line('MaxRadiusExtensionModifier = 0.0')
    writer.line('RadiusExtensionBulletCount = 1')
    writer.end()
    writer.end()
    writer.end()
    writer.line(f'ShootCameraShakePrototypeSID = {preset["camera_shake"]}')
    writer.line('//Jam')
    writer.line(f'MaxJamChance = {number(cfg.max_jam_chance)}')
    writer.begin('WeaponJamParams')
    for index in range(3):
        writer.begin(f'[{index}]')
        writer.line(f'JamChanceCoef = {number(cfg.jam_chance_coef)}')
        writer.line(f'FullJamTime = {number(cfg.jam_time)}')
        writer.end()
    writer.end()

    magazines = info['magazines']
    if magazines:
        writer.line('//Reload')
        writer.begin('WeaponReloadTimePerAttachment')
        for index, magazine in enumerate(magazines):
            writer.begin(f'[{index}]')
            writer.line(f'AttachPrototypeSID = Gun{info["weapon_id"]}_Mag{magazine["name"]}')
            writer.line(f'TacticalReloadTimeMultiplier = {number(magazine["tactical"])}')
            writer.line(f'FullReloadTimeMultiplier = {number(magazine["full_reload"])}')
            if index == 0:
                writer.line('UnloadTime = 0.0')
            writer.end()
        writer.end()
    writer.line('//DeadBody Ammo MaxCount')
    writer.line(f'MinDeadNPCLoadedAmmoCount = {cfg.dead_ammo_min}')
    writer.line(f'MaxDeadNPCLoadedAmmoCount = {max(cfg.dead_ammo_min, cfg.dead_ammo_max)}')
    writer.line()
    writer.line('//Static data')
    writer.begin('WeaponStaticMeshParts')
    for index, (path, socket) in enumerate(info['parts']):
        writer.begin(f'[{index}]')
        writer.line(f'MeshPath = {path}')
        writer.line(f'SocketName = {socket}')
        writer.end()
    writer.end()
    writer.line()

    writer.line('//Attachments')
    writer.begin('CompatibleAttachments', '{bskipref}')
    index = 0
    if cfg.allow_silencer:
        writer.begin(f'[{index}]')
        writer.line('AttachPrototypeSID = EN_Silen_2')
        writer.line('Muzzle = SilencerMuzzle')
        writer.line('Socket = SilencerMuzzleSocket')
        writer.line('MeshPrototypeSID = EN_Silen_5')
        writer.line('IconPosX = 205')
        writer.line('IconPosY = 9')
        writer.line(f"WeaponSpecificIcon = Texture2D'{GAME_ICONS}/Integral/T_inv_w_integral_en_silen_5."
                    "T_inv_w_integral_en_silen_5'")
        writer.end()
        index += 1
    laser_upgrades = [name for name in preset['upgrades'] if 'Laser' in name]
    if cfg.allow_laser:
        writer.begin(f'[{index}]')
        writer.line('AttachPrototypeSID = EN_Laser_1')
        writer.line(f"WeaponSpecificIcon = Texture2D'{GAME_ICONS}/UDP/T_inv_w_udp_en_laser_1.T_inv_w_udp_en_laser_1'")
        writer.line('Socket = LaserSocket')
        if laser_upgrades and cfg.keep_upgrades:
            writer.begin('RequiredUpgradeIDs')
            writer.line(f'[0] = {laser_upgrades[0]}')
            writer.end()
        writer.line('IconPosX = 150')
        writer.line('IconPosY = 30')
        writer.end()
        index += 1
    for magazine in magazines:
        icon = 'magdefault' if magazine['preinstalled'] else 'magincreased'
        writer.begin(f'[{index}]')
        writer.line(f'AttachPrototypeSID = Gun{info["weapon_id"]}_Mag{magazine["name"]}')
        writer.line(f'Socket = {magazine["socket"]}')
        writer.line('IconPosX = 0')
        writer.line('IconPosY = 0')
        writer.line(f"WeaponSpecificIcon = Texture2D'{GAME_ICONS}/Integral/T_inv_w_integral_{icon}."
                    f"T_inv_w_integral_{icon}'")
        writer.end()
        index += 1
    writer.end()
    preinstalled = [m for m in magazines if m['preinstalled']]
    if preinstalled:
        writer.begin('PreinstalledAttachmentsItemPrototypeSIDs', '{bskipref}')
        for index, magazine in enumerate(preinstalled):
            writer.begin(f'[{index}]')
            writer.line(f'AttachSID = Gun{info["weapon_id"]}_Mag{magazine["name"]}')
            writer.line('bHiddenInInventory = true')
            writer.end()
        writer.end()
    writer.line('//Upgrades')
    writer.begin('UpgradePrototypeSIDs', '{bskipref}')
    if cfg.keep_upgrades:
        for index, upgrade in enumerate(preset['upgrades']):
            writer.line(f'[{index}] = {upgrade}')
    writer.end()
    writer.line('//WWise Events and parameters')
    for text in preset['audio']:
        writer.line(text)
    writer.line('//Visual sockets')
    socket = magazines[0]['socket'] if magazines else 'jnt_magazine'
    writer.line(f'DefaultEjectMagazineSocketName = {socket}')
    writer.line(f'DefaultInsertMagazineSocketName = {socket}')
    writer.end()
    return writer.text()


def text_key(info):
    """SID stem the game reads the name and description from."""
    return info['cfg'].localization_sid.strip() or info['sid']


def localization_entries(info):
    """Name and description entries in the mod text asset's {SID, LanguagesToLocalizedStrings} shape."""
    cfg = info['cfg']
    names, descriptions = {}, {}
    for entry in cfg.texts:
        member = LANGUAGE_MEMBERS.get(entry.language)
        if member is None:
            continue
        key = f'ELocalizationLanguage::{member}'
        if entry.name.strip():
            names[key] = entry.name.replace('\\n', '\n')
        if entry.description.strip():
            descriptions[key] = entry.description.replace('\\n', '\n')
    entries = []
    for suffix, texts in (('name', names), ('description', descriptions)):
        if texts:
            entries.append({'SID': f'sid_items_{text_key(info)}_{suffix}', 'LanguagesToLocalizedStrings': texts})
    return entries


def localization_json(info):
    entries = localization_entries(info)
    return json.dumps(entries, ensure_ascii=False, indent=2) + '\n' if entries else None


def cfg_files(info):
    """Return {path relative to the output folder: file text}."""
    name = info['weapon_id']
    base = os.path.join('GameLite', 'ModGameData', info['mod'])
    files = {
        os.path.join(base, 'ItemPrototypes', f'{name}WeaponPrototypes.cfg'): weapon_prototypes(info),
        os.path.join(base, 'ItemPrototypes', f'{name}AttachPrototypes.cfg'): attach_prototypes(info),
        os.path.join(base, 'MeshPrototypes', f'{name}MeshPrototypes.cfg'): mesh_prototypes(info),
        os.path.join(base, 'WeaponData', 'CharacterWeaponSettingsPrototypes', 'PlayerWeaponSettingsPrototypes',
                     f'{name}PlayerWeaponSettingsPrototypes.cfg'): player_settings(info),
        os.path.join(base, 'WeaponData', 'WeaponAttributesPrototypes', 'PlayerWeaponAttributesPrototypes',
                     f'{name}PlayerWeaponAttributesPrototypes.cfg'): player_attributes(info),
        os.path.join(base, 'WeaponData', 'WeaponGeneralSetupPrototypes',
                     f'{name}WeaponGeneralSetupPrototypes.cfg'): general_setup(info),
    }
    localization = localization_json(info)
    if localization:
        files[os.path.join('Localization', f'{info["mod"]}-{name}-localization.json')] = localization
    return files


def write_cfg_files(context):
    info = build_context(context)
    if not info['output_root']:
        raise RuntimeError('Choose an output folder.')
    written = []
    for relative, text in cfg_files(info).items():
        path = os.path.join(info['output_root'], relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
        written.append(path)
    return written, info


def export_cfg_files(operator, context):
    """Write the CFG files and the localisation JSON, reporting problems on the operator."""
    written, info = write_cfg_files(context)
    if not info['magazines']:
        operator.report({'WARNING'}, 'No separate magazine meshes found; magazine entries were skipped.')
    if not localization_entries(info):
        operator.report({'WARNING'}, 'No weapon name entered; the game will show the raw SID.')
    elif not any(entry.language == 'en' and entry.name.strip() for entry in info['cfg'].texts):
        operator.report({'WARNING'}, 'No English name entered; other languages fall back to English.')
    return written, info

class ARSENAL_OT_CfgApplyTemplate(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_apply_template'
    bl_label = 'Reset Stats to Template'
    bl_description = 'Overwrite all weapon stats with the values of the chosen template weapon'

    def execute(self, context):
        apply_preset(context.scene.arsenal_cfg)
        return {'FINISHED'}


class ARSENAL_OT_CfgMagazineAdd(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_magazine_add'
    bl_label = 'Add Magazine'

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        entry = cfg.magazines.add()
        entry.preinstalled = len(cfg.magazines) == 1
        entry.name = 'Default' if entry.preinstalled else f'Extra{len(cfg.magazines)}'
        cfg.active_magazine = len(cfg.magazines) - 1
        return {'FINISHED'}


class ARSENAL_OT_CfgMagazineRemove(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_magazine_remove'
    bl_label = 'Remove Magazine'

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        if 0 <= cfg.active_magazine < len(cfg.magazines):
            cfg.magazines.remove(cfg.active_magazine)
            cfg.active_magazine = max(0, cfg.active_magazine - 1)
        return {'FINISHED'}


def fill_magazine_list(cfg, others):
    """Replace the magazine list with the magazines found among the extra meshes; returns how many."""
    cfg.magazines.clear()
    for found in detect_magazines(others):
        entry = cfg.magazines.add()
        entry.name = found['name']
        entry.full_object = found['full']
        entry.empty_object = found['empty']
        entry.preinstalled = found['preinstalled']
        entry.capacity = cfg.max_ammo
    cfg.active_magazine = 0
    return len(cfg.magazines)


class ARSENAL_OT_CfgMagazineDetect(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_magazine_detect'
    bl_label = 'Detect Magazines'
    bl_description = ('Fill the list from the separate weapon meshes (for example magazine_full and '
                      'magazine_empty become one magazine)')

    def execute(self, context):
        try:
            rig, _backup, bone_joints, _plan = animation_export._build_static_plan(context)
            _main, _bones, others = static_mesh.classify_meshes(rig, context.scene, bone_joints)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        count = fill_magazine_list(context.scene.arsenal_cfg, others)
        self.report({'INFO'}, f'Found {count} magazine(s).')
        return {'FINISHED'}


class ARSENAL_UL_CfgMagazines(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon='MESH_CYLINDER')
        if item.preinstalled:
            layout.label(text='Preinstalled')


class ARSENAL_PT_CustomWeaponPanel(bpy.types.Panel):
    bl_label = '4. Create Your Custom Weapon'
    bl_idname = 'ARSENAL_PT_CustomWeaponPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 4

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text='Now add or edit your weapon,')
        col.label(text='and make your animation changes.')
        col.separator()
        col.label(text='Then set up its game stats below.')
        col.label(text='Export All writes the CFG files too.')


class _CfgSubPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_parent_id = 'ARSENAL_PT_CustomWeaponPanel'
    bl_options = {'DEFAULT_CLOSED'}

    def props(self, context, names):
        cfg = context.scene.arsenal_cfg
        col = self.layout.column(align=True)
        for name in names:
            col.prop(cfg, name)


class ARSENAL_OT_CfgClearText(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_clear_text'
    bl_label = 'Clear Language'
    bl_description = 'Remove the name and description entered for the selected language'

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        for index, entry in enumerate(cfg.texts):
            if entry.language == cfg.text_language:
                cfg.texts.remove(index)
                break
        return {'FINISHED'}


class ARSENAL_PT_CfgText(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Name & Description'
    bl_options = set()
    bl_order = 1

    def draw(self, context):
        cfg = context.scene.arsenal_cfg
        layout = self.layout
        row = layout.row(align=True)
        row.prop(cfg, 'text_language', text='')
        row.operator('object.arsenal_cfg_clear_text', text='', icon='X')
        col = layout.column(align=True)
        col.prop(cfg, 'text_name')
        col.prop(cfg, 'text_description')
        done = [entry.language for entry in cfg.texts if entry.name.strip() or entry.description.strip()]
        if done:
            layout.label(text='Entered: ' + ', '.join(code for code, _label, _desc in LANGUAGES if code in done))
        else:
            layout.label(text='Pick a language, then type a name and description.')
        if 'en' not in done:
            layout.label(text='Other languages fall back to English if no text is provided.', icon='INFO')
        layout.prop(cfg, 'localization_sid')


class ARSENAL_PT_CfgIdentity(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Weapon'

    def draw(self, context):
        export = context.scene.arsenal_export
        cfg = context.scene.arsenal_cfg
        self.props(context, ('cost', 'weight', 'durability', 'durability_per_shot'))
        try:
            weapon_id, sid = weapon_names(context.scene, export, cfg)
            box = self.layout.box()
            box.label(text=f'Weapon ID: {sid}')
            box.label(text=f'Mod: {mod_name(export)}')
        except RuntimeError as error:
            self.layout.label(text=str(error), icon='ERROR')


class ARSENAL_PT_CfgDamage(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Damage & Range'

    def draw(self, context):
        self.props(context, ('base_damage', 'armor_damage', 'armor_piercing', 'cover_piercing', 'base_bleeding',
                             'bleeding_chance', 'effective_distance', 'drop_off_distance',
                             'min_distance_modifier', 'projectile_drop_length', 'fire_loudness', 'base_comfort'))
        self.layout.label(text='Inventory stat bars (0-1)')
        self.props(context, ('ui_accuracy', 'ui_rate_of_fire', 'ui_handling', 'ui_damage', 'ui_range'))


class ARSENAL_PT_CfgHandling(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Handling & Fire'

    def draw(self, context):
        self.props(context, ('fire_interval', 'recoil_radius', 'dispersion_radius', 'aiming_time',
                             'offset_aiming_time', 'lean_aiming_time', 'lean_restore_time',
                             'max_jam_chance', 'jam_chance_coef', 'jam_time'))


class ARSENAL_PT_CfgAmmo(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Ammo & Magazines'

    def draw(self, context):
        cfg = context.scene.arsenal_cfg
        layout = self.layout
        self.props(context, ('max_ammo', 'caliber', 'dead_ammo_min', 'dead_ammo_max'))
        layout.label(text='Magazines (empty list = detect automatically)')
        row = layout.row()
        row.template_list('ARSENAL_UL_CfgMagazines', '', cfg, 'magazines', cfg, 'active_magazine', rows=3)
        side = row.column(align=True)
        side.operator('object.arsenal_cfg_magazine_add', icon='ADD', text='')
        side.operator('object.arsenal_cfg_magazine_remove', icon='REMOVE', text='')
        layout.operator('object.arsenal_cfg_magazine_detect', icon='VIEWZOOM')
        if 0 <= cfg.active_magazine < len(cfg.magazines):
            item = cfg.magazines[cfg.active_magazine]
            col = layout.column(align=True)
            for name in ('name', 'full_object', 'empty_object', 'capacity', 'preinstalled'):
                col.prop(item, name)
            if not item.preinstalled:
                col.prop(item, 'cost')
                col.prop(item, 'weight')
            col.prop(item, 'tactical_reload')
            col.prop(item, 'full_reload')


class ARSENAL_PT_CfgAttachments(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Attachments & Upgrades'

    def draw(self, context):
        self.props(context, ('allow_silencer', 'allow_laser', 'keep_upgrades'))


CLASSES = (
    ARSENAL_CfgMagazine,
    ARSENAL_CfgText,
    ARSENAL_WeaponCfg,
    ARSENAL_OT_CfgClearText,
    ARSENAL_PT_CustomWeaponPanel,
    ARSENAL_PT_CfgText,
    ARSENAL_OT_CfgApplyTemplate,
    ARSENAL_OT_CfgMagazineAdd,
    ARSENAL_OT_CfgMagazineRemove,
    ARSENAL_OT_CfgMagazineDetect,
    ARSENAL_UL_CfgMagazines,
    ARSENAL_PT_CfgIdentity,
    ARSENAL_PT_CfgDamage,
    ARSENAL_PT_CfgHandling,
    ARSENAL_PT_CfgAmmo,
    ARSENAL_PT_CfgAttachments,
)
