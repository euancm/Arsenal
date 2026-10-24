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
## Static meshes

One FBX is written per mesh to `<output>/_Stalker_2/weapons/<Weapon Category>/p_<weapon>/AnimMesh/`. File names come from the **mesh object names**; the weapon name is not used for them. The weapon category (default `pistol`) is a field in the panel.

- Every mesh bound to the weapon rig (parented to it, or with an Armature modifier pointing at it) is exported.
- The **main weapon mesh** is the one weighted to the most weapon bones. Its object name is the weapon name (`e9`), and it is split per bone: each face goes to the bone with the highest summed vertex weight, and the file is `SM_wpn_e9_SM_<joint>` (for example `Weapon` → `jnt_offset` → `SM_wpn_e9_SM_offset`). Bones with no faces are skipped with a warning.
- **Every other mesh** is exported whole as `SM_wpn_<weapon>_SM_<object name>`, for example a separate mesh called `magazine_full` gives `SM_wpn_e9_SM_magazine_full`. Its origin is the head of the mapped bone with the most weight on it. Use this for variants such as full and empty magazines: separate the mesh, keep the same Armature modifier and vertex group.
- Object names must be unique after naming; collisions are reported by Validate.
- Meshes are taken from the rest pose, so the current pose does not matter.
- Each object's origin is its bone head, with vertices stored relative to it (translation only, no rotation).

### World model

The same button also writes the non-animated world model into the parent folder of `AnimMesh`: `<output>/_Stalker_2/weapons/<category>/p_<weapon>/SM_<weapon>.FBX` for the whole main mesh (not split per bone), and `SM_<weapon>_<object name>.FBX` for every other mesh (for example `SM_e9_magazine_full.FBX`). These are all positioned relative to the head of the `Weapon` root bone, so the assembled parts stay aligned with each other.

## Importing into ZoneKit

**Export All** also writes the import script and copies its path to the clipboard. It also writes:

- `Textures/*.png` next to the world model, from the weapon's Blender material (`_D`, `_N`, `_RMA` images). Materials whose diffuse image starts with `T_` are treated as original game materials and are not exported.
- `import_<weapon>.json`, a manifest of every exported file, texture and material.
- `import_<weapon>.py`, a script for the ZoneKit editor.

After **Export All**, paste the clipboard (the script's path, e.g. `D:\Euan\3D\Stalker Mods\MonkeyMod\import_monkeygun.py`) into the ZoneKit editor's Python bar and press Enter. It imports the textures (correct sRGB / normal / mask settings), creates the material instance from the parent material, imports the static meshes and assigns materials, then imports the player and weapon animations onto their skeletons. Existing assets are skipped; add `--overwrite` to re-import. The mount point is the **Mod Name** (e.g. `/MonkeyMod`). The other assets are fixed: player skeleton `SK_Stalker`, weapon skeleton `SK_<weapon>`, parent material `MI_PBR_Weapons` and physical material `PM_MetalSolid`. The skeletons must already exist in the project.

### Animation montages

Export the template weapon's montages from ZoneKit along with its animations, and have them in your mod's Content (named for your weapon, e.g. `MG_monkeygun_fp_reload`). After the animations are imported, the script repoints every slot in your weapon's montages, and every montage and sequence in its `AnimCollection`, from the template's animation (e.g. `AS_udp_fp_reload`) to the matching new one (`AS_monkeygun_fp_reload`). The match swaps the template weapon's name for yours in the folder and file name; if that fails it falls back to a unique match on the rest of the name. Anything with no matching new animation is listed as a warning and keeps the template animation. The `AnimCollection`'s magazine SIDs (the template's `Gun<Template>_Mag...`) are also replaced with your weapon's magazine SIDs from the Magazines section: a normal template magazine becomes your preinstalled (default) magazine and an extended one (name containing extend/increase/big/large/long/drum) becomes your first other magazine. Check the log lines starting `collection` to confirm the swaps. The step is safe to re-run. The editor's Python can't edit a montage's slot tracks, so the script repoints the `AnimCollection` and lists any montages still playing template animations. The ZoneKit setup script (Set Up panel) renames the montages together with the animations, which keeps their references correct.

Running the script with a normal Python prints the import plan without needing Unreal (`--dry-run`).

## Output

Files mirror the library: `<output>/_STALKER2/Animations/Player/AnimSequences/pt/<new>/<Category>/AS_fp_<new>_<action>.fbx` and `<output>/_STALKER2/Animations/Weapons/pt/<new>/AnimSequences/fp/<Category>/AS_<new>_fp_<action>.fbx`. The action name is the file suffix. The export refuses to write inside the library folder.

## Debug output

The **Debug Output** button at the bottom of the Export panel writes a plain-text summary of every setting (export, importer and weapon CFG), the rigs and meshes in the scene, the static mesh plan, the derived weapon data and the last import manifest. It goes to the clipboard, the system console and a text block called "Arsenal Debug". Paste it when reporting a problem.

## How it works

- The exported pose is the visible pose of the rig, so IK edits on the limbs are baked to plain keys. The spine and fingers are read from their FK controls.
- Only rotation is taken from the rig for rotation-mapped bones; the character skeleton keeps its original bone lengths and proportions.
- Bones with no mapping (armour, bags, helpers) keep the template animation. If an action is longer than the template, the last template frame is held.
- The weapon file follows the character's `jnt_weapon` bone, uses the rig's `Weapon` control for `jnt_offset`, and copies the character's hands.
- Frame rate is kept; the first frame is written at time 0, and the action length can change.

## Known limitations

- `idle_aim` and related frames export the aim-compensated weapon position, so they differ slightly from the original FBX.
- Actions retargeted before the frame-1 wrist fix should be retargeted again before exporting.
- The weapon FBX keeps the original root node name (`jnt_wpn_udp`).
