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

import bpy


PLAYER_PREFIX = "AS_fp_udp_"
WEAPON_PREFIX = "AS_udp_fp_"
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


def _scan_library(root):
    animations_folder = root
    player_folder = os.path.join(animations_folder, "Player")
    weapon_folder = os.path.join(animations_folder, "Weapons")
    if not os.path.isdir(player_folder) or not os.path.isdir(weapon_folder):
        animations_folder = os.path.join(root, "Animations")
        player_folder = os.path.join(animations_folder, "Player")
        weapon_folder = os.path.join(animations_folder, "Weapons")
    if not os.path.isdir(player_folder) or not os.path.isdir(weapon_folder):
        raise FileNotFoundError("Select the STALKER2 folder or its Animations folder, containing Player and Weapons")

    player = _collect_animations(player_folder, PLAYER_PREFIX)
    weapon = _collect_animations(weapon_folder, WEAPON_PREFIX)
    ambiguous = {key for key, paths in player.items() if len(paths) != 1}
    ambiguous.update(key for key, paths in weapon.items() if len(paths) != 1)

    pairs = []
    for key in sorted(player.keys() & weapon.keys()):
        if key in ambiguous:
            continue
        suffix, player_path = player[key][0]
        _, weapon_path = weapon[key][0]
        pairs.append((suffix, player_path, weapon_path))

    player_only = sorted(key for key in player.keys() - weapon.keys())
    weapon_only = sorted(key for key in weapon.keys() - player.keys())
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


def _create_base_skeleton(context, root):
    existing_armatures = [obj for obj in context.scene.objects if obj.type == "ARMATURE"]
    if existing_armatures:
        raise RuntimeError("Base skeleton setup requires a blank scene with no armatures")

    pairs, _, _, _ = _scan_library(root)
    idle_pair = next((pair for pair in pairs if pair[0].casefold() == "idle"), None)
    if idle_pair is None:
        raise RuntimeError("Could not find the matching AS_fp_udp_idle.FBX and AS_udp_fp_idle.FBX files")

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
        character_meshes = [obj for obj in player_objects if obj.type == "MESH"]
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
    strip.extrapolation = "NOTHING"
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

    constraints = []
    try:
        for name, source in claimed.items():
            constraint = master.pose.bones[name].constraints.new("COPY_TRANSFORMS")
            constraint.name = "STALKER 2 animation transfer"
            constraint.target = source
            constraint.subtarget = name
            constraint.owner_space = "LOCAL"
            constraint.target_space = "LOCAL"
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


def _import_pair(context, master, pair):
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

    try:
        player_objects, player_actions, player_rig, player_action = _import_fbx(player_path)
        weapon_objects, weapon_actions, weapon_rig, weapon_action = _import_fbx(weapon_path)
        player_end = _put_action_on_nla(player_rig, player_action)
        weapon_end = _put_action_on_nla(weapon_rig, weapon_action)
        constraints = _copy_bone_transforms(
            master,
            ((player_rig, player_action), (weapon_rig, weapon_action)),
        )

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

        frame_end = max(player_end, weapon_end)
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
    animation_root: bpy.props.StringProperty(name="Animation Root", subtype="DIR_PATH")
    scan_summary: bpy.props.StringProperty(name="Scan", default="Choose the STALKER 2 root folder and scan.")


class STALKER2_OT_create_base_skeleton(bpy.types.Operator):
    bl_idname = "stalker2.create_base_skeleton"
    bl_label = "Create Base Skeleton"
    bl_description = "Build the master rig and camera from the paired idle FBX animations"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            armature = _create_base_skeleton(context, root)
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
            pairs, player_only, weapon_only, ambiguous = _scan_library(root)
        except (OSError, TypeError) as error:
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

    def execute(self, context):
        settings = context.scene.stalker2_animation_importer
        try:
            master = _find_master_armature(context)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        root = bpy.path.abspath(settings.animation_root).strip()
        try:
            pairs, player_only, weapon_only, ambiguous = _scan_library(root)
        except (OSError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.scan_summary = _scan_summary(pairs, player_only, weapon_only, ambiguous)
        if not pairs:
            self.report({"WARNING"}, "No matching animation pairs found")
            return {"CANCELLED"}
        for suffix in player_only:
            self.report({"WARNING"}, f"Character animation found: {suffix}; weapon animation missing")
        for suffix in weapon_only:
            self.report({"WARNING"}, f"Weapon animation found: {suffix}; character animation missing")
        for suffix in ambiguous:
            self.report({"WARNING"}, f"Ambiguous animation suffix skipped: {suffix}")

        successes = 0
        failures = []
        for pair in pairs:
            try:
                _import_pair(context, master, pair)
                successes += 1
            except Exception as error:
                failures.append((pair[0], str(error)))
                self.report({"WARNING"}, f"Failed {pair[0]}: {error}")

        if failures:
            self.report({"WARNING"}, f"Imported {successes}/{len(pairs)} pairs; {len(failures)} failed")
        else:
            self.report({"INFO"}, f"Imported {successes} animation pairs")
        return {"FINISHED"}


class STALKER2_PT_animation_importer(bpy.types.Panel):
    bl_label = "1. Import Assets"
    bl_idname = "STALKER2_PT_animation_importer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "STALKER 2"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        settings = context.scene.stalker2_animation_importer
        layout.prop(settings, "animation_root")
        layout.operator("stalker2.create_base_skeleton", icon="ARMATURE_DATA")
        layout.operator("stalker2.scan_animations", icon="FILE_FOLDER")
        layout.label(text=settings.scan_summary)
        row = layout.row()
        row.enabled = any(
            obj.type == "ARMATURE" and obj.get(BASE_MARKER, False)
            for obj in context.scene.objects
        )
        row.operator("stalker2.import_animations", icon="ACTION")


CLASSES = (
    STALKER2_AnimationImporterProperties,
    STALKER2_OT_create_base_skeleton,
    STALKER2_OT_scan_animations,
    STALKER2_OT_import_animations,
    STALKER2_PT_animation_importer,
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