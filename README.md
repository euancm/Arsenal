# STALKER 2 Arsenal

**Make your own STALKER 2 weapons in Blender.**

Arsenal is a Blender add-on for 3D artists and modders. Start with a game weapon,
replace its model, edit its animations and set up its stats, attachments and shop
availability. Arsenal handles much of the file preparation between Blender and
ZoneKit, STALKER 2's modding tools.

This is a tool for making mods, not a playable mod itself. Some Blender experience
is recommended, but you do not need to write Python scripts or edit configuration
files by hand for the normal workflow.

## Made with Arsenal: E9 Pistol Pack

The **E9 Pistol Pack** was created using Arsenal. It brings three new handguns to
the Zone, with custom models, textures and hand-edited first-person animations.

Try the finished mod:

- [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3837819248)
- [Nexus Mods](https://www.nexusmods.com/stalker2heartofchornobyl/mods/3317)
- [mod.io](https://mod.io/g/stalker2/m/e9-pistol-pack)

The mod is a separate download, not a requirement for using Arsenal.

## What you can do

- Replace a template weapon with your own model and textures to create a new item.
- Edit first-person animations using familiar Blender rig controls.
- Set damage, fire modes, recoil, sounds, names and descriptions.
- Configure magazines, silencers, lasers and weapon upgrades.
- Create inventory images and choose which traders and NPCs carry your weapon.
- Export the files needed to bring your weapon back into ZoneKit and package it.

## What you need

- **Blender 5.2.2 or newer**, with the **Rigify** add-on enabled.
- **STALKER 2 ZoneKit**, installed and working, with a mod project already created.
- Your own weapon artwork and a separate working folder for the project.

Game models and textures are not included. Arsenal gets the template files from
your own ZoneKit installation. Keep your weapon projects and exports outside the
downloaded Arsenal folder.

## Install

1. Open [GitHub Releases](https://github.com/euancm/Arsenal/releases).
2. Under the latest release's **Assets**, download **`stalker2_arsenal-<version>.zip`**.
   Do not choose **Source code (zip)** or **Source code (tar.gz)**.
3. In Blender, open **Edit > Preferences > Add-ons**. Choose **Install from Disk**
   from the menu at the top right and select the downloaded zip **without unzipping it**.
4. Enable **Stalker 2 Arsenal** and **Rigify**.

In the 3D View, press **N** to open the sidebar, then find the **STALKER 2** tab.

If Blender cannot read a bundled resource file, see the
[download and resource notes](Arsenal/doc/arsenal.md#download-and-resource-notes).

## Make your first weapon

Start with a new, empty Blender file. The sidebar panels follow this order:

### 1. Set up

Choose a **Template** and enter your **Weapon Name**, **Mod Name** and **Working
Folder**. The mod name must match your existing ZoneKit mod.

Press **Create ZoneKit Setup Script**. Arsenal copies the script's path to your
clipboard. In ZoneKit, select your mod, paste that path into the **Python bar**
and run it. This prepares copies of the template assets for your weapon.

### 2. Import and prepare the animations

Back in Blender, press **Import Weapon** in panel 2. Then press **Retarget
Animation** in panel 3 to put the original animations onto the editable rig.

These steps can take several minutes; Blender may appear frozen while working.
Wait for the completion message. Press **Numpad 0** to see the first-person camera.

### 3. Make it your own

Edit or replace the weapon model, add your textures and adjust the animations.
Panel **4. Create Your Custom Weapon** contains the game settings: stats, names,
magazines, attachments, upgrades, inventory images and trader/NPC availability.

Custom magazines, silencers and lasers can automatically appear at the weapon's
traders at half its stock chance. For example, a 50% effective weapon chance gives
each custom attachment a 25% chance.

Save your Blender file regularly.

### 4. Export

In panel **5. Export**, press **Export All**. Arsenal checks the settings and
automatically exports your rig's animations using the template's original names
and folders. Keep the original action names, even when replacing an animation
entirely. There is no animation-selection list to maintain.

Arsenal writes the assets and game settings and copies a new ZoneKit import
script's path to your clipboard. Resolve any errors or warnings before continuing.

### 5. Bring it into the game

In ZoneKit, select your mod and run the new script from the **Python bar**.
Check the completion message and Output Log for warnings.

Before packaging, open your mod's **Mod Editor options** and set its
**AnimCollection** to your weapon's first-person collection. Save the options,
package the mod, install it and test in game.

For later changes, repeat **Export All**, run the newly generated import script,
and package again. Always use the latest script.

## A few important tips

- **Key the controls you change in each animation.** A pose visible in Blender
  is not necessarily saved in that animation. See the
  [animation editing guide](Arsenal/doc/exporting_animations.md#keeping-edited-animations-correct-on-export).
- Keep swappable parts, such as full and empty magazines, as separate objects
  attached to the weapon rig. Adding bones does not add them to the game skeleton.
- Save only your mod's assets in ZoneKit. Decline requests to check out or save
  shared base-game skeletons.
- Check aiming, attachments, animations and inventory images in game. Trader
  stock may need a refresh, and existing NPC inventories do not update immediately.
- Back up both your Blender project and ZoneKit mod before major changes.

## Current limitations

**Only the workflow replacing a pistol has been tested end to end so far.**
Testing with more weapon types is planned. The template menu includes 38 standard
base-game firearms, including SMGs, rifles, shotguns, sniper rifles, the machine
gun and launcher, but those other workflows are experimental. Named/unique variants
are not separate templates.

Known shotgun and rifle import problems are tracked in the
[development plan](Arsenal/PLAN.md#known-non-pistol-import-issues).

Automatic sight alignment is not included. You can adjust existing
[weapon sockets in Blender](Arsenal/doc/weapon_sockets.md), but a different model
may still need manual aiming and attachment adjustments. Shared movement animations,
such as walking and sprinting, still come from the game.

## Help and detailed guides

- [Add-on guide and troubleshooting notes](Arsenal/doc/arsenal.md)
- [Editing and exporting animations](Arsenal/doc/exporting_animations.md)
- [Weapon settings, attachments, upgrades and trader inventories](Arsenal/doc/cfg_export.md)
- [Inventory images](Arsenal/doc/inventory_images.md)
- [Weapon sockets and attachment placement](Arsenal/doc/weapon_sockets.md)

For development, see the [developer notes](Arsenal/doc/arsenal.md#for-developers)
and [development plan](Arsenal/PLAN.md).

## Credits and licence

Arsenal began with [Artem Poletsky's blender_1_click_rig](https://github.com/artempoletsky/blender_1_click_rig).
Thanks also to [tnebes/stalker2mods](https://github.com/tnebes/stalker2mods) for CFG
modding references and [sdwvit/S2Mods](https://github.com/sdwvit/S2Mods) for
localisation references.

Most of the add-on's code was developed with GitHub Copilot.

See [LICENSE](LICENSE) and [third-party notices](NOTICE.md).
