# STALKER 2 Animation Importer

Developer documentation for the importer module integrated into Stalker 2 Arsenal (`stalker2_arsenal/stalker2_animation_importer.py`). It creates a base first-person rig from paired idle FBXs, then combines matching character and weapon animation pairs into actions on that rig.

## Requirements and Scope

- Blender with the FBX importer enabled. The minimum supported version is Blender 5.2.2; earlier versions are not supported.
- The asset directory must contain `Animations/Player` and `Animations/Weapons`. The add-on accepts either the folder containing `Animations`, or the `Animations` folder itself.
- The base-skeleton operation is designed for a blank scene. It refuses to run if the active scene already contains an armature.
- The add-on imports animation and the character mesh included in the character idle FBX. It does not import weapon meshes or build a material setup.
- No third-party Python packages are required.

## Installation and Quick Start

1. In Blender, install and enable **Stalker 2 Arsenal** from Preferences. The importer is included.
2. Start from a new Blender scene. The base-skeleton operation requires that the scene contain no armatures.
3. In **3D View > Sidebar > STALKER 2 > 1. Import Assets**, set **Animation Root** to either the `_STALKER2` directory or its `Animations` subdirectory.
4. Click **Create Base Skeleton**. This imports the character and weapon idle FBXs, joins their rigs, retains the character mesh, and creates the camera.
5. Click **Scan Animations** to see the number of matching pairs and any unmatched or ambiguous suffixes.
6. Click **Import All** to build one action per matching pair.
7. Save the `.blend` file after reviewing the generated actions and scene.

The tested workspace produced a 120-bone armature, one retained character mesh, one camera, and 32 animation actions. The supplied library also has four unmatched animations.

## Asset Layout and Pairing

The scanner recursively visits:

```text
Animations/Player/**/*.FBX
Animations/Weapons/**/*.FBX
```

It identifies files by filename stem, not by directory name:

| Side | Prefix | Example | Pair key |
| --- | --- | --- | --- |
| Character | `AS_fp_udp_` | `AS_fp_udp_reload.FBX` | `reload` |
| Weapon | `AS_udp_fp_` | `AS_udp_fp_reload.FBX` | `reload` |

Matching is case-insensitive. Suffixes are compared after `casefold()`, and the character-side spelling is used for the generated action name. Matching suffixes present on both sides form pairs. A suffix with more than one file on either side is ambiguous and skipped. A suffix found on only one side is reported and skipped.

The idle pair used to create the base skeleton is found through the same scan and must have the suffix `idle`. The exact expected files are `AS_fp_udp_idle.FBX` and `AS_udp_fp_idle.FBX`.

## Base Skeleton Creation

The **Create Base Skeleton** operator calls `_create_base_skeleton` and performs these operations:

1. Refuses to proceed if the scene already contains an armature.
2. Locates the matching idle pair and imports each FBX with `global_scale=100` and `use_custom_normals=False`.
3. Captures the imported objects and actions so cleanup only affects data created by this operation.
4. Clears the idle actions from both source rigs.
5. Deletes weapon-rig bones whose names already exist in the character rig. The character rig owns the hand bones; the weapon rig contributes the unique weapon bones.
6. Joins the weapon rig into the character rig, using the character armature as the destination. The provided files produce 120 bones after this join.
7. Renames the armature and its data to `STALKER 2 Master Armature` and `STALKER 2 Master Skeleton`.
8. Clears armature animation data and resets all pose-bone location, rotation, and scale channels to their identity values.
9. Sets the armature and retained character mesh object scales to `(1, 1, 1)`. The mesh remains linked to the armature through its existing parent and Armature modifier.
10. Removes weapon-side meshes and other temporary imported objects, the imported idle actions, and the default startup objects named `Camera`, `Cube`, and `Light`.
11. Creates and activates a camera parented to the `jnt_camera` bone.

All mesh objects imported from the character idle FBX are retained. In the supplied assets this is `SK_stalker`. Weapon-side mesh objects are removed. The mesh is not joined to the armature or otherwise altered beyond setting its object scale to identity.

### Camera Configuration

The active camera is named `STALKER 2 First Person Camera` and has these settings:

| Property | Value |
| --- | --- |
| Parent type | Bone |
| Parent bone | `jnt_camera` |
| Local location | `(0, 0, 0)` |
| Local Euler rotation | `(90°, 0°, 0°)` |
| Lens | `18 mm` |
| Sensor fit / width | Horizontal / `36 mm` |
| Clip range | `0.01` to `10000` Blender units |

The 90-degree X rotation converts the camera bone's forward +Y axis to Blender camera forward (-Z). Change `_create_camera` if the source rig's camera-bone orientation changes.

When the character is converted to Rigify, the camera is reparented to the generated `Camera` control with local location `(0, 0, 0)`, local rotation `(90°, 0°, -90°)`, and unit scale.

## Animation Import Pipeline

**Import All** finds the base armature by the custom property `stalker2_base_skeleton`; users do not select a destination armature in the panel. Exactly one tagged armature must exist in the current scene.

Each pair is processed independently:

1. Import the character FBX and weapon FBX with `global_scale=100` and `use_custom_normals=False`.
2. Get each source armature's active action and place that action on a new NLA track. Each strip begins at frame 1 and uses `REPLACE` blending, so both source rigs evaluate simultaneously.
3. Determine animated bone names from action F-curves. If curves are not exposed through the legacy API, the code attempts Blender's layered-action channel bags; if no curve names can be read, it falls back to all bone names shared by source and destination.
4. Add a local-space **Copy Transforms** constraint on each matching master pose bone, targeting the same-named bone on the corresponding imported source armature.
5. When both files animate the same bone, the first source wins. The character source is supplied first, so character transforms take priority for shared hands; weapon transforms are used for weapon-specific bones.
6. Select the master armature and run `bpy.ops.nla.bake` with visual keying, all pose bones, constraint clearing disabled, and curve cleaning enabled. The bake starts at frame 1 and ends at the longest imported action duration.
7. Name the baked action with the shared suffix and set `use_fake_user=True`, so it remains in the file when not assigned.
8. Remove temporary constraints, source armatures, source meshes, and imported source actions. Restore the user's active object, selection, frame, and prior master action/NLA state.

The action combination intentionally uses NLA evaluation and Bake Action. It does not merge F-curves mathematically, perform IK retargeting, or remap differently named bones.

## Actions, Collisions, and Errors

Generated actions carry the custom property `stalker2_animation_importer`. If an action with the requested suffix already exists:

- An unmarked action is treated as user data; that pair fails rather than overwriting it.
- A marked action may be replaced only when it is not in use. An in-use generated action is left unchanged and that pair fails.

Import All continues after a pair-level failure and reports the suffix and error. Scanning reports unmatched and ambiguous suffix counts. Base creation reports an error when the root is invalid, the idle pair is missing, the scene already has an armature, or the character skeleton lacks `jnt_camera`.

The final scene objects are cleaned per pair. The add-on removes imported actions even if the FBX importer assigns them a fake user. It does not perform a global purge of unrelated orphaned materials or images.

## User Interface and Internal API

The panel is registered as `STALKER2_PT_animation_importer` in **View3D > Sidebar > STALKER 2**. Scene settings are registered under `scene.stalker2_animation_importer`:

| Setting | Purpose |
| --- | --- |
| `animation_root` | Directory path used for discovery and imports |
| `scan_summary` | Last scan result displayed in the panel |

Operators:

| Operator | Purpose |
| --- | --- |
| `bpy.ops.stalker2.create_base_skeleton()` | Build the idle-derived armature, retain the character mesh, and create the camera |
| `bpy.ops.stalker2.scan_animations()` | Scan and report matching, unmatched, and ambiguous files |
| `bpy.ops.stalker2.import_animations()` | Import and bake all matching pairs onto the tagged armature |

Core helpers are module-level functions to keep the import, bake, and cleanup behavior testable: `_scan_library`, `_create_base_skeleton`, `_import_fbx`, `_put_action_on_nla`, `_copy_bone_transforms`, `_bake_parameters`, and `_import_pair`.

Custom-property markers:

| Marker | Stored on | Purpose |
| --- | --- | --- |
| `stalker2_base_skeleton` | Generated armature and camera | Identify the generated base rig and camera |
| `stalker2_animation_importer` | Generated actions | Distinguish replaceable add-on actions from user actions |

## Developer Verification

The complete workflow was tested headlessly with Blender 5.2.2 using the provided idle FBXs and `jnt_root` structure. The integration test started from factory startup, ran the three operators, and verified:

- The base armature has 120 bones and object scale `(1, 1, 1)`.
- `SK_stalker` remains in the scene, parented to the master armature with an Armature modifier targeting it.
- No weapon mesh or imported `Unreal Take` actions remain after base creation.
- The camera is parented to `jnt_camera` and active in the scene.
- All 32 matching animation pairs produce actions.
- The final scene contains only the master armature, `SK_stalker`, and the generated camera.

To reproduce interactively from Blender's Python Console after enabling the add-on:

```python
settings = bpy.context.scene.stalker2_animation_importer
settings.animation_root = r"D:\path\to\_STALKER2\Animations"
bpy.ops.stalker2.create_base_skeleton()
bpy.ops.stalker2.scan_animations()
bpy.ops.stalker2.import_animations()
```

For automated tests, run Blender with `--background --factory-startup --python-expr`, register/import the add-on, set the animation root, then call the same operators. Use a disposable session or a copy of a `.blend` file: test imports modify the open scene in memory.

## Known Limitations

- Only the `udp` first-person filename prefixes are recognized.
- The base builder uses the idle pair and assumes its character rig includes `jnt_camera`.
- The generated rig is a same-name skeleton join, not a general skeleton merge or retargeting system.
- Shared animated bones are resolved by source order, with the character source taking precedence.
- There is no import-selected UI, weapon mesh import, attachment setup, material setup, or export workflow.
- Blender 5.2.2 is the minimum supported and verified runtime.
