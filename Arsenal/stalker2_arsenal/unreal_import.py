"""Imports a Stalker 2 Arsenal export into the Unreal editor.

Run it once from the editor's Python console:

    py "<path to this file>"

Options (after the path): --overwrite re-imports assets that already exist.
Run with a normal Python (outside Unreal) to print the plan without importing anything.
"""
import json
import os
import copy
import re
import shutil
import sys

BAKED_MANIFEST = None

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


def warn(message):
    print('WARNING: ' + message)
    if unreal is not None:
        unreal.log_warning(message)


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


class Importer:
    PARAMETER_DEFAULTS = {'D': 'Diffuse_VT', 'N': 'Normal_VT', 'RMA': 'RMAE_VT'}

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

    def import_animations(self, files, skeleton_path):
        pending = [(path, folder, name) for path, folder, name in files if self.wanted(folder, name, replace=True)]
        if not pending:
            return
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
        self.import_tasks([self.task(path, folder, name, options) for path, folder, name in pending])

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
            if name.startswith('_') or name in ('cast', 'static_class', 'get_class'):
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

    def update_montages(self):
        """After the animations are imported, point the weapon's montages and anim collection at them."""
        weapon = self.manifest['weapon'].lower()
        assets = self.mod_assets()
        report = {'lines': [], 'unmatched': [], 'inaccessible': []}

        def ours(package):
            return '/' + weapon + '/' in package.lower() or f'/{weapon}_' in package.lower() or f'_{weapon}_' in package.lower()

        updated = 0
        for package in sorted(assets['montage'].values()):
            if not ours(package):
                continue
            montage = self.library.load_asset(package)
            if montage is not None and self.repoint_montage(montage, assets, report):
                updated += 1
        for package in sorted(assets['collection'].values()):
            if not ours(package):
                continue
            collection = self.library.load_asset(package)
            if collection is not None and self.repoint_collection(collection, assets, report):
                updated += 1
        for line in report['lines']:
            log('  ' + line)
        if self.manifest.get('magazines') and not any('_Mag' in line for line in report['lines']):
            warn('No magazine SIDs were replaced in the anim collection; set them by hand '
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
        mount = self.manifest['game_root']
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
        candidates = ['localized_texts', 'localised_texts', 'texts', 'localized_text', 'entries']
        candidates += [n for n in own if 'text' in n.lower() and n not in candidates]
        for name in candidates:
            try:
                asset.get_editor_property(name)
                return name
            except Exception:
                continue
        raise RuntimeError(f'no readable text array property on the text asset; its Python attributes are: {own}')

    @staticmethod
    @staticmethod
    def language_value(key):
        member = key.split('::')[-1]
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', member).upper()
        return getattr(unreal.ELocalizationLanguage, name)

    def import_localization(self):
        """Write the weapon's name and description into the mod's localisation text asset."""
        entries = self.manifest.get('localization') or []
        if not entries:
            log('No weapon name or description to import.')
            return
        try:
            asset = self.text_tool_asset()
            prop = self.texts_property(asset)
            current = list(asset.get_editor_property(prop))
            sids = [str(item.get_editor_property('sid')) for item in current]
            for entry in entries:
                struct = getattr(unreal, 'ModTextToolLocalizedText', None)
                if struct is not None:
                    item = struct()
                elif current:
                    item = copy.deepcopy(current[0])
                else:
                    raise RuntimeError('the ModTextToolLocalizedText struct is not exposed to Python')
                item.set_editor_property('sid', entry['SID'])
                item.set_editor_property('languages_to_localized_strings', {
                    self.language_value(key): text for key, text in entry['LanguagesToLocalizedStrings'].items()})
                if entry['SID'] in sids:
                    current[sids.index(entry['SID'])] = item
                else:
                    current.append(item)
                    sids.append(entry['SID'])
                log(f'  text {entry["SID"]}')
            asset.set_editor_property(prop, current)
            self.library.save_loaded_asset(asset)
            self.count('text entries')
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
        if not os.path.isdir(source):
            return
        target_root = self.mod_content_folder()
        if target_root is None:
            warn(f'Could not find the mod folder on disk; copy "{source}" into the mod\'s Content folder by hand.')
            return
        copied = 0
        for folder, _dirs, files in os.walk(source):
            destination = os.path.join(target_root, 'GameLite', os.path.relpath(folder, source))
            os.makedirs(destination, exist_ok=True)
            for name in files:
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
        self.copy_game_data()
        self.import_skeletal_mesh()
        self.import_textures()
        self.import_materials()
        self.import_static_meshes()
        self.import_animations(self.plan['player_animations'], self.manifest['player_skeleton'])
        self.import_animations(self.plan['weapon_animations'], self.manifest['weapon_skeleton'])
        self.update_montages()
        self.import_localization()
        self.tidy_empty_folders()
        log('Arsenal import finished: ' + ', '.join(f'{count} {label}' for label, count in self.counts.items()))


def print_plan(manifest, base_dir):
    for key, items in build_plan(manifest, base_dir).items():
        print(f'{key}: {len(items)}')
        for item in items:
            print('   ', item)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    manifest_path = find_manifest()
    with open(manifest_path, encoding='utf-8') as handle:
        manifest = json.load(handle)
    base_dir = os.path.dirname(manifest_path)
    if unreal is None or '--dry-run' in argv:
        print_plan(manifest, base_dir)
        return
    Importer(manifest, base_dir, '--overwrite' in argv).run()


if unreal is not None or __name__ == '__main__':
    main()
