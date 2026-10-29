bl_info = {
    "name": "STALKER 2 Animation Importer",
    "author": "OpenAI",
    "version": (1, 0, 0),
    "blender": (5, 2, 2),
    "location": "View3D > Sidebar > STALKER 2",
    "description": "Combines matching STALKER 2 character and weapon FBX animations",
    "category": "Animation",
}

import math
import os
import re
import textwrap
import bpy
from .notifications import completion, report


DEFAULT_WEAPON_NAME = "UDP"


def _prefixes(weapon_name):
    name = (weapon_name or "").strip()
    if not name:
        raise ValueError("Enter the weapon name (for example UDP, AK74 or Malyuk) first")
    return f"AS_fp_{name}_", f"AS_{name}_fp_"


def _player_prefixes(weapon_name):
    """Offset aim clips use a second player prefix: AS_FP_Player_Udp_IdleToOffsetAim_01."""
    player_prefix, _ = _prefixes(weapon_name)
    return player_prefix, f"AS_FP_Player_{weapon_name.strip()}_"


# A clip with only one half (the weapon's idle_boltlock, the player's offset aim) is paired with the other
# side's idle, which is what the game plays alongside it. The stand-in is never exported.
STAND_IN_SUFFIX = "idle"


def stand_in_half(pair):
    """'player' or 'weapon' when that half of a scanned pair is an idle stand-in, otherwise None."""
    suffix, player_path, weapon_path = pair
    ending = "_" + suffix.casefold()
    for kind, path in (("player", player_path), ("weapon", weapon_path)):
        if not os.path.splitext(os.path.basename(path))[0].casefold().endswith(ending):
            return kind
    return None

ACTION_MARKER = "stalker2_animation_importer"
BASE_MARKER = "stalker2_base_skeleton"
BONE_PATH_PATTERN = re.compile(r'pose\.bones\["((?:[^"\\]|\\.)+)"\]')


def _collect_animations(folder, prefix):
    found = {}
    for directory, _, filenames in os.walk(folder):
        for filename in filenames:
            if not filename.lower().endswith(".fbx"):
                continue
            stem = os.path.splitext(filename)[0]
            if not stem.casefold().startswith(prefix.casefold()):
                continue
            suffix = stem[len(prefix):]
            if suffix:
                found.setdefault(suffix.casefold(), []).append((suffix, os.path.join(directory, filename)))
    return found


def _scan_library(root, weapon_name):
    player_prefix, weapon_prefix = _prefixes(weapon_name)
    player_folder = weapon_folder = None
    # The exported-files folder holds _STALKER2; older setups pointed at _STALKER2 or Animations.
    for animations_folder in (
            root,
            os.path.join(root, "Animations"),
            os.path.join(root, "_STALKER2", "Animations")):
        player_folder = os.path.join(animations_folder, "Player")
        weapon_folder = os.path.join(animations_folder, "Weapons")
        if os.path.isdir(player_folder) and os.path.isdir(weapon_folder):
            break
    else:
        player_folder = weapon_folder = None
        # Fall back to searching below the chosen folder (for example one level above the export).
        for directory, folders, _files in os.walk(root):
            lowered = {f.casefold(): f for f in folders}
            if 'player' in lowered and 'weapons' in lowered and os.path.basename(directory).casefold() == 'animations':
                player_folder = os.path.join(directory, lowered['player'])
                weapon_folder = os.path.join(directory, lowered['weapons'])
                break
        if not player_folder:
            raise FileNotFoundError("Select the Exported Files folder, containing the _STALKER2 and _Stalker_2 folders")

    player = {}
    for prefix in _player_prefixes(weapon_name):
        for key, found in _collect_animations(player_folder, prefix).items():
            player.setdefault(key, []).extend(found)
    weapon = _collect_animations(weapon_folder, weapon_prefix)
    ambiguous = {key for key, paths in player.items() if len(paths) != 1}
    ambiguous.update(key for key, paths in weapon.items() if len(paths) != 1)

    pairs = []
    for key in sorted(player.keys() & weapon.keys()):
        if key in ambiguous:
            continue
        suffix, player_path = player[key][0]
        _, weapon_path = weapon[key][0]
        pairs.append((suffix, player_path, weapon_path))

    def stand_in(side):
        found = side.get(STAND_IN_SUFFIX)
        return found[0][1] if found and STAND_IN_SUFFIX not in ambiguous else None

    # The *_add idles are not clips of their own: the ZoneKit import rebuilds them from the idle.
    player_only, weapon_only = [], []
    for key in sorted(player.keys() - weapon.keys() - ambiguous):
        if key.endswith("_add") or not stand_in(weapon):
            player_only.append(key)
        else:
            pairs.append((player[key][0][0], player[key][0][1], stand_in(weapon)))
    for key in sorted(weapon.keys() - player.keys() - ambiguous):
        if key.endswith("_add") or not stand_in(player):
            weapon_only.append(key)
        else:
            pairs.append((weapon[key][0][0], stand_in(player), weapon[key][0][1]))
    pairs.sort(key=lambda pair: pair[0].casefold())
    ambiguous_names = sorted(ambiguous)
    return pairs, player_only, weapon_only, ambiguous_names


def _scan_summary(pairs, player_only, weapon_only, ambiguous):
    details = []
    if player_only or weapon_only:
        details.append(f"{len(player_only) + len(weapon_only)} unmatched")
    if ambiguous:
        details.append(f"{len(ambiguous)} ambiguous")
    suffix = f"; {', '.join(details)}" if details else ""
    return f"Found {len(pairs)} matching animation pairs{suffix}."


def _find_master_armature(context):
    masters = [
        obj for obj in context.scene.objects
        if obj.type == "ARMATURE" and obj.get(BASE_MARKER, False)
    ]
    if len(masters) != 1:
        raise RuntimeError("Create the base skeleton before importing animations")
    return masters[0]


def _remove_duplicate_bones(source, destination):
    duplicates = {bone.name for bone in source.data.bones} & {bone.name for bone in destination.data.bones}
    if not duplicates:
        return

    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    if source.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    for name in duplicates:
        bone = source.data.edit_bones.get(name)
        if bone is None:
            continue
        parent = bone.parent
        for child in list(bone.children):
            child.parent = parent
            child.use_connect = False
        source.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")


def _reset_pose(armature):
    for pose_bone in armature.pose.bones:
        pose_bone.location = (0.0, 0.0, 0.0)
        if pose_bone.rotation_mode == "QUATERNION":
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        elif pose_bone.rotation_mode == "AXIS_ANGLE":
            pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        else:
            pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)


def _create_camera(armature):
    if armature.data.bones.get("jnt_camera") is None:
        raise RuntimeError("Character idle skeleton has no jnt_camera bone")

    camera_data = bpy.data.cameras.new("STALKER 2 First Person Camera")
    camera_data.lens = 18.0
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 0.01
    camera_data.clip_end = 10000.0
    camera = bpy.data.objects.new("STALKER 2 First Person Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.parent = armature
    camera.parent_type = "BONE"
    camera.parent_bone = "jnt_camera"
    camera.location = (0.0, 0.0, 0.0)
    camera.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    camera[BASE_MARKER] = True
    bpy.context.scene.camera = camera
    return camera


def _is_lower_lod(name):
    """True for LOD1 and above of an exported mesh (SK_stalker_LOD1); only the full-detail mesh is wanted."""
    found = re.search(r"_LOD(\d+)(?:\.\d+)?$", name, re.IGNORECASE)
    return bool(found) and int(found.group(1)) > 0


def _create_base_skeleton(context, root, weapon_name):
    existing_armatures = [
        obj for obj in context.scene.objects
        if obj.type == "ARMATURE" and not obj.get("arsenal_weapon_rig", False)
    ]
    if existing_armatures:
        raise RuntimeError("Base skeleton setup requires a scene with no armatures other than the imported weapon rig")

    pairs, _, _, _ = _scan_library(root, weapon_name)
    idle_pair = next((pair for pair in pairs if pair[0].casefold() == "idle"), None)
    if idle_pair is None:
        player_prefix, weapon_prefix = _prefixes(weapon_name)
        raise RuntimeError(f"Could not find the matching {player_prefix}idle.FBX and {weapon_prefix}idle.FBX files")

    initial_objects = list(context.scene.objects)
    imported_objects = []
    imported_actions = []
    camera = None
    armature = None
    try:
        _, player_path, weapon_path = idle_pair
        player_objects, player_actions, player_rig, _ = _import_fbx(player_path)
        imported_objects.extend(player_objects)
        imported_actions.extend(player_actions)
        character_meshes = [obj for obj in player_objects if obj.type == "MESH" and not _is_lower_lod(obj.name)]
        weapon_objects, weapon_actions, weapon_rig, _ = _import_fbx(weapon_path)
        imported_objects.extend(weapon_objects)
        imported_actions.extend(weapon_actions)

        player_rig.animation_data.action = None
        weapon_rig.animation_data.action = None
        _remove_duplicate_bones(weapon_rig, player_rig)

        for obj in context.view_layer.objects:
            obj.select_set(False)
        player_rig.select_set(True)
        weapon_rig.select_set(True)
        context.view_layer.objects.active = player_rig
        bpy.ops.object.join()
        armature = player_rig
        armature.name = "STALKER 2 Master Armature"
        armature.data.name = "STALKER 2 Master Skeleton"
        armature.animation_data_clear()
        armature.scale = (1.0, 1.0, 1.0)
        for mesh in character_meshes:
            mesh.scale = (1.0, 1.0, 1.0)
        _reset_pose(armature)
        armature[BASE_MARKER] = True
        from . import import_weapon
        import_weapon.add_missing_weapon_bones(context, armature)

        _remove_imported(
            [obj for obj in imported_objects if obj != armature and obj not in character_meshes],
            imported_actions,
        )
        for obj in initial_objects:
            if obj.name in {"Camera", "Cube", "Light"} and bpy.data.objects.get(obj.name) is obj:
                bpy.data.objects.remove(obj, do_unlink=True)

        camera = _create_camera(armature)
        context.view_layer.objects.active = armature
        armature.select_set(True)
        return armature
    except Exception:
        if camera is not None and bpy.data.objects.get(camera.name) is camera:
            bpy.data.objects.remove(camera, do_unlink=True)
        _remove_imported(imported_objects, imported_actions)
        raise


def _animated_bones(action, source_armature, master):
    names = set()
    curves = []
    try:
        curves.extend(action.fcurves)
    except (AttributeError, RuntimeError, TypeError):
        pass

    if not curves and source_armature.animation_data:
        slot = getattr(source_armature.animation_data, "action_slot", None)
        if slot is not None:
            for layer in getattr(action, "layers", ()):
                for strip in layer.strips:
                    channelbag_getter = getattr(strip, "channelbag", None)
                    if channelbag_getter is None:
                        continue
                    try:
                        channelbag = channelbag_getter(slot)
                    except (TypeError, RuntimeError):
                        channelbag = None
                    if channelbag is not None:
                        curves.extend(channelbag.fcurves)

    try:
        for curve in curves:
            match = BONE_PATH_PATTERN.search(curve.data_path)
            if match:
                name = match.group(1).replace('\\"', '"').replace("\\\\", "\\")
                names.add(name)
    except (AttributeError, RuntimeError, TypeError):
        names.clear()

    shared = {bone.name for bone in source_armature.pose.bones} & {bone.name for bone in master.pose.bones}
    return names & shared if names else shared


def _import_fbx(filepath):
    existing_objects = {obj.as_pointer() for obj in bpy.data.objects}
    existing_actions = {action.as_pointer() for action in bpy.data.actions}
    units = bpy.context.scene.unit_settings
    saved_scale = units.scale_length
    units.scale_length = 1.0
    try:
        bpy.ops.import_scene.fbx(
            filepath=filepath,
            global_scale=100.0,
            use_custom_normals=False,
        )
    except Exception:
        objects = [obj for obj in bpy.data.objects if obj.as_pointer() not in existing_objects]
        actions = [action for action in bpy.data.actions if action.as_pointer() not in existing_actions]
        _remove_imported(objects, actions)
        raise
    finally:
        units.scale_length = saved_scale
    objects = [obj for obj in bpy.data.objects if obj.as_pointer() not in existing_objects]
    actions = [action for action in bpy.data.actions if action.as_pointer() not in existing_actions]
    armatures = [
        obj for obj in objects
        if obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action
    ]
    if len(armatures) != 1:
        _remove_imported(objects, actions)
        raise RuntimeError(f"Expected one animated armature in {os.path.basename(filepath)}, found {len(armatures)}")
    return objects, actions, armatures[0], armatures[0].animation_data.action


def _put_action_on_nla(armature, action):
    animation_data = armature.animation_data_create()
    animation_data.action = None
    animation_data.use_nla = True
    track = animation_data.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, 1, action)
    strip.action_frame_start = action.frame_range[0]
    strip.action_frame_end = action.frame_range[1]
    strip.blend_type = "REPLACE"
    strip.extrapolation = "HOLD_FORWARD"
    return max(1, math.ceil(1 + action.frame_range[1] - action.frame_range[0]))


def _remove_imported(objects, actions):
    live_objects = []
    for obj in objects:
        try:
            if bpy.data.objects.get(obj.name) is obj:
                live_objects.append(obj)
        except ReferenceError:
            continue

    data_blocks = {obj.data for obj in live_objects if obj.data is not None}
    for obj in live_objects:
        if bpy.data.objects.get(obj.name) is obj:
            bpy.data.objects.remove(obj, do_unlink=True)

    for data in data_blocks:
        if data.users != 0:
            continue
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Armature):
            bpy.data.armatures.remove(data)
        elif isinstance(data, bpy.types.Camera):
            bpy.data.cameras.remove(data)
        elif isinstance(data, bpy.types.Light):
            bpy.data.lights.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)

    for action in actions:
        try:
            if bpy.data.actions.get(action.name) is action:
                action.use_fake_user = False
                if action.users == 0:
                    bpy.data.actions.remove(action)
        except ReferenceError:
            continue


def _copy_bone_transforms(master, sources):
    claimed = {}
    for source, action in sources:
        for name in _animated_bones(action, source, master):
            claimed.setdefault(name, source)
    if not claimed:
        raise RuntimeError("No animated bones matched the master armature")

    # The weapon armature object is itself animated (it follows jnt_weapon), so its
    # root bone (jnt_offset) must be copied in world space; local values lose that motion.
    world_space = set()
    for source, action in sources[1:]:
        for name in _animated_bones(action, source, master):
            if source.data.bones[name].parent is None:
                claimed[name] = source
                world_space.add(name)

    constraints = []
    try:
        for name, source in claimed.items():
            constraint = master.pose.bones[name].constraints.new("COPY_TRANSFORMS")
            constraint.name = "STALKER 2 animation transfer"
            constraint.target = source
            constraint.subtarget = name
            space = "WORLD" if name in world_space else "LOCAL"
            constraint.owner_space = space
            constraint.target_space = space
            constraints.append((master.pose.bones[name], constraint))
    except Exception:
        _remove_constraints(constraints)
        raise
    return constraints


def _remove_constraints(constraints):
    for pose_bone, constraint in constraints:
        if constraint in pose_bone.constraints[:]:
            pose_bone.constraints.remove(constraint)


def _bake_parameters(frame_start, frame_end):
    requested = {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "step": 1,
        "only_selected": False,
        "visual_keying": True,
        "clear_constraints": False,
        "use_current_action": False,
        "bake_types": {"POSE"},
        "channel_types": {"LOCATION", "ROTATION", "SCALE", "BBONE", "PROPS"},
        "clean_curves": True,
    }
    supported = bpy.ops.nla.bake.get_rna_type().properties.keys()
    return {name: value for name, value in requested.items() if name in supported}


def _existing_action_can_be_replaced(name):
    action = bpy.data.actions.get(name)
    if action is None:
        return None
    if not action.get(ACTION_MARKER, False):
        raise RuntimeError(f"Action '{name}' already exists and was not created by this addon")
    expected_users = 1 if action.use_fake_user else 0
    if action.users > expected_users:
        raise RuntimeError(f"Generated action '{name}' is currently in use; it was left unchanged")
    return action


def _reveal(context, obj):
    """Make obj evaluated by the depsgraph; returns an undo callable.

    After conversion the master is kept in a hidden backup collection. A hidden object is
    not evaluated, so a visual-keyed bake onto it records a stale pose instead of the clip.
    """
    restore = []

    def walk(layer_collection):
        for child in layer_collection.children:
            if obj.name in child.collection.all_objects:
                restore.append((child, "exclude", child.exclude))
                restore.append((child, "hide_viewport", child.hide_viewport))
                restore.append((child.collection, "hide_viewport", child.collection.hide_viewport))
                child.exclude = False
                child.hide_viewport = False
                child.collection.hide_viewport = False
                walk(child)

    walk(context.view_layer.layer_collection)
    restore.append((obj, "hide_viewport", obj.hide_viewport))
    obj.hide_viewport = False
    hidden = obj.hide_get()
    obj.hide_set(False)
    context.view_layer.update()

    def undo():
        if bpy.data.objects.get(obj.name) is obj:
            obj.hide_set(hidden)
        for owner, attribute, value in reversed(restore):
            setattr(owner, attribute, value)
        context.view_layer.update()

    return undo


def _import_pair(context, master, pair):
    unreveal = _reveal(context, master)
    try:
        return _import_pair_visible(context, master, pair)
    finally:
        unreveal()


def _import_pair_visible(context, master, pair):
    suffix, player_path, weapon_path = pair
    old_action = _existing_action_can_be_replaced(suffix)
    player_objects = player_actions = weapon_objects = weapon_actions = []
    constraints = []
    animation_data_existed = master.animation_data is not None
    old_master_action = master.animation_data.action if animation_data_existed else None
    old_master_use_nla = master.animation_data.use_nla if animation_data_existed else True
    original_frame = context.scene.frame_current
    prior_active = context.view_layer.objects.active
    prior_selected = [obj for obj in context.view_layer.objects if obj.select_get()]
    prior_active_mode = prior_active.mode if prior_active is not None else "OBJECT"
    prior_mode = master.mode if master == prior_active else "OBJECT"
    baked_action = None
    baked_action_completed = False
    original_scale = master.scale.copy()

    try:
        player_objects, player_actions, player_rig, player_action = _import_fbx(player_path)
        weapon_objects, weapon_actions, weapon_rig, weapon_action = _import_fbx(weapon_path)
        player_end = _put_action_on_nla(player_rig, player_action)
        weapon_end = _put_action_on_nla(weapon_rig, weapon_action)
        constraints = _copy_bone_transforms(
            master,
            ((player_rig, player_action), (weapon_rig, weapon_action)),
        )
        # World-space copies need the master to share the imported objects' scale
        # (the FBX importer scales objects by the scene unit scale). Baked values
        # are armature-space, so this does not affect the result.
        master.scale = weapon_rig.matrix_world.to_scale()
        context.view_layer.update()

        if master.animation_data is None:
            master.animation_data_create()
        master.animation_data.action = None
        master.animation_data.use_nla = False
        for obj in context.view_layer.objects:
            obj.select_set(False)
        master.select_set(True)
        context.view_layer.objects.active = master
        if master.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="POSE")

        # A stand-in idle runs for as long as the clip it accompanies.
        frame_end = {"player": weapon_end, "weapon": player_end}.get(stand_in_half(pair), max(player_end, weapon_end))
        result = bpy.ops.nla.bake(**_bake_parameters(1, frame_end))
        if "FINISHED" not in result or master.animation_data is None or master.animation_data.action is None:
            raise RuntimeError("Bake Action did not produce an action")
        baked_action = master.animation_data.action
        baked_action.name = f"__STALKER2_IMPORT_TEMP__{suffix}"

        if old_action is not None:
            bpy.data.actions.remove(old_action)
        baked_action.name = suffix
        baked_action.use_fake_user = True
        baked_action[ACTION_MARKER] = True
        baked_action_completed = True
        return baked_action
    finally:
        master.scale = original_scale
        _remove_constraints(constraints)
        if animation_data_existed and master.animation_data is not None:
            master.animation_data.action = old_master_action
            master.animation_data.use_nla = old_master_use_nla
        elif not animation_data_existed and master.animation_data is not None:
            if not master.animation_data.nla_tracks:
                master.animation_data_clear()

        if baked_action is not None and not baked_action_completed and baked_action.users == 0:
            bpy.data.actions.remove(baked_action)

        _remove_imported(player_objects, player_actions)
        _remove_imported(weapon_objects, weapon_actions)
        context.scene.frame_set(original_frame)
        for obj in context.view_layer.objects:
            obj.select_set(False)
        for obj in prior_selected:
            if bpy.data.objects.get(obj.name) is obj:
                obj.select_set(True)
        context.view_layer.objects.active = prior_active
        if master == prior_active and master.mode != prior_mode:
            bpy.ops.object.mode_set(mode=prior_mode)
        elif prior_active is not None and prior_active.mode != prior_active_mode:
            bpy.ops.object.mode_set(mode=prior_active_mode)


class STALKER2_AnimationImporterProperties(bpy.types.PropertyGroup):
    weapon_name: bpy.props.StringProperty(
        name="Template Animation Name",
        description="The template weapon's name in its animation files, e.g. udp, viper or ak74 (AS_fp_<name>_*.FBX)",
        default=DEFAULT_WEAPON_NAME,
    )
    mesh_name: bpy.props.StringProperty(
        name="Template Mesh Name",
        description="The template weapon's name in its skeletal and static mesh files (SK_<name>.FBX), "
                    "e.g. vip for the SMG. Leave empty when it is the same as the animation name",
    )
    animation_root: bpy.props.StringProperty(
        name="Exported Files",
        description="Folder containing the exported _STALKER2 and _Stalker_2 folders",
        subtype="DIR_PATH",
    )
    scan_summary: bpy.props.StringProperty(name="Scan", default="Enter the weapon name, choose the exported files folder and scan.")


class STALKER2_OT_create_base_skeleton(bpy.types.Operator):
    bl_idname = "stalker2.create_base_skeleton"
    bl_label = "Create Base Skeleton"
    bl_description = "Build the master rig and camera from the paired idle FBX animations"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            armature = _create_base_skeleton(context, root, settings.weapon_name)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created base skeleton with {len(armature.data.bones)} bones and camera")
        return {"FINISHED"}


class STALKER2_OT_scan_animations(bpy.types.Operator):
    bl_idname = "stalker2.scan_animations"
    bl_label = "Scan Animations"
    bl_description = "Find matching character and weapon animation FBX files"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            pairs, player_only, weapon_only, ambiguous = _scan_library(root, settings.weapon_name)
        except (OSError, TypeError, ValueError) as error:
            settings.scan_summary = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.scan_summary = _scan_summary(pairs, player_only, weapon_only, ambiguous)
        self.report({"INFO"}, settings.scan_summary)
        return {"FINISHED"}


class STALKER2_OT_import_animations(bpy.types.Operator):
    bl_idname = "stalker2.import_animations"
    bl_label = "Import All"
    bl_description = "Import and combine all matching animation pairs"
    bl_options = {"REGISTER"}

    @completion('Animation import')
    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        try:
            master = _find_master_armature(context)
        except RuntimeError as error:
            report(self, {"ERROR"}, str(error))
            return {"CANCELLED"}

        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            pairs, player_only, weapon_only, ambiguous = _scan_library(root, settings.weapon_name)
        except (OSError, TypeError, ValueError) as error:
            report(self, {"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.scan_summary = _scan_summary(pairs, player_only, weapon_only, ambiguous)
        if not pairs:
            report(self, {"WARNING"}, "No matching animation pairs found")
            return {"CANCELLED"}
        for suffix in player_only:
            report(self, {"WARNING"}, f"Character animation found: {suffix}; weapon animation missing")
        for suffix in weapon_only:
            report(self, {"WARNING"}, f"Weapon animation found: {suffix}; character animation missing")
        for suffix in ambiguous:
            report(self, {"WARNING"}, f"Ambiguous animation suffix skipped: {suffix}")

        successes = 0
        failures = []
        for pair in pairs:
            try:
                _import_pair(context, master, pair)
                successes += 1
            except Exception as error:
                failures.append((pair[0], str(error)))
                report(self, {"WARNING"}, f"Failed {pair[0]}: {error}")

        if failures:
            report(self, {"WARNING"}, f"Imported {successes}/{len(pairs)} pairs; {len(failures)} failed")
        else:
            report(self, {"INFO"}, f"Imported {successes} animation pairs")
        return {"FINISHED"}


class STALKER2_OT_import_weapon(bpy.types.Operator):
    bl_idname = "stalker2.import_weapon"
    bl_label = "Import Weapon"
    bl_description = ("Import the weapon rig and meshes, the character skeleton and every animation, map the bones "
                      "and convert the character to Rigify, ready for retargeting")
    bl_options = {"REGISTER", "UNDO"}

    @completion('Weapon import')
    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        ui = context.scene.arsenal_ui
        from . import import_weapon

        def fail(step, error):
            settings.scan_summary = f"Failed at: {step}"
            report(self, {"ERROR"}, f"{step}: {error}")
            return {"CANCELLED"}

        def step(label, operator):
            result = operator()
            if "FINISHED" not in result:
                raise RuntimeError("see the console or the report log for details")
            return result

        from . import setup_panel
        setup_panel.apply_template_defaults(context.scene, context.scene.arsenal_cfg.setup_template)

        root = bpy.path.abspath(settings.animation_root).strip()
        name = settings.weapon_name.strip()
        if not name or not root:
            report(self, {"ERROR"}, "Enter the weapon name and choose the exported files folder first.")
            return {"CANCELLED"}
        if any(obj.type == "ARMATURE" and (obj.get(import_weapon.RIG_MARKER) or obj.get(BASE_MARKER))
               for obj in context.scene.objects):
            report(self, {"ERROR"}, "A weapon has already been imported into this scene. Start from a new scene.")
            return {"CANCELLED"}

        current = "Import weapon rig"
        try:
            _rig, _main, skipped = import_weapon.import_rigged_weapon(
                context, root, import_weapon.donor_mesh_name(settings))
            for part in skipped:
                report(self, {"WARNING"}, f'No bone for the part "{part}"; it was not imported')

            current = "Create base skeleton"
            master = _create_base_skeleton(context, root, name)

            current = "Import animations"
            step(current, bpy.ops.stalker2.import_animations)

            current = "Map character bones"
            _select_only_object(context, master)
            step(current, bpy.ops.object.arsenal_generate_mapping_guess)
            _select_only_object(context, master)
            step(current, bpy.ops.object.arsenal_generate_weapon_mapping_guess)

            current = "Convert to Rigify"
            _select_only_object(context, master)
            step(current, bpy.ops.object.arsenal_convert_to_rigify_by_mapping)
        except Exception as error:
            return fail(current, error)

        settings.scan_summary = "Imported. Edit the weapon, then retarget the animations."
        report(self, {"INFO"}, "Weapon imported and converted. Select the rig and click Retarget Animation.")
        return {"FINISHED"}


def _select_only_object(context, obj):
    for other in context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _present_clip_names(rig):
    """Clip keys this blend already has, as plain or retargeted (rig_) actions."""
    names = set()
    for action in bpy.data.actions:
        for name in (action.name, action.get("arsenal_source_action", "")):
            if name:
                names.add(name.casefold())
                if name.casefold().startswith("rig_"):
                    names.add(name[4:].casefold())
    return names


def import_new_animations(context, rig, backup, root, weapon_name):
    """Import and retarget the library's clips that this converted blend does not have yet.

    Returns (retargeted action names, failures). Existing actions, edited or not, are left alone.
    """
    from . import retarget_animation

    pairs, _player_only, _weapon_only, _ambiguous = _scan_library(root, weapon_name)
    present = _present_clip_names(rig)
    wanted = [pair for pair in pairs if pair[0].casefold() not in present]
    if not wanted:
        return [], []

    failures = []
    sources = []
    for pair in wanted:
        try:
            sources.append(_import_pair(context, backup, pair))
        except Exception as error:
            failures.append((pair[0], str(error)))
    if not sources:
        return [], failures

    prior_action = rig.animation_data.action if rig.animation_data else None
    prior_slot = rig.animation_data.action_slot if rig.animation_data else None
    source_names = [source.name for source in sources]
    unreveal = _reveal(context, backup)
    try:
        mapping, _missing = retarget_animation.resolve_animation_mapping(backup, rig)
        if not mapping:
            raise RuntimeError("No animation bone mappings matched the source skeleton and Rigify rig")
        outputs = retarget_animation.retarget_animation_actions(
            context, backup, rig, mapping, set_anim_length=False, action_names=source_names)
    finally:
        unreveal()
        if rig.animation_data is not None:
            rig.animation_data.action = prior_action
            if prior_action is not None:
                rig.animation_data.action_slot = prior_slot

    for source in sources:
        bpy.data.actions.remove(source)
    names = []
    for output in outputs:
        source_name = output.get("arsenal_source_action", "")
        if source_name and not bpy.data.actions.get(source_name):
            output.name = source_name
        names.append(output.name)
    return names, failures


class STALKER2_OT_import_new_animations(bpy.types.Operator):
    bl_idname = "stalker2.import_new_animations"
    bl_label = "Import New Animations"
    bl_description = ("Import and retarget the clips in the exported files folder that this blend does not have "
                      "yet (for example after a newer setup exported more of them). Existing actions are not changed")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    @completion('New animation import')
    def execute(self, context):
        from . import export_animation
        settings = context.scene.stalker2_animation_importer
        rig, backup = export_animation.find_export_rig(context)
        if rig is None:
            report(self, {"ERROR"}, "No converted weapon rig found. Use Import Weapon first.")
            return {"CANCELLED"}
        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            names, failures = import_new_animations(context, rig, backup, root, settings.weapon_name)
        except Exception as error:
            report(self, {"ERROR"}, str(error))
            return {"CANCELLED"}
        for suffix, error in failures:
            report(self, {"WARNING"}, f"Failed {suffix}: {error}")
        if not names and not failures:
            settings.scan_summary = "No new animations found."
            report(self, {"INFO"}, settings.scan_summary)
        else:
            settings.scan_summary = f"Added {len(names)} animations."
            if names:
                report(self, {"INFO"}, f"Added {len(names)} animations: {', '.join(sorted(names))}")
        return {"FINISHED"}


STEPS = (
    'Fill in the details below: working folder, ZoneKit mod name, your weapon name and the template.',
    'Press "Create ZoneKit Setup Script". The script path is copied to your clipboard.',
    'In ZoneKit, make sure your mod is selected, then paste the path into the Python bar and run it. '
    'It exports the template weapon\'s files, checks the assets that stay in ZoneKit out into your mod and '
    'renames them to your weapon name. Check the report it writes to the ZoneKit Export folder.',
    'Back in Blender, press Import Weapon in the next panel.',
)


def draw_wrapped(layout, text, width=40):
    column = layout.column(align=True)
    column.scale_y = 0.8
    for line in textwrap.wrap(text, width):
        column.label(text=line)


class STALKER2_PT_animation_importer_help(bpy.types.Panel):
    bl_label = "Instructions"
    bl_idname = "STALKER2_PT_animation_importer_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "STALKER 2"
    bl_parent_id = "ARSENAL_PT_SetupPanel"

    def draw(self, context):
        for number, step in enumerate(STEPS, 1):
            draw_wrapped(self.layout, f'{number}. {step}')
            self.layout.separator(factor=0.3)


class STALKER2_PT_animation_importer(bpy.types.Panel):
    bl_label = "2. Import Weapon"
    bl_idname = "STALKER2_PT_animation_importer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "STALKER 2"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        settings = context.scene.stalker2_animation_importer
        if not settings.animation_root.strip():
            layout.label(text="Set the working folder in 1. Set Up first.", icon="INFO")
        layout.operator("stalker2.import_weapon", icon="IMPORT")
        layout.operator("stalker2.import_new_animations", icon="ADD")
        layout.label(text=settings.scan_summary)


CLASSES = (
    STALKER2_AnimationImporterProperties,
    STALKER2_OT_create_base_skeleton,
    STALKER2_OT_scan_animations,
    STALKER2_OT_import_animations,
    STALKER2_OT_import_weapon,
    STALKER2_OT_import_new_animations,
    STALKER2_PT_animation_importer,
    STALKER2_PT_animation_importer_help,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.stalker2_animation_importer = bpy.props.PointerProperty(
        type=STALKER2_AnimationImporterProperties
    )


def unregister():
    del bpy.types.Scene.stalker2_animation_importer
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()