# STALKER 2 Animation Importer

Developer documentation for the importer module integrated into Stalker 2 Arsenal (`stalker2_arsenal/stalker2_animation_importer.py`). It creates a base first-person rig from paired idle FBXs, then combines matching character and weapon animation pairs into actions on that rig.

## Requirements and Scope

- Blender with the FBX importer enabled. The minimum supported version is Blender 5.2.2; earlier versions are not supported.
- The asset directory must contain `Animations/Player` and `Animations/Weapons`. The add-on accepts either the folder containing `Animations`, or the `Animations` folder itself.
- The base-skeleton operation is designed for a blank scene. It refuses to run if the active scene already contains an armature.
- These operators import animation and the player's first-person body. Setup exports the textured body `SK_pla_sel_07` next to the animations; exports made before it fall back to the bare `SK_stalker` preview mesh included in the character idle FBX. Weapon meshes and materials are imported by **Import Weapon** (see "Attachments, sockets and textures").
- No third-party Python packages are required.

## Installation and Quick Start

Existing weapon sockets can also be edited as named Empty markers. See
[weapon sockets without opening SKEL](weapon_sockets.md) for authoring, catalogue
refresh, reset and socket-only ZoneKit imports.

1. In Blender, install and enable **Stalker 2 Arsenal** from Preferences. The importer is included.
2. Start from a new Blender scene. The base-skeleton operation requires no existing armatures;
   **Import Weapon** manages its temporary weapon rig internally.
3. In **3D View > Sidebar > STALKER 2 > 1. Set Up**, choose the template, enter your weapon name, the ZoneKit mod name and a working folder, then run the generated ZoneKit setup script (see the README). That fills **Exported Files** (`<working folder>/ZoneKit Export`, the folder containing `_STALKER2` and `_Stalker_2`), the template animation name (for example `udp`, or `viper` for the SMG) and the template mesh name (`vip` for the SMG; empty when it matches the animation name).
4. Click **Import Weapon** in panel 2. One click runs the whole setup: it imports `SK_<mesh name>.FBX` and the `AnimMesh/SM_*_<mesh name>_SM_*.FBX` parts (placed, weighted to their bones, joined into one mesh named after the donor; rename it to your new weapon, with bone shapes and red colours applied), creates the base skeleton and camera, imports every matching animation pair, guesses the character and weapon mappings and converts the character to a Rigify rig. Replace or edit the mesh and bones as needed.
5. Retarget the animations from panel 3. Keyframes are cleaned automatically afterwards.
6. Save the `.blend` file after reviewing the generated actions and scene.

There is no **Import New Animations** button or registered operator. Normal projects import the
template's matching clips in one pass. The internal `import_new_animations` development helper
is retained for regression work on disposable converted blends; it leaves existing actions alone.

The individual operators (Import Rigged Weapon, Create Base Skeleton, Scan Animations, Import All, the guess buttons) still exist but are no longer shown in the panel. Fingers are in separate `Fingers.L` / `Fingers.R` bone collections (plus Detail collections).

For the pistol (UDP) this gives a 120-bone armature, one retained character mesh, one camera and 37 animation actions, with no unmatched files.

## Asset Layout and Pairing

The scanner recursively visits:

```text
Animations/Player/**/*.FBX
Animations/Weapons/**/*.FBX
```

It identifies files by filename stem, not by directory name:

| Side | Prefix | Example | Pair key |
| --- | --- | --- | --- |
| Character | `AS_fp_<name>_` | `AS_fp_udp_reload.FBX` | `reload` |
| Character (offset aim) | `AS_FP_Player_<name>_` | `AS_FP_Player_Udp_IdleToOffsetAim_01.FBX` | `IdleToOffsetAim_01` |
| Weapon | `AS_<name>_fp_` | `AS_udp_fp_reload.FBX` | `reload` |

Matching is case-insensitive. Suffixes are compared after `casefold()`, and the character-side spelling is used for the generated action name. Matching suffixes present on both sides form pairs. A suffix with more than one file on either side is ambiguous and skipped.

The known `idle_aim_to_idle` / `aim_to_idle` naming variation is paired as one transition,
using the original character-side action name and both original donor file paths. It is
not imported as two actions with idle stand-ins. Duplicate files under either spelling
remain ambiguous rather than being selected arbitrarily.

Leftover halves that differ only by a trailing number, one character and one weapon (`sight_holographic_attach_BuckGrenLaunch2` and `sight_holographic_attach_BuckGrenLaunch` on the M16), are paired as a **variant pair** (`is_variant_pair`). The character-side suffix names the action, and the baked action records both file names (`stalker2_source_pair`). Export writes each half under its own donor file name. Actions baked before variant pairing used an idle stand-in for the missing half and lack this record. Export skips them with a warning, so delete the action, then import and retarget it again.

A suffix found on only one side (`idle_boltlock` and `break_bullet_idle` are weapon-only, the offset aim clips character-only) is paired with the other side's `idle` as a **stand-in** (`stand_in_half`). The bake runs for the real half's length, and export writes only the real half. `*_add` keys have no stand-in: those additive idles are rebuilt by the ZoneKit import script and stay unpaired.

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
10. When the export contains `_STALKER2/SkeletalMeshes/player/sel/sel_07/SK_pla_sel_07.glb` (exported as glTF because FBX export of this mesh crashes ZoneKit), imports that textured body, bakes its bind pose into the master's rest pose, parents it to the master with an Armature modifier and applies its textures from `materials.json`. It then replaces the preview mesh. The body's colour textures also drive the material's alpha, so thin cards such as the clothing threads show correctly. If the body cannot be imported, or comes in at the wrong size, the preview mesh is kept and a warning explains why.
11. Removes weapon-side meshes and other temporary imported objects, the imported idle actions, and the default startup objects named `Camera`, `Cube`, and `Light`.
12. Creates and activates a camera parented to the `jnt_camera` bone.

With the body export, the scene keeps one character mesh, `SK_pla_sel_07`. Older exports keep the mesh objects imported from the character idle FBX (`SK_stalker`, untextured), which are not joined to the armature or otherwise altered beyond setting their object scale to identity. Run setup again to export the body for an existing project. Mesh skinning is paused while animations are baked, so the denser body does not slow imports or retargeting.

### Camera Configuration

The active camera is named `STALKER 2 First Person Camera` and has these settings:

| Property | Value |
| --- | --- |
| Parent type | Bone |
| Parent bone | `jnt_camera` |
| Local location | `(0, -bone.length, 0)` (bone head) |
| Local Euler rotation | `(90°, 0°, 0°)` |
| Lens | `18 mm` |
| Composition guide | Center |
| Sensor fit / width | Horizontal / `36 mm` |
| Clip range | `0.01` to `10000` Blender units |

The 90-degree X rotation converts the camera bone's forward +Y axis to Blender camera forward (-Z). Change `_create_camera` if the source rig's camera-bone orientation changes.

Blender bone parenting places a zero-offset object at the bone tail. The negative local Y
offset cancels that displacement so the preview eye follows the animated bone head, matching
the exported camera joint rather than introducing a sideways iron-sight offset.

When the character is converted to Rigify, the camera is reparented to the generated `Camera`
control with local location `(0, -bone.length, 0)`, local rotation `(90°, 0°, -90°)`, identity
parent inverse and unit scale.

Existing saved scenes are not changed automatically. For a previously imported camera, set
its local Y location to the negative length of its parent bone (local X and Z remain zero).
Keep the existing camera rotation and do not offset the animated bone or `CameraSocket` to
compensate for this preview issue.

## Animation Import Pipeline

**Import All** finds the base armature by the custom property `stalker2_base_skeleton`; users do not select a destination armature in the panel. Exactly one tagged armature must exist in the current scene.

Each pair is processed independently:

1. Import the character FBX and weapon FBX with `global_scale=100` and `use_custom_normals=False`.
2. Get each source armature's active action and place that action on a new NLA track. Each strip begins at frame 1 and uses `REPLACE` blending, so both source rigs evaluate simultaneously.
3. Determine animated bone names from action F-curves. If curves are not exposed through the legacy API, the code attempts Blender's layered-action channel bags; if no curve names can be read, it falls back to all bone names shared by source and destination.
4. Add a local-space **Copy Transforms** constraint on each matching master pose bone, targeting the same-named bone on the corresponding imported source armature.
5. When both files animate the same bone, the first source wins. The character source is supplied first, so character transforms take priority for shared hands; weapon transforms are used for weapon-specific bones.
6. Temporarily reveal the master armature if it is hidden (after conversion it sits in the hidden **Arsenal Retarget Backups** collection, and a hidden object is not evaluated), select it and run `bpy.ops.nla.bake` with visual keying, all pose bones, constraint clearing disabled, and curve cleaning enabled. The bake starts at frame 1 and ends at the longest imported action duration (for a stand-in pair, the real half's duration).
7. Name the baked action with the shared suffix and set `use_fake_user=True`, so it remains in the file when not assigned.
8. Remove temporary constraints, source armatures, source meshes, and imported source actions. Restore the user's active object, selection, frame, and prior master action/NLA state.

The action combination intentionally uses NLA evaluation and Bake Action. It does not merge F-curves mathematically, perform IK retargeting, or remap differently named bones.

## Actions, Collisions, and Errors

Generated actions carry the custom property `stalker2_animation_importer`. If an action with the requested suffix already exists:

- An unmarked action is treated as user data; that pair fails rather than overwriting it.
- A marked action may be replaced only when it is not in use. An in-use generated action is left unchanged and that pair fails.

Import All continues after a pair-level failure and reports the suffix and error. Scanning reports unmatched and ambiguous suffix counts. Base creation reports an error when the root is invalid, the idle pair is missing, the scene already has an armature, or the character skeleton lacks `jnt_camera`.

The final scene objects are cleaned per pair. The add-on removes the actions created by each FBX import even if they have a fake user or another user; some Blender setups give them a stray Scene user, and a surviving raw take (`jnt_root|Unreal Take|Base Layer.001` and similar) keys object transforms. It does not perform a global purge of unrelated orphaned materials or images.

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

The development-only helper `import_new_animations(context, rig, backup, root, weapon_name)` imports and retargets only the pairs a converted blend has no action for; it has no operator or button.

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
- Every matching animation pair produces an action.
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

- Files are matched using the importer's **template animation name**, set by panel 1, as
  `AS_fp_<name>_*` and `AS_<name>_fp_*`. Do not replace that donor token with the custom
  weapon's display name.
- The base builder uses the idle pair and assumes its character rig includes `jnt_camera`.
- The generated rig is a same-name skeleton join, not a general skeleton merge or retargeting system.
- Shared animated bones are resolved by source order, with the character source taking precedence.
- These operators handle animation only; weapon meshes, attachments and materials are imported by **Import Weapon** (see below), and export is covered in [Exporting animations](exporting_animations.md).
- Blender 5.2.2 is the minimum supported and verified runtime.


Note: weapon-rig root motion (`jnt_offset`) is baked in world space so aim poses (`idle_aim`, `aim_to_idle`, `idle_to_aim`) align.

### Bone shapes

Each weapon bone is given the most specific matching library shape. Family words such as
`pistol`, `shotgun`, `rifle`, `smg` and `sniper` restrict a shape to that donor family;
shapes without a family word are shared. A base shape is only used for the `Weapon`
control, never a magazine bone such as `jnt_clip_base`. For example, a shotgun gets
the shotgun base and magazine shapes rather than the pistol versions.

Shapes are read from `stalker2_arsenal/shapes/weapon_bone_shapes.blend`: to add one,
save a mesh named `customboneshape_<family>_<part>` or `customboneshape_<part>` into
that file. Bones with no appropriate shape keep Blender's default display; additional
rifle and sniper shapes still need to be supplied.


## Attachments, sockets and textures

The ZoneKit setup script exports the chosen template's configured magazines, silencers,
lasers, iron sights, compatible scopes and underbarrel weapons, and preinstalled parts,
including the M860's default pump grip. It also
exports the weapon's sockets (`weapon_sockets.json`) and every exported mesh's material
textures (`Textures/` and `materials.json`). The attachment catalogue comes from the
game's weapon and attachment definitions, including each mesh's exact mounting socket.

Import Weapon only reads attachments belonging to the current donor, even if an export
folder contains files left by another template. A mesh named after another weapon may
still be valid when the game explicitly shares it: for example, Dnipro's increased
magazine references an AK74 mesh.

Direct bone-mounted attachments use an Armature modifier and the configured bone, such as
`jnt_magazine` or `jnt_clip_base`. Named mounts use the catalogue's complete reference-bone and socket
transforms, including rotation and scale. Different laser models can use `LaserSocket`
and `LaserSocket2`; they are not all placed at the first laser socket. Missing named
sockets or a catalogue from another donor stop import with an error.
Named-socket previews follow their marker live, with the armature deformation disabled
to avoid applying bone animation twice. Inventory and world-mesh snapshots exclude the
current animation pose but retain authored socket edits.

The attachment list is populated on a fresh import: default iron sights use editable custom
meshes, and other items default to **Reference Existing**. Optional meshes start hidden.
Skeletal underbarrel assets are imported as rigid previews without retaining their source
armatures, and are not duplicated into the mod by setup. Spare rounds parked beside the
launcher in its mesh (the M203's `jnt_m406_*` and `jnt_vog25_charge` bones) are left out of
the preview. Existing edits and attachment lists
are not replaced. See [Attachment configuration](cfg_export.md).

**After updating, regenerate and run the ZoneKit setup script for the selected template
before importing into a new Blender scene.** Previously generated scripts do not include
the new attachment list; old exports may be missing sights, pump grips or shared magazines.
Missing configured attachment files stop import before a weapon rig is created and identify
the files to re-export. Keep existing edited projects safe rather than importing over them.

Collision (`UCX_`) meshes and lower LODs are skipped. Materials are built from `materials.json`.
Nanite meshes are exported with Nanite temporarily off so the full-detail mesh is written
rather than the reduced fallback.

Meshes import with smooth shading and their original hard edges (kept as Sharp Edge marks; the FBX custom normals are dropped so the mesh stays editable). If the FBX carries none, the edges on UV island boundaries are marked sharp. Textures named `rain` are skipped; an `RMA` texture goes through a Split Colour node (red to Roughness, green to Metallic). Import Weapon also fills the Magazines list (Detect Magazines); silencers, lasers and other accessories are never detected as magazines.

Configured magazine meshes (default, increased/big/twin; full and empty, excluding half
variants) are exported from ZoneKit and imported; Detect Magazines names the standard
one Default and the others Increased/Twin/Drum. Normal Map nodes are set to the DirectX convention.

Montages: Python cannot edit montage slot tracks; rebuilding a montage with AnimMontageFactory
loses its slot name, notifies and length, and consolidate_assets on /Game assets crashes ZoneKit
(do not use it). Instead the setup script patches the name tables of the mod's own copies
(montages, sequences, the AnimCollection, the AnimBP and the skeletal mesh) so they reference
each other rather than the /Game originals (slots, sections, notifies and graphs are preserved),
then reloads them. Backups go to `<export folder>\reference_backups`. The weapon prototype also
points at the mod's own skeletal mesh. Fresh import scripts recover missing copies and repair
references before importing Blender assets; see [setup recovery](cfg_export.md#recovering-missing-zonekit-setup).
The importer can separately update attachment-notify SIDs without rebuilding montage tracks;
see [animation montages](exporting_animations.md#animation-montages).
