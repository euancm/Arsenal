# Stalker 2 Arsenal Development Plan

## Goal

Provide a single Blender add-on workflow that takes extracted STALKER 2 first-person assets through animation import, Rigify conversion, and retargeting, producing editable character, weapon, and camera animation.

The intended flow is:

```text
Import STALKER 2 assets
    -> Generate mapping
    -> Convert character by mapping
    -> Create or configure weapon and camera controls
    -> Retarget animation
    -> Edit the resulting actions
    -> Export the edited actions back to STALKER 2 FBX files
```

The Arsenal add-on and the Glock mod are separate deliverables in this repository. The add-on should remain installable on its own from `Stalker2Arsenal_Blender5_2.zip`.

## Current implementation

The following capabilities are implemented and should be preserved:

- Matching STALKER 2 character and weapon FBX animation pairs are imported and baked into Blender actions.
- **Convert Character By Mapping** creates a Rigify character rig and preserves a hidden source-armature backup for later retargeting.
- Retargeting supports Blender 5 layered actions, multiple actions, source frame ranges, matrix-based transforms, finger mappings, and backup restoration.
- Conversion creates a `Weapon` master control from `jnt_offset` and assigns it to a visible `Weapon` bone collection.
- Conversion creates a `Camera` control from `jnt_camera` and reparents the imported camera while preserving the documented transform.
- Appended weapon controls, custom shapes, and constraints can be merged into the generated Rigify armature; the weapon mesh modifier is rebound to that armature.
- Character, weapon, and camera channels can be retargeted into the same action.
- The importer is registered as part of the Arsenal add-on; a separate importer installation is not required.
- The sidebar presents Import, Mapping, Rig & Retarget, and Animation Tools under one **STALKER 2** tab.
- Mapping Setup starts with **Guess mapping from armature**; the mapping table saves edits automatically and no longer exposes mapping/template selectors.
- Blender 5.2.2 was used to validate the unified add-on and documented `reload_tactical` and appended-weapon workflows.
- Mapping UI state lives on `Scene.arsenal_ui` (saved in the .blend); conversion reads the entries from the scene, and JSON presets are only a convenience copy.
- Conversion forces Pose Position on the source/weapon/rig (retargeting does the same) and detaches the source armature's action before renaming bones, because Blender rewrites F-curve paths of the assigned action. The weapon rig is detected by its `Weapon` root bone plus mapping entries, merged into the rig, and its original is kept in the hidden backup collection (`arsenal_weapon_backup_id`).
- Headless tests need a VIEW_3D context override, so run Blender with the GUI and a `bpy.app.timers` callback.
- The merged weapon controls keep their authored world placement (aligned with the weapon mesh). Custom-shape scale is compensated for bone-length differences, since Blender multiplies shape scale (but not translation) by bone length. The `Weapon` root is kept deforming via its edit bone, and bone references are re-fetched after leaving edit mode (they go stale).

## Remaining work

### 1. Add a weapon control editor

- Add an operator and focused panel to create a control from a selected source weapon bone on the generated rig.
- Parent controls under `Weapon`, put them in the `Weapon` bone collection, and configure their custom shape and transform behavior consistently with appended controls.
- Persist the source-bone-to-control mapping on the generated rig using the existing mapping storage.
- Allow users to edit or remove a created control and its mapping without appending a prepared weapon rig.
- Validate with `jnt_magazine`, `jnt_shutter`, and `jnt_trigger`; confirm controls survive save/reopen and retarget into the character action.

### 2. Support arbitrary Blender cameras

- Provide a way to constrain a Blender camera to the generated `Camera` control without requiring the importer-created camera.
- Preserve the current imported-camera parenting and transform behavior.
- Validate camera motion through retargeting and check that constraints do not introduce double transforms.

### 3. Retire obsolete UI and operators

- Audit registrations, panels, menus, and internal call sites before removing legacy operators.
- Remove the Scene Settings and Armature Appearance sections and retire unused template-related UI.
- Keep operators and helpers that are still required internally, even if their user-facing entry points are removed.
- Verify the sidebar contains only the intended workflow and that registration and unregistration complete without errors.

Legacy candidates identified for review:

- Convert UE Character To Rigify
- Generate Metarig From Armature
- Generate Rig
- Bind Rigify Rig To Armature
- Rename Armature Reverse
- Add Prefix and Remove Prefix
- Pose Character To Mannequin Pose and Apply Pose
- Add Unreal Skeleton To Rig
- Reset Rigify and Apply Scale To Rigify

### 4. Run the animation regression matrix

Test these clips in Blender 5.2.2:

```text
reload
reload_tactical
shoot
shoot_aim
idle
idle_aim
equip
unequip
```

Check character and finger motion; weapon, magazine, slide, and trigger controls; camera synchronization; source frame ranges; missing keys; and double or exploding transforms. Repeat the appended-weapon conversion and retarget scenario.

### 5. Finalize the add-on release

- Update the user documentation for creating weapon controls and constraining cameras.
- Rebuild `Stalker2Arsenal_Blender5_2.zip` from `stalker2_arsenal/`.
- Install the ZIP into a clean Blender profile and smoke-test import, mapping, conversion, retargeting, and animation tools.
- Confirm the packaged add-on contains the current implementation and requires no separate importer installation.

### 6. Remove the manual weapon-rig alignment step (implemented)

**Problem.** The user must currently place the weapon rig by hand over the imported weapon animation bones. Mistakes are silent and show up later as an offset weapon in the retargeted actions. Matching individual bones is not an option, because a replacement weapon can have different magazine lengths, bone counts and bone positions.

**Chosen strategy: socket convention.** Every ZoneKit weapon is authored around the same attach origin, and the imported skeleton exposes it as `jnt_offset`. The generated rig already derives its `Weapon` root from `jnt_offset`. The user's weapon rig has a root bone called `Weapon`, which is the only thing that needs to line up. No other bone is compared or moved individually.

**Rule.** The `Weapon` root bone of the user's rig corresponds to `jnt_offset` of the imported skeleton. The add-on moves the weapon rig so the two coincide; bone shapes, counts and lengths are irrelevant.

#### Behaviour

1. Find the weapon rig (existing `find_weapon_armature` / **Weapon rig** picker) and the imported source armature's `jnt_offset`.
2. Compute the world-space rest position of both: `weapon_rig.matrix_world @ Weapon.head_local` and `source.matrix_world @ jnt_offset.head_local`. Use rest values, not posed ones, because the weapon FBX object is animated and imports at scale 100 when scene unit scale is 0.01 (see the importer aim fix).
3. Translate the whole weapon rig by the difference so the `Weapon` head sits on `jnt_offset`. Move the weapon mesh object(s) bound to the rig by the same amount, so mesh, controls and constraints stay consistent. Children keep their positions relative to the root; only the root bone is not moved on its own in edit mode, because that would leave the children behind.
4. Do this automatically at the start of **Convert Character by Mapping**, before `merge_appended_weapon_rig`, and report it ("Moved weapon rig by (x, y, z)"). Also offer a **Snap weapon rig to jnt_offset** button in the Mapping panel for use before conversion.
5. Make it idempotent: if the root is already within tolerance, do nothing. Store the applied offset on the generated rig as a custom property so repeated conversion gives the same result. The original, unmoved rig stays in the hidden **Arsenal Retarget Backups** collection.

#### Safety checks (warn only; never block)

- **Axes.** Compare the `Weapon` root's rest orientation with `jnt_offset`. If they differ by more than about 2 degrees, warn and show the angle. Only translate by default; offer to rotate as well when the user accepts.
- **Scale.** Compare the object scale and unit scale (for example 100 against 1, or the ratio between the weapon mesh and the old weapon). Warn on a ratio other than 1.
- **Sanity.** Warn when the mesh's bounding box does not contain or sit near the `Weapon` root, which suggests the origin was not authored as the socket.
- **Missing pieces.** Clear messages if there is no `Weapon` root, no `jnt_offset`, or several candidate rigs.

#### Open points

- Translate only, or also rotate to match `jnt_offset`? Proposed default: translate, and warn on rotation.
- Tolerance: proposed 1 mm in scene units, so it only skips when it is already exact.
- Should the weapon mesh always move with the rig? Proposed: yes, any mesh with an Armature modifier pointing at the rig.

#### Validation

- Baseline: `Stalker 2 Step Imported Weapon Model and Mapping set.blend`. The snap must change nothing (offset zero within tolerance).
- Copies with the weapon rig and mesh moved or rotated by arbitrary amounts, at scene unit scale 0.01 and 1.0. After the snap, the `Weapon` root must sit on `jnt_offset`, and retargeted `idle`, `idle_aim`, `reload_tactical` and `shoot` must match the baseline.
- A replacement-weapon test: a rig with a longer magazine and extra or missing bones, to confirm only the root is used.
- Confirm save/reopen keeps the stored offset, and that conversion twice gives the same result.

#### Implementation size

Small: one helper (`snap_weapon_rig_to_socket`), one operator and button, one call from the conversion operator, plus the warnings above. Update `doc/converting_to_rigify.md` and the README: authors should create the weapon rig in the new weapon's native ZoneKit frame, with its root bone named `Weapon`.

### 7. Export edited animations back to STALKER 2 FBX files (planned, not started)

**Goal.** After editing the retargeted actions on the Rigify rig, produce one player FBX and one weapon FBX per action, named and structured like the originals (`AS_fp_<weapon>_<action>.FBX` and `AS_<weapon>_fp_<action>.FBX`), carrying the **original STALKER 2 skeletons** (bone names, hierarchy, units, axes) so ZoneKit can import them onto the game skeletons.

**What we already have to build on**

- The pristine source skeleton, with original bone names, is kept in the hidden **Arsenal Retarget Backups** collection. The working source armature is deleted during conversion, so the backup is the only intact copy.
- The mapping (source bone -> rig bone) is stored on the rig (`arsenal_custom_retarget_mapping`) and on `Scene.arsenal_ui`.
- Retargeting is matrix-based and per frame (`apply_retargeted_pose`): `target_world = (source_pose_world @ source_rest_world^-1) @ target_rest_world`. The export is the same maths in reverse: `source_world = target_world @ target_rest_world^-1 @ source_rest_world`.
- Retargeted actions carry `arsenal_source_action` and now have the original action's name, which is the FBX suffix.

**What is missing (these gaps shape the plan)**

1. **The original actions are deleted after retargeting**, so animation on source bones with no mapping (helper bones, armour, bag and similar `jnt_` bones, leaf bones) no longer exists anywhere in the .blend. Export must restore it from somewhere.
2. **The importer merged two FBX skeletons** (player and weapon) into one master armature and removed duplicate bones (`_remove_duplicate_bones`). Nothing records which bone came from which file, so the master cannot yet be split back into two files.
3. **The importer records no file paths.** Each action keeps only its suffix; the library root, weapon name and the player and weapon file paths are lost.
4. **The weapon FBX's root node is animated at object level.** Its armature object follows the player's `jnt_weapon` bone and has animated scale (see the aim fix). The importer reproduces this on `jnt_offset` with world-space constraints and temporary master-scale matching. Export has to invert that exactly, and Blender's FBX exporter writes the armature differently from how the game exports it (an extra node above the root bone).
5. **The FBX importer used `global_scale=100`**, shifts frame 0 to frame 1 and (with the user's 0.01 unit scale) produces objects at scale 100. Export must reverse unit scale, axes and the one-frame offset, or the animation will be 100 times too small or a frame late.
6. **Weapon rig bones are not source bones.** The user's replacement weapon rig has its own bones; they only exist in the game skeleton through the mapping. Export therefore always targets the **original game skeleton**, never the user's rig, and unmapped source bones need a defined behaviour.

#### Strategy

Export in four stages: **record**, **reverse-retarget**, **split**, **write**.

**Stage 1: record source metadata at import (small, and must be done first).**

- On the master armature, store: library root, weapon name, and for each bone its origin (`player` or `weapon`) plus whether the weapon file also contained it (the removed duplicates). Store this as a JSON custom property so it survives save and the backup copy.
- On each imported action, store `arsenal_player_fbx` and `arsenal_weapon_fbx` (paths relative to the library root, including the original subfolders such as `Player/AnimSequences/pt/udp/Idle`), the source frame range and the FBX frame rate.
- Copy these properties from the source action to the retargeted action in `create_output_action`, so they survive the removal of the originals.
- For files imported before this change: rebuild the same data on demand by re-scanning the library folder (the user must point at it) and comparing bone names against the `idle` pair. If the folder is unavailable, fall back to the questions below.

**Stage 2: reverse retarget (rig -> original source skeleton).**

- Work on a temporary copy of the backup armature, never the backup itself.
- For each frame of each action to export, evaluate the rig in the same state the retarget used (FK, IK_FK = 1, forced Pose Position) and write source bone matrices parent-first with the reversed formula above, reusing the depth ordering and the two-pass settle used by the baker.
- Read from the **deforming result** of each mapped bone (the evaluated `DEF-` bone where one exists, otherwise the mapped control), so IK edits, drivers and constraint-driven controls export as the visible pose.
- Unmapped source bones: use the per-bone policy below (original animation by default, otherwise rest pose).
- Key every frame (baked, no simplification) and include the first and last frame of the action range.
- Convert armature-space values back to the file's local frame, undoing the `jnt_offset` world-space override and the master-scale matching done in `_import_pair`.

**Stage 3: split into player and weapon files.**

- Use the recorded bone origins: player bones go to the player FBX, weapon bones to the weapon FBX, duplicated bones to both.
- Each file contains only an armature (and no meshes, unless the questions below say otherwise) whose bones, names, parenting, rest pose and roll equal the original FBX's. Build it from the backup/skeleton records, not from the Rigify rig.
- The weapon file's root-node (object-level) motion is written back as the root node's animation so the game sees the same hierarchy it exported.

**Stage 4: write the FBX files.**

Two options, chosen after the Phase 0 test:

- **A. Blender's FBX exporter (recommended to start).** Armature only, `add_leaf_bones=False`, `bake_anim=True` with force start/end keying, no NLA strips, only the current action, no simplification, `global_scale` and `apply_unit_scale`/`apply_scale_options` set to undo the import scale, axes matching the importer. Name the armature object so the exported root node matches the original. Cheap, and no extra dependencies.
- **B. Patch the original FBX.** Read the original file for each action and replace only the animation curves for the edited bones, leaving every other node, unit, axis and property untouched. Highest fidelity and guaranteed hierarchy, but needs an FBX reader/writer (Autodesk FBX SDK Python bindings or a small binary-FBX writer) and an extra dependency to ship in the add-on.
- Decision rule: use A unless Phase 0 shows ZoneKit rejects the result or the hierarchy/units cannot be made to match; then go to B (or a hybrid: use B only for the weapon file's root node).

#### Interface

- Add an **Export** section to the STALKER 2 tab, after **Rig & Retarget**:
  - **Output folder**, plus an option to mirror the original relative subfolders (default on).
  - **Weapon name** and **Library folder** shown read-only from the import (stored values), with an edit button when they are missing.
  - An **action list** (UIList): a checkbox, the action name, a status icon (unchanged / edited since import / new / warning), and the two file names that will be written.
  - **Select all / none / only edited**.
  - **Unmapped bones**: *Keep original animation* (needs the library) / *Rest pose*.
  - **Overwrite**: *Ask* / *Always* / *Skip existing* (and a safeguard that refuses to write into the library folder itself unless confirmed).
  - Buttons: **Validate** (dry run: reports bones, frame ranges, scale checks and missing metadata without writing), **Export selected**, **Open output folder**.
- Detect "edited since import" from a hash of the action's F-curves stored when the action is retargeted. Unedited actions are skipped by default.
- Move **Weapon name** into a shared header used by Import and Export, so both always agree.
- Allow a new action (not in the original set) to be exported: it needs a valid suffix and a template (copy the `idle` pair's subfolders).
- Report progress and a summary per action; failures name the action and the reason and never leave half-written files (write to a temp name, then rename).

#### Questions for the user

1. **How does ZoneKit take the FBXs back?** Which import path do you use (Asset Actions > Import, drag and drop, bulk import), and does it import onto the existing player and weapon skeleton assets? Is there anything it rejects (an extra root node named `Armature`, scale, a bone not in the skeleton, a different frame rate)?
The FBXs are simply dropped into the zonekit. I have tested this with "AS_fp_udp_reload.fbx", including renaming it to "Test Import.fbx" beforehand, and it works as expected.
2. **Do you have a known-good non-original FBX** (any Blender-exported animation that ZoneKit imported successfully) so we can copy its export settings?
I have imported "AS_fp_udp_reload.fbx" using the standard blender fbx importer and edited it so one of the fingers sticks out. I have successfully reimported it into the zonekit with no error messages.
3. **Will the original FBX library stay available** next to the project? It would let us restore unmapped-bone animation and the exact skeleton, and to compare results. If not, we use rest pose for unmapped bones and the skeleton must be stored inside the .blend.
Yes
4. **Output layout:** mirror the original subfolders, a flat folder, or straight into the mod's `Source FBX Files` structure? Where should files go by default?
Mirror the original subfolders
5. **What goes into the FBX:** armature plus animation only, or also the character and weapon meshes as in the originals (and, if so, which)?
Armature plus animation only
6. **Which actions:** every action, only edited ones, or whichever are ticked? Do you need to export brand-new actions?
Whichever actions are ticked - this allows the user to keep work in progress or utility actions without affecting export. It is likely that there will be brand new actions.
7. **Frame rate and range:** keep the original FBX frame rate and length, or let the user change the length (frame range of the edited action)?
The frame rate should be kept. If the user has edited the action length (e.g changing an "equip" from 60 frames to 90 frames) this should be allowed. The goal of the addon is to facilitate entirely new weapons and animations.
8. **Camera:** is `jnt_camera` motion (the `Camera` control) the only camera data the game needs, or do the FBXs contain a separate camera node?
Yes, jnt_camera is all it needs.
9. **IK or FK edits:** is it fine to bake the visible pose, so IK edits become plain keys on the game skeleton? (Expected: yes.)
Yes.
10. **Replacement weapon:** confirm that the exported animation targets the **original** game weapon skeleton, and the new weapon's mesh is skinned to it separately (so none of the user's own weapon bones ever appear in the exported FBX).
Yes

#### Phases

- **Phase 0: feasibility spike (no add-on changes).** In a scratch script, take one action (`idle`, `unequip` and `reload_tactical`), reverse-retarget it to a copy of the backup, write FBXs with the Blender exporter, and re-import them with the existing importer. Compare with the original baked action, and import the files into ZoneKit once. Measure: axis, unit and frame-offset errors; hierarchy differences against the original FBX; the weapon root-node behaviour. This decides A or B in Stage 4 and settles questions 1, 2 and 5.
- **Phase 1: metadata.** Stage 1 (importer and retarget changes, plus the legacy-rebuild helper). No export yet.
- **Phase 2: reverse retarget.** Stage 2 as a function that returns baked source-skeleton actions; round-trip tested without any FBX.
- **Phase 3: split and write.** Stages 3 and 4 with an operator and no UI beyond a single button.
- **Phase 4: interface.** The Export section, list, validation, overwrite handling and progress.
- **Phase 5: docs and release.** New `doc/exporting_animations.md`, README workflow, rebuild the ZIP and smoke-test from a clean profile.

#### Validation

- **Round trip (automated).** For all 32 actions: import -> convert -> retarget -> export (no edits) -> re-import the exported pair with the existing importer -> compare to the original baked action. Pass: mapped bones within 0.1 cm and 0.1 degrees on every frame; unmapped bones identical when the library is available.
- **Edit test.** Move the right hand and the magazine control in `reload_tactical`, export, re-import, and check that only the expected bones differ and that the weapon stays aligned (this is where the weapon-root and `jnt_offset` handling is most exposed).
- **Structure test.** Dump the node and bone list of the exported and the original FBX; names, hierarchy, bone count, frame range and frame rate must match. Check the weapon file's root node and object-level scale and position.
- **Unit and scale test** at scene unit scale 0.01 and 1.0 (exported values must be the same either way), plus a frame-offset check (first exported frame is time 0).
- **Pose-state test.** Export with the rig in Rest Position and with IK_FK set to IK; results must be identical to FK Pose Position.
- **Game test.** Import the exported `idle`, `unequip` and `reload_tactical` pairs into ZoneKit, package the mod and verify the animations in game with no distorted wrists or offset weapon.
- **Failure handling.** Missing metadata, missing library folder, unwritable output folder, name clashes, and an action with no keys must each give a clear message and no partial files.

#### Risks

- The weapon root-node mismatch (Blender writes an extra `Armature` node; the original root animates at object level). It is the main reason Phase 0 comes first.
- Bone roll and axis conventions on export can differ from the original (visible as rotated bones in ZoneKit even when Blender looks right). The structure test catches this.
- Frame 1 convergence: the export uses the same settle passes as the baker; keep them in step.
- If the exported FBX is not accepted, option B is a larger piece of work, because it adds a dependency.

## Acceptance criteria

- Import the UDP skeleton and animations, generate a mapping, and convert the character by mapping.
- Generate the `Weapon` and `Camera` controls; create additional weapon controls as needed.
- Retarget at least the reload workflow so character, weapon, and camera controls are editable in the resulting action.
- Preserve source frame ranges and avoid missing keys, double transforms, and exploding transforms.
- Keep the imported source backup available for later retargeting.
