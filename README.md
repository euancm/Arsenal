# STALKER 2 Arsenal


Based on and originally developed from: https://github.com/artempoletsky/blender_1_click_rig

This project began as a modified version of the original project and has since evolved to focus on STALKER 2 weapon import/export and animation workflows in Blender.
Credit to [Artem Poletsky](https://github.com/artempoletsky) for the foundation on which this project was built. See [NOTICE.md](NOTICE.md).

Further credits:
- [tnebes/stalker2mods](https://github.com/tnebes/stalker2mods) - the modding guide behind the weapon config tooltips and CFG export.
- [sdwvit/S2Mods](https://github.com/sdwvit/S2Mods/blob/master/.claude/skills/eng-localization/SKILL.md) - the localisation reference (text SIDs and the mod text asset format) behind the weapon name and description feature.

This project is intended to be a solution to automatically import stalker 2 weapons from the Stalker 2 Zonekit into blender, making them simpler to work with a standard animation rig, allowing tweaks, replacements and other mods to be put together more simply. It will also allow automatic compilation of all the finished files needed to implement a custom weapon.

## Custom Pistol

![A screenshot of the Blender interface showing the custom pistol](BannerImage.png)

The custom pistol mod is the testbed for development of the Arsenal blender addon.

You should be able to copy this project into YourStalker2ZoneKitInstallation\Stalker2\Mods then open zonekit and click "Package Mod" successfully.


## Arsenal

Arsenal is a Blender add-on that combines the STALKER 2 animation importer with mapping, Rigify conversion, and retargeting tools. Install the packaged add-on from Blender Preferences:

Requires Blender 5.2.2 or newer. The packaged add-on is not published yet; for now, load it from source with [dev_load_addon.py](Arsenal/dev_load_addon.py).

See the [add-on guide](Arsenal/doc/arsenal.md) and the [development plan](Arsenal/PLAN.md) for details.

## Exporting your own source assets

The extracted FBX files are not distributed with this repository (they belong to gsc). The add-on's setup script exports them from your own ZoneKit install.

In ZoneKit, weapons are stored in two places. Animations are in `_STALKER2/Animations/...` (for example `Player/AnimSequences/pt/udp` and `Weapons/pt/udp`), and models and textures in `_Stalker_2/weapons/pistol/p_udp`. Not every weapon names its animations and meshes alike (the SMG is `viper` for animations but `vip` for meshes), so the add-on has a separate name for each.

[survey_template_assets.py](Arsenal/zonekit_tools/survey_template_assets.py) lists every file a template weapon uses and what the add-on does with it. Run it in ZoneKit (paste its path into the Python bar); the results go to `Arsenal/zonekit_tools/survey_output`, which is git-ignored.

## Workflow

### 1. Set up (Blender and ZoneKit)

Start with a new, empty Blender file and press N in the 3D view to open the **STALKER 2** tab.

1. In panel **1. Set Up**, choose the **Template**: the base game weapon your weapon starts from (pistol, SMG, rifle, shotgun or sniper). This also fills the weapon's stats and selects which files are exported.
2. Enter your **Weapon Name** (e.g. `Cool Pistol`), the **Mod Name** (the name of your mod in ZoneKit, which must already exist) and a **Working Folder**. The add-on uses `<working folder>/ZoneKit Export` for the ZoneKit export and `<working folder>/Blender Export` for what it exports later.
3. Press **Create ZoneKit Setup Script**. The path of the script is copied to your clipboard.
4. In ZoneKit, make sure your mod is the selected one, paste the path into the Python bar and run it. The script:
   - exports the template's first-person animations, its skeletal mesh and its animated static mesh parts to the ZoneKit Export folder;
   - checks out the assets that stay in ZoneKit (montages, animation collection, anim blueprint, skeleton, skeletal mesh and the animation sequences) into your mod;
   - renames them all to your weapon name with the asset rename function, like Batch Rename;
   - writes `zonekit_setup_<weapon>_report.txt` to the ZoneKit Export folder. Check it for warnings, especially "still references the template asset".

   Tick **Dry Run** first if you only want the report. The script has not been tested on every template yet, so try it on a scratch mod.

### 2. Import into Blender

1. Press **Import Weapon** in panel **2. Import Weapon**, then go and make a brew. It takes a little while (a minute or two), and Blender will look frozen, but it's working. It does all of this for you:
   - imports the weapon skeleton and all its static mesh parts, then places them, weights them to the right bones and joins them into one mesh
   - gives the weapon bones red colours and custom bone shapes
   - imports the headless character and all the matching animations (animation pairs with no character -> weapon match are additive animations, so those get skipped)
   - maps everything onto a standard Rigify rig, which is a really common setup in Blender with loads of tutorials out there
   - sets up the first person camera

   When it's done the character will be in his starting A pose, surrounded by rig controls. The status line under the button tells you how it went.
2. Press **Retarget Animation** in panel 3. This one is slow (about 5 minutes on my PC) as it does a lot of work to get a faithful result. Keyframes are cleaned up automatically afterwards.

Once it's finished the character will jump into an action pose. Press 0 on the numpad for an FPS view that matches the game. From here you can go into pose mode, play the animations and make whatever changes you like. The fingers are split into left and right bone collections to make life easier when both hands are close together.

### 3. Make your weapon

Edit, replace or add to the weapon mesh however you like (importing, appending or copy-pasting a new model all work), and tweak the animations as needed (panel 4).

A few things to know:
- Rename the main weapon mesh from the template mesh name (e.g. `udp`) to your new weapon's name.
- Extra parts that need to swap in-game, like `magazine_full` and `magazine_empty`, should be separate objects with the same armature modifier. Each one is exported as its own static mesh, named after the object.
- The skeleton exported to Unreal keeps the original bones, so extra bones you add won't be exported.

### 4. Export

Use panel 5, **Export**:

1. Check the **Mod Name** and **Output Folder** (both are set from panel 1).
3. Press **Refresh**, then tick the animations you want to export. **Validate** will check them for problems.
4. Press **Export All**. This writes the animations, the static meshes (one per weapon part, plus an unsplit world model) and the skeletal mesh into a mirrored ZoneKit folder structure. It also writes an Unreal import script and the weapon CFG files.

See [exporting animations](Arsenal/doc/exporting_animations.md) for the details.

The Unreal side (importing back into ZoneKit) is still a work in progress.

## License

See [LICENSE](LICENSE).
