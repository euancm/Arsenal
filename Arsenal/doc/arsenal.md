# Stalker 2 Arsenal Blender add-on

Stalker 2 Arsenal is a Blender add-on for the STALKER 2 first-person animation workflow. The importer, mapping tools, Rigify conversion, retargeting, and animation utilities are included in one installable add-on.

## Install

Zip the `stalker2_arsenal` folder (so the zip contains the folder itself), then in Blender use **Edit > Preferences > Add-ons > Install from Disk** and enable **Stalker 2 Arsenal**.

Blender 5.2.2 is the minimum supported version. See the [development plan](../PLAN.md) for implementation status and planned work.

## Workflow

Use the **STALKER 2** tab in the 3D View sidebar:

1. **Set Up**: choose the template weapon, your weapon name, mod name and working folder, and create the ZoneKit setup script. Run it in ZoneKit.
2. **Import Weapon**: one button imports the template's skeleton, meshes, attachments, textures and every first-person animation, builds the mapping and converts the character to a Rigify rig with the weapon and camera controls. The original armature is kept in a hidden backup for retargeting. **Import New Animations** adds any template animation missing from the blend.
3. **Retarget**: bake the imported animations onto the rig's character, weapon and camera controls.
4. **Create Your Custom Weapon**: edit the meshes and animations, and set the weapon's stats, magazines, name and description.
5. **Export**: write the animations, meshes, CFG files, localisation and the ZoneKit import script.

The [README](../../README.md) walks through the full workflow.

## Documentation

- [STALKER 2 animation importer](./stalker2_animation_importer.md)
- [Converting to Rigify](./converting_to_rigify.md)
- [Converting from Rigify](./converting_from_rigify.md)
- [Mappings and armature renaming](./mappings.md)
- [Animation retargeting](./animation.md)
- [Utilities](./utility.md)
- [Exporting animations and meshes](./exporting_animations.md)
- [Weapon CFG files](cfg_export.md)
