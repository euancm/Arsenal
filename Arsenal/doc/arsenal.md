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

Weapon import also creates an isolated inventory render scene using the bundled camera, sun lighting,
sky world and compositor template. Panel 4 provides render/clear previews for the weapon and its
magazines. Scene creation, geometry refresh and camera assignment are automatic; use Blender's
scene selector for manual camera or lighting edits. See [inventory image previews](inventory_images.md).
The images are packed into the blend and exported as PNGs by Export All. The generated importer
creates mod-owned UI textures; CFG inventory references and custom attachment localisation are
generated alongside them. Standard is shared for inventory layers, Upgrade for large upgrade layers,
and MagazineStandalone for standalone magazine icons; authored framing and clipping are retained.

The [README](../../README.md) walks through the full workflow.

Setup creates mod-owned copies directly; it does not use revision-control checkout to create them or save shared base-game assets. Older generated setup scripts may report "not in the mod after checkout; copying it instead" and revision-control checkout dialogs: that is the fallback to duplication, not by itself evidence of a failed setup. A missing mod copy or stale-reference warning still needs investigation. Generate a fresh setup script to use the direct-copy behavior; re-export to refresh the embedded import script after updating the add-on.

## Documentation

- [STALKER 2 animation importer](./stalker2_animation_importer.md)
- [Converting to Rigify](./converting_to_rigify.md)
- [Internal bone mappings](./mappings.md)
- [Animation retargeting](./animation.md)
- [Exporting animations and meshes](./exporting_animations.md)
- [Weapon CFG files](cfg_export.md)
- [Inventory image previews](inventory_images.md)
