import json
import bpy
import os

mappings_folder = os.path.dirname(os.path.realpath(__file__)) + '/mappings/'
anim_mappings_folder = os.path.dirname(os.path.realpath(__file__)) + '/animation_mappings/'

def user_mappings_folder(anim=False, create=False):
    folder = bpy.utils.user_resource(
        'DATAFILES',
        path=os.path.join('stalker2_arsenal', 'animation_mappings' if anim else 'mappings'),
        create=create,
    )
    if not folder:
        raise RuntimeError("Blender's user-data directory is unavailable.")
    return folder


def _mapping_names(anim=False):
    names = set()
    for folder in (
        anim_mappings_folder if anim else mappings_folder,
        user_mappings_folder(anim=anim),
    ):
        if os.path.isdir(folder):
            names.update(os.path.splitext(name)[0] for name in os.listdir(folder) if name.endswith('.json'))
    return sorted(names)


def get_anim_mappings(self, context):
    return [(name, name, name) for name in _mapping_names(anim=True)]


def get_mappings(self, context):
    names = _mapping_names()
    return [(name, name, name) for name in names]


def _mapping_filename(mapping):
    if not mapping or mapping in {'.', '..'} or any(char in mapping for char in '\\/:*?"<>|\0'):
        raise ValueError(f'Invalid mapping name: {mapping!r}')
    return mapping + '.json'


def is_bundled_mapping(mapping, anim=False):
    folder = anim_mappings_folder if anim else mappings_folder
    return os.path.isfile(os.path.join(folder, _mapping_filename(mapping)))


def get_mapping_file(mapping, anim = False):
    filename = _mapping_filename(mapping)
    if is_bundled_mapping(mapping, anim=anim):
        return os.path.join(anim_mappings_folder if anim else mappings_folder, filename)
    return os.path.join(user_mappings_folder(anim=anim), filename)

def has_mapping(mapping, anim = False):
    return os.path.exists(get_mapping_file(mapping, anim = anim))

def load_mapping(mapping, anim = False):
    file = get_mapping_file(mapping, anim = anim)
    with open(file) as json_file:
        data = json.load(json_file)
    return data

def save_mapping(mapping, data, anim = False):
    filename = _mapping_filename(mapping)
    if is_bundled_mapping(mapping, anim=anim):
        raise ValueError(f"Bundled mapping '{mapping}' is read-only. Save it under a different name.")
    file = os.path.join(user_mappings_folder(anim=anim, create=True), filename)
    with open(file, 'w') as outfile:
        json.dump(data, outfile, indent=2, separators=(',', ': '))

def remove_mapping(mapping, anim = False):
    if is_bundled_mapping(mapping, anim=anim):
        raise ValueError(f"Bundled mapping '{mapping}' is read-only and cannot be removed.")
    os.remove(get_mapping_file(mapping, anim = anim))

class BoneMapping(object):
    """Map bones names from different rigs"""

    def __init__(self, name, reverse, data=None):
        if data is None:
            data = load_mapping(name)
        mapping = {}
        for key, value in data:
            if reverse:
                mapping[value] = key
            else:
                mapping[key] = value
        self.mapping = mapping

    def get_name(self, name, safe = True):
        if name in self.mapping:
            return self.mapping[name]
        if safe:
            return name
        else:
            return None

    def rename_armature(self, armature):
        bpy.ops.object.mode_set(mode = 'EDIT')
        for bone in armature.edit_bones:
            bone.name = self.get_name(bone.name)
