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

## Acceptance criteria

- Import the UDP skeleton and animations, generate a mapping, and convert the character by mapping.
- Generate the `Weapon` and `Camera` controls; create additional weapon controls as needed.
- Retarget at least the reload workflow so character, weapon, and camera controls are editable in the resulting action.
- Preserve source frame ranges and avoid missing keys, double transforms, and exploding transforms.
- Keep the imported source backup available for later retargeting.
