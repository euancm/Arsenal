"""Imports a Stalker 2 Arsenal export into the Unreal editor.

Run it once from the editor's Python console:

    py "<path to this file>"

Options (after the path): --overwrite re-imports assets that already exist.
Run with a normal Python (outside Unreal) to print the plan without importing anything.
"""
import json
import math
import os
import re
import shutil
import sys
import types
import uuid

BAKED_MANIFEST = None
SETUP_SOURCE = None
DISTRIBUTION_SOURCE = None
DISTRIBUTION_DEFAULTS = None

try:
    import unreal
except ImportError:
    unreal = None


def norm(name):
    """Compare material names regardless of Blender's .001 suffixes and Unreal's name clean-up."""
    name = re.sub(r'[._]\d{3}$', '', str(name))
    return re.sub(r'[^0-9A-Za-z]+', '_', name).lower()


def game_folder(root, relative_file):
    folder = os.path.dirname(relative_file).replace('\\', '/').strip('/')
    return f'{root}/{folder}' if folder else root


def asset_name(relative_file):
    return os.path.splitext(os.path.basename(relative_file))[0]


def socket_mod_path(path, root):
    if not isinstance(root, str):
        raise RuntimeError('Sockets require a valid mod mount.')
    root = root.rstrip('/')
    if (not re.fullmatch(r'/[A-Za-z0-9_]+', root) or root.casefold() in ('/game', '/engine')
            or not isinstance(path, str) or not path.startswith(root + '/')
            or not re.fullmatch(r'/[A-Za-z0-9_/]+', path)
            or '//' in path):
        raise RuntimeError(f'Sockets require a mod-owned asset path, not {path!r}.')
    return path


def validate_socket_transform(value):
    if not isinstance(value, dict):
        raise RuntimeError('Invalid socket transform.')
    for field in ('location', 'rotation', 'scale'):
        values = value.get(field)
        if (not isinstance(values, list) or len(values) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise RuntimeError(f'Socket {field} must contain three finite numbers.')
    if any(v <= 0 for v in value['scale']) or max(value['scale']) - min(value['scale']) > 0.00001:
        raise RuntimeError('Mirrored, singular or nonuniform socket scale is unsupported.')
    return value


def validate_weapon_sockets(manifest):
    payload = manifest.get('weapon_sockets')
    if payload is None:
        return None
    if (not isinstance(payload, dict) or type(payload.get('version')) is not int
            or payload['version'] != 1 or payload.get('units') != 'cm'):
        raise RuntimeError('Unsupported weapon socket payload version or units.')
    mesh = socket_mod_path(payload.get('mesh'), manifest['game_root'])
    if mesh != manifest['weapon_skeleton']:
        raise RuntimeError('Socket destination must be the weapon mesh used by the export.')
    if ('source_mesh' in payload and (not isinstance(payload['source_mesh'], str)
            or not re.fullmatch(r'/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)+', payload['source_mesh']))):
        raise RuntimeError('Invalid socket source mesh path.')
    entries = payload.get('entries')
    if not isinstance(entries, list):
        raise RuntimeError('Socket entries must be a list.')
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError('Invalid socket entry.')
        for field in ('name', 'bone'):
            if not isinstance(entry.get(field), str) or not re.fullmatch(r'[A-Za-z0-9_]+', entry[field]):
                raise RuntimeError(f'Invalid socket {field}.')
        key = entry['name'].casefold()
        if key in names:
            raise RuntimeError(f'Duplicate socket: {entry["name"]}')
        names.add(key)
        if type(entry.get('enabled')) is not bool:
            raise RuntimeError(f'Socket {entry["name"]} needs an explicit override state.')
        baseline = validate_socket_transform(entry.get('baseline'))
        transform = validate_socket_transform(entry.get('transform'))
        if transform['scale'] != baseline['scale']:
            raise RuntimeError(f'Scale editing is unsupported for socket {entry["name"]}.')
    return payload


def validate_world_mesh_sockets(manifest):
    payload = manifest.get('world_mesh_sockets')
    if payload is None:
        return None
    if (not isinstance(payload, dict) or type(payload.get('version')) is not int
            or payload['version'] != 1 or payload.get('units') != 'cm'):
        raise RuntimeError('Unsupported world mesh socket payload version or units.')
    mesh = socket_mod_path(payload.get('mesh'), manifest['game_root'])
    packages = {manifest['game_root'].rstrip('/') + '/' + os.path.splitext(path)[0].replace('\\', '/')
                for path in manifest['static_meshes']}
    if mesh not in packages:
        raise RuntimeError('World socket destination is not one of the exported static meshes.')
    if not isinstance(payload.get('entries'), list):
        raise RuntimeError('World mesh socket entries must be a list.')
    names = set()
    for entry in payload['entries']:
        if (not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
                or not re.fullmatch(r'[A-Za-z0-9_]+', entry['name'])):
            raise RuntimeError('Invalid world mesh socket name.')
        if entry['name'].casefold() in names:
            raise RuntimeError(f'Duplicate world mesh socket: {entry["name"]}')
        names.add(entry['name'].casefold())
        validate_socket_transform(entry)
    return payload


def socket_transform(socket):
    def values(property_name, components):
        value = socket.get_editor_property(property_name)
        return [float(getattr(value, axis)) for axis in components]
    return {
        'location': values('relative_location', 'xyz'),
        'rotation': values('relative_rotation', ('roll', 'pitch', 'yaw')),
        'scale': values('relative_scale', 'xyz'),
    }


def socket_quaternion(rotation):
    roll, pitch, yaw = [math.radians(v) / 2 for v in rotation]
    sr, cr = math.sin(roll), math.cos(roll)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    return (cr * sp * sy - sr * cp * cy, -cr * sp * cy - sr * cp * sy,
            cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy)


def socket_transforms_equal(left, right):
    dot = abs(sum(a * b for a, b in zip(socket_quaternion(left['rotation']),
                                       socket_quaternion(right['rotation']))))
    angle = math.degrees(2 * math.acos(min(1.0, dot)))
    return (math.dist(left['location'], right['location']) <= 0.001
            and max(abs(a - b) for a, b in zip(left['scale'], right['scale'])) <= 0.00001
            and angle <= 0.01)


def set_socket_transform(socket, transform):
    socket.set_editor_property('relative_location', unreal.Vector(*transform['location']))
    roll, pitch, yaw = transform['rotation']
    socket.set_editor_property('relative_rotation', unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll))
    socket.set_editor_property('relative_scale', unreal.Vector(*transform['scale']))


def build_plan(manifest, base_dir):
    root = manifest['game_root'].rstrip('/')

    def files(rels):
        return [(os.path.join(base_dir, rel), game_folder(root, rel), asset_name(rel)) for rel in rels]

    textures = [
        (path, folder, name, texture['kind'])
        for (path, folder, name), texture in zip(
            files([texture['file'] for texture in manifest['textures']]), manifest['textures'])
    ]
    materials = []
    for material in manifest['materials']:
        entries = {}
        for kind, stem in material['textures'].items():
            match = next((t for t in textures if t[2] == stem), None)
            entries[kind] = f'{match[1]}/{stem}' if match else None
        materials.append((material['name'], entries))
    return {
        'ui_images': files([entry['file'] for entry in manifest.get('ui_images', [])]),
        'textures': textures,
        'materials': materials,
        'static_meshes': files(manifest['static_meshes']),
        'player_animations': files(manifest['animations']['player']),
        'weapon_animations': files(manifest['animations']['weapon']),
        'skeletal_mesh': files([manifest['skeletal_mesh']]) if manifest.get('skeletal_mesh') else [],
    }


def find_manifest():
    if BAKED_MANIFEST and os.path.isfile(BAKED_MANIFEST):
        return BAKED_MANIFEST
    try:
        candidate = os.path.splitext(os.path.abspath(__file__))[0] + '.json'
    except NameError:
        candidate = ''
    if os.path.isfile(candidate):
        return candidate
    raise RuntimeError('Cannot find the import manifest (import_<weapon>.json) next to this script.')


def log(message):
    print(message)
    if unreal is not None:
        unreal.log(message)


WARNINGS = []


def warn(message):
    WARNINGS.append(message)
    print('WARNING: ' + message)
    if unreal is not None:
        unreal.log_warning(message)


def notify_completion(error=None):
    status = 'failed' if error is not None else 'finished with warnings' if WARNINGS else 'complete'
    message = str(error) if error is not None else (
        f'{len(WARNINGS)} warnings. See the Output Log for details.' if WARNINGS
        else 'Import finished.')
    if error is None:
        message += (
            '\n\nBefore packaging: open your mod in the Mod Editor and update the AnimCollection '
            'options to use your weapon\'s first-person collection. Localisation SIDs and translations '
            'are imported automatically; resolve any localisation warnings in the Output Log. '
            'Save the AnimCollection options, then package and test the mod.')
    if unreal is not None:
        category = (unreal.AppMsgCategory.ERROR if error is not None else
                    unreal.AppMsgCategory.WARNING if WARNINGS else unreal.AppMsgCategory.INFO)
        unreal.EditorDialog.show_message(
            f'Arsenal import {status}', message, unreal.AppMsgType.OK, message_category=category)


def name_key(name, token):
    """An asset name without its AS_/MG_ prefix and the weapon name, e.g. AS_udp_fp_reload -> fp_reload."""
    name = str(name).lower().split('_', 1)[-1]
    name = name.replace(str(token).lower(), '')
    return '_'.join(part for part in name.split('_') if part)


def find_replacement(ref_package, weapon, mount, mod_assets):
    """Find the mod asset that replaces a template weapon's asset (sequence or montage).

    ref_package is the template asset's package path, e.g.
    /Game/_STALKER2/Animations/Weapons/pt/udp/AnimSequences/fp/Reload/AS_udp_fp_reload.
    mod_assets maps lower-case package path -> package path of the assets in the mod.
    The template weapon name is whichever folder in the path the new weapon's name takes the place of.
    """
    parts = ref_package.strip('/').split('/')
    name = parts[-1]
    folders = parts[1:-1]
    mount_name = mount.strip('/').split('/')[0]
    weapon_lower = weapon.lower()
    for index, folder in enumerate(folders):
        if folder.lower() == weapon_lower:
            continue
        swapped = folders[:index] + [weapon] + folders[index + 1:]
        candidate_name = re.sub(re.escape(folder), weapon, name, flags=re.IGNORECASE)
        candidate = '/' + '/'.join([mount_name] + swapped + [candidate_name])
        found = mod_assets.get(candidate.lower())
        if found:
            return found
    for folder in folders:
        key = name_key(name, folder)
        prefix = name.split('_', 1)[0].lower()
        matches = [package for package in mod_assets.values()
                   if package.rsplit('/', 1)[-1].lower().startswith(prefix + '_')
                   and name_key(package.rsplit('/', 1)[-1], weapon) == key
                   and weapon_lower in [part.lower() for part in package.split('/')]]
        if len(matches) == 1:
            return matches[0]
    return None


def template_sequence_package(package, weapon, template_weapon, mount):
    if not package.startswith(mount.rstrip('/') + '/'):
        raise ValueError(f'Not a mod package: {package}')
    pattern = re.compile(rf'(?<![a-z0-9]){re.escape(weapon)}(?![a-z0-9])', re.IGNORECASE)
    return '/Game' + pattern.sub(template_weapon, package[len(mount.rstrip('/')):])


def transforms_equal(left, right):
    # Additive base subtraction/reapplication rounds native-key positions by up to ~5e-5 cm.
    for field, tolerance in (('translation', 1e-4), ('rotation', 1e-5), ('scale3d', 1e-5)):
        a, b = getattr(left, field), getattr(right, field)
        axes = ('x', 'y', 'z', 'w') if field == 'rotation' else ('x', 'y', 'z')
        if all(abs(getattr(a, axis) - getattr(b, axis)) <= tolerance for axis in axes):
            continue
        if field == 'rotation' and all(abs(getattr(a, axis) + getattr(b, axis)) <= tolerance for axis in axes):
            continue
        return False
    return True


def raw_pose_options():
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    options.retrieve_additive_as_full_pose = True
    return options


MAGAZINE_SID = re.compile(r'\bGun[A-Za-z0-9_]*?_Mag[A-Za-z0-9_]*')
EXTENDED_WORDS = ('extend', 'increas', 'big', 'large', 'long', 'drum', 'ext')


def is_extended(sid):
    return any(word in sid.split('_Mag', 1)[-1].lower() for word in EXTENDED_WORDS)


def new_magazine_sid(sid, magazines):
    """The mod's magazine SID replacing a template weapon's magazine SID, or None to leave it alone."""
    if not magazines or any(sid == magazine['sid'] for magazine in magazines):
        return None
    default = next((m for m in magazines if m.get('preinstalled')), magazines[0])
    others = [m for m in magazines if m is not default]
    if not is_extended(sid):
        return default['sid']
    extended = next((m for m in others if is_extended(m['name'])), others[0] if others else None)
    return extended['sid'] if extended else None


def swap_magazine_sids(text, magazines, lines=None, label=''):
    def swap(match):
        new = new_magazine_sid(match.group(0), magazines)
        if new is None:
            return match.group(0)
        if lines is not None:
            lines.append(f'collection {label}: {match.group(0)} -> {new}')
        return new
    return MAGAZINE_SID.sub(swap, text)


# SID-keyed maps of the anim collection's internal_animations. The game looks entries up by the CFG's
# magazine/attachment SID, so a missing key means no animation and a stuck weapon state.
COLLECTION_SID_MAPS = ('reloading', 'one_hand_reloading', 'attaching_by_sid')
TEMPLATE_ATTACHMENT_PREFIXES = {'silencer': 'EN_Silen_', 'laser': 'EN_Laser_'}


def new_attachment_sid(sid, attachments):
    """Resolve a donor attachment SID to the configured attachment of the same kind."""
    if any(item['sid'] == sid for item in attachments):
        return None
    for kind, prefix in TEMPLATE_ATTACHMENT_PREFIXES.items():
        if sid.startswith(prefix):
            targets = {item['sid'] for item in attachments if item.get('kind') == kind}
            if len(targets) > 1:
                raise ValueError(f'{sid} has multiple {kind} replacements: {", ".join(sorted(targets))}')
            return next(iter(targets), None)
    return None


def planned_collection_sids(keys, magazines, attachments=None):
    """{donor SID: configured SID} replacements, including obsolete duplicate keys."""
    plan = {}
    for key in sorted(str(key) for key in keys):
        new = (new_magazine_sid(key, magazines) if MAGAZINE_SID.fullmatch(key)
               else new_attachment_sid(key, attachments or []))
        if new and new != key:
            plan[key] = new
    return plan


class Importer:
    PARAMETER_DEFAULTS = {'D': 'Diffuse_VT', 'N': 'Normal_VT', 'RMA': 'RMAE_VT'}
    ADDITIVE_SETTINGS = ('ref_pose_seq', 'ref_pose_type', 'ref_frame_index', 'additive_anim_type')

    def __init__(self, manifest, base_dir, overwrite):
        self.manifest = manifest
        self.base_dir = base_dir
        self.plan = build_plan(manifest, base_dir)
        self.overwrite = overwrite
        self.library = unreal.EditorAssetLibrary
        self.tools = unreal.AssetToolsHelpers.get_asset_tools()
        self.managed = {}
        self.game_materials = None
        self.counts = {}

    def count(self, label):
        self.counts[label] = self.counts.get(label, 0) + 1

    def wanted(self, folder, name, replace=False):
        """True if the asset should be imported (missing, --overwrite, or replace for copies made by the setup script)."""
        replace = replace and self.manifest.get('replace_existing_assets', False)
        if self.library.does_asset_exist(f'{folder}/{name}') and not (self.overwrite or replace):
            self.count('skipped (exists)')
            return False
        return True

    def import_tasks(self, tasks):
        if not tasks:
            return []
        self.tools.import_asset_tasks(tasks)
        done = []
        for task in tasks:
            objects = list(task.get_editor_property('imported_object_paths'))
            if objects:
                self.count('imported')
                done.extend(objects)
            else:
                warn(f'Nothing was imported from {task.get_editor_property("filename")}')
                self.count('failed')
        return done

    def task(self, filename, folder, name, options=None):
        task = unreal.AssetImportTask()
        task.set_editor_property('filename', filename)
        task.set_editor_property('destination_path', folder)
        task.set_editor_property('destination_name', name)
        task.set_editor_property('replace_existing', True)
        task.set_editor_property('replace_existing_settings', True)
        task.set_editor_property('automated', True)
        task.set_editor_property('save', True)
        if options is not None:
            task.set_editor_property('options', options)
        return task

    def find_skeleton_asset(self, path):
        """Look for the skeleton by name anywhere in the project, e.g. the base game's /Game/_STALKER2/... copy."""
        name = path.rstrip('/').rsplit('/', 1)[-1]
        candidates = []
        try:
            registry = unreal.AssetRegistryHelpers.get_asset_registry()
            for class_name in ('SkeletalMesh', 'Skeleton'):
                class_path = unreal.TopLevelAssetPath('/Script/Engine', class_name)
                for data in registry.get_assets_by_class(class_path, False):
                    asset_name = str(data.get_editor_property('asset_name'))
                    if asset_name.lower() in (name.lower(), name.lower() + '_skeleton'):
                        candidates.append(str(data.get_editor_property('package_name')))
        except Exception as error:
            warn(f'Could not search the asset registry for "{name}" ({error}).')
        # Prefer the base game copy, then an exact name match
        candidates.sort(key=lambda package: (not package.startswith('/Game/'),
                                             package.rsplit('/', 1)[-1].lower() != name.lower()))
        for package in candidates:
            asset = self.library.load_asset(package)
            if asset is not None:
                log(f'Using {package} for the missing "{path}".')
                return asset
        return None

    def skeleton(self, path):
        asset = (self.library.load_asset(path) or self.library.load_asset(path + '_Skeleton')
                 or self.find_skeleton_asset(path))
        if asset is None:
            raise RuntimeError(
                f'Cannot find "{path}". Create the skeleton first (import the weapon skeletal mesh), '
                'or check the skeleton name.')
        if isinstance(asset, unreal.SkeletalMesh):
            asset = asset.get_editor_property('skeleton')
        return asset

    def import_textures(self):
        settings = {
            'D': (True, unreal.TextureCompressionSettings.TC_DEFAULT),
            'N': (False, unreal.TextureCompressionSettings.TC_NORMALMAP),
            'RMA': (False, unreal.TextureCompressionSettings.TC_MASKS),
        }
        tasks = [self.task(path, folder, name) for path, folder, name, _kind in self.plan['textures']
                 if self.wanted(folder, name)]
        self.import_tasks(tasks)
        for _path, folder, name, kind in self.plan['textures']:
            texture = self.library.load_asset(f'{folder}/{name}')
            if texture is None:
                continue
            srgb, compression = settings[kind]
            texture.set_editor_property('srgb', srgb)
            texture.set_editor_property('compression_settings', compression)
            if self.manifest.get('virtual_textures', True):
                texture.set_editor_property('virtual_texture_streaming', True)
            self.library.save_loaded_asset(texture)

    def import_ui_images(self):
        if not self.plan['ui_images']:
            return
        root = self.manifest['game_root'].rstrip('/')
        if not re.fullmatch(r'/[A-Za-z0-9_]+', root) or root.lower() in ('/game', '/engine'):
            raise RuntimeError(f'UI images require a mod-owned content mount, not {root!r}')
        for _path, folder, _name in self.plan['ui_images']:
            if not folder.startswith(root + '/UI/Arsenal/'):
                raise RuntimeError(f'UI image is outside the mod-owned Arsenal image folder: {folder}')
        planned = [(path, folder, name) for path, folder, name in self.plan['ui_images']
                   if self.wanted(folder, name, replace=True)]
        tasks = [self.task(path, folder, name) for path, folder, name in planned]
        imported = {str(path).split('.', 1)[0] for path in self.import_tasks(tasks)}
        missing = {f'{folder}/{name}' for _path, folder, name in planned} - imported
        if missing:
            raise RuntimeError('UI texture import failed; existing images were not refreshed: '
                               + ', '.join(sorted(missing)))
        for _path, folder, name in self.plan['ui_images']:
            path = f'{folder}/{name}'
            texture = self.library.load_asset(path)
            if texture is None:
                raise RuntimeError(f'UI texture import failed: {path}')
            texture.set_editor_property('srgb', True)
            texture.set_editor_property('compression_settings',
                                        unreal.TextureCompressionSettings.TC_EDITOR_ICON)
            texture.set_editor_property('lod_group', unreal.TextureGroup.TEXTUREGROUP_UI)
            texture.set_editor_property('mip_gen_settings', unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
            texture.set_editor_property('virtual_texture_streaming', False)
            if not self.library.save_loaded_asset(texture):
                raise RuntimeError(f'Could not save UI texture: {path}')

    def import_materials(self):
        folder = self.manifest['material_folder']
        parent = self.library.load_asset(self.manifest['parent_material'])
        phys = self.library.load_asset(self.manifest['phys_material']) if self.manifest.get('phys_material') else None
        parameters = dict(self.PARAMETER_DEFAULTS, **self.manifest.get('texture_parameters', {}))
        if parent is None:
            warn(f'Parent material {self.manifest["parent_material"]} not found; materials were not created.')
            return
        editing = unreal.MaterialEditingLibrary
        for name, textures in self.plan['materials']:
            path = f'{folder}/{name}'
            existed = self.library.does_asset_exist(path)
            if existed and not self.overwrite:
                self.managed[norm(name)] = self.library.load_asset(path)
                self.count('skipped (exists)')
                continue
            instance = self.library.load_asset(path) if existed else self.tools.create_asset(
                name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            editing.set_material_instance_parent(instance, parent)
            for kind, texture_path in textures.items():
                texture = self.library.load_asset(texture_path) if texture_path else None
                if texture is None:
                    warn(f'{name}: texture for {kind} not found ({texture_path}).')
                    continue
                editing.set_material_instance_texture_parameter_value(instance, parameters[kind], texture)
            if phys is not None:
                instance.set_editor_property('phys_material', phys)
            if self.manifest.get('virtual_textures', True):
                try:
                    editing.set_material_instance_static_switch_parameter_value(
                        instance, 'UseVirtualTexture_DoNotRename', True)
                except Exception as error:
                    warn(f'{name}: could not enable UseVirtualTexture_DoNotRename ({error}); set it by hand.')
            editing.update_material_instance(instance)
            self.library.save_loaded_asset(instance)
            self.managed[norm(name)] = instance
            self.count('imported')

    def find_game_material(self, key):
        if self.game_materials is None:
            self.game_materials = {}
            try:
                registry = unreal.AssetRegistryHelpers.get_asset_registry()
                path = unreal.TopLevelAssetPath('/Script/Engine', 'MaterialInstanceConstant')
                for data in registry.get_assets_by_class(path, False):
                    name = norm(data.get_editor_property('asset_name'))
                    package = str(data.get_editor_property('package_name'))
                    if name not in self.game_materials or package.startswith('/Game/'):
                        self.game_materials[name] = package
            except Exception as error:
                warn(f'Could not search the asset registry for existing materials ({error}).')
        package = self.game_materials.get(key)
        return self.library.load_asset(package) if package else None

    def assign_materials(self, mesh):
        for index, slot in enumerate(mesh.get_editor_property('static_materials')):
            slot_name = str(slot.get_editor_property('material_slot_name'))
            key = norm(slot_name)
            material = self.managed.get(key) or self.find_game_material(key)
            if material is None:
                warn(f'{mesh.get_name()}: no material found for slot "{slot_name}".')
                continue
            mesh.set_material(index, material)

    def import_static_meshes(self):
        mount = self.manifest['game_root'].rstrip('/')
        packages = {
            f'{folder}/{name}' for _path, folder, name in self.plan['static_meshes']
        }
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        for data in registry.get_assets_by_path(mount + '/_Stalker_2/weapons', recursive=True):
            if str(data.asset_class_path.asset_name) == 'StaticMesh':
                packages.add(str(data.package_name))
        collisions = [
            package for package in sorted(packages)
            if self.library.does_asset_exist('/Game' + package[len(mount):])
        ]
        if collisions:
            raise RuntimeError(
                'Static mesh packages would override vanilla weapons. Archive the old mod-owned '
                'packages outside Content and export with a unique weapon mesh name: '
                + ', '.join(collisions))
        options = unreal.FbxImportUI()
        options.set_editor_property('automated_import_should_detect_type', False)
        options.set_editor_property('mesh_type_to_import', unreal.FBXImportType.FBXIT_STATIC_MESH)
        options.set_editor_property('import_mesh', True)
        options.set_editor_property('import_as_skeletal', False)
        options.set_editor_property('import_animations', False)
        options.set_editor_property('import_materials', False)
        options.set_editor_property('import_textures', False)
        pending = [(path, folder, name) for path, folder, name in self.plan['static_meshes']
                   if self.wanted(folder, name, replace=True)]
        imported = self.import_tasks([self.task(path, folder, name, options) for path, folder, name in pending])
        for object_path in imported:
            mesh = self.library.load_asset(object_path)
            if mesh is not None:
                self.assign_materials(mesh)
                self.library.save_loaded_asset(mesh)
        self.apply_world_mesh_sockets()

    def apply_world_mesh_sockets(self):
        payload = validate_world_mesh_sockets(self.manifest)
        if payload is None or not payload['entries']:
            return
        mesh = self.library.load_asset(payload['mesh'])
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError(f'Cannot load world socket destination static mesh: {payload["mesh"]}')
        changes = []
        for entry in payload['entries']:
            names = [name for name in mesh.get_socket_names()
                     if str(name).casefold() == entry['name'].casefold()]
            if len(names) > 1:
                raise RuntimeError(f'Duplicate existing world mesh socket: {entry["name"]}')
            socket = mesh.find_socket(names[0]) if names else None
            if socket is not None and socket.get_outer() != mesh:
                raise RuntimeError(f'World socket is not owned by its static mesh: {entry["name"]}')
            before = socket_transform(socket) if socket is not None else None
            if before is None or not socket_transforms_equal(before, entry):
                changes.append((entry, socket, before))
        if not changes:
            log('  world magazine sockets unchanged; no save needed')
            return
        changed = []
        mesh.modify()
        try:
            for entry, socket, before in changes:
                if socket is None:
                    socket = unreal.StaticMeshSocket(outer=mesh)
                    socket.set_editor_property('socket_name', entry['name'])
                    mesh.add_socket(socket)
                changed.append((socket, before))
                socket.modify()
                set_socket_transform(socket, entry)
                if (mesh.find_socket(entry['name']) != socket
                        or not socket_transforms_equal(socket_transform(socket), entry)):
                    raise RuntimeError(f'World socket readback failed: {entry["name"]}')
            if not self.library.save_loaded_asset(mesh):
                raise RuntimeError(f'Could not save world magazine sockets on {payload["mesh"]}')
        except Exception as error:
            rollback_errors = []
            for socket, before in reversed(changed):
                try:
                    if before is None:
                        mesh.remove_socket(socket)
                    else:
                        set_socket_transform(socket, before)
                except Exception as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if changed:
                try:
                    if not self.library.save_loaded_asset(mesh):
                        rollback_errors.append('could not save restored world magazine sockets')
                except Exception as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                raise RuntimeError(f'{error}; world socket rollback failed: {rollback_errors}') from error
            raise
        self.counts['world magazine sockets'] = len(changes)
        log(f'  saved {len(changes)} world magazine sockets on {payload["mesh"]}')

    def import_animations(self, files, skeleton_path):
        pending = [(path, folder, name) for path, folder, name in files if self.wanted(folder, name, replace=True)]
        if not pending:
            return
        playback = {}
        for _path, folder, name in pending:
            package = f'{folder}/{name}'
            if self.library.does_asset_exist(package):
                asset = self.library.load_asset(package)
                if asset is None:
                    raise RuntimeError(f'Cannot read animation settings before import: {package}')
                playback[package] = {key: asset.get_editor_property(key) for key in self.ADDITIVE_SETTINGS}
        skeleton = self.skeleton(skeleton_path)
        options = unreal.FbxImportUI()
        options.set_editor_property('automated_import_should_detect_type', False)
        options.set_editor_property('mesh_type_to_import', unreal.FBXImportType.FBXIT_ANIMATION)
        options.set_editor_property('import_mesh', False)
        options.set_editor_property('import_as_skeletal', False)
        options.set_editor_property('import_animations', True)
        options.set_editor_property('import_materials', False)
        options.set_editor_property('import_textures', False)
        options.set_editor_property('skeleton', skeleton)
        animation_options = options.get_editor_property('anim_sequence_import_data')
        animation_options.set_editor_property('preserve_local_transform', True)
        animation_options.set_editor_property('use_default_sample_rate', False)
        animation_options.set_editor_property('custom_sample_rate', 0)
        tasks = [self.task(path, folder, name, options) for path, folder, name in pending]
        for task in tasks:
            # Interchange recomputes locals from sheared globals, changing the baked pose.
            task.set_editor_property('factory', unreal.FbxFactory())
        flag = 'Interchange.FeatureFlags.Import.FBX'
        interchange_enabled = unreal.SystemLibrary.get_console_variable_bool_value(flag)
        try:
            if interchange_enabled:
                unreal.SystemLibrary.execute_console_command(None, flag + ' 0')
            self.import_tasks(tasks)
            for package, settings in playback.items():
                asset = self.library.load_asset(package)
                if asset is None:
                    raise RuntimeError(f'Cannot restore animation settings after import: {package}')
                self.restore_additive_settings(asset, settings)
        finally:
            if interchange_enabled:
                unreal.SystemLibrary.execute_console_command(None, flag + ' 1')

    def restore_additive_settings(self, asset, settings):
        if all(asset.get_editor_property(key) == value for key, value in settings.items()):
            return
        for key, value in settings.items():
            asset.set_editor_property(key, value)
        if not self.library.save_loaded_asset(asset):
            raise RuntimeError(f'Could not save additive settings on {asset.get_path_name()}')
        log(f'  restored additive settings on {asset.get_name()}')
        self.count('additive settings restored')

    def import_skeletal_mesh(self):
        """Create SK_<weapon> (and its skeleton) from the exported armature before any animation needs it."""
        pending = [(path, folder, name) for path, folder, name in self.plan['skeletal_mesh']
                   if self.wanted(folder, name, replace=True)]
        if not pending:
            return
        options = unreal.FbxImportUI()
        options.set_editor_property('automated_import_should_detect_type', False)
        options.set_editor_property('mesh_type_to_import', unreal.FBXImportType.FBXIT_SKELETAL_MESH)
        options.set_editor_property('import_mesh', True)
        options.set_editor_property('import_as_skeletal', True)
        options.set_editor_property('import_animations', False)
        options.set_editor_property('import_materials', False)
        options.set_editor_property('import_textures', False)
        options.set_editor_property('create_physics_asset', False)
        self.import_tasks([self.task(path, folder, name, options) for path, folder, name in pending])

    def apply_weapon_sockets(self):
        payload = validate_weapon_sockets(self.manifest)
        if payload is None or not payload['entries']:
            return
        mesh = self.library.load_asset(payload['mesh'])
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError(f'Cannot load socket destination skeletal mesh: {payload["mesh"]}')
        tag = 'ArsenalWeaponSocketsV1'
        old_tag = self.library.get_metadata_tag(mesh, tag)
        try:
            managed = json.loads(old_tag) if old_tag else {}
        except ValueError as error:
            raise RuntimeError(f'Invalid Arsenal socket metadata on {payload["mesh"]}') from error
        if not isinstance(managed, dict):
            raise RuntimeError(f'Invalid Arsenal socket metadata on {payload["mesh"]}')
        updated = dict(managed)
        changes = []
        pending = []
        donor = None
        reference = unreal.SkeletalMeshComponent()
        reference.set_skeletal_mesh_asset(mesh)
        # Preflight every requested socket before modifying any UObject.
        for entry in payload['entries']:
            name = entry['name']
            if reference.get_bone_index(entry['bone']) < 0:
                raise RuntimeError(f'Socket {name} has no destination bone {entry["bone"]}.')
            previous = managed.get(name)
            desired = entry['transform'] if entry['enabled'] else entry['baseline']
            socket = mesh.find_socket(name)
            missing = socket is None
            if missing and payload.get('source_mesh'):
                if donor is None:
                    donor = self.library.load_asset(payload['source_mesh'])
                    if not isinstance(donor, unreal.SkeletalMesh) or donor == mesh:
                        raise RuntimeError(f'Cannot load independent socket donor: {payload["source_mesh"]}')
                socket = donor.find_socket(name)
            if socket is None or str(socket.get_editor_property('bone_name')) != entry['bone']:
                raise RuntimeError(f'Socket {name} is missing or its original bone changed; rerun setup/import.')
            current = socket_transform(socket)
            if missing and not socket_transforms_equal(current, entry['baseline']):
                raise RuntimeError(f'Donor socket {name} changed; review the donor catalogue.')
            if previous is not None:
                if (not isinstance(previous, dict) or previous.get('bone') != entry['bone']
                        or not socket_transforms_equal(validate_socket_transform(previous.get('baseline')),
                                                       entry['baseline'])):
                    raise RuntimeError(f'Source changed for managed socket {name}; review the donor catalogue.')
                last = validate_socket_transform(previous.get('last'))
                if not (socket_transforms_equal(current, last)
                        or socket_transforms_equal(current, entry['baseline'])):
                    raise RuntimeError(f'Socket {name} changed outside Arsenal; refusing to overwrite it.')
            elif not missing and (not entry['enabled'] or socket_transforms_equal(desired, entry['baseline'])):
                continue
            elif not socket_transforms_equal(current, entry['baseline']):
                raise RuntimeError(f'Socket {name} has an unmanaged override; refusing to overwrite it.')
            owner = socket.get_outer()
            source_mesh = donor if missing else mesh
            if owner != source_mesh and owner != source_mesh.get_editor_property('skeleton'):
                raise RuntimeError(f'Unexpected owner for socket {name}: {owner.get_path_name()}')
            created = previous.get('created', False) if previous else False
            needs_copy = missing or (owner != mesh and not socket_transforms_equal(current, desired))
            if needs_copy:
                for api_owner, method in ((self.library, 'duplicate_asset'), (self.library, 'delete_loaded_asset'),
                                          (unreal, 'load_object'), (mesh, 'add_socket'), (socket, 'rename')):
                    if not callable(getattr(api_owner, method, None)):
                        raise RuntimeError(f'Cannot create an independent mesh socket: missing {method}.')
                created = True
            if entry['enabled'] and not socket_transforms_equal(desired, entry['baseline']):
                updated[name] = {'bone': entry['bone'], 'baseline': entry['baseline'],
                                 'last': desired, 'created': created}
            elif created:
                updated[name] = {'bone': entry['bone'], 'baseline': entry['baseline'],
                                 'last': entry['baseline'], 'created': True}
            else:
                updated.pop(name, None)
            if needs_copy or not socket_transforms_equal(current, desired):
                pending.append((entry, socket, current, desired, needs_copy))
        if not pending and updated == managed:
            return
        clones = {}
        added = []
        mesh.modify()
        try:
            for entry, source, before, desired, needs_copy in pending:
                socket = source
                if needs_copy:
                    owner_path = source.get_outer().get_path_name()
                    if owner_path not in clones:
                        staging = (self.manifest['game_root'].rstrip('/') + '/_ArsenalSocketStaging/'
                                   + uuid.uuid4().hex + '/SocketSource')
                        clone = self.library.duplicate_asset(owner_path, staging)
                        if clone is None or clone == source.get_outer():
                            raise RuntimeError(f'Cannot independently copy socket owner {owner_path}')
                        clones[owner_path] = clone
                    clone = clones[owner_path]
                    socket = unreal.load_object(None, clone.get_path_name() + ':' + source.get_name())
                    if (socket is None or socket == source or socket.get_outer() != clone
                            or str(socket.get_editor_property('socket_name')) != entry['name']
                            or str(socket.get_editor_property('bone_name')) != entry['bone']
                            or not socket_transforms_equal(socket_transform(socket), before)):
                        raise RuntimeError(f'Independent socket copy failed: {entry["name"]}')
                    if not socket.rename(name='ArsenalSocket_' + uuid.uuid4().hex, outer=mesh):
                        raise RuntimeError(f'Cannot assign copied socket {entry["name"]} to the weapon mesh')
                    mesh.add_socket(socket, add_to_skeleton=False)
                    added.append((entry, socket, before))
                    if mesh.find_socket(entry['name']) != socket or socket.get_outer() != mesh:
                        raise RuntimeError(f'Mesh-only socket lookup failed: {entry["name"]}')
                changes.append((socket, before, desired))
            for socket, before, desired in changes:
                set_socket_transform(socket, desired)
                if not socket_transforms_equal(socket_transform(socket), desired):
                    raise RuntimeError(f'Socket readback failed: {socket.get_path_name()}')
                log(f'  socket {socket.get_editor_property("socket_name")}: {before} -> {desired}')
            self.library.set_metadata_tag(mesh, tag, json.dumps(updated, sort_keys=True))
            for _entry, source, before, _desired, needs_copy in pending:
                if needs_copy and not socket_transforms_equal(socket_transform(source), before):
                    raise RuntimeError('A source socket changed while creating a mesh-only copy.')
            if not self.library.save_loaded_asset(mesh):
                raise RuntimeError(f'Could not save socket owner {payload["mesh"]}')
        except Exception as error:
            failures = []
            for socket, before, _desired in changes:
                try:
                    set_socket_transform(socket, before)
                except Exception as rollback_error:
                    failures.append(f'{socket.get_path_name()}: {rollback_error}')
            try:
                if added:
                    restored = dict(managed)
                    for entry, socket, before in added:
                        set_socket_transform(socket, before)
                        restored[entry['name']] = {
                            'bone': entry['bone'], 'baseline': entry['baseline'], 'last': before, 'created': True}
                    self.library.set_metadata_tag(mesh, tag, json.dumps(restored, sort_keys=True))
                    failures.append('New mesh-only overrides remain at donor placement; '
                                    'ZoneKit exposes no socket removal API')
                elif old_tag:
                    self.library.set_metadata_tag(mesh, tag, old_tag)
                else:
                    self.library.remove_metadata_tag(mesh, tag)
                if not self.library.save_loaded_asset(mesh):
                    failures.append(f'Could not save rollback: {payload["mesh"]}')
            except Exception as rollback_error:
                failures.append(str(rollback_error))
            if failures:
                raise RuntimeError(f'{error}; socket rollback failed: {"; ".join(failures)}') from error
            raise
        finally:
            cleanup_errors = []
            for clone in clones.values():
                try:
                    if not self.library.delete_loaded_asset(clone):
                        cleanup_errors.append(f'Could not clean up temporary socket source {clone.get_path_name()}')
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            if cleanup_errors:
                active_error = sys.exception()
                raise RuntimeError(f'{active_error or "Socket save completed"}; {"; ".join(cleanup_errors)}') \
                    from active_error
        for entry in payload['entries']:
            previous = managed.get(entry['name'])
            if (previous and previous.get('created') and not entry['enabled']
                    and not socket_transforms_equal(previous['last'], entry['baseline'])):
                warn(f'{entry["name"]}: restored donor placement; the baseline mesh-only override is retained '
                     'because ZoneKit exposes no socket removal API.')
        for entry, socket, _before in added:
            if mesh.find_socket(entry['name']) != socket or socket.get_outer() != mesh:
                raise RuntimeError(f'Socket ownership changed after temporary-source cleanup: {entry["name"]}')
        self.count('socket meshes saved')
        log(f'  applied {len(changes)} socket changes to {payload["mesh"]}')

    @staticmethod
    def same_raw_animation(asset, original):
        library = unreal.AnimationLibrary
        if abs(asset.get_play_length() - original.get_play_length()) > 1e-6:
            return False
        frames = library.get_num_frames(asset)
        if (frames != library.get_num_frames(original)
                or library.get_animation_interpolation_type(asset) != library.get_animation_interpolation_type(original)):
            return False
        names = library.get_animation_track_names(asset)
        if set(names) != set(library.get_animation_track_names(original)):
            return False
        if not names:
            raise RuntimeError(f'No raw animation tracks on {asset.get_path_name()}')
        if frames < 1:
            raise RuntimeError(f'No animation intervals on {asset.get_path_name()}')
        options = raw_pose_options()
        for frame in range(frames + 1):
            time = asset.get_play_length() * frame / frames
            ours = unreal.AnimPoseExtensions.get_anim_pose_at_time(asset, time, options)
            theirs = unreal.AnimPoseExtensions.get_anim_pose_at_time(original, time, options)
            for name in names:
                a = unreal.AnimPoseExtensions.get_bone_pose(ours, name, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(theirs, name, unreal.AnimPoseSpaces.LOCAL)
                if not transforms_equal(a, b):
                    return False
        return True

    def sync_additive_idle(self, source, target):
        """The collection plays *_idle*_add, not the nonadditive FBX reference clip."""
        if source.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE:
            raise RuntimeError(f'Expected a nonadditive idle: {source.get_path_name()}')
        if target.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE:
            raise RuntimeError(f'Expected a local additive idle: {target.get_path_name()}')
        frames = unreal.AnimationLibrary.get_num_frames(target) + 1
        if frames < 2:
            raise RuntimeError(f'Cannot resample an idle with fewer than two keys: {target.get_path_name()}')
        names = unreal.AnimationLibrary.get_animation_track_names(source)
        if not names:
            raise RuntimeError(f'No raw idle tracks on {source.get_path_name()}')
        options = raw_pose_options()
        tracks = {name: ([], [], []) for name in names}
        unchanged = set(unreal.AnimationLibrary.get_animation_track_names(target)) == set(names)
        for frame in range(frames):
            time = source.get_play_length() * frame / (frames - 1)
            pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(source, time, options)
            current = unreal.AnimPoseExtensions.get_anim_pose_at_time(
                target, target.get_play_length() * frame / (frames - 1), options) if unchanged else None
            for name, (positions, rotations, scales) in tracks.items():
                transform = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)
                positions.append(transform.translation)
                rotations.append(transform.rotation)
                scales.append(transform.scale3d)
                if unchanged:
                    actual = unreal.AnimPoseExtensions.get_bone_pose(current, name, unreal.AnimPoseSpaces.LOCAL)
                    unchanged = transforms_equal(transform, actual)
        if unchanged:
            return
        controller = target.controller
        controller.open_bracket('Sync exported additive idle', False)
        try:
            controller.remove_all_bone_tracks(False)
            if unreal.AnimationLibrary.get_animation_track_names(target):
                raise RuntimeError(f'Could not clear idle tracks on {target.get_path_name()}')
            for name, values in tracks.items():
                if not controller.add_bone_curve(name, False) or not controller.set_bone_track_keys(
                        name, *values, should_transact=False):
                    raise RuntimeError(f'Could not write {name} on {target.get_path_name()}')
        finally:
            controller.close_bracket(False)
        if not self.library.save_loaded_asset(target):
            raise RuntimeError(f'Could not save additive idle {target.get_path_name()}')
        log(f'  additive idle {target.get_name()} <- {source.get_name()} (kept timing, curves and additive base)')
        self.count('additive idles synced')

    def update_additive_playback(self):
        assets = self.mod_assets()['sequence']
        exported = {
            f'{folder}/{name}'.lower()
            for _path, folder, name in self.plan['player_animations']
        }
        template_weapon = self.manifest.get('template_weapon')
        mount = self.manifest['game_root'].rstrip('/')
        weapon = self.manifest['weapon']
        if template_weapon:
            for package in sorted(exported):
                if package not in assets:
                    warn(f'Cannot verify additive settings: exported animation not found in registry: {package}')
                    continue
                asset = self.library.load_asset(assets[package])
                if asset.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE:
                    continue
                original_path = template_sequence_package(assets[package], weapon, template_weapon, mount)
                if not self.library.does_asset_exist(original_path):
                    continue
                original = self.library.load_asset(original_path)
                if original.get_editor_property('additive_anim_type') == unreal.AdditiveAnimationType.AAT_NONE:
                    continue
                settings = {key: original.get_editor_property(key) for key in self.ADDITIVE_SETTINGS}
                reference = settings['ref_pose_seq']
                if reference is not None:
                    replacement = find_replacement(self.package_of(reference), weapon, mount, assets)
                    if replacement is not None:
                        settings['ref_pose_seq'] = self.library.load_asset(replacement)
                        if settings['ref_pose_seq'] is None:
                            raise RuntimeError(f'Cannot load additive reference: {replacement}')
                self.restore_additive_settings(asset, settings)
        for package in sorted(exported):
            if package.endswith(('_idle', '_idle_aim')):
                companion = package.rsplit('/', 1)[-1] + '_add'
                matches = [path for path in assets.values()
                           if path.rsplit('/', 1)[-1].lower() == companion]
                if len(matches) > 1:
                    raise RuntimeError(f'Ambiguous additive idle for {package}: {matches}')
                if matches and matches[0].lower() not in exported:
                    self.sync_additive_idle(self.library.load_asset(assets[package]),
                                            self.library.load_asset(matches[0]))

        if not template_weapon:
            warn('Regenerate the import script to preserve unchanged overlays\' original additive references.')
            return
        for package in sorted(assets.values()):
            if package.lower() in exported or '/animations/player/' not in package.lower():
                continue
            if not re.search(rf'(?<![a-z0-9]){re.escape(weapon)}(?![a-z0-9])', package, re.IGNORECASE):
                continue
            asset = self.library.load_asset(package)
            if asset.get_editor_property('additive_anim_type') == unreal.AdditiveAnimationType.AAT_NONE:
                continue
            reference = asset.get_editor_property('ref_pose_seq')
            if reference is None or not self.package_of(reference).startswith(mount + '/'):
                continue
            original_path = template_sequence_package(package, weapon, template_weapon, mount)
            if not self.library.does_asset_exist(original_path):
                warn(f'Cannot verify additive reference for {package}: missing template {original_path}')
                continue
            original = self.library.load_asset(original_path)
            settings = ('additive_anim_type', 'ref_pose_type', 'ref_frame_index')
            if any(asset.get_editor_property(key) != original.get_editor_property(key) for key in settings):
                log(f'  kept custom additive settings on {asset.get_name()}')
                continue
            if not self.same_raw_animation(asset, original):
                log(f'  kept custom additive reference on {asset.get_name()} (raw tracks differ from template)')
                continue
            original_reference = original.get_editor_property('ref_pose_seq')
            if original_reference is None:
                raise RuntimeError(f'Template additive clip has no reference: {original_path}')
            asset.set_editor_property('ref_pose_seq', original_reference)
            if not self.library.save_loaded_asset(asset):
                raise RuntimeError(f'Could not save additive reference on {package}')
            log(f'  unchanged overlay {asset.get_name()}: restored {original_reference.get_path_name()}')
            self.count('additive references restored')

    def mod_assets(self):
        """Animation assets of the mod: {kind: {lower package: package}}, kind is sequence/montage/collection."""
        mount = self.manifest['game_root'].rstrip('/')
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        found = {'sequence': {}, 'montage': {}, 'collection': {}}
        for data in registry.get_assets_by_path(f'{mount}/_STALKER2/Animations', recursive=True):
            class_path = getattr(data, 'asset_class_path', None)
            class_name = str(class_path.asset_name if class_path else data.get_editor_property('asset_class'))
            package = str(data.get_editor_property('package_name'))
            if class_name == 'AnimSequence':
                found['sequence'][package.lower()] = package
            elif class_name == 'AnimMontage':
                found['montage'][package.lower()] = package
            elif 'AnimCollection' in class_name:
                found['collection'][package.lower()] = package
        return found

    @staticmethod
    def package_of(asset):
        return str(asset.get_path_name()).split('.')[0]

    def sequence_length(self, sequence):
        for getter in (lambda: unreal.AnimationLibrary.get_sequence_length(sequence),
                       lambda: sequence.get_play_length(),
                       lambda: sequence.get_editor_property('sequence_length')):
            try:
                return float(getter())
            except Exception:
                continue
        return None

    def replace_reference(self, asset, kind, assets, report):
        """The mod's replacement for a template-weapon sequence/montage, or None to leave it alone."""
        if asset is None:
            return None
        package = self.package_of(asset)
        mount = self.manifest['game_root'].rstrip('/')
        if package.lower().startswith(mount.lower() + '/'):
            return None
        package_new = find_replacement(package, self.manifest['weapon'], mount, assets[kind])
        if package_new is None:
            parts = package.strip('/').split('/')
            name = parts[-1].lower()
            if any(len(folder) > 2 and folder.lower() != 'common' and f'_{folder.lower()}_' in name
                   for folder in parts[1:-1]):
                report['unmatched'].append(package)
            return None
        return self.library.load_asset(package_new)

    def scale_timing(self, items, ratio, report):
        """Scale the link time of notifies / sections (best effort; the properties are not always exposed)."""
        for item in items:
            try:
                item.set_editor_property('link_value', float(item.get_editor_property('link_value')) * ratio)
            except Exception:
                report['timing_skipped'] = True

    def repoint_montage(self, montage, assets, report):
        try:
            tracks = list(montage.get_editor_property('slot_anim_tracks'))
        except Exception:
            self.report_manual_montage(montage, assets, report)
            return False
        changed = False
        ratio = None
        for track_index, track in enumerate(tracks):
            anim_track = track.get_editor_property('anim_track')
            segments = list(anim_track.get_editor_property('anim_segments'))
            for segment_index, segment in enumerate(segments):
                old = segment.get_editor_property('anim_reference')
                new = self.replace_reference(old, 'sequence', assets, report)
                if new is None:
                    continue
                new_length = self.sequence_length(new)
                start = float(segment.get_editor_property('anim_start_time'))
                old_length = float(segment.get_editor_property('anim_end_time')) - start
                segment.set_editor_property('anim_reference', new)
                if new_length:
                    segment.set_editor_property('anim_end_time', new_length)
                    if segment_index == 0 and track_index == 0 and old_length > 0:
                        ratio = (new_length - start) / old_length
                segments[segment_index] = segment
                report['lines'].append(f'{montage.get_name()}: {old.get_name()} -> {new.get_name()}')
                changed = True
            anim_track.set_editor_property('anim_segments', segments)
            track.set_editor_property('anim_track', anim_track)
            tracks[track_index] = track
        if not changed:
            return False
        montage.set_editor_property('slot_anim_tracks', tracks)
        if ratio and abs(ratio - 1) > 0.001:
            try:
                montage.set_editor_property(
                    'sequence_length', float(montage.get_editor_property('sequence_length')) * ratio)
            except Exception:
                report['timing_skipped'] = True
            for name in ('composite_sections', 'notifies'):
                try:
                    self.scale_timing(list(montage.get_editor_property(name)), ratio, report)
                except Exception:
                    report['timing_skipped'] = True
        skeleton = self.montage_skeleton(montage)
        if skeleton is not None:
            try:
                montage.set_editor_property('skeleton', skeleton)
            except Exception:
                report['skeleton_skipped'] = True
        self.library.save_loaded_asset(montage)
        return True

    def report_manual_montage(self, montage, assets, report):
        """Montage slot data is not exposed to Python: say what the montage plays and what it should play."""
        try:
            current = montage.get_first_anim_reference()
        except Exception:
            current = None
        if current is None:
            return
        package = self.package_of(current)
        if package.lower().startswith(self.manifest['game_root'].rstrip('/').lower() + '/'):
            return
        new = self.replace_reference(current, 'sequence', assets, report)
        report['inaccessible'].append(
            f'{montage.get_name()}: plays {current.get_name()}'
            + (f', should play {new.get_name()}' if new is not None else ', no matching new animation'))

    def sync_attachment_notifies(self, montage, report):
        """Remap the donor item spawned/attached by montage notifies, not just collection keys."""
        magazines = self.manifest.get('magazines') or []
        attachments = self.manifest.get('attachments') or []
        if not magazines and not attachments:
            return False
        mount = self.manifest['game_root'].rstrip('/')
        if not re.fullmatch(r'/[A-Za-z0-9_]+', mount) or mount.lower() in ('/game', '/engine') or not (
                self.package_of(montage).lower().startswith(mount.lower() + '/')):
            raise RuntimeError('Attachment notifies must belong to a mod-owned montage.')
        name = montage.get_name()
        changes = []
        try:
            for event in unreal.AnimationLibrary.get_animation_notify_events(montage):
                notify = event.get_editor_property('notify')
                if notify is None or notify.get_class().get_name() != 'AnimNotify_AttachItem':
                    continue
                if self.package_of(notify) != self.package_of(montage):
                    raise RuntimeError('Attachment notify is not owned by this montage.')
                old = notify.get_editor_property('binded_attach_sid')
                sid = str(old)
                new = (new_magazine_sid(sid, magazines) if MAGAZINE_SID.fullmatch(sid)
                       else new_attachment_sid(sid, attachments))
                if new and new != sid:
                    changes.append((notify, old, type(old)(new)))
        except Exception as error:
            warn(f'{name}: cannot plan attachment notify SIDs ({error}); set BindedAttachSid by hand.')
            return False
        if not changes:
            return False
        try:
            for notify, old, new in changes:
                notify.set_editor_property('binded_attach_sid', new)
            if any(str(notify.get_editor_property('binded_attach_sid')) != str(new)
                   for notify, old, new in changes):
                raise RuntimeError('attachment notify SIDs did not read back correctly')
            if not self.library.save_loaded_asset(montage):
                raise RuntimeError('could not save attachment notify SIDs')
        except Exception as error:
            for notify, old, new in changes:
                notify.set_editor_property('binded_attach_sid', old)
            warn(f'{name}: attachment notify changes were restored ({error}); set BindedAttachSid by hand.')
            return False
        for notify, old, new in changes:
            report['lines'].append(f'{name}: notify BindedAttachSid {old} -> {new}')
        return True

    def montage_skeleton(self, montage):
        key = 'weapon_skeleton' if '/weapons/' in self.package_of(montage).lower() else 'player_skeleton'
        try:
            return self.skeleton(self.manifest[key])
        except RuntimeError:
            return None

    def repoint_value(self, owner, name, assets, report, depth=0):
        """Walk a property tree, swapping template montage/sequence references for the mod's. True if changed."""
        try:
            value = owner.get_editor_property(name)
        except Exception:
            return False
        if type(value).__name__ in ('Name', 'str'):
            new_text = swap_magazine_sids(str(value), self.manifest.get('magazines'), report['lines'], name)
            if new_text != str(value):
                owner.set_editor_property(name, new_text)
                return True
            return False
        if type(value).__name__ in ('SoftObjectPath', 'SoftObjectPtr', 'SoftObjectReference'):
            path = str(value).split("'")[-2] if "'" in str(value) else str(value)
            target = self.library.load_asset(path.split('.')[0]) if path.startswith('/') else None
            if isinstance(target, (unreal.AnimMontage, unreal.AnimSequence)):
                kind = 'montage' if isinstance(target, unreal.AnimMontage) else 'sequence'
                new = self.replace_reference(target, kind, assets, report)
                if new is not None:
                    owner.set_editor_property(name, new)
                    report['lines'].append(f'collection {name}: {target.get_name()} -> {new.get_name()}')
                    return True
            return False
        if isinstance(value, unreal.AnimMontage) or isinstance(value, unreal.AnimSequence):
            kind = 'montage' if isinstance(value, unreal.AnimMontage) else 'sequence'
            new = self.replace_reference(value, kind, assets, report)
            if new is None:
                return False
            owner.set_editor_property(name, new)
            report['lines'].append(f'collection {name}: {value.get_name()} -> {new.get_name()}')
            return True
        if depth > 6:
            return False
        changed = False
        struct_base = getattr(unreal, 'StructBase', None)
        if isinstance(value, (list, tuple)) or type(value).__name__ == 'Array':
            items = list(value)
            for index, item in enumerate(items):
                if type(item).__name__ in ('Name', 'str'):
                    swapped = swap_magazine_sids(str(item), self.manifest.get('magazines'), report['lines'], name)
                    if swapped != str(item):
                        items[index] = swapped
                        changed = True
                elif struct_base is not None and isinstance(item, struct_base):
                    if self.repoint_struct(item, assets, report, depth + 1):
                        items[index] = item
                        changed = True
            if changed:
                owner.set_editor_property(name, items)
        elif struct_base is not None and isinstance(value, struct_base):
            if self.repoint_struct(value, assets, report, depth + 1):
                owner.set_editor_property(name, value)
                changed = True
        return changed

    def repoint_struct(self, struct, assets, report, depth):
        changed = False
        for name in dir(struct):
            if not name.startswith('_'):
                changed = self.repoint_value(struct, name, assets, report, depth) or changed
        return changed

    def repoint_text(self, text, assets, report, label):
        """Swap every template montage/sequence path in exported struct text for the mod's replacement."""
        def swap(match):
            package, name = match.group(1), match.group(2)
            kind = 'montage' if name.lower().startswith('mg_') else 'sequence'
            mount = self.manifest['game_root'].rstrip('/')
            new = find_replacement(package, self.manifest['weapon'], mount, assets[kind])
            if new is None:
                parts = package.strip('/').split('/')
                if any(len(f) > 2 and f.lower() != 'common' and f'_{f.lower()}_' in name.lower() for f in parts[1:-1]):
                    report['unmatched'].append(package)
                return match.group(0)
            new_name = new.rsplit('/', 1)[-1]
            report['lines'].append(f'collection {label}: {name.split(".")[0]} -> {new_name}')
            return f'{new}.{new_name}'
        text = re.sub(r"(/Game/[A-Za-z0-9_\-/]+)\.([A-Za-z0-9_\-]+)", swap, text)
        return swap_magazine_sids(text, self.manifest.get('magazines'), report['lines'], label)

    def swap_magazines(self, value, report, label, depth=0):
        """Recursively replace template magazine SIDs in names, arrays, maps (keys too) and structs.

        Returns (value, changed)."""
        magazines = self.manifest.get('magazines')
        if not magazines or depth > 8:
            return value, False
        kind = type(value).__name__
        if kind in ('Name', 'str', 'Text'):
            old = str(value)
            new = swap_magazine_sids(old, magazines, report['lines'], label)
            if new == old:
                return value, False
            return (unreal.Name(new) if kind == 'Name' else new), True
        if isinstance(value, dict) or kind == 'Map':
            result, changed = {}, False
            for key, item in value.items():
                new_key, key_changed = self.swap_magazines(key, report, label, depth + 1)
                new_item, item_changed = self.swap_magazines(item, report, label, depth + 1)
                result[new_key] = new_item
                changed = changed or key_changed or item_changed
            return (result if changed else value), changed
        if isinstance(value, (list, tuple)) or kind == 'Array':
            items, changed = [], False
            for item in value:
                new_item, item_changed = self.swap_magazines(item, report, label, depth + 1)
                items.append(new_item)
                changed = changed or item_changed
            return (items if changed else value), changed
        struct_base = getattr(unreal, 'StructBase', None)
        if struct_base is not None and isinstance(value, struct_base):
            changed = False
            for name in dir(value):
                if name.startswith('_'):
                    continue
                try:
                    inner = value.get_editor_property(name)
                except Exception:
                    continue
                new_inner, inner_changed = self.swap_magazines(inner, report, f'{label}.{name}', depth + 1)
                if inner_changed:
                    value.set_editor_property(name, new_inner)
                    changed = True
            return value, changed
        return value, False

    def repoint_collection(self, collection, assets, report):
        changed = False
        for name in dir(collection):
            if name.startswith('_') or name in ('cast', 'static_class', 'get_class', 'internal_animations'):
                continue
            try:
                value = collection.get_editor_property(name)
            except Exception:
                continue
            try:
                value, swapped = self.swap_magazines(value, report, name)
                if swapped:
                    collection.set_editor_property(name, value)
                    changed = True
                    value = collection.get_editor_property(name)
            except Exception as error:
                warn(f'Could not replace magazine SIDs in {name} of the anim collection ({error}).')
            if hasattr(value, 'export_text') and hasattr(value, 'import_text'):
                try:
                    text = value.export_text()
                    new_text = self.repoint_text(text, assets, report, name)
                    if new_text != text:
                        value.import_text(new_text)
                        collection.set_editor_property(name, value)
                        changed = True
                except Exception as error:
                    warn(f'Could not edit {name} of the anim collection as text ({error}); trying property by property.')
                    changed = self.repoint_value(collection, name, assets, report) or changed
            else:
                changed = self.repoint_value(collection, name, assets, report) or changed
        if changed:
            self.library.save_loaded_asset(collection)
        return changed

    def sync_collection_sids(self, collection, report):
        """Replace donor SID keys, preserving values and existing configured entries."""
        magazines = self.manifest.get('magazines') or []
        attachments = self.manifest.get('attachments') or []
        if not magazines and not attachments:
            return False
        name = collection.get_name()
        try:
            original = collection.get_editor_property('internal_animations').copy()
            internal = original.copy()
        except Exception as error:
            warn(f'{name}: cannot read internal_animations ({error}); add magazine/attachment SIDs by hand.')
            return False
        replaced = {}
        for field in COLLECTION_SID_MAPS:
            try:
                entries = dict(internal.get_editor_property(field))
                keys = list(entries.keys())
            except Exception as error:
                warn(f'{name}: cannot read {field} ({error}); add magazine/attachment SIDs by hand.')
                continue
            try:
                plan = planned_collection_sids(
                    keys, magazines, attachments if field == 'attaching_by_sid' else None)
            except ValueError as error:
                warn(f'{name}: cannot replace {field} SIDs ({error}); set them by hand.')
                return False
            if field == 'attaching_by_sid':
                present = {str(key) for key in keys} | set(plan.values())
                for item in attachments:
                    if item.get('kind') == 'silencer' and item.get('sid') not in present:
                        warn(f'{name}: the template has no silencer attach animation to copy for {item["sid"]}; '
                             'attaching it from the quick menu will not animate.')
            if not plan:
                continue
            by_name = {str(key): key for key in keys}
            try:
                for source, sid in plan.items():
                    key = by_name[source]
                    target = type(key)(sid)
                    if target not in entries:
                        entries[target] = entries[key]
                    del entries[key]
                internal.set_editor_property(field, entries)
            except Exception as error:
                warn(f'{name}: cannot replace {field} SID keys ({error}); changes were not applied.')
                return False
            replaced[field] = plan
        if not replaced:
            return False
        try:
            collection.modify()
            collection.set_editor_property('internal_animations', internal)
            if not self.collection_sids_match(collection, original, replaced):
                raise RuntimeError('magazine/attachment SID entries did not read back correctly')
            if not self.library.save_loaded_asset(collection):
                raise RuntimeError('could not save the replaced magazine/attachment SID entries')
        except Exception as error:
            collection.set_editor_property('internal_animations', original)
            warn(f'{name}: magazine/attachment SID changes were restored ({error}); set them by hand.')
            return False
        for field, plan in replaced.items():
            for source, sid in plan.items():
                report['lines'].append(f'collection {field}: {source} -> {sid} (replaced)')
        return True

    @staticmethod
    def collection_sids_match(collection, original, replaced):
        """Check exact replacement keys/values, including preservation of existing targets."""
        def text(value):
            return value.export_text() if hasattr(value, 'export_text') else repr(value)

        internal = collection.get_editor_property('internal_animations')
        for field in COLLECTION_SID_MAPS:
            try:
                old_map = original.get_editor_property(field)
            except Exception:
                if field in replaced:
                    return False
                continue
            before = {str(key): text(value) for key, value in old_map.items()}
            after = {str(key): text(value) for key, value in internal.get_editor_property(field).items()}
            expected = dict(before)
            for source, sid in replaced.get(field, {}).items():
                value = expected.pop(source)
                expected.setdefault(sid, value)
            if after != expected:
                return False
        return True

    def update_montages(self):
        """After the animations are imported, point the weapon's montages and anim collection at them."""
        weapon = self.manifest['weapon'].lower()
        assets = self.mod_assets()
        report = {'lines': [], 'unmatched': [], 'inaccessible': []}

        def ours(package):
            return '/' + weapon + '/' in package.lower() or f'/{weapon}_' in package.lower() or f'_{weapon}_' in package.lower()

        updated = 0
        collections_seen = 0
        for package in sorted(assets['montage'].values()):
            if not ours(package):
                continue
            montage = self.library.load_asset(package)
            if montage is None:
                continue
            changed = self.repoint_montage(montage, assets, report)
            if self.sync_attachment_notifies(montage, report) or changed:
                updated += 1
        for package in sorted(assets['collection'].values()):
            if not ours(package):
                continue
            collection = self.library.load_asset(package)
            if collection is None:
                continue
            collections_seen += 1
            changed = self.repoint_collection(collection, assets, report)
            if self.sync_collection_sids(collection, report) or changed:
                updated += 1
        for line in report['lines']:
            log('  ' + line)
        if self.manifest.get('magazines') and not collections_seen:
            warn('No weapon anim collection was found; regenerate the import script with Export All '
                 f'({", ".join(m["sid"] for m in self.manifest["magazines"])}).')
        if report['inaccessible']:
            warn('Montage slot data cannot be edited from this editor\'s Python, so these montages still '
                 'play template animations. Rename the template assets with the Arsenal ZoneKit setup script '
                 '(Set Up panel) so the montages reference your weapon\'s animations. These montages need it:')
            for line in report['inaccessible']:
                warn('  ' + line)
        for package in sorted(set(report['unmatched'])):
            warn(f'No animation for {package.rsplit("/", 1)[-1]} was imported; the template animation is used.')
        if report.get('timing_skipped'):
            warn('Some montage notify/section timings could not be rescaled; check montages whose length changed.')
        if report.get('skeleton_skipped'):
            warn('Could not change the skeleton of some montages; set it by hand if they report a mismatch.')
        self.counts['montages/collections updated'] = updated

    def text_tool_asset(self):
        """The mod's localisation text asset (created if the mod has none)."""
        mount = self.manifest['game_root'].rstrip('/')
        if not re.fullmatch(r'/[A-Za-z0-9_]+', mount) or mount.lower() in ('/game', '/engine'):
            raise RuntimeError(f'localisation requires a mod-owned content mount, not {mount!r}')
        mod = mount.strip('/')
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        found = []
        for data in registry.get_assets_by_path(mount, recursive=True):
            if str(data.asset_class_path.asset_name) == 'LocalizationModTextToolAsset':
                found.append(data)
        for data in found:
            if str(data.asset_name).lower() == f'{mod}TextToolAsset'.lower():
                return data.get_asset()
        if found:
            if len(found) != 1:
                raise RuntimeError('multiple localisation text assets found; cannot choose safely: '
                                   + ', '.join(str(data.package_name) for data in found))
            return found[0].get_asset()
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset_class = getattr(unreal, 'LocalizationModTextToolAsset', None)
        for path in ('/Script/ModKitEditor.LocalizationModTextToolAsset',
                     '/Script/ModKit.LocalizationModTextToolAsset'):
            if asset_class is None:
                asset_class = unreal.find_object(None, path) or unreal.load_object(None, path)
        if asset_class is None:
            names = sorted(n for n in dir(unreal) if 'TextTool' in n or 'Localiz' in n)
            raise RuntimeError('the text tool class is not exposed to Python; unreal attributes matching '
                               f'TextTool/Localiz: {names}')
        asset = tools.create_asset(f'{mod}TextToolAsset', mount, asset_class, None)
        if asset is None:
            raise RuntimeError('could not create the localisation text asset')
        return asset

    @staticmethod
    def texts_property(asset):
        """Python name of the asset's array of localised texts (the exposed name is not known in advance)."""
        own = sorted(set(dir(asset)) - set(dir(unreal.Object)))
        own = [n for n in own if not n.startswith('_')]
        candidates = ['LocalizedTexts', 'localized_texts', 'localised_texts', 'texts', 'localized_text', 'entries']
        candidates += [n for n in own if 'text' in n.lower() and n not in candidates]
        for name in candidates:
            try:
                asset.get_editor_property(name)
                return name
            except Exception:
                continue
        raise RuntimeError(f'no readable text array property on the text asset; its Python attributes are: {own}')

    @staticmethod
    def localization_language(key):
        member = re.split(r'(?:E?LocalizationLanguage)(?:::|\.)', str(key))[-1]
        member = member.strip('<> ').split(':', 1)[0].strip()
        if member.isupper() or '_' in member:
            member = ''.join(word.title() for word in member.split('_'))
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', member):
            raise ValueError(f'invalid localisation language: {key!r}')
        return member

    @classmethod
    def localization_snapshot(cls, texts):
        result = {}
        for item in texts:
            sid = str(item.get_editor_property('SID'))
            languages = {}
            for key, text in item.get_editor_property('LanguagesToLocalizedStrings').items():
                member = cls.localization_language(key)
                if member in languages:
                    raise ValueError(f'duplicate localisation language for {sid}: {member}')
                languages[member] = str(text)
            if not sid and all(not text.strip() or text == 'UNLOCALIZED MOD STRING'
                               for text in languages.values()):
                # ZoneKit replaces blank-row translations with this sentinel on array assignment.
                continue
            if not sid or sid in result:
                raise ValueError(f'empty or duplicate localisation SID in asset: {sid!r}')
            result[sid] = {'languages': languages, 'text': item.export_text()}
        return result

    @staticmethod
    def localization_struct_text(sid, languages):
        def escape(text):
            return (text.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '\\r')
                    .replace('\n', '\\n').replace('\t', '\\t'))

        values = ','.join(f'({language},"{escape(text)}")' for language, text in languages.items())
        return f'(SID="{escape(sid)}",LanguagesToLocalizedStrings=({values}))'

    @classmethod
    def validate_localization(cls, texts, before, source):
        after = cls.localization_snapshot(texts)
        if set(after) != set(before) | set(source):
            raise RuntimeError('localisation SID set differs from the planned update')
        for sid, original in before.items():
            if sid not in source and after[sid] != original:
                raise RuntimeError(f'unrelated localisation entry changed: {sid}')
        for sid, translations in source.items():
            expected = dict(before[sid]['languages']) if sid in before else {}
            expected.update(translations)
            if after[sid]['languages'] != expected:
                raise RuntimeError(f'localisation translations differ from the planned update: {sid}')

    def import_localization(self):
        """Upsert weapon and purchasable attachment text into the mod's localisation asset."""
        entries = self.manifest.get('localization') or []
        if not entries:
            log('No weapon or attachment name or description to import.')
            return
        log('Weapon and attachment localisation entries (SID and language values for copy/paste):')
        for entry in entries:
            log(entry['SID'])
            for language, text in entry['LanguagesToLocalizedStrings'].items():
                log(f'  {language}')
                log(str(text).replace('\r', '\\r').replace('\n', '\\n'))
        try:
            source = {}
            for entry in entries:
                sid = entry['SID']
                if not isinstance(sid, str) or not re.fullmatch(r'sid_[A-Za-z0-9_]+', sid) or sid in source:
                    raise ValueError(f'invalid or duplicate localisation SID: {sid!r}')
                languages = {}
                for key, text in entry['LanguagesToLocalizedStrings'].items():
                    member = self.localization_language(key)
                    if member in languages or not isinstance(text, str) or not text.strip():
                        raise ValueError(f'invalid or duplicate translation for {sid}: {key}')
                    languages[member] = text
                if not languages:
                    raise ValueError(f'no translations supplied for {sid}')
                source[sid] = languages
            asset = self.text_tool_asset()
            prop = self.texts_property(asset)
            original = asset.get_editor_property(prop)
            before = self.localization_snapshot(original)
            current = original.copy()
            indices = {str(item.get_editor_property('SID')): index for index, item in enumerate(current)
                       if str(item.get_editor_property('SID'))}
            empty_indices = [index for index, item in enumerate(current)
                             if not str(item.get_editor_property('SID'))]
            changed = 0
            for sid, translations in source.items():
                merged = dict(before[sid]['languages']) if sid in before else {}
                merged.update(translations)
                if sid in before and merged == before[sid]['languages']:
                    continue
                if sid in before:
                    index = indices[sid]
                elif empty_indices:
                    index = empty_indices.pop(0)
                else:
                    index = len(current)
                    # Native TArray resizing constructs even unexposed structs, without a template entry.
                    current.resize(index + 1)
                item = current[index]
                if not item.import_text(self.localization_struct_text(sid, merged)):
                    raise RuntimeError(f'ZoneKit rejected localisation text for {sid}')
                current[index] = item
                changed += 1
            self.validate_localization(current, before, source)
            if not changed:
                log(f'  localisation unchanged ({len(source)} entries); no save needed')
                return
            asset.modify()
            try:
                asset.set_editor_property(prop, current)
                self.validate_localization(asset.get_editor_property(prop), before, source)
                if not self.library.save_loaded_asset(asset):
                    raise RuntimeError('could not save the localisation text asset')
            except Exception as error:
                try:
                    asset.set_editor_property(prop, original)
                except Exception as restore_error:
                    raise RuntimeError(f'{error}; could not restore the original localisation entries: '
                                       f'{restore_error}') from error
                raise
            self.counts['text entries'] = changed
            log(f'  saved localisation: {changed} entries updated, other entries and translations preserved')
        except Exception as error:
            warn(f'Could not write the localisation text asset from Python ({error}). Add the entries from '
                 'Localization/*-localization.json in the export folder with the Mod Editor text tool instead.')

    def mod_content_folder(self):
        mod = self.manifest['game_root'].strip('/').split('/')[0]
        candidates = [os.path.join(unreal.Paths.project_dir(), 'Mods', mod, 'Content'),
                      unreal.Paths.convert_relative_path_to_full(f'../../Mods/{mod}/Content')]
        for path in candidates:
            if os.path.isdir(path):
                return os.path.normpath(path)
        return None

    def copy_game_data(self):
        """Copy the exported GameLite folder (the CFG files) into the mod's Content folder."""
        source = os.path.join(self.base_dir, 'GameLite')
        distribution = self.manifest.get('distribution')
        if not os.path.isdir(source) and distribution is None:
            return
        target_root = self.mod_content_folder()
        if target_root is None:
            if distribution is not None:
                raise RuntimeError('Could not find the mod Content folder for combined distribution.')
            warn(f'Could not find the mod folder on disk; copy "{source}" into the mod\'s Content folder by hand.')
            return
        copied = 0
        mod = self.manifest['game_root'].strip('/').split('/')[0]
        if distribution is not None:
            if (distribution.get('mod') != mod
                    or distribution.get('weapon') != self.manifest['weapon']):
                raise RuntimeError('Distribution settings do not match the import weapon or mod.')
            if not DISTRIBUTION_SOURCE or not DISTRIBUTION_DEFAULTS:
                raise RuntimeError('Missing distribution composer; regenerate with Export All.')
            module = types.ModuleType('arsenal_distribution_compose')
            exec(compile(DISTRIBUTION_SOURCE, 'arsenal_distribution_compose', 'exec'), module.__dict__)
            count = module.update_mod(target_root, distribution, DISTRIBUTION_DEFAULTS, warn=warn)
            log(f'  rebuilt combined distribution for {count} weapons')
            self.counts['distribution weapons'] = count
        mod_data = os.path.join(source, 'ModGameData')
        for folder, dirs, files in os.walk(source):
            if os.path.normcase(folder) == os.path.normcase(mod_data):
                for name in list(dirs):
                    if name != mod:
                        dirs.remove(name)
                        warn(f'Skipped CFG folder for another mod: {os.path.join(folder, name)}. '
                             f'Only ModGameData/{mod} belongs to this import; old exports must not '
                             'override the current weapon settings.')
            destination = os.path.join(target_root, 'GameLite', os.path.relpath(folder, source))
            os.makedirs(destination, exist_ok=True)
            for name in files:
                if distribution is not None:
                    relative = os.path.relpath(os.path.join(folder, name), source).replace('\\', '/')
                    if re.fullmatch(r'GameData/ItemGeneratorPrototypes/' + re.escape(mod)
                                    + r'_\w+Distribution\.cfg', relative) or re.fullmatch(
                                        r'ModGameData/' + re.escape(mod)
                                        + r'/ItemGeneratorPrototypes/\w+Distribution\.cfg', relative):
                        with open(os.path.join(folder, name), encoding='utf-8-sig') as handle:
                            if not handle.read().startswith('// Generated by Arsenal.'):
                                raise RuntimeError(f'Unexpected non-Arsenal distribution export: {relative}')
                        continue
                shutil.copy2(os.path.join(folder, name), os.path.join(destination, name))
                copied += 1
        log(f'  copied {copied} CFG files into {os.path.join(target_root, "GameLite")}')
        self.counts['CFG files copied'] = copied

    def tidy_empty_folders(self):
        """Delete folders the import left empty (e.g. a template weapon's folder after assets moved out)."""
        root = self.manifest['game_root'].rstrip('/')
        try:
            entries = self.library.list_assets(root, True, True)
        except Exception:
            return
        folders = {str(e).rstrip('/') for e in entries if '.' not in str(e).rsplit('/', 1)[-1]}
        removed = 0
        for folder in sorted(folders, key=len, reverse=True):
            if folder != root and self.library.does_directory_exist(folder) \
                    and not self.library.does_directory_have_assets(folder, True):
                if self.library.delete_directory(folder):
                    removed += 1
        if removed:
            log(f'  removed {removed} empty folders')

    def run(self):
        log(f'Arsenal import for "{self.manifest["weapon"]}"')
        validate_weapon_sockets(self.manifest)
        validate_world_mesh_sockets(self.manifest)
        self.ensure_setup()
        self.copy_game_data()
        self.import_skeletal_mesh()
        self.apply_weapon_sockets()
        self.import_textures()
        self.import_ui_images()
        self.import_materials()
        self.import_static_meshes()
        self.import_animations(self.plan['player_animations'], self.manifest['player_skeleton'])
        self.import_animations(self.plan['weapon_animations'], self.manifest['weapon_skeleton'])
        self.update_additive_playback()
        self.update_montages()
        self.import_localization()
        self.tidy_empty_folders()
        log('Arsenal import finished: ' + ', '.join(f'{count} {label}' for label, count in self.counts.items()))

    def ensure_setup(self):
        config = self.manifest.get('setup')
        if config is None:
            warn('This import manifest has no setup recovery data; regenerate it with Export All. '
                 'Run the ZoneKit setup script first.')
            return
        if not SETUP_SOURCE:
            raise RuntimeError('Setup recovery source is missing; regenerate the import script with Export All.')
        if ('/' + config['mod'] != self.manifest['game_root'].rstrip('/')
                or config['weapon'] != self.manifest['weapon']):
            raise RuntimeError('Setup recovery does not match the export weapon or mod.')
        module = types.ModuleType('arsenal_embedded_setup')
        exec(compile(SETUP_SOURCE, 'arsenal_embedded_setup', 'exec'), module.__dict__)
        module.warn = warn
        config = dict(config, export_dir=self.base_dir, dry_run=False, export=False)
        module.ensure_mod_assets(config)


def print_plan(manifest, base_dir):
    for key, items in build_plan(manifest, base_dir).items():
        print(f'{key}: {len(items)}')
        for item in items:
            print('   ', item)
    entries = manifest.get('localization') or []
    print(f'localization: {len(entries)}')
    for entry in entries:
        print('   ', entry['SID'])
    sockets = validate_weapon_sockets(manifest)
    if sockets is not None:
        print(f'weapon sockets: {len(sockets["entries"])} on {sockets["mesh"]}')
    world_sockets = validate_world_mesh_sockets(manifest)
    if world_sockets is not None:
        print(f'world magazine sockets: {len(world_sockets["entries"])} on {world_sockets["mesh"]}')


def _main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    manifest_path = find_manifest()
    with open(manifest_path, encoding='utf-8') as handle:
        manifest = json.load(handle)
    base_dir = os.path.dirname(manifest_path)
    if unreal is None or '--dry-run' in argv:
        print_plan(manifest, base_dir)
        return
    importer = Importer(manifest, base_dir, '--overwrite' in argv)
    if '--sockets-only' in argv:
        if validate_weapon_sockets(manifest) is None:
            raise RuntimeError('No Blender socket payload; regenerate the import script with socket markers.')
        importer.apply_weapon_sockets()
        log('Arsenal socket-only import finished.')
    else:
        importer.run()


def main(argv=None):
    WARNINGS.clear()
    try:
        _main(argv)
    except Exception as error:
        if unreal is not None:
            unreal.log_error(f'Arsenal import failed: {error}')
            notify_completion(error)
        raise
    else:
        if unreal is not None and '--dry-run' not in (sys.argv[1:] if argv is None else argv):
            notify_completion()


if unreal is not None or __name__ == '__main__':
    main()
