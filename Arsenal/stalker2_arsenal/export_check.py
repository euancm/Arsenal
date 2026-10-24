"""Consistency checks on the names and paths the export generates.

Every function returns a list of warning strings; an empty list means nothing was found.
"""

import os
import re

DEFAULT_OBJECT_NAME = re.compile(r'^(Cube|Mesh|Object|Plane|Sphere|Cylinder|Cone|Suzanne|Icosphere|Torus|Circle|Empty)(\.\d+)?$',
                                 re.IGNORECASE)
PLACEHOLDER_WORDS = ('monkeymod', 'coolgun', 'example', 'placeholder', 'yourmod', 'yourweapon', 'untitled', 'newweapon')
OBJECT_REFERENCE = re.compile(r"(\w+)'(/[^'\s]+)\.([^'./\s]+)'")
SID_DEFINITION = re.compile(r'^\s*SID\s*=\s*(\S+)', re.MULTILINE)
SID_REFERENCE = re.compile(
    r'^\s*(MeshPrototypeSID|MeshInWorldPrototypeSID|AttachPrototypeSID|AttachSID|DefaultWeaponSettingsSID)\s*=\s*(\S+)',
    re.MULTILINE)


def _is_template_name(name, template_words):
    folded = name.casefold()
    return any(word in folded for word in template_words)


def name_warnings(info):
    """Names that will make the generated files inconsistent or look like leftovers."""
    warnings = []
    weapon = info['anim_name']
    mesh_name = info['mesh_name']
    if mesh_name.casefold() != weapon.casefold():
        warnings.append(
            f'The main weapon mesh object is called "{mesh_name}" but the weapon name (from the English Name) is '
            f'"{weapon}". The static meshes will be written to p_{mesh_name}/SM_wpn_{mesh_name}_* while the '
            f'animations, skeleton and SIDs use "{weapon}". Rename the mesh object to "{weapon}" (or change the '
            f'English Name) so they match.')
    objects = [('main weapon mesh', mesh_name)]
    for magazine in info['magazines']:
        objects.append((f'magazine "{magazine["name"]}" (full)', magazine['full'].name))
        objects.append((f'magazine "{magazine["name"]}" (empty)', magazine['empty'].name))
    for label, name in objects:
        if DEFAULT_OBJECT_NAME.match(name):
            warnings.append(f'The {label} object still has the default Blender name "{name}".')
    for label, value in (('Mod Name', info['mod']), ('weapon name', weapon)):
        if _is_template_name(value, PLACEHOLDER_WORDS):
            warnings.append(f'The {label} "{value}" looks like an example or placeholder value.')
    return warnings


def _find_file(root, relative):
    """Case-insensitive lookup of root/relative (Unreal paths are case-insensitive, Windows folders too)."""
    folder = root
    for part in [part for part in relative.split('/') if part]:
        if not os.path.isdir(folder):
            return None
        match = next((entry for entry in os.listdir(folder) if entry.casefold() == part.casefold()), None)
        if match is None:
            return None
        folder = os.path.join(folder, match)
    return folder if os.path.exists(folder) else None


def path_warnings(info, cfg_paths):
    """Check the written CFG files against each other and against the exported files."""
    warnings = []
    output_root = info['output_root']
    mount = info['mount']
    weapon = info['anim_name'].casefold()
    texts = {}
    for path in cfg_paths:
        if path.lower().endswith('.cfg') and os.path.exists(path):
            with open(path, encoding='utf-8') as handle:
                texts[path] = handle.read()

    defined = set()
    for text in texts.values():
        defined.update(SID_DEFINITION.findall(text))
    for path, text in texts.items():
        name = os.path.basename(path)
        for field, value in SID_REFERENCE.findall(text):
            if value not in defined:
                warnings.append(f'{name}: {field} "{value}" is not defined in any generated CFG file.')
        for kind, asset_path, asset_name in OBJECT_REFERENCE.findall(text):
            if not mount or not asset_path.startswith(mount + '/'):
                continue
            if asset_path.rsplit('/', 1)[-1] != asset_name:
                warnings.append(f'{name}: "{asset_path}.{asset_name}" has a different object name than its asset.')
            if weapon != 'udp' and 'udp' in asset_path.casefold():
                warnings.append(f'{name}: path "{asset_path}" still contains the template name "udp".')
            if kind == 'StaticMesh':
                relative = asset_path[len(mount) + 1:]
                if _find_file(output_root, relative + '.FBX') is None:
                    warnings.append(f'{name}: StaticMesh "{asset_path}" has no exported FBX ({relative}.FBX).')

    mod_folder = os.path.join(output_root, 'GameLite', 'ModGameData')
    if os.path.isdir(mod_folder) and info['mod'] not in os.listdir(mod_folder):
        warnings.append(f'GameLite/ModGameData has no "{info["mod"]}" folder.')
    for folder, names, files in os.walk(output_root):
        for entry in names + files:
            relative = os.path.relpath(os.path.join(folder, entry), output_root)
            if weapon != 'udp' and re.search(r'(^|[^a-z])udp([^a-z]|$)', entry, re.IGNORECASE) \
                    and not relative.startswith('GameLite'):
                warnings.append(f'Exported path "{relative}" still contains the template name "udp".')
            if re.search(r'[<>{}]', entry):
                warnings.append(f'Exported path "{relative}" contains a placeholder character.')
    return _collapse(warnings)


def _collapse(warnings, limit=3):
    """Keep the first few warnings of each kind (same text outside quotes) and count the rest."""
    kept, counts = [], {}
    for warning in warnings:
        kind = re.sub(r'"[^"]*"', '""', warning)
        counts[kind] = counts.get(kind, 0) + 1
        if counts[kind] <= limit:
            kept.append(warning)
    for kind, count in counts.items():
        if count > limit:
            kept.append(f'...and {count - limit} more like: {kind}')
    return kept
