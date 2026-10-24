"""Debug report: a plain-text summary of the add-on's settings and the state it will export from."""
import os
import sys
import traceback

import bpy


def value_text(value, depth=0):
    if isinstance(value, bpy.types.ID):
        return f'<{type(value).__name__} "{value.name}">'
    if isinstance(value, bpy.types.bpy_struct):
        return dump_group(value, depth + 1)
    if hasattr(value, '__len__') and not isinstance(value, str):
        return '[' + ', '.join(value_text(item, depth) for item in value) + ']'
    if isinstance(value, float):
        return f'{value:.6g}'
    return repr(value)


def dump_group(group, depth=0):
    """Every property of a PropertyGroup, one per line; collections are expanded."""
    pad = '  ' * (depth + 1)
    lines = []
    for prop in group.bl_rna.properties:
        if prop.identifier == 'rna_type':
            continue
        value = getattr(group, prop.identifier, None)
        if prop.type == 'COLLECTION':
            lines.append(f'{pad}{prop.identifier}: {len(value)} item(s)')
            for index, item in enumerate(value):
                lines.append(f'{pad}  [{index}]')
                lines.extend(f'{pad}  {line.strip()}' for line in dump_group(item, depth + 2).splitlines())
        elif prop.type == 'POINTER' and not isinstance(value, bpy.types.ID):
            lines.append(f'{pad}{prop.identifier}: {value_text(value, depth)}')
        else:
            lines.append(f'{pad}{prop.identifier}: {value_text(value, depth)}')
    return '\n'.join(lines)


def section(title, builder):
    lines = ['', f'== {title} ==']
    try:
        result = builder()
        lines.extend(result if isinstance(result, list) else str(result).splitlines())
    except Exception as error:
        lines.append(f'(failed: {error})')
        if not isinstance(error, RuntimeError):
            lines.extend('    ' + line for line in traceback.format_exc().splitlines()[-6:])
    return lines


def environment(context):
    addon = sys.modules.get(__package__)
    version = '.'.join(str(part) for part in getattr(addon, 'bl_info', {}).get('version', ()))
    return [f'Add-on version: {version}',
            f'Blender: {bpy.app.version_string}',
            f'Blend file: {bpy.data.filepath or "(unsaved)"}',
            f'Active object: {context.object.name if context.object else None} '
            f'({context.object.type if context.object else ""}, mode {context.object.mode if context.object else ""})',
            f'Unit scale: {context.scene.unit_settings.scale_length}, fps: {context.scene.render.fps}']


def rigs(context):
    from . import export_animation
    lines = []
    rig, backup = export_animation.find_export_rig(context)
    lines.append(f'Export rig: {rig.name if rig else None}; retarget backup: {backup.name if backup else None}')
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE':
            lines.append(f'Armature "{obj.name}": {len(obj.data.bones)} bones, '
                         f'collections {[c.name for c in obj.data.collections_all][:12]}')
    meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    lines.append(f'Mesh objects ({len(meshes)}): ' + ', '.join(
        f'{obj.name}[{len(obj.data.polygons)}f,{len(obj.material_slots)}mat]' for obj in meshes[:40]))
    return lines


def paths(context):
    export = context.scene.arsenal_export
    importer = context.scene.stalker2_animation_importer
    lines = []
    for label, raw in (('Output folder', export.output_folder), ('Animation library', importer.animation_root)):
        path = bpy.path.abspath(raw).strip()
        state = 'exists' if path and os.path.isdir(path) else 'MISSING'
        lines.append(f'{label}: {path or "(empty)"} [{state}]')
    return lines


def export_state(context):
    from . import export_animation
    export = context.scene.arsenal_export
    lines = [f'Derived weapon name: "{export_animation.weapon_name(context.scene)}"',
             f'Mod mount: "{export_animation.mod_mount(export)}"']
    ticked = [item for item in export.actions if item.enabled]
    lines.append(f'Actions: {len(export.actions)} listed, {len(ticked)} ticked')
    for item in export.actions:
        lines.append(f'  [{"x" if item.enabled else " "}] {item.name}'
                     f'  template="{item.template}" folder="{item.folder}"  status: {item.status}')
    return lines


def static_plan(context):
    from . import export_animation
    rig, _backup, bone_joints, plan = export_animation._build_static_plan(context)
    lines = [f'Mapped weapon bones -> joints ({len(bone_joints)}): '
             + ', '.join(f'{bone}->{joint}' for bone, joint in bone_joints.items())]
    for label, stem, path in plan:
        lines.append(f'  {label}: {stem} -> {path} [{"exists" if os.path.isfile(path) else "not written"}]')
    return lines


def cfg_state(context):
    from . import weapon_cfg
    cfg = context.scene.arsenal_cfg
    lines = [f'Template: {cfg.setup_template}; base weapon: {weapon_cfg.base_weapon(cfg)}']
    info = weapon_cfg.build_context(context)
    lines.append(f'Weapon id: {info["weapon_id"]}, SID: {info["sid"]}, mesh: {info["mesh_name"]}')
    lines.append(f'Mesh folder: {info["mesh_folder"]}')
    lines.append(f'Animation folder: {info["animation_dir"]}')
    for magazine in info['magazines']:
        lines.append(f'Magazine {magazine["name"]}: SID Gun{info["weapon_id"]}_Mag{magazine["name"]}, '
                     f'preinstalled={magazine["preinstalled"]}, socket={magazine["socket"]}, '
                     f'full={magazine["full_path"]}, empty={magazine["empty_path"]}')
    lines.append('Weapon parts: ' + ', '.join(joint for _path, joint in info['parts']))
    lines.append('CFG files: ' + ', '.join(sorted(weapon_cfg.cfg_files(info))))
    lines.append('Localisation SIDs: ' + ', '.join(entry['SID'] for entry in weapon_cfg.localization_entries(info)))
    return lines


def group_dump(group_name):
    def build(context):
        return dump_group(getattr(context.scene, group_name)).splitlines()
    return build


def setup_state(context):
    from . import setup_panel
    lines = dump_group(context.scene.arsenal_setup).splitlines()
    problems = setup_panel.setup_problems(context)
    lines.append('Problems: ' + ('; '.join(problems) if problems else 'none'))
    if not problems:
        lines.append(f'Script config: {setup_panel.build_config(context)}')
    return lines


def import_script(context):
    import json
    export = context.scene.arsenal_export
    output = bpy.path.abspath(export.output_folder).strip()
    lines = []
    if not os.path.isdir(output):
        return ['Output folder missing.']
    for name in sorted(os.listdir(output)):
        if name.startswith('import_') and name.endswith('.json'):
            import json
            with open(os.path.join(output, name), encoding='utf-8') as handle:
                manifest = json.load(handle)
            lines.append(f'{name}: weapon={manifest.get("weapon")}, game_root={manifest.get("game_root")}')
            lines.append(f'  weapon_skeleton={manifest.get("weapon_skeleton")}')
            lines.append(f'  magazines={manifest.get("magazines")}')
            animations = manifest.get('animations', {})
            lines.append(f'  animations: {len(animations.get("player", []))} player, '
                         f'{len(animations.get("weapon", []))} weapon; static meshes: {len(manifest.get("static_meshes", []))}; '
                         f'textures: {len(manifest.get("textures", []))}; materials: {len(manifest.get("materials", []))}')
            lines.append(f'  skeletal_mesh={manifest.get("skeletal_mesh")}; game_materials={manifest.get("game_materials")}')
    return lines or ['No import_*.json in the output folder yet (run Export All).']


def build_report(context):
    lines = ['STALKER 2 Arsenal debug report', '=' * 30]
    sections = (
        ('Environment', lambda: environment(context)),
        ('Paths', lambda: paths(context)),
        ('Rigs and meshes', lambda: rigs(context)),
        ('Set Up (ZoneKit script)', lambda: setup_state(context)),
        ('Export settings', lambda: dump_group(context.scene.arsenal_export).splitlines()),
        ('Export state', lambda: export_state(context)),
        ('Static mesh plan', lambda: static_plan(context)),
        ('Animation importer settings', lambda: dump_group(context.scene.stalker2_animation_importer).splitlines()),
        ('Weapon CFG settings', lambda: dump_group(context.scene.arsenal_cfg).splitlines()),
        ('Derived weapon data', lambda: cfg_state(context)),
        ('Last import script manifest', lambda: import_script(context)),
    )
    for title, builder in sections:
        lines.extend(section(title, builder))
    return '\n'.join(lines) + '\n'


class ARSENAL_OT_DebugReport(bpy.types.Operator):
    bl_idname = 'object.arsenal_debug_report'
    bl_label = 'Debug Output'
    bl_description = ('Write a plain-text summary of all the mod settings to the clipboard, the system console '
                      'and a text block named "Arsenal Debug", to help diagnose problems')

    def execute(self, context):
        text = build_report(context)
        context.window_manager.clipboard = text
        block = bpy.data.texts.get('Arsenal Debug') or bpy.data.texts.new('Arsenal Debug')
        block.clear()
        block.write(text)
        print(text)
        self.report({'INFO'}, 'Debug report copied to the clipboard (also in the "Arsenal Debug" text block).')
        return {'FINISHED'}


CLASSES = (ARSENAL_OT_DebugReport,)
