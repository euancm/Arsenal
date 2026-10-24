# Stalker 2 Arsenal Blender add-on

Stalker 2 Arsenal is a Blender add-on for the STALKER 2 first-person animation workflow. The importer, mapping tools, Rigify conversion, retargeting, and animation utilities are included in one installable add-on.

## Install

In Blender Preferences, install the `Stalker2Arsenal_Blender5_2.zip` package (zip the `stalker2_arsenal` folder; it is not published yet).

Blender 5.2.2 is the minimum supported version. See the [development plan](../PLAN.md) for implementation status and planned work.

## Workflow

Use the **STALKER 2** tab in the 3D View sidebar:

1. **Import Assets**: choose the STALKER 2 folder containing `Animations/Player` and `Animations/Weapons`, create the base skeleton, then scan and import matching animation pairs.
2. **Mapping Setup** (hidden in the panel; generated automatically by Import Weapon): generate a source-to-Rigify mapping, fill any blank source entries, and add mappings for an appended `Weapon` armature when present; the mapping is stored in the .blend file (and saved as a JSON preset) so it survives closing and reopening Blender.
3. **Retarget**: (conversion now happens in Import Weapon) convert the character by mapping and retarget the imported actions onto the character, weapon, and camera controls. Conversion merges an appended `Weapon` rig and keeps a hidden source backup for future retargeting.
4. **Animation Tools**: bake or edit animation as needed.

## Documentation

- [STALKER 2 animation importer](./stalker2_animation_importer.md)
- [Converting to Rigify](./converting_to_rigify.md)
- [Converting from Rigify](./converting_from_rigify.md)
- [Mappings and armature renaming](./mappings.md)
- [Animation retargeting](./animation.md)
- [Utilities](./utility.md)
- [Weapon CFG files](cfg_export.md)
