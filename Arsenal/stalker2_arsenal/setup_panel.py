import os
import re

import bpy

from . import export_animation as animation_export

SETUP_TEMPLATE_NAME = 'unreal_setup.py'
ZONEKIT_FOLDER = 'ZoneKit Export'
BLENDER_FOLDER = 'Blender Export'

# Names the template weapon's files use. Animations and meshes are not always named alike (SMG: viper / vip).
_ATTACH = '/Game/_Stalker_2/weapons/attachments/'
_LASER = _ATTACH + 'ls/SM_ls01_en_laser_01/SM_ls01_en_laser_01'
# Silencer and laser meshes (from MeshPrototypes.cfg via each weapon's CompatibleAttachments).
TEMPLATE_DEFAULTS = {
    'TemplatePistol': {'animation': 'udp', 'mesh': 'udp', 'category': 'pistol',
                       'attachments': [_ATTACH + 'sc/SM_sc01_en_silen_1/SM_sc01_en_silen_1', _LASER]},
    'TemplateSMG': {'animation': 'viper', 'mesh': 'vip', 'category': 'pistol_mashine_gun',
                    'attachments': [_ATTACH + 'sc/SM_sc02_en_silen_2/SM_sc02_en_silen_2', _LASER]},
    'TemplateRifle': {'animation': 'ak74', 'mesh': 'ak74', 'category': 'sturm_riffle',
                      'attachments': [_ATTACH + 'sc/SM_sc02_ru_silen_2/SM_sc02_ru_silen_2']},
    'TemplateShotgun': {'animation': 'm860', 'mesh': 'm86000', 'category': 'shotgun', 'attachments': [_LASER]},
    'TemplateSniper': {'animation': 'threeline', 'mesh': 'threeline', 'category': 'sniper_riffle',
                       'attachments': []},
}
MOD_NAME = re.compile(r'^[A-Za-z0-9_]+$')


def apply_template_defaults(scene, template):
    """Point the importer and static-mesh category at the files of the chosen template weapon."""
    defaults = TEMPLATE_DEFAULTS.get(template)
    if not defaults:
        return
    importer = scene.stalker2_animation_importer
    importer.weapon_name = defaults['animation']
    importer.mesh_name = '' if defaults['mesh'] == defaults['animation'] else defaults['mesh']
    scene.arsenal_export.static_category = defaults['category']


def _working_changed(self, context):
    folder = bpy.path.abspath(self.working_folder).strip()
    if not folder:
        return
    context.scene.stalker2_animation_importer.animation_root = os.path.join(folder, ZONEKIT_FOLDER)
    context.scene.arsenal_export.output_folder = os.path.join(folder, BLENDER_FOLDER)


def _get_mod_name(self):
    return bpy.context.scene.arsenal_export.unreal_mount


def _set_mod_name(self, value):
    bpy.context.scene.arsenal_export.unreal_mount = value.strip().strip('/')


def _english_entry(cfg, create=False):
    for entry in cfg.texts:
        if entry.language == 'en':
            return entry
    if create:
        entry = cfg.texts.add()
        entry.language = 'en'
        return entry
    return None


def _get_weapon_name(self):
    entry = _english_entry(bpy.context.scene.arsenal_cfg)
    return entry.name if entry else ''


def _set_weapon_name(self, value):
    _english_entry(bpy.context.scene.arsenal_cfg, create=True).name = value


class ARSENAL_SetupProps(bpy.types.PropertyGroup):
    working_folder: bpy.props.StringProperty(
        name='Working Folder', subtype='DIR_PATH', update=_working_changed,
        description=f'A folder for this weapon. The ZoneKit export goes in "{ZONEKIT_FOLDER}" and the files '
                    f'Blender exports in "{BLENDER_FOLDER}"')
    mod_name: bpy.props.StringProperty(
        name='Mod Name', get=_get_mod_name, set=_set_mod_name,
        description='The name of your mod in ZoneKit (e.g. MonkeyMod). Same as Mod Name in the Export panel')
    weapon_name: bpy.props.StringProperty(
        name='Weapon Name', get=_get_weapon_name, set=_set_weapon_name,
        description='Your weapon\'s name, as players see it (English). File and asset names are made from it, '
                    'lower-case without spaces')
    dry_run: bpy.props.BoolProperty(
        name='Dry Run', default=False,
        description='Only write the report of what the ZoneKit script would export and rename; change nothing')
    export_additive: bpy.props.BoolProperty(
        name='Export Additive Animations', default=False,
        description='Also export additive animation sequences. The add-on does not use them yet, '
                    'so they are only checked out and renamed')
    status: bpy.props.StringProperty(default='')


def setup_problems(context):
    """Reasons the setup script cannot be made yet; empty when everything is filled in."""
    setup = context.scene.arsenal_setup
    problems = []
    folder = bpy.path.abspath(setup.working_folder).strip()
    if not folder:
        problems.append('Choose a working folder.')
    elif not os.path.isdir(folder):
        problems.append('The working folder does not exist.')
    if not setup.mod_name.strip():
        problems.append('Enter the ZoneKit mod name.')
    elif not MOD_NAME.match(setup.mod_name.strip()):
        problems.append('The mod name may only contain letters, digits and underscores.')
    if not animation_export.weapon_name(context.scene):
        problems.append('Enter your weapon name.')
    return problems


def build_config(context):
    scene = context.scene
    setup = scene.arsenal_setup
    apply_template_defaults(scene, scene.arsenal_cfg.setup_template)
    importer = scene.stalker2_animation_importer
    animation = importer.weapon_name.strip().lower()
    mesh = (importer.mesh_name.strip() or animation).lower()
    return {
        'template': scene.arsenal_cfg.setup_template,
        'weapon': animation_export.weapon_name(scene),
        'mod': setup.mod_name.strip(),
        'export_dir': os.path.join(bpy.path.abspath(setup.working_folder).strip(), ZONEKIT_FOLDER),
        'anim_tokens': [animation],
        'mesh_tokens': [mesh],
        'attachment_meshes': list(TEMPLATE_DEFAULTS.get(scene.arsenal_cfg.setup_template, {}).get('attachments', [])),
        'dry_run': setup.dry_run,
        'export_additive': setup.export_additive,
        'export': True,
        'checkout': True,
    }


def write_setup_script(context):
    problems = setup_problems(context)
    if problems:
        raise RuntimeError(' '.join(problems))
    config = build_config(context)
    working = bpy.path.abspath(context.scene.arsenal_setup.working_folder).strip()
    os.makedirs(config['export_dir'], exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), SETUP_TEMPLATE_NAME), encoding='utf-8') as handle:
        script = handle.read()
    script = script.replace('CONFIG = None', f'CONFIG = {config!r}', 1)
    path = os.path.join(working, f'zonekit_setup_{config["weapon"]}.py')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(script)
    return path, config


class ARSENAL_OT_CreateSetupScript(bpy.types.Operator):
    bl_idname = 'object.arsenal_create_setup_script'
    bl_label = 'Create ZoneKit Setup Script'
    bl_description = ('Write the script that exports the template weapon\'s files, checks the other assets '
                      'out into your mod and renames them. Its path is copied to the clipboard for ZoneKit\'s '
                      'Python bar')

    def execute(self, context):
        try:
            path, config = write_setup_script(context)
        except (OSError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        context.window_manager.clipboard = path
        context.scene.arsenal_setup.status = f'Script path copied: {os.path.basename(path)}'
        self.report({'INFO'}, f'Paste into the ZoneKit Python bar (copied): {path}')
        return {'FINISHED'}


class ARSENAL_PT_SetupPanel(bpy.types.Panel):
    bl_label = '1. Set Up'
    bl_idname = 'ARSENAL_PT_SetupPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        setup = context.scene.arsenal_setup
        cfg = context.scene.arsenal_cfg
        importer = context.scene.stalker2_animation_importer

        layout.label(text='Template')
        row = layout.row(align=True)
        row.prop(cfg, 'setup_template', text='')
        row.operator('object.arsenal_cfg_apply_template', text='', icon='FILE_REFRESH')

        col = layout.column(align=True)
        col.prop(setup, 'weapon_name')
        col.prop(setup, 'mod_name')
        col.prop(setup, 'working_folder')

        col = layout.column(align=True)
        col.prop(setup, 'export_additive')
        col.prop(setup, 'dry_run')

        problems = setup_problems(context)
        for problem in problems[:2]:
            layout.label(text=problem, icon='ERROR')
        row = layout.row()
        row.enabled = not problems
        row.operator('object.arsenal_create_setup_script', icon='SCRIPT')
        if setup.status:
            layout.label(text=setup.status)


CLASSES = (
    ARSENAL_SetupProps,
    ARSENAL_OT_CreateSetupScript,
    ARSENAL_PT_SetupPanel,
)
