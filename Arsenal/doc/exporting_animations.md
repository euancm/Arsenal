# Exporting animations

The **5. Export** panel turns the actions on the Rigify rig back into STALKER 2 FBX files that use the original game skeletons (a player FBX and a weapon FBX per action).

## Steps

1. Select the generated rig (the one with the hidden retarget backup).
2. Enter the weapon's English **Name** (4. Create Your Custom Weapon > Name & Description); the weapon name used in file and folder names is made from it (lowercase, letters and digits only, e.g. "Cool Pistol" becomes `coolpistol`). In the Export panel set the **Mod Name** (the name of your mod in ZoneKit) and choose an **Output Folder**. The library folder and the original weapon name are taken from the import panel, so keep them set.
3. Press **Refresh**, then tick the actions to export (**All** / **None** help). New actions are listed too.
4. Optional, for the highlighted action:
   - **Template**: the original animation to copy the skeleton and unmapped bones from. Empty means the animation with the same name, or `idle` for a new action.
   - **Folder**: the category folder below the weapon folder, for example `Reload/TwoHands`. Empty copies the template folder.
5. **Validate** checks everything and prints the files it would write (see the system console). **Export All** writes the animations, the static meshes (see below), the CFG files and the import script.

**Export All** shows one completion popup. Its title distinguishes success, warnings and failure;
details remain in Blender's report log and system console. Imports and retargeting use the same
notifications. Background Blender runs print completion instead of opening a popup.

## Keeping edited animations correct on export

**If a control's pose matters in an animation, key it in that animation.** A pose that looks right
in the viewport is not necessarily stored in the selected action.

Blender can keep an unkeyed control where you left it while editing another action. Export treats
each action independently and resets unkeyed transforms to rest, so one animation's changes do not
leak into the others. This can make a hand jump away from the gun or an elbow bend differently in
the FBX, even though the viewport looked correct.

### Which controls need keys?

For an arm using IK, check these controls on the generated Rigify rig. `.L` and `.R` mean the
character's left and right, not the left and right of the screen.

| Purpose | Left arm | Right arm | What to key |
| --- | --- | --- | --- |
| Hand position and orientation | `hand_ik.L` | `hand_ik.R` | Location, Rotation and Scale |
| Upper-arm IK orientation and scale; affects the elbow bend | `upper_arm_ik.L` | `upper_arm_ik.R` | Location, Rotation and Scale |
| Elbow pole target, when used | `upper_arm_ik_target.L` | `upper_arm_ik_target.R` | Location, Rotation and Scale |
| Selects FK or IK | `upper_arm_parent.L` | `upper_arm_parent.R` | The **IK/FK** custom property |

On this Rigify rig, **IK/FK = 0 is IK; 1 is FK**. Intermediate values blend them.
Keying that switch does **not** key the hand, upper-arm or pole-target transforms.

If you edit a leg using IK, the equivalent controls are `foot_ik.L/R`, `thigh_ik.L/R` and
`thigh_ik_target.L/R`, with the IK/FK switch on `thigh_parent.L/R`.

Also key anything else you deliberately animate:

- In FK, the arm controls are `upper_arm_fk.L/R`, `forearm_fk.L/R` and `hand_fk.L/R`.
- Key `Weapon`, `Camera`, finger controls and other pose controls in each action that depends on
  their edited transforms.
- If you change a **Child Of** or other constraint's Influence, key that property too.
  Constraint keys do not replace transform keys, and transform keys do not store the Influence.

You do not need to key every bone in the rig. Key the controls you use and the offsets they depend
on; leave generated `ORG-`, `MCH-` and `DEF-` bones alone.

### A safe editing workflow

1. **Choose the action first.** Select the generated rig, enter Pose Mode and select the intended
   action in the Action Editor. Check the action name before inserting keys.
2. **Choose FK or IK for each arm.** Set the IK/FK property and key it by right-clicking the
   property and choosing **Insert Keyframe**. If switching modes mid-animation, use Rigify's
   snapping controls to preserve the pose and key the controls on both sides of the switch.
3. **Store the starting offsets.** For an IK arm, select its hand, upper-arm IK and any pole-target
   controls you use from the table above. At the action's first frame, insert keys for
   **Location, Rotation and Scale**. Use that keying set, or insert keys on those transform
   properties in the Item panel. Do not rely on an unspecified default keying set.
4. **Animate and key your edits.** Add transform keys wherever the intended pose changes.
   Key constraint Influence separately when it changes. Auto Keying can help, but do not assume
   it stored controls or properties you did not touch.
5. **Check the end pose.** Scrub to the last frame and confirm the hands, elbows and weapon are
   correct. Add keys for the intended end pose. For a fixed offset, the first and last values
   should be identical; for motion, key the different poses you actually want.
6. **Repeat for every affected action.** Keys in `reload` do not supply offsets for
   `idle_to_aim`, `aim_to_idle` or `idle_aim`. Check both transitions separately.
7. **Export and inspect before packaging.** Review export errors, then preview the imported
   sequences in ZoneKit. Compare the first, middle and last frames with Blender.

When checking an existing action, first establish the pose you actually intend. Do not blindly
key a hand position inherited from whichever action you viewed previously. Save a copy before
repairing keys.

### If export reports an unkeyed IK control

The exporter checks every integer frame and rejects active IK-chain controls with non-rest
transform properties that are not keyed in the action. The error names the control, action,
frame and missing properties.

Select that action and control, restore the intended pose, and key **Location, Rotation and
Scale**. For example, an error naming `upper_arm_ik.R` needs keys on that control, not just
`hand_ik.R` or the IK/FK switch. Then re-export.

This check is a safety net, not proof that every edit is keyed: it does not validate all FK,
finger, camera, constraint or other custom-property changes. If an FBX differs from the viewport,
check those keys too.

## Static meshes

One FBX is written per mesh to `<output>/_Stalker_2/weapons/<Weapon Category>/p_<weapon>/AnimMesh/`. File names come from the **mesh object names**; the weapon name is not used for them. The weapon category (default `pistol`) is a field in the panel.

- Every mesh bound to the weapon rig (parented to it, or with an Armature modifier pointing at it) is exported.
- The **main weapon mesh** is the one weighted to the most weapon bones. Its object name is the weapon name (`e9`), and it is split per bone: each face goes to the bone with the highest summed vertex weight, and the file is `SM_wpn_e9_SM_<joint>` (for example `Weapon` → `jnt_offset` → `SM_wpn_e9_SM_offset`). Bones with no faces are skipped with a warning.
- If the main mesh still has the template's name (`udp`), the custom weapon name supplies its export namespace instead (`coolpistol`). The object itself is not renamed. Keeping the retail folder/file names would make ZoneKit classify those assets as overrides, replacing UDP and its unique variants. Artist-assigned custom mesh names are still respected. The CFG and import manifest use the same resolved name.
- **Every other mesh** is exported whole as `SM_wpn_<weapon>_SM_<object name>`, for example a separate mesh called `magazine_full` gives `SM_wpn_e9_SM_magazine_full`. Its origin is the head of the mapped bone with the most weight on it. Use this for variants such as full and empty magazines: separate the mesh, keep the same Armature modifier and vertex group.
- Object names must be unique after naming; collisions are reported by Validate.
- Meshes are taken from the rest pose, so the current pose does not matter.
- Each object's origin is its bone head, with vertices stored relative to it (translation only, no rotation).

### World model

The same button also writes the non-animated world model into the parent folder of `AnimMesh`: `<output>/_Stalker_2/weapons/<category>/p_<weapon>/SM_<weapon>.FBX` for the whole main mesh (not split per bone), and `SM_<weapon>_<object name>.FBX` for every other mesh (for example `SM_e9_magazine_full.FBX`). These are all positioned relative to the head of the `Weapon` root bone, so the assembled parts stay aligned with each other.

### Skeletal carrier mesh

The export also writes `SK_<weapon>.FBX` from the donor's skeletal carrier mesh. Its root must keep the donor name (`jnt_wpn_udp` for the pistol). The donor FBX's outer `SK_udp` empty is removed from the exported hierarchy while preserving the armature's world transform: exporting that wrapper as `SK_<weapon>` makes Unreal import an extra root bone, which cannot merge with the template skeleton. Renaming only the armature does not fix an extra wrapper.

## Importing into ZoneKit

**Export All** also writes the import script and copies its path to the clipboard. It also writes:

- `Textures/*.png` next to the world model, from the weapon's Blender material (`_D`, `_N`, `_RMA` images). Materials whose diffuse image starts with `T_` are treated as original game materials and are not exported.
- `import_<weapon>.json`, a manifest of every exported file, texture and material.
- `import_<weapon>.py`, a script for the ZoneKit editor.

After **Export All**, paste the clipboard (the script's path, e.g. `D:\Euan\3D\Stalker Mods\MonkeyMod\import_monkeygun.py`) into the ZoneKit editor's Python bar and press Enter. It imports the textures (correct sRGB / normal / mask settings), creates the material instance from the parent material, imports the static meshes and assigns materials, then imports the player and weapon animations onto their skeletons. Existing assets are skipped; add `--overwrite` to re-import. The mount point is the **Mod Name** (e.g. `/MonkeyMod`). The other assets are fixed: player skeleton `SK_Stalker`, weapon skeleton `SK_<weapon>`, parent material `MI_PBR_Weapons` and physical material `PM_MetalSolid`. The skeletons must already exist in the project.

The latest generated setup/export and import scripts show an OK dialog when finished, with a
success, warning or error category. Warnings are counted for that run; inspect the Output Log
(and the setup report for setup/export) before packaging. Failures still raise the original
exception. Older generated scripts must be regenerated to gain notifications. Unreal's
`-unattended` mode logs the dialog without waiting for input; an import `--dry-run` prints its
plan without a completion dialog.

Animation tasks explicitly use `FbxFactory` with **Preserve Local Transform** enabled.
Interchange's global-to-local reconstruction changes rotations and scales in stretched hierarchies,
even when that option is set. An explicit factory alone does not route existing Interchange assets
through the legacy importer: the script temporarily disables `Interchange.FeatureFlags.Import.FBX`
for the animation batch and restores its previous value in `finally`, including on failure.
No persistent global setting change or base-game skeleton save is needed.

The importer rejects both planned static-mesh package collisions with `/Game` and old vanilla-named
static meshes still present in the mod. Re-exporting under a new name does not remove previously
imported assets: back up and archive the old **mod-owned** packages outside `Content` before importing
again. Do not delete or check out the corresponding base-game assets.

### Additive playback and handoff

The game's collection plays `idle_add` and `idle_aim_add`, not the nonadditive `idle` and
`idle_aim` used as additive reference poses. After importing an edited idle, the script
regenerates its existing additive companion's bone tracks from that idle. It retains the
companion's duration, curves, additive mode and base-pose reference settings. An explicitly exported
additive companion is left alone. This keeps the runtime resting pose and the edited transition
in the same local-bone representation, even where their visible hand positions were already equal.

Do not convert these assets to mesh-space additives based only on a graph node name.
That conversion was tested in game and caused a tilted default view and severe arm
deformation in game; it has been reverted. The importer preserves the donor's local-space
idle mode and preserves exported overlays' additive settings across FBX reimport. Full-pose comparisons and
isolated virtual-attachment composition do not validate the complete runtime graph.

The legacy FBX importer can reset an existing sequence's additive mode and reference settings
when replacing it. The script captures those settings before import and restores them afterwards.
If an exported player overlay has already lost its additive settings, the script recovers them
from the matching template sequence, using the mod's matching reference animation when available.
Existing nonzero additive modes and custom reference settings are preserved. Plain `idle` and
`idle_aim` remain nonadditive. A correct full-pose sequence preview alone does not confirm that an
overlay is configured correctly for the game's additive graph.

### Overlays edited in Blender

Fire (`shoot`, `shoot_end`, `shoot_aim`, `shoot_aim_end`), `empty_click`, `empty_click_aim`, `equip`,
`unequip` and the offset aim clips are additive overlays, like reload, melee, `break_bullet` and the aim
transitions. The setup script exports all of them except the `*_add` idles, so they are imported and
exported like any other clip, edited or not. An exported overlay keeps its additive mode and the mod's
reference (for most, the mod's exported idle), so the game shows the pose you see in Blender. The
weapon-only clips (`idle_boltlock`, `break_bullet_idle`) and the character-only offset aim clips write
just their own half.

Clips you untick in the Export panel stay as the setup copied them, as described next.

### Copied overlays left unexported

Copied, unedited shooting/recovery and equip overlays must still subtract their **original**
reference pose. Repointing them to an edited idle without rebasing their raw tracks introduces
an unwanted offset. The import manifest records the template weapon; the importer restores an
overlay's original reference only when every raw track/key and its additive settings still
match the template. Exported or independently modified overlays keep their custom references.
Using a base-game reference is intentional; the base-game package is never edited or saved.

Unmapped `jnt_l_weapon` and `jnt_r_weapon` sockets retain their donor component-space animation.
Their hidden Rigify raw-copy bones are not animated controls and do not drive the character mesh;
exporting their static poses can corrupt runtime attachment/IK behavior despite perfectly matching
visible wrist and fingertip poses. Explicit control mappings still take precedence.

The bake samples four times per action frame (120 Hz with a 30 FPS template), including evaluated
FK/IK constraints at subframes. Socket component poses interpolate between the donor's native
samples; their compensated local transforms are then solved at every bake sample. Integer-frame-only
tests miss the excursions produced when Unreal interpolates changing parent/child compensation.
The FBX exporter retains those subframe samples, and the importer uses automatic source-rate
detection instead of forcing 30 Hz. Clip durations still follow the template FBX frame rate, as
before; the saved scene FPS is restored after export. For real-time viewport comparisons, use
the template rate too (30 FPS for UDP). A scene saved at 25 FPS plays the same keys more slowly.

### Animation montages

Export the template weapon's montages from ZoneKit along with its animations, and have them in your mod's Content (named for your weapon, e.g. `MG_monkeygun_fp_reload`). After the animations are imported, the script repoints every slot in your weapon's montages, and every montage and sequence in its `AnimCollection`, from the template's animation (e.g. `AS_udp_fp_reload`) to the matching new one (`AS_monkeygun_fp_reload`). The match swaps the template weapon's name for yours in the folder and file name; if that fails it falls back to a unique match on the rest of the name. Anything with no matching new animation is listed as a warning and keeps the template animation. The `AnimCollection`'s magazine SIDs (the template's `Gun<Template>_Mag...`) are also replaced with your weapon's magazine SIDs from the Magazines section: a normal template magazine becomes your preinstalled (default) magazine and an extended one (name containing extend/increase/big/large/long/drum) becomes your first other magazine. Check the log lines starting `collection` to confirm the swaps. The step is safe to re-run. The editor's Python can't edit a montage's slot tracks, so the script repoints the `AnimCollection` and lists any montages still playing template animations. The ZoneKit setup script (Set Up panel) renames the montages together with the animations, which keeps their references correct.

Running the script with a normal Python prints the import plan without needing Unreal (`--dry-run`).

## Output

Files mirror the library: `<output>/_STALKER2/Animations/Player/AnimSequences/pt/<new>/<Category>/AS_fp_<new>_<action>.fbx` and `<output>/_STALKER2/Animations/Weapons/pt/<new>/AnimSequences/fp/<Category>/AS_<new>_fp_<action>.fbx`. The action name is the file suffix. The export refuses to write inside the library folder.

## Debug output

The **Debug Output** button at the bottom of the Export panel writes a plain-text summary of every setting (export, importer and weapon CFG), the rigs and meshes in the scene, the static mesh plan, the derived weapon data and the last import manifest. It goes to the clipboard, the system console and a text block called "Arsenal Debug". Paste it when reporting a problem.

## How it works

- The exported pose is sampled after Rigify evaluates its constraints. Mesh-driving `DEF-` bones supply the hand, finger/palm, arm-twist and sleeve deformation. `ORG-` bones or controls are used only where no deform counterpart exists.
- Mapped bones export the evaluated translation, rotation and scale. A rotation-only **retarget input** mapping does not discard translation or stretch on export: doing so moves an IK wrist and breaks the pose. Bone names and the rest skeleton remain unchanged.
- Conversion saves the complete source-to-deform mapping, including bones with no corresponding Rigify control.
- Local transforms are solved using Unreal's TRS composition, rather than Blender's shearing matrix hierarchy. The paired weapon uses the same reconstructed character pose.
- Bones with no matching rig bone keep the template animation. If an action is longer than the template, the last template frame is held.
- Each action is exported on its own: any control the action does not key is treated as being at rest, not wherever another action left it. Blender's viewport doesn't do this, so when switching actions a control keyed only in one action (for example a finger edited only in `reload`) stays posed in the viewport. Key a control in every action where its pose matters.
- The rig's first upper-arm deform bone carries the arm's full twist, as the game's `jnt_*_arm` does (Rigify's default removes it), because the game blends our clips with its own bone by bone.
- `jnt_spine_01` and `jnt_spine_02` keep the template's twist, length and translation; only their bend follows the rig. Rigify's stretchy spine matches the joint positions but not those frames, and the game's look and crouch layers rotate the spine in those frames. Everything from `jnt_spine_03` outwards follows the rig exactly.
- Existing animation additive types and reference poses are retained on reimport. Raw-pose validation alone is insufficient: additive extraction, the consuming graph and its virtual attachment bones must also be checked. A distorted idle reference can change reload, equip and shooting overlays even when the reload's own raw joints match.
- The weapon file follows the character's `jnt_weapon` bone, uses the rig's `Weapon` control for `jnt_offset`, and copies the character's hands.
- The template frame rate is kept; the first action frame is written at time 0, and the action length can change. Export restores the saved scene FPS afterwards.

## Known limitations

- Arbitrary Blender shear cannot be represented exactly by FBX/Unreal TRS tracks. The reload regression checks 4,510 evaluated arm/hand/sleeve vertices over 94 frames in FK, blended and IK modes. The saved Unreal reload pair was also checked in both raw and compressed evaluation (14,852 bone poses): maximum position/rotation error 0.000438 cm / 0.000207 degrees. Comparing those actual Unreal transforms with the evaluated viewport gives index-finger error below 0.000374 cm and sleeve error below 0.000684 cm. The largest remaining geometric error is approximately 0.0251 cm (0.251 mm), on the non-uniformly scaled pinky tip. Matching joint transforms alone does not prove matching deformation. Runtime montage blends, aim offsets and other procedural layers remain additional sources of differences.
- `idle_aim` and related frames export the aim-compensated weapon position, so they differ slightly from the original FBX.
- The weapon FBX keeps the original root node name (`jnt_wpn_udp`).
