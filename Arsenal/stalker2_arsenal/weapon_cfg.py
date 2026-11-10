"""Weapon settings and the CFG files STALKER 2 needs for a working weapon mod.

The base files use the game's Content/GameLite/ModGameData layout in the export folder:
ItemPrototypes (weapon, attachments), MeshPrototypes, and the WeaponData general setup, player
settings and player attributes. Custom trees add UpgradePrototypes and EffectPrototypes.
Everything the add-on already knows (weapon name, mesh names,
bone sockets, mod name, folders) is filled in automatically; the rest comes from the panel.
"""
import json
import os
import re

import bpy

from . import export_animation as animation_export
from . import export_static_mesh as static_mesh
from .weapon_presets import PRESETS
from .notifications import report
from . import weapon_upgrades

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
                              'hip_loop_start')) + ('fire_modes',)
FIRE_MODES = (
    ('SemiAutomatic', 'Semi-automatic', 'One shot per trigger pull', 1),
    ('Queue', 'Burst', 'A fixed number of shots per trigger pull', 2),
    ('Automatic', 'Automatic', 'Keep firing while the trigger is held', 4),
)
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
    cfg.fire_modes = preset['fire_modes']
    for key in PRESET_PROPERTIES:
        if key in preset and key != 'fire_modes':
            setattr(cfg, key, preset[key])
    cfg.recoil_recovery_delay = 0.0
    cfg.recoil_recovery_time = 0.06


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


class ARSENAL_CfgText(bpy.types.PropertyGroup):
    """An item's name and description in one language."""
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


class ARSENAL_CfgMagazine(bpy.types.PropertyGroup):
    texts: bpy.props.CollectionProperty(type=ARSENAL_CfgText)
    text_language: bpy.props.EnumProperty(name='Language', items=LANGUAGES, default='en')
    text_name: bpy.props.StringProperty(name='Display Name', get=_get_text_name, set=_set_text_name)
    text_description: bpy.props.StringProperty(
        name='Description', get=_get_text_description, set=_set_text_description)
    localization_sid: bpy.props.StringProperty(name='Text Key Override')
    inventory_image: bpy.props.PointerProperty(type=bpy.types.Image)
    upgrade_image: bpy.props.PointerProperty(type=bpy.types.Image)
    standalone_image: bpy.props.PointerProperty(type=bpy.types.Image)
    standalone_camera: bpy.props.PointerProperty(type=bpy.types.Object)
    name: bpy.props.StringProperty(name='ID', default='Default',
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


def _attachment_kind_changed(self, context):
    if self.socket in ('SilencerMuzzleSocket', 'LaserSocket'):
        self.socket = 'SilencerMuzzleSocket' if self.kind == 'silencer' else 'LaserSocket'


class ARSENAL_CfgAttachment(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='ID', default='Silencer')
    kind: bpy.props.EnumProperty(name='Type', items=[
        ('silencer', 'Silencer', 'Inherits EN_Silen_2 behaviour'),
        ('laser', 'Laser', 'Inherits EN_Laser_1 behaviour')], update=_attachment_kind_changed)
    mesh_object: bpy.props.PointerProperty(
        name='Mesh', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'MESH')
    socket: bpy.props.StringProperty(name='Socket', default='SilencerMuzzleSocket')
    cost: bpy.props.FloatProperty(name='Cost', default=2500, min=0)
    weight: bpy.props.FloatProperty(name='Weight', default=0.1, min=0)
    texts: bpy.props.CollectionProperty(type=ARSENAL_CfgText)
    text_language: bpy.props.EnumProperty(name='Language', items=LANGUAGES, default='en')
    text_name: bpy.props.StringProperty(name='Display Name', get=_get_text_name, set=_set_text_name)
    text_description: bpy.props.StringProperty(
        name='Description', get=_get_text_description, set=_set_text_description)
    localization_sid: bpy.props.StringProperty(name='Text Key Override')
    inventory_image: bpy.props.PointerProperty(type=bpy.types.Image)
    upgrade_image: bpy.props.PointerProperty(type=bpy.types.Image)
    standalone_image: bpy.props.PointerProperty(type=bpy.types.Image)


class ARSENAL_CfgUpgradeEffect(bpy.types.PropertyGroup):
    prototype: bpy.props.EnumProperty(
        name='Base Effect', items=weapon_upgrades.EFFECT_ITEMS, default='DamagePos20Effect',
        update=weapon_upgrades.effect_changed,
        description='Existing game effect to use, or inherit for a custom numerical effect')
    custom: bpy.props.BoolProperty(name='Custom Values', description='Export a mod-owned effect with the values below')
    percent: bpy.props.BoolProperty(name='Percentage', default=True,
                                   description='Write percentage modifiers rather than absolute values')
    value_min: bpy.props.FloatProperty(name='Minimum', default=20,
                                       description='Signed game modifier; negative reduces the affected stat')
    value_max: bpy.props.FloatProperty(name='Maximum', default=20,
                                       description='Use the same minimum and maximum for a fixed modifier')
    beneficial: bpy.props.EnumProperty(
        name='Benefit', items=[(v, v, '') for v in ('None', 'Positive', 'Negative')], default='Positive',
        description='Whether the game presents this effect as a benefit or penalty')
    show_effect: bpy.props.BoolProperty(name='Show Effect in Upgrade Details', default=True)


class ARSENAL_CfgUpgrade(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='ID', description='Unique ID within this tree; used by prerequisite lists')
    template_sid: bpy.props.StringProperty(options={'HIDDEN'})
    image: bpy.props.PointerProperty(type=bpy.types.Image)
    texts: bpy.props.CollectionProperty(type=ARSENAL_CfgText)
    text_language: bpy.props.EnumProperty(name='Language', items=LANGUAGES, default='en')
    text_name: bpy.props.StringProperty(name='Display Name', get=_get_text_name, set=_set_text_name)
    text_description: bpy.props.StringProperty(name='Description', get=_get_text_description, set=_set_text_description)
    base_cost: bpy.props.FloatProperty(name='Cost', default=1000, min=0)
    horizontal: bpy.props.IntProperty(name='Column', default=0, min=0)
    vertical: bpy.props.EnumProperty(name='Position', items=[(v, v, '') for v in ('None', 'Top', 'Down')])
    target_part: bpy.props.EnumProperty(
        name='Weapon Part', items=[(v, v, '') for v in ('Barrel', 'Body', 'PistolGrip', 'Stock')])
    modification: bpy.props.BoolProperty(name='Modification')
    hidden_without_item: bpy.props.BoolProperty(name='Hide Without Required Item')
    keep_restrictions: bpy.props.BoolProperty(
        name='Keep Base Global-variable Restrictions', default=True,
        description='Retain the donor blueprint/quest variable restrictions; item and skill requirements below remain editable')
    required: bpy.props.StringProperty(name='Prerequisite Upgrade IDs',
                                      description='Comma-separated IDs of other upgrades in this custom tree')
    blocking: bpy.props.StringProperty(name='Mutually Exclusive Upgrade IDs',
                                      description='Comma-separated IDs of other upgrades that block this upgrade')
    interchangeable: bpy.props.StringProperty(name='Interchangeable Upgrade IDs',
                                              description='Comma-separated IDs of equivalent upgrades in this tree')
    attachments: bpy.props.StringProperty(name='Attachment SIDs',
                                         description='Comma-separated item SIDs installed by this upgrade')
    required_items: bpy.props.StringProperty(name='Required Item SIDs',
                                            description='Comma-separated game item SIDs, for example blueprint items')
    skills: bpy.props.StringProperty(name='Required Skills', description='Comma-separated technician skill IDs')
    connection_lines: bpy.props.StringProperty(name='Connection Lines',
                                               description='Comma-separated None, Top or Down layout connectors')
    effects: bpy.props.CollectionProperty(type=ARSENAL_CfgUpgradeEffect)
    active_effect: bpy.props.IntProperty()


def _get_fire_modes(self):
    # Older blends have no stored fire settings; retain their template's inherited modes.
    default = sum(value for mode, _label, _description, value in FIRE_MODES
                  if mode in PRESETS[self.setup_template]['fire_modes'])
    return (self.get('fire_modes', default) & 7) or default


def _set_fire_modes(self, value):
    self['fire_modes'] = (value & 7) or _get_fire_modes(self)
    self['default_fire_mode'] = _get_default_fire_mode(self)
    self['active_fire_mode'] = _get_active_fire_mode(self)


def _get_default_fire_mode(self):
    default = PRESETS[self.setup_template]['default_fire_mode']
    preferred = self.get('default_fire_mode', next(value for mode, _label, _description, value in FIRE_MODES
                                                 if mode == default))
    enabled = _get_fire_modes(self)
    return preferred if preferred in (1, 2, 4) and preferred & enabled else next(
        value for _mode, _label, _description, value in FIRE_MODES if value & enabled)


def _set_default_fire_mode(self, value):
    if value not in (1, 2, 4) or not value & _get_fire_modes(self):
        raise ValueError('The default fire mode must be enabled.')
    self['default_fire_mode'] = value


def _active_fire_mode_items(self, context):
    enabled = _get_fire_modes(self)
    return [item for item in FIRE_MODES if item[3] & enabled]


def _get_active_fire_mode(self):
    value = self.get('active_fire_mode', _get_default_fire_mode(self))
    return value if value in (1, 2, 4) and value & _get_fire_modes(self) else _get_default_fire_mode(self)


def _set_active_fire_mode(self, value):
    if value not in (1, 2, 4) or not value & _get_fire_modes(self):
        raise ValueError('Select an enabled fire mode.')
    self['active_fire_mode'] = value


def _fire_mode_checkbox(mode, label, description):
    def get(self):
        return mode in self.fire_modes

    def set_enabled(self, value):
        enabled = set(self.fire_modes)
        if value:
            enabled.add(mode)
        else:
            enabled.discard(mode)
        self.fire_modes = enabled

    return bpy.props.BoolProperty(name=label, description=description, get=get, set=set_enabled)


def _get_is_default_fire_mode(self):
    return _get_active_fire_mode(self) == _get_default_fire_mode(self)


def _set_is_default_fire_mode(self, value):
    if value:
        _set_default_fire_mode(self, _get_active_fire_mode(self))


class ARSENAL_WeaponCfg(bpy.types.PropertyGroup):
    upgrades: bpy.props.CollectionProperty(type=ARSENAL_CfgUpgrade)
    active_upgrade: bpy.props.IntProperty()
    upgrade_template: bpy.props.StringProperty(options={'HIDDEN'})
    attachments: bpy.props.CollectionProperty(type=ARSENAL_CfgAttachment)
    active_attachment: bpy.props.IntProperty()
    inventory_image: bpy.props.PointerProperty(type=bpy.types.Image)
    upgrade_image: bpy.props.PointerProperty(type=bpy.types.Image)
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
    fire_modes: bpy.props.EnumProperty(
        name='Available Fire Modes', items=FIRE_MODES, options={'ENUM_FLAG'},
        get=_get_fire_modes, set=_set_fire_modes,
        description='Modes the player can switch between. Enable at least one')
    default_fire_mode: bpy.props.EnumProperty(
        name='Default Fire Mode', items=FIRE_MODES,
        get=_get_default_fire_mode, set=_set_default_fire_mode,
        description='Starting fire mode; must be one of the available modes')
    fire_mode_semi: _fire_mode_checkbox(*FIRE_MODES[0][:3])
    fire_mode_burst: _fire_mode_checkbox(*FIRE_MODES[1][:3])
    fire_mode_auto: _fire_mode_checkbox(*FIRE_MODES[2][:3])
    active_fire_mode: bpy.props.EnumProperty(
        name='Fire Mode', items=_active_fire_mode_items,
        get=_get_active_fire_mode, set=_set_active_fire_mode,
        description='Enabled fire mode to inspect; handling values below are shared across modes')
    is_default_fire_mode: bpy.props.BoolProperty(
        name='Default fire mode', get=_get_is_default_fire_mode, set=_set_is_default_fire_mode,
        description='Use this mode when the weapon starts; select another mode and check it to change '
                    'the default. The only default cannot be cleared')
    burst_length: bpy.props.IntProperty(
        name='Burst Length', default=PISTOL['burst_length'], min=2,
        description='Number of shots per burst (FireQueueCount)')
    recoil_radius: bpy.props.FloatProperty(name='Recoil Radius', description='Size of the recoil kick. Larger means more camera movement while firing', default=PISTOL['recoil_radius'], min=0.0)
    recoil_recovery_delay: bpy.props.FloatProperty(
        name='Recoil Recovery Delay', default=0.0, min=0.0,
        description='Seconds before camera recoil starts returning after firing '
                    '(RecoilParams RadiusNormalizationDelay)')
    recoil_recovery_time: bpy.props.FloatProperty(
        name='Recoil Recovery Time', default=0.06, min=0.0,
        description='Seconds for camera recoil to return after firing; increase for a slower recovery '
                    '(RecoilParams RadiusNormalizationInterval). Zero is immediate')
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
        update=weapon_upgrades.tree_changed,
        description='Use the unchanged template upgrades; uncheck to edit a mod-owned tree seeded from the template')


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
            word = (qualifier.group(1) or qualifier.group(2)).lower()
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
            'settings': entry,
            'name': entry.name, 'full': entry.full_object, 'empty': entry.empty_object,
            'preinstalled': entry.preinstalled, 'capacity': entry.capacity, 'cost': entry.cost,
            'weight': entry.weight, 'tactical': entry.tactical_reload, 'full_reload': entry.full_reload})
    return result


def collect_attachments(cfg, others):
    result = []
    names = set()
    meshes = {obj for obj, _bones in others}
    for item in cfg.attachments:
        if not SAFE_ID.fullmatch(item.name) or item.name.casefold() in names:
            raise RuntimeError('Custom attachment IDs must be unique and contain only letters, digits and underscores.')
        names.add(item.name.casefold())
        if item.mesh_object not in meshes:
            raise RuntimeError(f'Attachment "{item.name}" needs a separate mesh weighted to a mapped weapon bone.')
        if not SAFE_ID.fullmatch(item.socket):
            raise RuntimeError(f'Attachment "{item.name}" needs a valid socket name.')
        result.append({'name': item.name, 'kind': item.kind, 'settings': item,
                       'object': item.mesh_object, 'socket': item.socket,
                       'template': 'EN_Silen_2' if item.kind == 'silencer' else 'EN_Laser_1'})
    return result


def compatible_attachment_sids(info):
    """[{'sid', 'kind'}] for the silencer/laser entries written to CompatibleAttachments."""
    cfg = info['cfg']
    custom = info.get('attachments', [])
    kinds = {item['kind'] for item in custom}
    result = []
    if cfg.allow_silencer and 'silencer' not in kinds:
        result.append({'sid': 'EN_Silen_2', 'kind': 'silencer'})
    if cfg.allow_laser and 'laser' not in kinds:
        result.append({'sid': 'EN_Laser_1', 'kind': 'laser'})
    result.extend({'sid': item['sid'], 'kind': item['kind']} for item in custom)
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
    if len({item['name'].casefold() for item in magazines}) != len(magazines):
        raise RuntimeError('Magazine IDs must be unique.')
    attachments = collect_attachments(cfg, others)
    template = static_mesh.template_token(context.scene)
    for magazine in magazines:
        for key in ('full', 'empty'):
            obj = magazine[key]
            stem = static_mesh.attachment_stem(mesh_name, obj.name, template)
            magazine[key + '_path'] = mesh_path(f'{mesh_folder}/AnimMesh', stem)
        bones = static_mesh.weighted_bones(magazine['full'], bone_joints)
        magazine['socket'] = bone_joints[max(bones, key=bones.get)] if bones else 'jnt_magazine'
    for item in attachments:
        item['sid'] = f'Gun{weapon_id}_Attach{item["name"]}'
        stem = static_mesh.attachment_stem(mesh_name, item['object'].name, template)
        item['mesh_path'] = mesh_path(f'{mesh_folder}/AnimMesh', stem)

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
        'parts': parts, 'magazines': magazines, 'attachments': attachments, 'animation_dir': animation_dir,
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
    image = image_reference(info, cfg, 'inventory', 'body')
    if image:
        writer.line(f'Icon = {image}')
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
        settings = magazine.get('settings')
        if not magazine['preinstalled'] and settings and settings.localization_sid.strip():
            writer.line(f'LocalizationSID = {settings.localization_sid.strip()}')
        image = image_reference(info, settings, 'standalone', f'Mag{magazine["name"]}')
        if image and not magazine['preinstalled']:
            writer.line(f'Icon = {image}')
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
    for item in info.get('attachments', []):
        settings = item['settings']
        writer.begin(item['sid'], '{refurl=@BaseGame/ItemPrototypes/AttachPrototypes.cfg;'
                     f'refkey={item["template"]}}}')
        writer.line(f'SID = {item["sid"]}')
        writer.line(f'MeshPrototypeSID = {item["sid"]}')
        writer.line(f'Cost = {number(settings.cost)}')
        writer.line(f'Weight = {number(settings.weight)}')
        if settings.localization_sid.strip():
            writer.line(f'LocalizationSID = {settings.localization_sid.strip()}')
        image = image_reference(info, settings, 'standalone', f'Attach{item["name"]}')
        if image:
            writer.line(f'Icon = {image}')
        writer.begin('FittingWeaponsSIDs', '{bskipref}')
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
    for item in info.get('attachments', []):
        entry(item['sid'], item['mesh_path'])
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
    if not cfg.fire_modes:
        raise RuntimeError('Enable at least one fire mode in Handling & Fire.')
    if cfg.default_fire_mode not in cfg.fire_modes:
        raise RuntimeError('The default fire mode must be enabled in Handling & Fire.')
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
    writer.begin('FireTypes', '{bskipref}')
    for index, mode in enumerate(mode for mode, _label, _description, _value in FIRE_MODES
                                 if mode in cfg.fire_modes):
        writer.line(f'[{index}] = EFireType::{mode}')
    writer.end()
    writer.line(f'DefaultFireType = EFireType::{cfg.default_fire_mode}')
    writer.line(f'FireQueueCount = {cfg.burst_length if "Queue" in cfg.fire_modes else 0}')
    writer.line(f'CameraRecoilPatternPath = {preset["recoil_pattern"]}')
    writer.line(f'CameraRecoilPatternBlendCurve = {preset["recoil_blend"]}')
    writer.begin('RecoilParams')
    writer.line(f'RecoilRadius = {number(cfg.recoil_radius)}')
    writer.line(f'CameraAimRecoilPatternLoopStartKeyIndex = {preset["aim_loop_start"]}')
    writer.line(f'CameraHipRecoilPatternLoopStartKeyIndex = {preset["hip_loop_start"]}')
    writer.begin('ShootingStateParams')
    writer.begin('RadiusNormalizationModifiers')
    writer.line(f'RadiusNormalizationDelay = {number(cfg.recoil_recovery_delay)}')
    writer.line(f'RadiusNormalizationInterval = {number(cfg.recoil_recovery_time)}')
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
    custom_kinds = {item['kind'] for item in info.get('attachments', [])}
    if cfg.allow_silencer and 'silencer' not in custom_kinds:
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
    laser_upgrade = weapon_upgrades.laser_upgrade(info)
    if cfg.allow_laser and 'laser' not in custom_kinds:
        writer.begin(f'[{index}]')
        writer.line('AttachPrototypeSID = EN_Laser_1')
        writer.line(f"WeaponSpecificIcon = Texture2D'{GAME_ICONS}/UDP/T_inv_w_udp_en_laser_1.T_inv_w_udp_en_laser_1'")
        writer.line('Socket = LaserSocket')
        if laser_upgrade:
            writer.begin('RequiredUpgradeIDs')
            writer.line(f'[0] = {laser_upgrade}')
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
        image = image_reference(info, magazine.get('settings'), 'inventory', f'Mag{magazine["name"]}')
        writer.line(f"WeaponSpecificIcon = " + (image or
                    f"Texture2D'{GAME_ICONS}/Integral/T_inv_w_integral_{icon}.T_inv_w_integral_{icon}'"))
        writer.end()
        index += 1
    for item in info.get('attachments', []):
        writer.begin(f'[{index}]')
        writer.line(f'AttachPrototypeSID = {item["sid"]}')
        writer.line(f'MeshPrototypeSID = {item["sid"]}')
        writer.line(f'Socket = {item["socket"]}')
        if item['kind'] == 'silencer':
            writer.line('Muzzle = SilencerMuzzle')
        writer.line('IconPosX = 0')
        writer.line('IconPosY = 0')
        image = image_reference(info, item['settings'], 'inventory', f'Attach{item["name"]}')
        writer.line(f'WeaponSpecificIcon = {image or ""}')
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
    for index, upgrade in enumerate(weapon_upgrades.upgrade_sids(info)):
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


def image_reference(info, settings, family, token):
    from .inventory_images import image_asset
    if settings is None or getattr(settings, f'{family}_image', None) is None:
        return ''
    path = image_asset(info, token, family)
    return f"Texture2D'{path}.{path.rsplit('/', 1)[-1]}'"


def localization_entries(info):
    """Name and description entries in the mod text asset's {SID, LanguagesToLocalizedStrings} shape."""
    entries = []
    targets = [(info['cfg'], text_key(info))]
    targets += [(item['settings'], f'Gun{info["weapon_id"]}_Mag{item["name"]}')
                for item in info.get('magazines', [])
                if item.get('settings') and not item['preinstalled']]
    targets += [(item['settings'], item['sid']) for item in info.get('attachments', [])]
    for settings, sid in targets:
        sid = settings.localization_sid.strip() or sid
        if not SAFE_ID.fullmatch(sid):
            raise RuntimeError(f'Invalid localisation SID: "{sid}".')
        for suffix in ('name', 'description'):
            texts = {f'ELocalizationLanguage::{LANGUAGE_MEMBERS[entry.language]}':
                     getattr(entry, suffix).replace('\\n', '\n')
                     for entry in settings.texts if entry.language in LANGUAGE_MEMBERS
                     and getattr(entry, suffix).strip()}
            if texts:
                entry = {'SID': f'sid_items_{sid}_{suffix}', 'LanguagesToLocalizedStrings': texts}
                previous = next((value for value in entries if value['SID'] == entry['SID']), None)
                if previous and previous != entry:
                    raise RuntimeError(f'Conflicting text for {entry["SID"]}. Use distinct text keys.')
                if previous is None:
                    entries.append(entry)
    entries.extend(weapon_upgrades.localization_entries(info))
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
    files.update(weapon_upgrades.files(info))
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
        report(operator, {'WARNING'}, 'No separate magazine meshes found; magazine entries were skipped.')
    if not localization_entries(info):
        report(operator, {'WARNING'}, 'No weapon name entered; the game will show the raw SID.')
    elif not any(entry.language == 'en' and entry.name.strip() for entry in info['cfg'].texts):
        report(operator, {'WARNING'}, 'No English name entered; other languages fall back to English.')
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
    bl_description = 'Add a magazine configuration; assign its full/empty meshes, capacity and optional text/images'

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
    bl_description = 'Remove the selected magazine configuration, not its mesh objects or previously exported files'

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
    bl_description = ('Replace the magazine list and its text/image settings using detected full/empty meshes; '
                      'the first detected magazine is marked preinstalled')

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
        if getattr(item, 'preinstalled', False):
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
    bl_description = ('Clear this item\'s name and description in the selected language; other languages remain; '
                      'does not remove translations already imported into ZoneKit')
    magazine_index: bpy.props.IntProperty(default=-1)
    attachment_index: bpy.props.IntProperty(default=-1)
    upgrade_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        if self.magazine_index >= 0:
            cfg = cfg.magazines[self.magazine_index]
        elif self.attachment_index >= 0:
            cfg = cfg.attachments[self.attachment_index]
        elif self.upgrade_index >= 0:
            cfg = cfg.upgrades[self.upgrade_index]
        for index, entry in enumerate(cfg.texts):
            if entry.language == cfg.text_language:
                cfg.texts.remove(index)
                break
        return {'FINISHED'}


def draw_localization(layout, settings, magazine_index=-1, attachment_index=-1, upgrade_index=-1):
    row = layout.row(align=True)
    row.prop(settings, 'text_language', text='')
    clear = row.operator('object.arsenal_cfg_clear_text', text='', icon='X')
    clear.magazine_index, clear.attachment_index = magazine_index, attachment_index
    clear.upgrade_index = upgrade_index
    layout.prop(settings, 'text_name')
    layout.prop(settings, 'text_description')
    if upgrade_index < 0:
        layout.prop(settings, 'localization_sid')
    done = [entry.language for entry in settings.texts if entry.name.strip() or entry.description.strip()]
    if done:
        layout.label(text='Entered: ' + ', '.join(done))


class ARSENAL_OT_CfgAttachmentEdit(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_attachment_edit'
    bl_label = 'Edit Custom Attachment'
    bl_description = 'Add or remove a custom silencer/laser configuration without deleting its mesh objects'
    bl_options = {'REGISTER', 'UNDO'}
    remove: bpy.props.BoolProperty()

    @classmethod
    def description(cls, context, properties):
        if properties.remove:
            return 'Remove the selected custom attachment settings, not its mesh or exported files'
        return 'Add a custom silencer or laser; assign its weighted mesh, socket, price, text and render images'

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        if self.remove:
            if not 0 <= cfg.active_attachment < len(cfg.attachments):
                report(self, {'ERROR'}, 'Select a custom attachment to remove.')
                return {'CANCELLED'}
            cfg.attachments.remove(cfg.active_attachment)
            cfg.active_attachment = max(0, cfg.active_attachment - 1)
        else:
            item = cfg.attachments.add()
            used = {entry.name for entry in cfg.attachments if entry != item}
            index = 1
            while f'Attachment{index}' in used:
                index += 1
            item.name = f'Attachment{index}'
            cfg.active_attachment = len(cfg.attachments) - 1
        return {'FINISHED'}


class ARSENAL_OT_CfgUpgradeEdit(bpy.types.Operator):
    bl_idname = 'object.arsenal_cfg_upgrade_edit'
    bl_label = 'Edit Custom Upgrade Tree'
    bl_description = 'Edit only this weapon\'s custom upgrade settings; shared base-game upgrades are never modified'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(items=[
        ('ADD', 'Add Upgrade', 'Add a new upgrade based on the selected upgrade'),
        ('REMOVE', 'Remove Upgrade', 'Remove the selected upgrade; repair references to its ID afterwards'),
        ('RESET', 'Reset Tree to Template', 'Replace the custom tree, text and images with current template defaults'),
        ('ADD_EFFECT', 'Add Effect', 'Add an effect to the selected upgrade'),
        ('REMOVE_EFFECT', 'Remove Effect', 'Remove the selected effect from this upgrade'),
        ('CLEAR_IMAGE', 'Clear Image', 'Use the donor upgrade illustration instead of the selected image'),
    ])

    @classmethod
    def description(cls, context, properties):
        return {
            'ADD': 'Add an upgrade seeded from the selected donor; set a unique ID, text, effects and dependencies',
            'REMOVE': 'Remove the selected custom upgrade; update any prerequisites or exclusions referring to its ID',
            'RESET': 'Replace the custom tree, text and image assignments with current template defaults',
            'ADD_EFFECT': 'Add a base-game effect or a mod-owned numerical effect to this upgrade',
            'REMOVE_EFFECT': 'Remove the selected effect from this upgrade without modifying the base game',
            'CLEAR_IMAGE': 'Clear this upgrade illustration assignment and use the donor image on the next export',
        }[properties.action]

    def invoke(self, context, event):
        if self.action == 'RESET':
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        cfg = context.scene.arsenal_cfg
        if cfg.keep_upgrades:
            report(self, {'ERROR'}, 'Uncheck Use Base Weapon Upgrade Tree before editing a custom tree.')
            return {'CANCELLED'}
        if self.action == 'RESET':
            weapon_upgrades.seed_tree(cfg)
        elif self.action == 'ADD':
            template = (cfg.upgrades[cfg.active_upgrade].template_sid
                        if 0 <= cfg.active_upgrade < len(cfg.upgrades) else
                        PRESETS[cfg.setup_template]['upgrades'][0])
            used = {item.name for item in cfg.upgrades}
            index = 1
            while f'Upgrade{index}' in used:
                index += 1
            item = cfg.upgrades.add()
            item.name, item.template_sid = f'Upgrade{index}', template
            cfg.active_upgrade = len(cfg.upgrades) - 1
        elif not 0 <= cfg.active_upgrade < len(cfg.upgrades):
            report(self, {'ERROR'}, 'Select a custom upgrade first.')
            return {'CANCELLED'}
        elif self.action == 'REMOVE':
            cfg.upgrades.remove(cfg.active_upgrade)
            cfg.active_upgrade = max(0, cfg.active_upgrade - 1)
        else:
            item = cfg.upgrades[cfg.active_upgrade]
            if self.action == 'ADD_EFFECT':
                effect = item.effects.add()
                weapon_upgrades.effect_changed(effect, context)
                item.active_effect = len(item.effects) - 1
            elif self.action == 'REMOVE_EFFECT':
                if not 0 <= item.active_effect < len(item.effects):
                    report(self, {'ERROR'}, 'Select an effect first.')
                    return {'CANCELLED'}
                item.effects.remove(item.active_effect)
                item.active_effect = max(0, item.active_effect - 1)
            elif self.action == 'CLEAR_IMAGE':
                from .inventory_images import assign_image
                assign_image(item, 'image', None)
        return {'FINISHED'}


class ARSENAL_UL_CfgUpgradeEffects(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.prototype + (' (custom)' if item.custom else ''))


def draw_upgrades(layout, context):
    cfg = context.scene.arsenal_cfg
    if cfg.keep_upgrades:
        return
    layout.label(text='Custom Upgrade Tree (mod-owned)')
    if cfg.upgrade_template != cfg.setup_template:
        layout.label(text='Tree retains the previous template; Reset replaces it.', icon='INFO')
    layout.operator('object.arsenal_cfg_upgrade_edit', text='Reset Tree to Template').action = 'RESET'
    row = layout.row()
    row.template_list('ARSENAL_UL_CfgMagazines', 'upgrades', cfg, 'upgrades', cfg, 'active_upgrade', rows=4)
    buttons = row.column(align=True)
    for action, icon in (('ADD', 'ADD'), ('REMOVE', 'REMOVE')):
        buttons.operator('object.arsenal_cfg_upgrade_edit', text='', icon=icon).action = action
    if not 0 <= cfg.active_upgrade < len(cfg.upgrades):
        return
    item = cfg.upgrades[cfg.active_upgrade]
    layout.label(text=f'Based on: {item.template_sid}')
    for name in ('name', 'base_cost', 'target_part', 'horizontal', 'vertical', 'connection_lines',
                 'modification', 'hidden_without_item', 'required', 'blocking', 'interchangeable',
                 'required_items', 'skills', 'keep_restrictions', 'attachments'):
        layout.prop(item, name)
    box = layout.box()
    box.label(text='Upgrade Name & Description (blank retains donor text)')
    draw_localization(box, item, upgrade_index=cfg.active_upgrade)
    box = layout.box()
    box.label(text='Upgrade Illustration')
    if item.image:
        box.template_icon(icon_value=item.image.preview_ensure().icon_id, scale=6)
    else:
        box.label(text='Uses donor image')
    row = box.row(align=True)
    select = row.operator('arsenal.inventory_image_file', text='Select Image', icon='FILE_FOLDER')
    select.upgrade_index = cfg.active_upgrade
    select.magazine_index, select.attachment_index, select.family = -1, -1, 'upgrade'
    row.operator('object.arsenal_cfg_upgrade_edit', text='', icon='X').action = 'CLEAR_IMAGE'
    box = layout.box()
    box.label(text='Functionality')
    row = box.row()
    row.template_list('ARSENAL_UL_CfgUpgradeEffects', '', item, 'effects', item, 'active_effect', rows=3)
    buttons = row.column(align=True)
    for action, icon in (('ADD_EFFECT', 'ADD'), ('REMOVE_EFFECT', 'REMOVE')):
        buttons.operator('object.arsenal_cfg_upgrade_edit', text='', icon=icon).action = action
    if 0 <= item.active_effect < len(item.effects):
        effect = item.effects[item.active_effect]
        box.prop(effect, 'prototype')
        box.prop(effect, 'custom')
        if effect.custom:
            for name in ('percent', 'value_min', 'value_max', 'beneficial', 'show_effect'):
                box.prop(effect, name)
            box.label(text='Signed game values: negative reduces the affected stat.')


class ARSENAL_PT_CfgText(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Name & Description'
    bl_options = set()
    bl_order = 1

    def draw(self, context):
        cfg = context.scene.arsenal_cfg
        layout = self.layout
        row = layout.row(align=True)
        row.prop(cfg, 'text_language', text='')
        clear = row.operator('object.arsenal_cfg_clear_text', text='', icon='X')
        clear.magazine_index, clear.attachment_index, clear.upgrade_index = -1, -1, -1
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
        from . import inventory_images
        if context.scene.arsenal_inventory.source_scene is None:
            inventory_images.draw_images(self.layout, context)


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
        cfg = context.scene.arsenal_cfg
        self.layout.label(text='Available Fire Modes')
        row = self.layout.row(align=True)
        for prop, mode in (('fire_mode_semi', 'SemiAutomatic'), ('fire_mode_burst', 'Queue'),
                           ('fire_mode_auto', 'Automatic')):
            checkbox = row.row(align=True)
            checkbox.enabled = len(cfg.fire_modes) > 1 or mode not in cfg.fire_modes
            checkbox.prop(cfg, prop)
        self.layout.separator()
        self.layout.label(text='Fire Mode Settings')
        self.layout.prop(cfg, 'active_fire_mode', text='')
        self.layout.prop(cfg, 'is_default_fire_mode')
        if cfg.active_fire_mode == 'Queue':
            self.layout.prop(cfg, 'burst_length')
        self.layout.label(text='Handling values are shared across fire modes')
        self.props(context, ('fire_interval', 'recoil_radius', 'recoil_recovery_delay', 'recoil_recovery_time',
                             'dispersion_radius', 'aiming_time',
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
            if not item.preinstalled:
                box = layout.box()
                box.label(text='Magazine Name & Description')
                draw_localization(box, item, magazine_index=cfg.active_magazine)
            from . import inventory_images
            inventory_images.draw_images(layout, context, cfg.active_magazine)


class ARSENAL_PT_CfgAttachments(_CfgSubPanel, bpy.types.Panel):
    bl_label = 'Attachments & Upgrades'

    def draw(self, context):
        self.props(context, ('allow_silencer', 'allow_laser', 'keep_upgrades'))
        cfg = context.scene.arsenal_cfg
        layout = self.layout
        if not cfg.keep_upgrades:
            draw_upgrades(layout.box(), context)
        layout.label(text='Custom attachments replace the matching base-game option.')
        row = layout.row()
        row.template_list('ARSENAL_UL_CfgMagazines', 'attachments', cfg, 'attachments',
                          cfg, 'active_attachment', rows=2)
        buttons = row.column(align=True)
        buttons.operator('object.arsenal_cfg_attachment_edit', text='', icon='ADD').remove = False
        buttons.operator('object.arsenal_cfg_attachment_edit', text='', icon='REMOVE').remove = True
        if 0 <= cfg.active_attachment < len(cfg.attachments):
            item = cfg.attachments[cfg.active_attachment]
            for name in ('name', 'kind', 'mesh_object', 'socket', 'cost', 'weight'):
                layout.prop(item, name)
            layout.label(text='Mesh must be weighted to a mapped weapon bone.')
            layout.label(text='Laser socket: LaserSocket; silencer: SilencerMuzzleSocket.')
            draw_localization(layout.box(), item, attachment_index=cfg.active_attachment)
            from . import inventory_images
            inventory_images.draw_images(layout, context, attachment_index=cfg.active_attachment)


CLASSES = (
    ARSENAL_CfgText,
    ARSENAL_CfgMagazine,
    ARSENAL_CfgAttachment,
    ARSENAL_CfgUpgradeEffect,
    ARSENAL_CfgUpgrade,
    ARSENAL_WeaponCfg,
    ARSENAL_OT_CfgClearText,
    ARSENAL_OT_CfgAttachmentEdit,
    ARSENAL_OT_CfgUpgradeEdit,
    ARSENAL_UL_CfgUpgradeEffects,
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
