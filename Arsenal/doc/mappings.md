# Internal bone mappings

**Import Weapon** generates the STALKER-to-Rigify mapping automatically. The mapping panel is
hidden in the normal workflow; no manual armature renaming or preset selection is required.

## Required bundled references

- `mappings/uemannequin_rigify.json` maps canonical Unreal bone names to Rigify names.
  Bone guessing uses it to recognize STALKER names, and retargeting uses it to resolve the actual
  source bones. Despite its inherited name, it is not an unused mannequin preset.
- `animation_mappings/rigify_uemannequin.json` identifies the Rigify animation controls and the
  transforms to retarget. It is also required.

Mixamo, DAZ and the reverse-conversion neck2 preset are no longer shipped.

## Generated mappings

The guess operator saves generated mapping JSON in Blender's user-data directory, under
`stalker2_arsenal/mappings/`. On Windows with Blender 5.2 this is normally
`%APPDATA%\Blender Foundation\Blender\5.2\datafiles\stalker2_arsenal\mappings\`.
Blender resolves the location, including portable or custom user-directory settings.

The operator reuses the active user mapping or chooses a name based on the source armature
(with `_2`, `_3`, etc. for collisions). Loading and listing mappings includes both user files
and bundled references. Bundled references are read-only and take precedence over a user file
with the same name; save edited copies under a different name.

Generated files no longer live inside the addon, so reinstalling the ZIP does not replace them.
Blender's user-data directory is version-specific; when upgrading Blender, copy any mappings
you want to retain into the new version's equivalent folder.

Scene mapping entries are used during conversion. The generated rig stores its character and
weapon mappings so retargeting and export do not depend on reopening a generated JSON preset.
The generated STALKER files formerly stored in this checkout have been moved to user data.
For older addon installations, move custom JSON files from the addon's `mappings/` folder to
the user directory before reinstalling. Leave `uemannequin_rigify.json` bundled with the addon.

For development, mapping guess, entry editing, save and weapon-mapping operators remain available.
See [Rigify conversion](./converting_to_rigify.md).
