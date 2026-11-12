# Stalker 2 Arsenal Blender add-on

Stalker 2 Arsenal is a Blender add-on for the STALKER 2 first-person animation workflow. The importer, mapping tools, Rigify conversion, retargeting, and animation utilities are included in one installable add-on.

## Install

Download `stalker2_arsenal-<version>.zip` from the **Assets** section of
[GitHub Releases](https://github.com/euancm/Arsenal/releases). In Blender use
**Edit > Preferences > Add-ons > Install from Disk**, select the zip without extracting it,
and enable **Stalker 2 Arsenal**. Do not install GitHub's automatic **Source code** archives.

Blender 5.2.2 is the minimum supported version. See the [development plan](../PLAN.md) for implementation status and planned work.
Enable Rigify before importing a weapon. Both bundled `.blend` libraries and the JSON catalogues
are required and included in the release zip; Git clones need `git lfs pull` before packaging the add-on.

**Only replacing a pistol has been tested end to end.** More weapon types will be tested;
other donor workflows are experimental. See the [known import issues](../PLAN.md#known-non-pistol-import-issues).

### Download and resource notes

The add-on includes two required Blender libraries: `resources/inventory_scene.blend` for
inventory rendering and `shapes/weapon_bone_shapes.blend` for rig controls. Keep these, the JSON
catalogues and both mapping folders inside the add-on when creating its installation zip.

These `.blend` files are stored using Git LFS, which handles binary files separately from
source code. If cloning the repository, install Git LFS and run `git lfs pull` before packaging
the add-on. If using a downloaded source archive, check that the libraries contain real Blender
data: a tiny text file beginning `version https://git-lfs.github.com/spec/v1` is a pointer,
not the library. Obtain the actual LFS files before installing; renaming the pointer will not fix it.

## Workflow

Use the **STALKER 2** tab in the 3D View sidebar:

1. **Set Up**: choose the template weapon, your weapon name, mod name and working folder, and create the ZoneKit setup script. Run it in ZoneKit.
2. **Import Weapon**: one button imports the template's skeleton, meshes, attachments, textures and every matching first-person animation, builds the mapping and converts the character to a Rigify rig with the weapon and camera controls. The original armature is kept in a hidden backup for retargeting.
3. **Retarget**: bake the imported animations onto the rig's character, weapon and camera controls.
4. **Create Your Custom Weapon**: edit the meshes, animations and [weapon sockets](weapon_sockets.md), and set the weapon's stats, magazines, name, description, upgrades and trader/NPC distribution.
5. **Export**: press **Export All** to check and write all matching rig animations, meshes, CFG files, localisation and the ZoneKit import script. Keep the original action names. The category and animation folders follow the selected template; Mod Name is entered only in Set Up.

Weapon import also creates an isolated inventory render scene using the bundled camera, sun lighting,
sky world and compositor template. Panel 4 provides render/clear previews for the weapon and its
magazines. Scene creation, geometry refresh and camera assignment are automatic; use Blender's
scene selector for manual camera or lighting edits. See [inventory image previews](inventory_images.md).
The images are packed into the blend and exported as PNGs by Export All. The generated importer
creates mod-owned UI textures; CFG inventory references and custom attachment localisation are
generated alongside them. Standard is shared for inventory layers, Upgrade for large upgrade layers,
and MagazineStandalone for standalone magazine icons; authored framing and clipping are retained.

Trader/NPC defaults follow the weapon template and remain saved in the blend. The global
**Stock Custom Attachments** option makes purchasable custom magazines, silencers and lasers
follow enabled weapon traders at half the weapon's effective stock chance. The importer combines
all weapons' distribution into one mod-wide CFG; back up `<mod folder>/Arsenal/distribution.json`
with your mod. See [CFG export](cfg_export.md#trader-and-npc-inventories) for gates, quantities,
shared-magazine references and re-import requirements.

The [README](../../README.md) gives a shorter getting-started walkthrough.

Setup creates mod-owned copies directly; it does not use revision-control checkout to create them or save shared base-game assets. Older generated setup scripts may report "not in the mod after checkout; copying it instead" and revision-control checkout dialogs: that is the fallback to duplication, not by itself evidence of a failed setup. A missing mod copy or stale-reference warning still needs investigation. Generate a fresh setup script to use the direct-copy behavior; re-export to refresh the embedded import script after updating the add-on.

## Documentation

- [STALKER 2 animation importer](./stalker2_animation_importer.md)
- [Converting to Rigify](./converting_to_rigify.md)
- [Internal bone mappings](./mappings.md)
- [Animation retargeting](./animation.md)
- [Exporting animations and meshes](./exporting_animations.md)
- [Weapon CFG files](cfg_export.md)
- [Inventory image previews](inventory_images.md)
- [Weapon sockets without opening SKEL](weapon_sockets.md)

## For developers

### Loading from source

Use [dev_load_addon.py](../dev_load_addon.py) instead of reinstalling a zip after each code edit.
Open it in Blender's Text Editor with **Text > Open**, then **Run Script**. Run it again to
reload the add-on. It disables an installed zip copy so the two do not clash.

The bundled `uemannequin_rigify` and `rigify_uemannequin` mappings are live dependencies, not
unused character presets. Generated mappings are stored in Blender's user-data directory;
see [mapping storage and migration](mappings.md).

Setup, import, reference-patching and distribution-composition code is embedded into generated
ZoneKit scripts. Regenerate those scripts after changing the add-on; reloading Blender does not
update existing scripts.

### Building a release

The add-on is Python; its installable zip contains source code and required resources, not
platform-specific compiled bytecode. After `git lfs pull`, build it from the repository root:

```powershell
python -B Arsenal\zonekit_tools\build_release.py 'D:\Arsenal Releases'
```

Choose an output folder outside the checkout. The builder checks syntax, JSON and real Blender
resource headers, excludes caches, backups, extracted assets and developer tools, and writes
the zip plus a SHA-256 checksum. It includes the licence and third-party notice.

To distribute through GitHub, commit and push the intended changes, then push a version tag
matching the add-on version (for example `v1.0.0`). The
[release workflow](../../.github/workflows/release.yml) checks out the real LFS resources,
runs asset-free regressions, builds the package and creates a **draft GitHub Release** with
the zip/checksum attached. Review the release and publish it. Do not tag an older commit:
the release is built from the tagged source, not local uncommitted changes.

Developer diagnostics remain callable from Blender's Python Console:
`bpy.ops.object.arsenal_export_validate()` and `bpy.ops.object.arsenal_debug_report()`.
They are not normal workflow buttons. The missing-clip import helper remains an internal
development function; no Import New Animations operator is registered.

### Developer validation

Run from the repository root. Asset-free plain-Python tests:

```powershell
python -B -m unittest Arsenal.zonekit_tools.test_build_release Arsenal.zonekit_tools.test_unreal_setup Arsenal.zonekit_tools.test_animation_import Arsenal.zonekit_tools.test_completion_notifications Arsenal.zonekit_tools.test_weapon_distribution Arsenal.zonekit_tools.test_distribution_compose Arsenal.zonekit_tools.test_weapon_sockets Arsenal.zonekit_tools.test_world_mesh_sockets
```

Blender tests document their command in each module's opening docstring. For example:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python 'Arsenal\zonekit_tools\test_addon_registration.py'
```

Registration, camera placement, IK-control validation, mapping storage, static meshes, CFG,
inventory images, weapon upgrades and socket-marker tests use disposable synthetic scenes.
Animation round-trip, new-animation and skeleton-export tests need an external weapon blend or
donor FBX as specified in their docstrings. Native ZoneKit socket/collection persistence tests
require a disposable `ArsenalSocketProbe` mod and a second fresh process. Never point those tests
at a real weapon mod. Do not run blanket test discovery under plain Python: Blender/ZoneKit
modules need their respective runtimes.

### Reference data and audits

[survey_template_assets.py](../zonekit_tools/survey_template_assets.py) lists the assets a template
uses. Run it in ZoneKit; its reports go to the git-ignored `zonekit_tools/survey_output` folder.
[audit_mod.py](../zonekit_tools/audit_mod.py) runs in plain Python and lists a mod's dangling or
leftover template references.

The bundled weapon, distribution and upgrade JSON catalogues contain structured defaults and
asset identifiers, not extracted assets. Regenerate them with
[build_weapon_templates.py](../zonekit_tools/build_weapon_templates.py),
[build_distribution_defaults.py](../zonekit_tools/build_distribution_defaults.py) and
[build_upgrade_defaults.py](../zonekit_tools/build_upgrade_defaults.py) when the installed game
data changes. Preserve existing template and upgrade-effect enum numbers when expanding a
catalogue; they are stored numerically in saved blends. The upgrade builder reuses IDs from
the previous catalogue. Keep exported textures, models, test blends, reports and packages outside the
checkout. Required `.blend` libraries must remain included; Blender backups and Python caches
must not be added.
