import math
import os
import re

import bpy
from mathutils import Matrix, Quaternion

from . import bone_functions as b_fun
from . import export_skeleton
from . import export_static_mesh as static_mesh
from . import stalker2_animation_importer as importer
from .retarget_animation import (
    action_slot_curves,
    find_retarget_backup,
    get_pose_bone_name,
    resolve_animation_mapping,
)

FALLBACK_TEMPLATE = 'idle'
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
IDENTITY = Matrix.Identity(4)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_export_rig(context):
    candidates = [context.view_layer.objects.active] + list(context.scene.objects)
    for obj in candidates:
        if obj and obj.type == 'ARMATURE' and obj.data.get('rig_id'):
            backup, _collection = find_retarget_backup(obj)
            if backup:
                return obj, backup
    return None, None


def rig_action_slot(action, rig):
    best = None
    for slot in action.slots:
        if slot.target_id_type != 'OBJECT':
            continue
        count = len({
            get_pose_bone_name(curve.data_path)
            for curve in action_slot_curves(action, slot)
            if get_pose_bone_name(curve.data_path) in rig.pose.bones
        })
        if count and (best is None or count > best[1]):
            best = (slot, count)
    return best[0] if best else None


def exportable_actions(rig):
    result = []
    for action in bpy.data.actions:
        if action.is_action_legacy or action.get(importer.ACTION_MARKER):
            continue
        if rig_action_slot(action, rig):
            result.append(action)
    return sorted(result, key=lambda item: item.name.casefold())


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------

def library_anchor_parts(path):
    parts = os.path.normpath(path).split(os.sep)
    for index in range(len(parts) - 2, 0, -1):
        if (parts[index].casefold() == 'animations'
                and parts[index + 1].casefold() in {'player', 'weapons'}):
            return parts[index - 1:]
    raise ValueError(f'Cannot find the STALKER2\\Animations folder in {path}')


def rename_weapon_folders(folders, old_name, new_name):
    """Swap the old weapon name for the new one, including the template's folder under 'pt' (e.g. pt/udp)."""
    result = []
    for index, part in enumerate(folders):
        after_pt = index > 0 and folders[index - 1].casefold() == 'pt'
        result.append(new_name if after_pt or part.casefold() == old_name.casefold() else part)
    return result


def export_relative_path(template_path, kind, old_name, new_name, suffix, folder_override):
    parts = library_anchor_parts(template_path)
    folders = parts[:-1]
    if folder_override:
        marker = old_name if kind == 'player' else 'fp'
        index = max((i for i, part in enumerate(folders) if part.casefold() == marker.casefold()), default=None)
        if index is None and kind == 'player':
            index = max((i for i, part in enumerate(folders[:-1]) if part.casefold() == 'pt'), default=None)
            index = None if index is None else index + 1
        if index is None:
            raise ValueError(f'No "{marker}" folder to apply the folder override to in {template_path}')
        override_parts = [part for part in re.split(r'[\\/]+', folder_override) if part]
        folders = folders[:index + 1] + override_parts
    folders = rename_weapon_folders(folders, old_name, new_name)
    stem = INVALID_FILENAME_CHARS.sub('_', suffix)
    if kind == 'player':
        filename = f'AS_fp_{new_name}_{stem}.fbx'
    else:
        filename = f'AS_{new_name}_fp_{stem}.fbx'
    return os.path.join(*folders, filename)


def is_inside(path, folder):
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


def plan_export(item_name, template_override, folder_override, pairs, old_name, new_name,
                output_root, library_root):
    by_key = {suffix.casefold(): (suffix, player, weapon) for suffix, player, weapon in pairs}
    if template_override:
        key = template_override.casefold()
        if key not in by_key:
            raise ValueError(f'Template "{template_override}" not found in the library')
        exact = False
    elif item_name.casefold() in by_key:
        key = item_name.casefold()
        exact = True
    elif FALLBACK_TEMPLATE in by_key:
        key = FALLBACK_TEMPLATE
        exact = False
    else:
        raise ValueError(f'No template pair for "{item_name}" (and no "{FALLBACK_TEMPLATE}" pair)')
    template = by_key[key]
    _suffix, player_template, weapon_template = template

    outputs = []
    for kind, template_path in (('player', player_template), ('weapon', weapon_template)):
        relative = export_relative_path(
            template_path, kind, old_name, new_name, item_name, folder_override)
        target = os.path.join(output_root, relative)
        if is_inside(target, library_root) or os.path.normcase(target) == os.path.normcase(template_path):
            raise ValueError('Output would overwrite the original library; choose a different output folder')
        outputs.append((kind, template_path, target))
    status = 'Matches an original animation' if exact else f'New - template "{template[0]}"'
    return outputs, status


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------

def bone_order(armature):
    ordered = []
    seen = set()

    def visit(bone):
        if bone.name in seen:
            return
        if bone.parent:
            visit(bone.parent)
        seen.add(bone.name)
        ordered.append(bone)

    for bone in armature.data.bones:
        visit(bone)
    return ordered


def rest_relatives(armature):
    relatives = {}
    for bone in armature.data.bones:
        if bone.parent:
            relatives[bone.name] = bone.parent.matrix_local.inverted_safe() @ bone.matrix_local
        else:
            relatives[bone.name] = bone.matrix_local.copy()
    return relatives


def sample_template(context, armature, frames):
    samples = {}
    for frame in frames:
        context.scene.frame_set(frame)
        context.view_layer.update()
        samples[frame] = (
            {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in armature.pose.bones},
            armature.matrix_world.copy(),
        )
    return samples


LIMB_CONTROLS = ('thigh_fk', 'shin_fk', 'foot_fk', 'upper_arm_fk', 'forearm_fk', 'hand_fk')


def visible_pose_name(rig, target_name):
    # Only the limbs have an IK alternative; ORG limb bones show the blended FK/IK result.
    if target_name.split('.')[0] in LIMB_CONTROLS:
        candidate = 'ORG-' + target_name.replace('_fk', '', 1)
        if candidate in rig.pose.bones:
            return candidate
    return target_name


def read_reversed_worlds(rig, backup, entries):
    rig_world = rig.matrix_world
    backup_inverse = backup.matrix_world.inverted_safe()
    result = {}
    for read_name, source_name in entries:
        pose_world = rig_world @ rig.pose.bones[read_name].matrix
        rest_target = rig_world @ rig.data.bones[read_name].matrix_local
        rest_source = backup.matrix_world @ backup.data.bones[source_name].matrix_local
        result[source_name] = backup_inverse @ (pose_world @ rest_target.inverted_safe() @ rest_source)
    return result


def solve_armature(order, relatives, original_basis, reversed_world, types, base=IDENTITY):
    """Return (worlds, basis) per bone; mapped bones take the edited pose."""
    worlds = {}
    basis = {}
    for bone in order:
        name = bone.name
        parent_world = worlds[bone.parent.name] if bone.parent else IDENTITY
        rest = parent_world @ relatives[name]
        original = original_basis[name]
        if name in reversed_world:
            local = rest.inverted_safe() @ (base @ reversed_world[name])
            loc, rot, _scale = local.decompose()
            original_loc, _original_rot, original_scale = original.decompose()
            if types.get(name) == 'rot':
                loc = original_loc
            basis[name] = Matrix.LocRotScale(loc, rot, original_scale)
        else:
            basis[name] = original.copy()
        worlds[name] = rest @ basis[name]
    return worlds, basis


def sample_rig(context, rig, backup, mapping, frames):
    entries = []
    types = {}
    for target_name, source_name, transform_type in mapping:
        entries.append((visible_pose_name(rig, target_name), source_name))
        types[source_name] = transform_type
    rows = []
    for frame in frames:
        context.scene.frame_set(frame)
        context.view_layer.update()
        rows.append(read_reversed_worlds(rig, backup, entries))
    return rows, types


def channel_values(basis_series, rotation_mode):
    locations = [basis.to_translation() for basis in basis_series]
    scales = [basis.to_scale() for basis in basis_series]
    rotations = []
    previous = None
    for basis in basis_series:
        quaternion = basis.to_quaternion()
        if rotation_mode == 'QUATERNION':
            if previous is not None:
                quaternion.make_compatible(previous)
            previous = quaternion
            rotations.append(tuple(quaternion))
        else:
            euler = quaternion.to_euler(rotation_mode, previous) if previous is not None else quaternion.to_euler(rotation_mode)
            previous = euler
            rotations.append(tuple(euler))
    return locations, rotations, scales


def add_curve(action, datablock, data_path, index, group, frames, values):
    curve = action.fcurve_ensure_for_datablock(datablock, data_path, index=index, group_name=group)
    curve.keyframe_points.add(len(frames))
    curve.keyframe_points.foreach_set(
        'co', [value for frame, v in zip(frames, values) for value in (frame, v)])
    curve.keyframe_points[0].interpolation = 'CONSTANT'
    curve.update()


def write_armature_action(armature, name, frames, bone_series, object_series=None):
    """Write the baked action. A leading key one frame before the clip holds the rest pose (identity bone
    transforms): the FBX exporter writes each node's default transform from the pose at the current frame, so
    exporting from that frame gives the file a true rest pose, as the original Unreal exports have."""
    frames = [frames[0] - 1.0] + list(frames)
    armature.animation_data_clear()
    animation_data = armature.animation_data_create()
    action = bpy.data.actions.new(name)
    animation_data.action = action
    animation_data.action_slot = action.slots.new('OBJECT', armature.name)

    for bone_name, basis_series in bone_series.items():
        mode = armature.pose.bones[bone_name].rotation_mode
        if mode == 'AXIS_ANGLE':
            mode = 'QUATERNION'
            armature.pose.bones[bone_name].rotation_mode = mode
        locations, rotations, scales = channel_values([Matrix.Identity(4)] + list(basis_series), mode)
        rotation_property = 'rotation_quaternion' if mode == 'QUATERNION' else 'rotation_euler'
        for prop, series, count in (
                ('location', locations, 3),
                (rotation_property, rotations, len(rotations[0])),
                ('scale', scales, 3)):
            for index in range(count):
                add_curve(action, armature, f'pose.bones["{bone_name}"].{prop}', index,
                          bone_name, frames, [value[index] for value in series])

    if object_series:
        armature.rotation_mode = 'XYZ'
        locations, rotations, scales = channel_values([object_series[0]] + list(object_series), 'XYZ')
        for prop, series in (('location', locations), ('rotation_euler', rotations), ('scale', scales)):
            for index in range(3):
                add_curve(action, armature, prop, index, 'Object Transforms',
                          frames, [value[index] for value in series])
    return action


def export_fbx(context, armature, filepath):
    for obj in context.scene.objects:
        obj.select_set(obj == armature)
    context.view_layer.objects.active = armature
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    partial = os.path.splitext(filepath)[0] + '.partial.fbx'
    try:
        bpy.ops.export_scene.fbx(
            filepath=partial,
            use_selection=True,
            object_types={'ARMATURE'},
            bake_anim=True,
            bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_simplify_factor=0.0,
            add_leaf_bones=False,
            armature_nodetype='ROOT',
            primary_bone_axis='Y',
            secondary_bone_axis='X',
            axis_forward='Y',
            axis_up='Z',
            global_scale=0.01,
            apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_NONE',
            path_mode='AUTO',
        )
        os.replace(partial, filepath)
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def export_action(context, rig, backup, mapping, action, slot, outputs):
    (_, player_template, player_target), (_, weapon_template, weapon_target) = outputs
    animation_data = rig.animation_data_create()
    animation_data.action = action
    animation_data.action_slot = slot
    first = math.floor(action.frame_range[0])
    last = math.ceil(action.frame_range[1])
    frames_in = list(range(first, last + 1))
    frames_out = [float(frame - first) for frame in frames_in]

    imported = []
    created = []
    try:
        player_objects, player_actions, player, player_action = importer._import_fbx(player_template)
        imported.append((player_objects, player_actions))
        weapon_objects, weapon_actions, weapon, weapon_action = importer._import_fbx(weapon_template)
        imported.append((weapon_objects, weapon_actions))

        template_first = math.floor(min(player_action.frame_range[0], weapon_action.frame_range[0]))
        template_last = math.ceil(max(player_action.frame_range[1], weapon_action.frame_range[1]))
        template_frames = [
            min(max(frame - first + template_first, template_first), template_last)
            for frame in frames_in
        ]
        unique_frames = sorted(set(template_frames))
        player_samples = sample_template(context, player, unique_frames)
        weapon_samples = sample_template(context, weapon, unique_frames)
        player_bone_names = {bone.name for bone in player.data.bones}
        weapon_only_names = {bone.name for bone in weapon.data.bones} - player_bone_names

        reversed_rows, types = sample_rig(context, rig, backup, mapping, frames_in)

        player_order, weapon_order = bone_order(player), bone_order(weapon)
        player_rel, weapon_rel = rest_relatives(player), rest_relatives(weapon)
        player_series = {bone.name: [] for bone in player_order}
        weapon_series = {bone.name: [] for bone in weapon_order}
        object_series = []

        for frame_index, template_frame in enumerate(template_frames):
            player_basis, _ = player_samples[template_frame]
            weapon_basis, weapon_original_world = weapon_samples[template_frame]
            edited = reversed_rows[frame_index]

            player_worlds, player_result = solve_armature(
                player_order, player_rel, player_basis,
                {name: world for name, world in edited.items() if name in player_bone_names},
                types)
            weapon_world = player_worlds.get('jnt_weapon', weapon_original_world)
            weapon_inverse = weapon_world.inverted_safe()

            weapon_given = {
                name: weapon_inverse @ world for name, world in edited.items()
                if name in weapon_only_names
            }
            for name in player_bone_names:
                if name in weapon.data.bones:
                    weapon_given[name] = weapon_inverse @ player_worlds[name]
            weapon_types = dict(types)
            for name in player_bone_names:
                weapon_types.pop(name, None)
            _worlds, weapon_result = solve_armature(
                weapon_order, weapon_rel, weapon_basis, weapon_given, weapon_types)

            for name, basis in player_result.items():
                player_series[name].append(basis)
            for name, basis in weapon_result.items():
                weapon_series[name].append(basis)
            object_series.append(weapon_world)

        scene = context.scene
        scene.frame_start = 0
        scene.frame_end = int(frames_out[-1])
        created.append(write_armature_action(player, action.name, frames_out, player_series))
        created.append(write_armature_action(weapon, action.name, frames_out, weapon_series, object_series))
        scene.frame_set(-1)
        export_fbx(context, player, player_target)
        export_fbx(context, weapon, weapon_target)
    finally:
        for objects, actions in reversed(imported):
            importer._remove_imported(objects, actions)
        for new_action in created:
            bpy.data.actions.remove(new_action)
    return player_target, weapon_target


def run_exports(context, rig, backup, plans):
    scene = context.scene
    saved = (
        scene.unit_settings.scale_length,
        scene.render.fps, scene.render.fps_base,
        scene.frame_start, scene.frame_end, scene.frame_current,
        rig.animation_data.action if rig.animation_data else None,
        rig.animation_data.action_slot if rig.animation_data else None,
        context.view_layer.objects.active,
    )
    written = []
    failures = []
    mapping, _missing = resolve_animation_mapping(backup, rig)
    if not mapping:
        raise RuntimeError('No animation bone mappings matched the source skeleton and Rigify rig.')
    try:
        scene.unit_settings.scale_length = 1.0
        with b_fun.forced_pose_position(rig, backup):
            for action, slot, outputs in plans:
                try:
                    written.extend(export_action(context, rig, backup, mapping, action, slot, outputs))
                except Exception as error:
                    failures.append((action.name, str(error)))
    finally:
        (scale, fps, fps_base, frame_start, frame_end, frame_current,
         rig_action, rig_slot, active) = saved
        scene.unit_settings.scale_length = scale
        scene.render.fps = fps
        scene.render.fps_base = fps_base
        scene.frame_start = frame_start
        scene.frame_end = frame_end
        if rig.animation_data:
            rig.animation_data.action = rig_action
            if rig_action:
                rig.animation_data.action_slot = rig_slot
        scene.frame_set(frame_current)
        for obj in scene.objects:
            obj.select_set(obj == active)
        context.view_layer.objects.active = active
    return written, failures


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class ARSENAL_ExportAction(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    enabled: bpy.props.BoolProperty(name='Export', default=True)
    template: bpy.props.StringProperty(
        name='Template',
        description='Original animation to use as the base (skeleton and unmapped bones). '
                    'Leave empty to use the animation with the same name, or "idle" for new actions')
    folder: bpy.props.StringProperty(
        name='Folder',
        description='Category folder below the weapon folder, e.g. Reload/TwoHands. '
                    'Leave empty to copy the template folder')
    status: bpy.props.StringProperty()


def weapon_name(scene):
    """The weapon's file/folder name: its English display name, lowercased with only letters and digits."""
    for entry in scene.arsenal_cfg.texts:
        if entry.language == 'en':
            return re.sub(r'[^a-z0-9]', '', entry.name.lower())
    return ''


def mod_mount(export):
    """The Unreal mount path of the mod (/<Mod Name>), or '' when no Mod Name is set."""
    name = export.unreal_mount.strip().strip('/')
    return '/' + name if name else ''


class ARSENAL_ExportProps(bpy.types.PropertyGroup):
    output_folder: bpy.props.StringProperty(name='Output Folder', subtype='DIR_PATH')
    static_category: bpy.props.StringProperty(
        name='Weapon Category',
        description='Weapon class folder for the static meshes: _Stalker_2/weapons/<category>/p_<weapon>/AnimMesh. '
                    'The weapon name comes from the main weapon mesh object',
        default='pistol')
    actions: bpy.props.CollectionProperty(type=ARSENAL_ExportAction)
    unreal_mount: bpy.props.StringProperty(
        name='Mod Name',
        description='The name of your mod in ZoneKit (the folder the mod is in, e.g. MonkeyMod). '
                    'It is also the Unreal mount path /<Mod Name> and the ModGameData/<Mod Name> folder',
        default='')
    active_index: bpy.props.IntProperty()
    summary: bpy.props.StringProperty(default='Refresh the list, then validate or export.')


class ARSENAL_UL_ExportActions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'enabled', text='')
        row.label(text=item.name)
        if item.status:
            row.label(text=item.status)


def _settings(context):
    return context.scene.arsenal_export, context.scene.stalker2_animation_importer


def _export_basics(context):
    export, importer_settings = _settings(context)
    rig, backup = find_export_rig(context)
    if not rig:
        raise RuntimeError('Select the generated Rigify rig (with its retarget backup).')
    new_name = weapon_name(context.scene)
    if not new_name:
        raise RuntimeError('Enter the weapon\'s English Name (4. Create Your Custom Weapon > Name & Description); '
                           'the file names are made from it.')
    if INVALID_FILENAME_CHARS.search(new_name):
        raise RuntimeError('The weapon\'s English Name makes an invalid file name.')
    output_root = bpy.path.abspath(export.output_folder).strip()
    if not output_root:
        raise RuntimeError('Choose an output folder.')
    library_root = bpy.path.abspath(importer_settings.animation_root).strip()
    return export, importer_settings, rig, backup, new_name, output_root, library_root


def _build_plans(context):
    export, importer_settings, rig, backup, new_name, output_root, library_root = _export_basics(context)
    old_name = importer_settings.weapon_name.strip()
    pairs, _player_only, _weapon_only, _ambiguous = importer._scan_library(library_root, old_name)

    plans = []
    problems = 0
    for item in export.actions:
        if not item.enabled:
            continue
        action = bpy.data.actions.get(item.name)
        slot = rig_action_slot(action, rig) if action else None
        if not slot:
            item.status = 'Action not found'
            problems += 1
            continue
        try:
            outputs, status = plan_export(
                item.name, item.template.strip(), item.folder.strip(), pairs,
                old_name, new_name, output_root, library_root)
        except ValueError as error:
            item.status = str(error)
            problems += 1
            continue
        item.status = status
        plans.append((action, slot, outputs))
    return rig, backup, plans, problems


def _build_static_plan(context):
    export, _importer_settings, rig, backup, _new_name, output_root, library_root = _export_basics(context)
    mapping, _missing = resolve_animation_mapping(backup, rig)
    bone_joints = static_mesh.weapon_bone_joints(rig, mapping)
    if not bone_joints:
        raise RuntimeError('No weapon rig bones are mapped to game joints, so there are no static meshes to export.')
    category = export.static_category.strip()
    try:
        _weapon, plan = static_mesh.plan_static_meshes(rig, bone_joints, category, output_root, context.scene)
    except ValueError as error:
        raise RuntimeError(str(error))
    if library_root and any(is_inside(path, library_root) for _bone, _stem, path in plan):
        raise RuntimeError('Output would write into the original library; choose a different output folder.')
    return rig, backup, bone_joints, plan


def _run_animation_export(context):
    rig, backup, plans, problems = _build_plans(context)
    if problems:
        raise RuntimeError(f'{problems} actions have problems; use Validate to see them.')
    if not plans:
        raise RuntimeError('No actions are ticked.')
    written, failures = run_exports(context, rig, backup, plans)
    return written, failures, len(plans)


def _run_static_export(context):
    export = context.scene.arsenal_export
    rig, backup, bone_joints, _plan = _build_static_plan(context)
    written, skipped = static_mesh.export_static_meshes(
        context, rig, backup, bone_joints,
        export.static_category.strip(), bpy.path.abspath(export.output_folder).strip())
    if not written:
        raise RuntimeError('No weapon geometry is weighted to the mapped weapon bones.')
    written.append(export_skeleton.export_weapon_skeleton(context))
    return written, skipped


class ARSENAL_OT_ExportRefresh(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_refresh'
    bl_label = 'Refresh'
    bl_description = 'List the actions on the rig that can be exported'

    def execute(self, context):
        export = context.scene.arsenal_export
        rig, _backup = find_export_rig(context)
        if not rig:
            self.report({'ERROR'}, 'No Rigify rig with a retarget backup found.')
            return {'CANCELLED'}
        previous = {item.name: (item.enabled, item.template, item.folder) for item in export.actions}
        export.actions.clear()
        for action in exportable_actions(rig):
            item = export.actions.add()
            item.name = action.name
            if action.name in previous:
                item.enabled, item.template, item.folder = previous[action.name]
        export.summary = f'{len(export.actions)} actions found.'
        return {'FINISHED'}


class ARSENAL_OT_ExportSelect(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_select'
    bl_label = 'Select'
    bl_description = 'Tick or untick every action'

    enabled: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        for item in context.scene.arsenal_export.actions:
            item.enabled = self.enabled
        return {'FINISHED'}


class ARSENAL_OT_ExportValidate(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_validate'
    bl_label = 'Validate'
    bl_description = 'Check the settings and show the files that would be written'

    def execute(self, context):
        try:
            _rig, _backup, plans, problems = _build_plans(context)
            _rig, _backup, _bone_joints, static_plan = _build_static_plan(context)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        for action, _slot, outputs in plans:
            for _kind, _template, target in outputs:
                print(f'[Arsenal export] {action.name}: {target}')
        for bone_name, _stem, target in static_plan:
            print(f'[Arsenal export] static mesh {bone_name}: {target}')
        try:
            from . import export_check, weapon_cfg
            for problem in export_check.name_warnings(weapon_cfg.build_context(context)):
                self.report({'WARNING'}, problem)
        except Exception as error:
            self.report({'WARNING'}, f'Name check skipped: {error}')
        context.scene.arsenal_export.summary = (
            f'{len(plans)} animations ready, {problems} with problems; {len(static_plan)} static meshes planned.')
        self.report({'INFO'}, context.scene.arsenal_export.summary)
        return {'FINISHED'}


def _report_animation(operator, context, result):
    written, failures, count = result
    for name, message in failures:
        operator.report({'WARNING'}, f'{name}: {message}')
    return f'{len(written)} animation files for {count - len(failures)} actions ({len(failures)} failed)', bool(failures)


def _report_static(operator, result):
    written, skipped = result
    for label in skipped:
        operator.report({'WARNING'}, f'No geometry for "{label}"; no static mesh written for it.')
    return f'{len(written)} static meshes', bool(skipped)


class ARSENAL_OT_ExportAllRun(bpy.types.Operator):
    bl_idname = 'object.arsenal_export_all'
    bl_label = 'Export All'
    bl_description = ('Export the ticked animations, the static meshes, the weapon CFG files and the Unreal import '
                      'script, then copy the script\'s path to the clipboard to paste into the ZoneKit Python bar')

    def execute(self, context):
        export = context.scene.arsenal_export
        parts = []
        warn = False
        try:
            _build_static_plan(context)
            if any(item.enabled for item in export.actions):
                summary, failed = _report_animation(self, context, _run_animation_export(context))
                parts.append(summary)
                warn = warn or failed
            else:
                self.report({'WARNING'}, 'No actions are ticked; exporting static meshes only.')
            summary, skipped = _report_static(self, _run_static_export(context))
            parts.append(summary)
            warn = warn or skipped
            try:
                from . import weapon_cfg
                written_cfgs, cfg_info = weapon_cfg.export_cfg_files(self, context)
                parts.append('the CFG files')
                from . import export_check
                problems = export_check.name_warnings(cfg_info) + export_check.path_warnings(cfg_info, written_cfgs)
                for problem in problems:
                    self.report({'WARNING'}, problem)
                    print(f'[Arsenal export] CHECK: {problem}')
                warn = warn or bool(problems)
            except Exception as error:
                self.report({'WARNING'}, f'CFG files not written: {error}')
                warn = True
            from . import export_unreal
            script_path, manifest = export_unreal.write_unreal_import(context)
            parts.append('the Unreal import script')
            if manifest['game_materials']:
                print('[Arsenal export] Slots left to the game\'s own materials: ' + ', '.join(manifest['game_materials']))
            context.window_manager.clipboard = script_path
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        export.summary = 'Wrote ' + ' and '.join(parts) + '.'
        self.report({'WARNING'} if warn else {'INFO'},
                    export.summary + ' The import script path is on the clipboard: paste it into the ZoneKit '
                    'Python bar.')
        return {'FINISHED'}


class ARSENAL_PT_ExportPanel(bpy.types.Panel):
    bl_label = '5. Export'
    bl_idname = 'ARSENAL_PT_ExportPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'STALKER 2'
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        export = context.scene.arsenal_export
        layout.prop(export, 'unreal_mount')
        layout.prop(export, 'output_folder')
        layout.prop(export, 'static_category')
        row = layout.row(align=True)
        row.operator('object.arsenal_export_refresh', icon='FILE_REFRESH')
        row.operator('object.arsenal_export_select', text='All').enabled = True
        row.operator('object.arsenal_export_select', text='None').enabled = False
        layout.template_list('ARSENAL_UL_ExportActions', '', export, 'actions', export, 'active_index', rows=6)
        if 0 <= export.active_index < len(export.actions):
            item = export.actions[export.active_index]
            layout.prop(item, 'template')
            layout.prop(item, 'folder')
        layout.label(text=export.summary)
        layout.operator('object.arsenal_export_validate', icon='CHECKMARK')
        layout.operator('object.arsenal_export_all', icon='EXPORT')
        layout.separator()
        layout.operator('object.arsenal_debug_report', icon='TEXT')


CLASSES = (
    ARSENAL_ExportAction,
    ARSENAL_ExportProps,
    ARSENAL_UL_ExportActions,
    ARSENAL_OT_ExportRefresh,
    ARSENAL_OT_ExportSelect,
    ARSENAL_OT_ExportValidate,
    ARSENAL_OT_ExportAllRun,
    ARSENAL_PT_ExportPanel,
)
