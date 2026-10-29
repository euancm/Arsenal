# STALKER 2 Arsenal

This repository contains a Blender add-on, not a playable weapon mod. Keep custom weapon
projects, extracted game assets, generated exports and packaged mods outside the checkout.
Historical test-mod names in the development plan are evidence, not bundled dependencies.

## Layout

- `Arsenal/stalker2_arsenal/`: add-on source and required resources, including the weapon
  control shape library in `shapes/weapon_bone_shapes.blend`.
- `Arsenal/zonekit_tools/`: developer audits and regression tests.
- `Arsenal/doc/`: user documentation.
- `Arsenal/PLAN.md`: technical decisions, test history and pending work.
- `Arsenal/GUIDE.md`: CFG modding reference.
- `Arsenal/dev_load_addon.py`: load or reload the add-on from source in Blender.

## Development

- Target Blender 5.2.2 or newer and follow the existing Python module/operator patterns.
- `unreal_setup.py`, `unreal_import.py` and `uasset_patch.py` are embedded into generated
  ZoneKit scripts. Keep them self-contained; existing generated scripts must be regenerated
  after changing their source.
- Use mod-owned assets for Unreal changes. Do not save or modify shared base-game
  skeletons or assets, and do not test destructive operations on a user's real mod.
- Preserve the donor skeleton hierarchy and additive playback settings. A correct
  standalone sequence preview does not prove correct runtime animation composition.
- Update the relevant user documentation when changing workflow or export behavior.

## Validation

Run the focused tests relevant to the change. Plain-Python setup/import/notification tests:

```powershell
python -m unittest Arsenal.zonekit_tools.test_unreal_setup Arsenal.zonekit_tools.test_animation_import Arsenal.zonekit_tools.test_completion_notifications
```

Blender-dependent tests document their command and required input files in their module
docstrings. Use a disposable scene or an external test blend; never assume a weapon
project is bundled with this repository.

## Localization

Weapon names and descriptions use `sid_items_<ItemSID>_name` and
`sid_items_<ItemSID>_description`. The add-on exports localization JSON through
`export_unreal.py`; the generated `unreal_import.py` script writes the mod's text asset.
See `Arsenal/doc/cfg_export.md` and the existing importer before adding localization logic.
Do not assume external TypeScript localization utilities or retail text catalogs exist here.
