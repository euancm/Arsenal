# STALKER 2 Arsenal


Based on and originally developed from: https://github.com/artempoletsky/blender_1_click_rig

This project began as a modified version of the original project and has since evolved to focus on STALKER 2 weapon import/export and animation workflows in Blender.
Credit to [Artem Poletsky](https://github.com/artempoletsky) for the foundation on which this project was built. See [NOTICE.md](NOTICE.md).

Further credits:
- [tnebes/stalker2mods](https://github.com/tnebes/stalker2mods) - the modding guide behind the weapon config tooltips and CFG export.
- [sdwvit/S2Mods](https://github.com/sdwvit/S2Mods/blob/master/.claude/skills/eng-localization/SKILL.md) - the localisation reference (text SIDs and the mod text asset format) behind the weapon name and description feature.

This project is intended to be a solution to automatically import stalker 2 weapons from the Stalker 2 Zonekit into blender, making them simpler to work with a standard animation rig, allowing tweaks, replacements and other mods to be put together more simply. It will also allow automatic compilation of all the finished files needed to implement a custom weapon.

## AI

Almost all of the code has been written by AI, specifically the github copilot sidebar in visual studio code.
To be honest, I'm more interested in modelling and texturing than software development, although I suppose AI is going to take that over soon too.


## Status: version 1

The full round trip works for the pistol template (UDP), tested in game from a blank slate:

- ZoneKit setup script → Blender import and retarget → edit → Blender export → ZoneKit import script → package the mod.
- The new weapon is a separate item with its own mesh and CFG stats. The vanilla UDP and Gambit pistols are left untouched.
- It takes normal and extended magazines, fires and reloads.
- Every first-person animation of the weapon can be edited in Blender: idle, aim and the aim transitions, reload (all variants), fire and aimed fire, empty click, equip and unequip, melee, offset aim, the empty-gun slide lock (`idle_boltlock`) and `break_bullet_idle`. What you see in the Blender viewport is what you get in game, including fingers, wrist twist and sleeves, and edited clips blend cleanly with the game's own.
- Animations shared by every pistol (sprint, walk, jump, cover lean and so on) come from the game and are not imported.

Known limitations:

- Only the pistol template has been tested in game. The SMG, rifle, shotgun and sniper templates are untested.
- Silencer and laser placement is not handled yet.
- A model whose sights sit higher or lower than the template's won't line up when aiming yet; a sight-alignment tool is planned.
- Rarely, the first aim right after loading a save may look jerky; it hasn't been reproduced reliably and looks like a game loading glitch.

The [development plan](Arsenal/PLAN.md) has the technical details and what's next.

## Custom Pistol

![A screenshot of the Blender interface showing the custom pistol](BannerImage.png)

The custom pistol (E9Gen7) in the repo root was the original testbed for the Arsenal add-on and is a separate deliverable. It has not been rebuilt or retested with the current pipeline; the add-on now builds each weapon into its own ZoneKit mod (see Workflow below).


## Arsenal

Arsenal is a Blender add-on that combines the STALKER 2 animation importer with mapping, Rigify conversion, retargeting and export tools.

Requires Blender 5.2.2 or newer.

To install, download this repository and zip the [Arsenal/stalker2_arsenal](Arsenal/stalker2_arsenal) folder, so the zip contains the `stalker2_arsenal` folder itself. In Blender, open **Edit > Preferences > Add-ons**, choose **Install from Disk** from the drop-down menu at the top right, pick the zip and enable **Stalker 2 Arsenal**.

If you're changing the add-on's code, load it from source instead with [dev_load_addon.py](Arsenal/dev_load_addon.py): in Blender's Text Editor use **Text > Open** on that file, then **Run Script**. Run it again after editing the code to reload. It disables an installed zip copy of the add-on so the two don't clash.

See the [add-on guide](Arsenal/doc/arsenal.md) and the [development plan](Arsenal/PLAN.md) for details.

## Exporting your own source assets

The extracted FBX files are not distributed with this repository (they belong to gsc). The add-on's setup script exports them from your own ZoneKit install.

In ZoneKit, weapons are stored in two places. Animations are in `_STALKER2/Animations/...` (for example `Player/AnimSequences/pt/udp` and `Weapons/pt/udp`), and models and textures in `_Stalker_2/weapons/pistol/p_udp`. Not every weapon names its animations and meshes alike (the SMG is `viper` for animations but `vip` for meshes), so the add-on has a separate name for each.

[survey_template_assets.py](Arsenal/zonekit_tools/survey_template_assets.py) lists every file a template weapon uses and what the add-on does with it. Run it in ZoneKit (paste its path into the Python bar); the results go to `Arsenal/zonekit_tools/survey_output`, which is git-ignored.

The other scripts in [zonekit_tools](Arsenal/zonekit_tools) are developer checks: [audit_mod.py](Arsenal/zonekit_tools/audit_mod.py) (plain Python) lists a mod's dangling or leftover template references, and the `test_*.py` files are regression tests: the Blender export and import (`test_animation_export.py`, `test_new_animations.py`, `test_skeleton_export.py`, run with `blender --background`), and the ZoneKit setup and import scripts (`test_unreal_setup.py`, `test_animation_import.py`, plain Python).

## Workflow

### 1. Set up (Blender and ZoneKit)

Start with a new, empty Blender file and press N in the 3D view to open the **STALKER 2** tab.

1. In panel **1. Set Up**, choose the **Template**: the base game weapon your weapon starts from (pistol, SMG, rifle, shotgun or sniper). This also fills the weapon's stats and selects which files are exported.
2. Enter your **Weapon Name** (e.g. `Cool Pistol`), the **Mod Name** (the name of your mod in ZoneKit, which must already exist) and a **Working Folder**. The add-on uses `<working folder>/ZoneKit Export` for the ZoneKit export and `<working folder>/Blender Export` for what it exports later.
3. Press **Create ZoneKit Setup Script**. The path of the script is copied to your clipboard.
4. In ZoneKit, make sure your mod is the selected one, paste the path into the Python bar and run it. The script:
   - exports the template's first-person animations, its skeletal mesh and its animated static mesh parts to the ZoneKit Export folder;
   - checks out the assets that stay in ZoneKit (montages, animation collection, anim blueprint, skeleton, skeletal mesh and the animation sequences) into your mod;
   - renames them all to your weapon name with the asset rename function, like Batch Rename, then rewrites their references so the montages, animation collection and anim blueprint use your weapon's assets instead of the template's;
   - writes `zonekit_setup_<weapon>_report.txt` to the ZoneKit Export folder. Check it for warnings, especially "still references the template asset".

   Tick **Dry Run** first if you only want the report. The script has not been tested on every template yet, so try it on a scratch mod.

### 2. Import into Blender

1. Press **Import Weapon** in panel **2. Import Weapon**, then go and make a brew. It takes a little while (a minute or two), and Blender will look frozen, but it's working. It does all of this for you:
   - imports the weapon skeleton and all its static mesh parts, then places them, weights them to the right bones and joins them into one mesh
   - gives the weapon bones red colours and custom bone shapes
   - imports the headless character and all the weapon's first-person animations (see Status above); a clip that only animates the weapon (or only the character) gets the idle for the other half
   - maps everything onto a standard Rigify rig, which is a really common setup in Blender with loads of tutorials out there
   - sets up the first person camera

   When it's done the character will be in his starting A pose, surrounded by rig controls. The status line under the button tells you how it went.
2. Press **Retarget Animation** in panel 3. This one is slow (about 5 minutes on my PC) as it does a lot of work to get a faithful result. Keyframes are cleaned up automatically afterwards.

Once it's finished the character will jump into an action pose. Press 0 on the numpad for an FPS view that matches the game. From here you can go into pose mode, play the animations and make whatever changes you like. The fingers are split into left and right bone collections to make life easier when both hands are close together.

### 3. Make your weapon

Edit, replace or add to the weapon mesh however you like (importing, appending or copy-pasting a new model all work), and tweak the animations as needed (panel 4).

If you delete one of the template's animations by mistake, **Import New Animations** in panel 2 (in Object Mode) brings back any that are missing, without touching the ones you have.

A few things to know:
- Each animation is exported on its own: a control you don't key in an animation is exported at its rest pose, even if the viewport still shows it where another animation left it. Key a control in every animation where its pose matters.
- Rename the main weapon mesh from the template mesh name (e.g. `udp`) to your new weapon's name.
- Extra parts that need to swap in-game, like `magazine_full` and `magazine_empty`, should be separate objects with the same armature modifier. Each one is exported as its own static mesh, named after the object.
- The skeleton exported to Unreal keeps the original bones, so extra bones you add won't be exported.

### 4. Export

Use panel 5, **Export**:

1. Check the **Mod Name** and **Output Folder** (both are set from panel 1).
2. Press **Refresh**, then tick the animations you want to export. **Validate** will check them for problems.
3. Press **Export All**. This writes the animations, the static meshes (one per weapon part, plus an unsplit world model) and the skeletal mesh into a mirrored ZoneKit folder structure. It also writes the weapon CFG files, a localisation JSON and a ZoneKit import script, `import_<weapon>.py`, whose path is copied to the clipboard.

Animations are exported at the template's 30 FPS. If your blend is set to another frame rate (for example 25 FPS), set it to 30 before comparing timing with the game.

See [exporting animations](Arsenal/doc/exporting_animations.md) and [CFG export](Arsenal/doc/cfg_export.md) for the details.

### 5. Import into ZoneKit, package and test

1. In ZoneKit, select your mod, paste the import script's path into the Python bar and run it. It imports the textures, materials, static and skeletal meshes, and the animations. It also refreshes the additive idle animations from your edited idles, repoints the weapon's montages and animation collection at your animations, and writes the weapon's name and description into the mod's text asset. Check the Output Log for warnings. Always use the script from the latest export: an older script contains older import code.
2. Package the mod in ZoneKit, then replace the installed pak and test in game.
3. When you close ZoneKit after packaging it may ask to save `SK_<weapon>` (save it; it's your mod's mesh) and to check out `SK_stalker_Skeleton` (decline; that's the base game's shared skeleton).

Re-exporting under a new weapon name doesn't remove assets imported under the old name. Archive old mod-owned packages outside `Content` first; never delete or check out base-game assets.

## License

See [LICENSE](LICENSE).
