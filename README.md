# STALKER 2 Arsenal


Based on and originally developed from: https://github.com/artempoletsky/blender_1_click_rig

This project began as a modified version of the original project and has since evolved to focus on STALKER 2 weapon import/export and animation workflows in Blender.
Credit to [Artem Poletsky](https://github.com/artempoletsky) for the foundation on which this project was built. See [NOTICE.md](NOTICE.md).

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

The extracted FBX files are not distributed with this repository (they belong to gsc).

In ZoneKit, weapons are stored in two places. Animations are in:
_STALKER2/Animations/Player/AnimSequences/pt/udp
and models, textures etc. are stored in:
_Stalker_2/weapons/pistol/p_udp

You can go to these folders, put "udp" in the search bar and "checkout" the relevant files (remember to create a new mod first), then use Asset Actions > Bulk Export.
This will maintain the expected folder structure.
(note right now it's only set up for the UDP pistol)

## Workflow

In blender, use the **STALKER 2** tab in the 3D View sidebar:

1. **Import Assets**: choose the exported  STALKER 2 folder containing `Animations/Player` and `Animations/Weapons`, create the base skeleton, then scan and import matching animation pairs.
2. **Mapping Setup**: generate a source-to-Rigify mapping, fill any blank source entries, and add mappings for an appended `Weapon` armature when present.
3. **Rig & Retarget**: convert the character by mapping and retarget the imported actions onto the character, weapon, and camera controls. Conversion merges an appended `Weapon` rig and keeps a hidden source backup for future retargeting.
4. **Animation Tools**: bake or edit animation as needed.



## License

See [LICENSE](LICENSE).
