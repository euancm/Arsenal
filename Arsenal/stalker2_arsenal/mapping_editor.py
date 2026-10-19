import bpy
import re
from . import preferences
import os

from . import map_bones, templates

oops = bpy.ops.object

def save_mapping_entries(ui):
    if ui.loading_mapping or not ui.active_mapping:
        return
    data = [
        [entry.bone_from, entry.bone_to]
        for entry in ui.mapping_entries
        if entry.bone_from and entry.bone_to
    ]
    map_bones.save_mapping(ui.active_mapping, data)


def update_mapping_entry(_self, context):
    ui = context.window_manager.arsenal_ui
    save_mapping_entries(ui)


class MappingEntry(bpy.types.PropertyGroup):
    bone_from: bpy.props.StringProperty(update=update_mapping_entry)
    bone_to: bpy.props.StringProperty(update=update_mapping_entry)

mappings = {
    'palm': r'(?i)(carpal|palm)',
    'head': r'(?i)(head)',
    'neck': r'(?i)(neck)',
    'pelvis': r'(?i)(pelvis|hip)',

    'thigh': r'(?i)(thigh|leg)',
    'shin': r'(?i)(shin|calf|leg)',
    'foot': r'(?i)(foot)',
    'toe': r'(?i)(toe|ball)',

    'thumb': r'(?i)(thumb)',
    'index': r'(?i)(index)',
    'middle': r'(?i)(mid)',
    'ring': r'(?i)(ring)',
    'pinky': r'(?i)(pinky)',

    'hand': '(?i)(hand)',
    'shoulder': '(?i)(shoulder|clavicle|collar)',
    'upperarm': '(?i)(upper_arm|upperarm|shldr)',
    'forearm': '(?i)(forearm|lowerarm)',

    'breast': '(?i)(breast|pectoral)',
    'spine': '(?i)(abdomen|chest|spine|pelvis|head|neck|hip)',
}

def get_bone_type(name):
    for type, exp in mappings.items():
        res = re.findall(exp, name)
        if res:
            return type
    return None

def get_bone_index(name):
    res = re.findall('(\d+)', name)
    if not res:
        return None
    return int(res[-1])

def get_bone_side(name):
    split_name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    tokens = re.findall(r'[a-z]+|\d+', split_name.lower())
    if 'l' in tokens:
        return 'l'
    if 'r' in tokens:
        return 'r'
    if 'left' in tokens:
        return 'l'
    if 'right' in tokens:
        return 'r'
    return None

def try_match_bone(name, names_to_search):
    return build_mapping_guesses([name], names_to_search).get(name)


def get_mapping_signature(name):
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    tokens = re.findall(r'[a-z]+|\d+', name.lower())
    while tokens and tokens[0] in {'jnt', 'joint', 'bone', 'bip', 'bip01', 'mixamorig'}:
        tokens.pop(0)

    side = get_bone_side(name)
    side_tokens = {'l'} if side == 'l' and 'l' in tokens else {'r'} if side == 'r' and 'r' in tokens else set()
    if not side_tokens and side == 'l' and 'left' in tokens:
        side_tokens = {'left'}
    elif not side_tokens and side == 'r' and 'right' in tokens:
        side_tokens = {'right'}
    tokens = [token for token in tokens if token not in side_tokens]
    token_set = set(tokens)

    finger_palm_indices = {'index': 1, 'middle': 2, 'mid': 2, 'ring': 3, 'pinky': 4}
    if 'meta' in token_set:
        for finger, palm_index in finger_palm_indices.items():
            if finger in token_set:
                return 'palm', side, palm_index, frozenset()

    if token_set.intersection({'thumb', 'index', 'middle', 'mid', 'ring', 'pinky'}):
        finger = next(type_name for type_name in ('thumb', 'index', 'middle', 'ring', 'pinky')
                      if type_name in token_set or (type_name == 'middle' and 'mid' in token_set))
        kind = finger
        allowed = {finger, 'hand', 'mid'}
    elif token_set.intersection({'forearm', 'lowerarm', 'fore', 'lower'}):
        kind = 'lowerarm'
        allowed = {'forearm', 'lowerarm', 'fore', 'lower', 'arm'}
    elif token_set.intersection({'upperarm', 'arm', 'shldr', 'bicep'}):
        kind = 'upperarm'
        allowed = {'upperarm', 'upper', 'arm', 'shldr', 'bicep'}
    elif token_set.intersection({'thigh', 'calf', 'leg'}):
        kind = 'thigh' if 'thigh' in token_set or 'up' in token_set else 'calf'
        allowed = {'thigh', 'calf', 'leg', 'up', 'lower'}
    elif token_set.intersection({'pelvis', 'hip', 'hips'}):
        kind = 'spine'
        allowed = {'pelvis', 'hip', 'hips', 'spine'}
    elif 'palm' in token_set:
        kind = 'palm'
        allowed = {'palm'}
    elif token_set.intersection({'clavicle', 'shoulder', 'collar'}):
        kind = 'clavicle'
        allowed = {'clavicle', 'shoulder', 'collar'}
    elif token_set.intersection({'spine', 'neck', 'head', 'hand', 'foot', 'toe', 'ball', 'breast', 'pectoral'}):
        kind = next(token for token in ('spine', 'neck', 'head', 'hand', 'foot', 'toe', 'ball', 'breast', 'pectoral')
                    if token in token_set)
        if kind == 'ball':
            kind = 'toe'
        elif kind == 'pectoral':
            kind = 'breast'
        allowed = {kind, 'ball', 'base', 'pectoral'}
    else:
        return None

    index = get_bone_index(name)
    qualifiers = {token for token in token_set if not token.isdigit()} - allowed - side_tokens
    if 'roll' in qualifiers:
        qualifiers.remove('roll')
        qualifiers.add('twist')
    return kind, side, index, frozenset(qualifiers)


def build_mapping_guesses(source_names, target_names):
    target_names = set(target_names)
    reference_by_signature = {}
    for source_name, target_name in map_bones.load_mapping('uemannequin_rigify'):
        signature = get_mapping_signature(source_name)
        if signature is not None:
            reference_by_signature.setdefault(signature, []).append(target_name)
    for side in ('L', 'R'):
        for finger_index in range(1, 5):
            signature = ('palm', side.lower(), finger_index, frozenset())
            target = f'palm.{finger_index:02d}.{side}'
            reference_by_signature.setdefault(signature, []).append(target)

    guesses = {}
    for source_name in source_names:
        signature = get_mapping_signature(source_name)
        if signature is None:
            continue

        reference_targets = reference_by_signature.get(signature, [])
        if not reference_targets and signature[2] is None:
            reference_targets = [
                target
                for candidate, candidate_targets in reference_by_signature.items()
                if candidate[0] == signature[0]
                and candidate[1] == signature[1]
                and candidate[3] == signature[3]
                for target in candidate_targets
            ]

        matching_targets = [target for target in reference_targets if target in target_names]
        if len(matching_targets) == 1:
            guesses[source_name] = matching_targets[0]

    target_counts = {}
    for target in guesses.values():
        target_counts[target] = target_counts.get(target, 0) + 1
    return {
        source: target for source, target in guesses.items()
        if target_counts[target] == 1
    }


class GenerateMappingGuessOperator(bpy.types.Operator):
    """Generate a best-guess mapping from the active armature."""
    bl_idname = "object.ARSENAL_generate_mapping_guess"
    bl_label = "Guess mapping from armature"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active
            and context.object.type == 'ARMATURE'
            and context.object.mode == 'OBJECT')

    def execute(self, context):
        armature = context.object.data
        reference = map_bones.load_mapping('uemannequin_rigify')
        target_names = list(dict.fromkeys(
            [target for _, target in reference]
            + [f'palm.{index:02d}.{side}' for side in ('L', 'R') for index in range(1, 5)]
        ))
        guesses = build_mapping_guesses(
            [bone.name for bone in armature.bones], target_names)
        source_by_target = {target: source for source, target in guesses.items()}

        ui = context.window_manager.arsenal_ui
        ui.edit_mapping = True
        base_name = re.sub(r'[^A-Za-z0-9_-]+', '_', context.object.name).strip('_').lower()
        base_name = (base_name or 'armature') + '_to_rigify'
        mapping_name = base_name
        suffix = 2
        while map_bones.has_mapping(mapping_name):
            mapping_name = f'{base_name}_{suffix}'
            suffix += 1

        ui.mapping_entries.clear()
        ui.loading_mapping = True
        try:
            for target_name in target_names:
                entry = ui.mapping_entries.add()
                entry.bone_from = source_by_target.get(target_name, '')
                entry.bone_to = target_name
        finally:
            ui.loading_mapping = False

        ui.new_mapping_name = mapping_name
        map_bones.save_mapping(mapping_name, [
            [entry.bone_from, entry.bone_to]
            for entry in ui.mapping_entries
            if entry.bone_from and entry.bone_to
        ])
        ui.active_mapping = mapping_name

        self.report(
            {'INFO'},
            f"Saved '{mapping_name}': guessed {len(guesses)} of {len(target_names)} target bones. "
            "Review the blank source entries and fill them in."
        )
        return {'FINISHED'}


class CreateMappingOperator(bpy.types.Operator):
    """Select two armatures. And set relations between bones."""
    bl_idname = "object.ARSENAL_create_mapping"
    bl_label = "Create mapping"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and len(context.selected_objects) == 2
            and context.view_layer.objects.active
            and context.object.mode == 'OBJECT')

    def execute(self, context):
        selected = list(context.selected_objects)
        active = context.view_layer.objects.active
        selected.remove(active)

        other = selected[0]
        active_names = [bone.name for bone in active.data.bones]
        other_names = [bone.name for bone in other.data.bones]
        guesses = build_mapping_guesses(active_names, other_names)
        reverse_guesses = build_mapping_guesses(other_names, active_names)
        if len(reverse_guesses) > len(guesses):
            active_names, other_names = other_names, active_names
            guesses = reverse_guesses

        ui = context.window_manager.arsenal_ui
        ui.edit_mapping = True
        ui.new_mapping_name = 'new_mapping_name'
        mapping_entries = ui.mapping_entries
        mapping_entries.clear()

        source_by_target = {target: source for source, target in guesses.items()}
        for name in other_names:
            entry = mapping_entries.add()
            entry.bone_from = source_by_target.get(name, '')
            entry.bone_to = name


        return {'FINISHED'}


class MappingRemoveEntryOperator(bpy.types.Operator):
    """Remove entry"""
    bl_idname = "object.ARSENAL_mapping_remove_entry"
    bl_label = "Remove entry"
    # bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        ui = context.window_manager.arsenal_ui
        mapping_entries = ui.mapping_entries
        mapping_entries.remove(self.index)
        save_mapping_entries(ui)
        return {'FINISHED'}


class MappingAddEntryOperator(bpy.types.Operator):
    """Add entry"""
    bl_idname = "object.ARSENAL_mapping_add_entry"
    bl_label = "Add entry"
    # bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ui = context.window_manager.arsenal_ui
        mapping_entries = ui.mapping_entries
        mapping_entries.add()
        return {'FINISHED'}

class SaveMappingOperator(bpy.types.Operator):
    """Save mapping"""
    bl_idname = "object.ARSENAL_save_mapping"
    bl_label = "Owerwrite mapping?"
    # bl_options = {'REGISTER', 'UNDO'}

    # name: bpy.props.StringProperty()

    def execute(self, context):
        ui = context.window_manager.arsenal_ui
        mapping_entries = ui.mapping_entries
        data = [
            [entry.bone_from, entry.bone_to]
            for entry in mapping_entries
            if entry.bone_from and entry.bone_to
        ]
        map_bones.save_mapping(ui.new_mapping_name, data)
        ui.active_mapping = ui.new_mapping_name
        return {'FINISHED'}

    def invoke(self, context, event):
        ui = context.window_manager.arsenal_ui
        if map_bones.has_mapping(ui.new_mapping_name):
            return context.window_manager.invoke_confirm(self, event)
        else:
            return self.execute(context)

class RemoveMappingOperator(bpy.types.Operator):
    """Remove mapping"""
    bl_idname = "object.ARSENAL_remove_mapping"
    bl_label = "Remove mapping?"
    # bl_options = {'REGISTER', 'UNDO'}

    # name: bpy.props.StringProperty()

    def execute(self, context):
        ui = context.window_manager.arsenal_ui
        map_bones.remove_mapping(ui.active_mapping)
        ui.reset_active_mapping()
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class RenameArmatureOperator(bpy.types.Operator):
    """Rename armature by mapping"""
    bl_idname = "armature.ARSENAL_rename_armature"
    bl_label = "Rename armature"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active)

    def execute(self, context):
        ui = context.window_manager.arsenal_ui
        mapping = map_bones.BoneMapping(ui.active_mapping, ui.rename_reverse)
        mapping.rename_armature(context.object.data)
        return {'FINISHED'}

class AddPrefixOperator(bpy.types.Operator):
    """Add prefix"""
    bl_idname = "armature.ARSENAL_add_prefix"
    bl_label = "Add prefix"
    bl_options = {'REGISTER', 'UNDO'}

    prefix: bpy.props.StringProperty(default = 'DEF-')

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active)

    def execute(self, context):
        oops.mode_set(mode = 'EDIT')
        for bone in context.object.data.edit_bones:
            bone.name = self.prefix + bone.name
        return {'FINISHED'}

class RemovePrefixOperator(bpy.types.Operator):
    """Remove prefix"""
    bl_idname = "armature.ARSENAL_remove_prefix"
    bl_label = "Remove prefix"
    bl_options = {'REGISTER', 'UNDO'}

    prefix: bpy.props.StringProperty(default = 'DEF-')

    @classmethod
    def poll(cls, context):
        return (context.space_data.type == 'VIEW_3D'
            and context.view_layer.objects.active)

    def execute(self, context):
        oops.mode_set(mode = 'EDIT')
        for bone in context.object.data.edit_bones:
            bone.name = re.sub('^'+self.prefix, '', bone.name)
        return {'FINISHED'}




class ARSENAL_IU_Props(bpy.types.PropertyGroup):


    def update_edit_mapping(self, value):
        if value:
            self.load_active_mapping()
            self.new_mapping_name = self.active_mapping

    def update_active_mapping(self, value):
        self.update_edit_mapping(self.edit_mapping)

    def load_active_mapping(self):
        data = map_bones.load_mapping(self.active_mapping)
        mapped_by_target = {
            target: source for source, target in data
            if source and target
        }
        reference_targets = list(dict.fromkeys(
            target for _, target in map_bones.load_mapping('uemannequin_rigify')))
        reference_target_set = set(reference_targets)
        data = [[mapped_by_target.get(target, ''), target] for target in reference_targets]
        data.extend(
            [source, target] for source, target in map_bones.load_mapping(self.active_mapping)
            if target not in reference_target_set
        )

        self.loading_mapping = True
        try:
            self.mapping_entries.clear()
            for key, value in data:
                entry = self.mapping_entries.add()
                entry.bone_from = key
                entry.bone_to = value
        finally:
            self.loading_mapping = False

    def reset_active_mapping(self):
        self.active_mapping = map_bones.get_mappings(self, None)[0][0]

    active_mapping: bpy.props.EnumProperty(
        name = "Mapping",
        description = "Saved mappings",
        items = map_bones.get_mappings,
        update = update_active_mapping,
        default = None
        )

    edit_mapping: bpy.props.BoolProperty(
        name = "Edit mapping",
        default = False,
        update = update_edit_mapping
        )

    new_mapping_name: bpy.props.StringProperty()
    mapping_entries:bpy.props.CollectionProperty(type=MappingEntry)
    loading_mapping: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    rename_reverse: bpy.props.BoolProperty(
        name = "Reverse",
        default = False
        )

    new_template_name: bpy.props.StringProperty()
    active_template: bpy.props.EnumProperty(
        name = "Template",
        description = "Saved templates",
        items = templates.get_templates,
        default = None
        )


class ARSENAL_PT_BoneMappingsPanel(bpy.types.Panel):
    """
    Addon panel
    """
    bl_label = '2. Mapping Setup'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 1

    def draw_mapping(self, col, ui):
        header = col.row()
        header.label(text='Source bone')
        header.label(text='Target bone')
        header.label(text='')

        i = 0
        for e in ui.mapping_entries:

            row = col.row()
            subcol = row.column()
            subcol.prop(e, 'bone_from', text = '')
            subcol = row.column()
            subcol.prop(e, 'bone_to',  text = '')
            subcol = row.column()
            prop = subcol.operator('object.ARSENAL_mapping_remove_entry', icon = 'X', text = '')
            prop.index = i

            i += 1
        col.operator('object.ARSENAL_mapping_add_entry')

    def draw(self, context):

        layout = self.layout
        col = layout.column()
        ui = context.window_manager.arsenal_ui

        if ui.edit_mapping:
            self.draw_mapping(col, ui)
        else:
            col.operator("object.ARSENAL_generate_mapping_guess", text='Guess mapping from armature')
