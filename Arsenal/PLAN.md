# Stalker 2 Arsenal Development Plan

## Goal

One Blender 5.2.2+ add-on that lets a 3D artist, with minimal technical input, take a STALKER 2 template weapon from ZoneKit, make it their own, and get it back into the game:

1. **Seamless import** from ZoneKit (animations, meshes, attachments, textures, sockets, CFG data).
2. **Simple editing** of weapon, mesh and animation data (Rigify rig, retargeting, controls).
3. **Seamless re-export and packaging** (FBX, ZoneKit import script, CFG, localisation, mod assets).

The add-on lives in `Arsenal/stalker2_arsenal/` and installs from `Stalker2Arsenal_Blender5_2.zip`. The Glock mod in the repo root is a separate deliverable.

## Workflow (as built)

```text
Blender panel 1 "Set Up"   choose template + weapon name + folders  -> writes zonekit_setup_<weapon>.py
ZoneKit (Python bar)       run the setup script: exports template assets, checks out copies into the mod,
                           batch-renames them to the new weapon name, tidies redirectors, writes a report
Blender panel 2 "Import"   imports skeletal mesh (full quality), attachments (all magazines), animations,
                           materials/textures, sockets; Detect Magazines runs automatically
Blender panel 3 "Retarget" Rigify conversion + retarget of character, weapon and camera animation
Blender panel 4 "Create Your Custom Weapon"  edit meshes/animation, weapon presets, CFG values
Blender panel 5 "Export"   FBX animations, skeletal/static meshes, CFG, localisation JSON,
                           ZoneKit import script (zonekit_import_<weapon>.py)
ZoneKit (Python bar)       run the import script: imports FBX, updates anim collections, reports montages
ZoneKit Mod Editor         add localisation text, package the mod
```

## State of each stage

| Stage | State |
|---|---|
| Template selection (Pistol, SMG, Rifle, Shotgun, Sniper) and setup-script generation | Done. Verified offline for all five templates. |
| ZoneKit export of sequences, additive sequences, skeletal/static meshes, magazines, sockets, textures | Done; ran in ZoneKit for the pistol. Socket API names are guesses. |
| ZoneKit checkout + batch rename | Done. Falls back to `duplicate_asset` when checkout is unavailable. |
| Blender import (pairing, LOD1/collision skip, smoothing, vertex-group attachments, DirectX normals, RMA split) | Done; materials tested with synthetic data only. |
| Rigify conversion, retargeting, weapon/camera controls | Done and validated in Blender 5.2.2. |
| Animation / mesh / CFG / localisation export | Done. |
| ZoneKit import script | Done; sequences and collections update. Montages are reported, not edited (see decisions). |
| Reference repointing (montages, AnimCollection, AnimBP, sequences) | **Automated in the setup script** (header patching, D6, extended by D11); verified headless in ZoneKit on a patched copy of the Jellyfish mod; a full setup run is still to be re-tested by the user. |
| Localisation into the mod | **Manual** (Mod Editor text tool using the exported JSON). |
| Weapon visible and fireable in game | **Failing** in the Jellyfish test (loads, does not fire or reload). Two definite defects fixed (D11, D12); retest needed. |

## Known issues

1. **Copied assets still referenced the template (fixed by D6/D11, pending full-run test).** Previously the mod's `MG_fp_<weapon>_*` copies reference the `/Game` `AS_*` sequences; the weapon animates with the original animation. Python in ZoneKit (UE 5.5.4) cannot edit montage slots, composite sections or notifies (probes in `zonekit_tools/`).
2. Attachment mesh names (`SM_wpn_udp_SM_SM_pt_udp_mag_*`) contain a doubled `SM_`. Checked on the Jellyfish output: it is cosmetic only (CFG paths, exported FBX and mod assets all agree) and the magazine SIDs are correct (`Gun<weapon>_MagDefault`, `_MagIncreased`), so it is left alone; renaming would create duplicate assets in existing mods.
3. Laser and silencer placement is not resolved; sockets are exported but the Blender side does not use them yet.
4. `cannot merge bone tree with the existing skeleton` and a missing `/<Mod>/_STALKER2/SkeletalMeshes/SK_Stalker` in ZoneKit (it exists only under `/Game`).
5. Jellyfish test (unmodified UDP, round-tripped through the add-on): loads in game but does not fire or reload. Static findings in "Jellyfish diagnosis" below; cause not yet proven. Possible non-asset causes to check on retest: no compatible ammo in the inventory / empty magazine.
6. Triangle-count effect of Nanite-off export is untested.
7. No in-add-on pre-flight check covering the whole pipeline.

## Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Minimum Blender version is 5.2.2. | User choice. |
| D2 | The earlier post-hoc montage patcher was removed (batch rename was brittle). Superseded by D6, which runs inside the setup script. | Patching at setup time removes user error. |
| D3 | **Never call `consolidate_assets` (or anything that deletes/redirects) on `/Game` assets.** Removed `repoint_to_copies`. | It turned `/Game/.../AS_udp_fp_*` into redirectors, ZoneKit then failed to reload the pak packages ("Invalid import object index") and crashed with `EXCEPTION_ACCESS_VIOLATION`. |
| D4 | Do not rebuild montages with `AnimMontageFactory`. | Probe: loses slot name (`DefaultSlot`), length (0.13 s vs 3.13 s) and most notifies. |
| D5 | `unreal_setup.py` only reports montages that still play template animations (`check_montages`, read-only). | Safe; tells the user which montages need action. |
| D6 | **Implemented:** `patch_references` (setup script, was `patch_montages`) uses `uasset_patch.py` to rewrite name-table entries in the mod's own montage copies (`/Game` AS path and old mod path to the new weapon's sequences), backs up to `<export folder>\reference_backups`, then `reload_packages(..., ASSUME_POSITIVE)`. A loaded package keeps its file open, so the setup script force-saves each loaded montage (`save_loaded_asset(m, False)`) before writing. Unsupported layouts (e.g. UE5 file version 1008) raise `PatchError` and are skipped with a warning. | Preserves slot, length, sections and notifies; touches only mod files, never `/Game`. |
| D7 | Fallback if patching reports a montage as unsupported: `check_montages` lists it with the sequence it should play for a manual swap. | Safety net. |
| D8 | ZoneKit Python can be tested headless: `Stalker2ModEditor-Win64-Shipping-Cmd.exe <uproject> -run=pythonscript -script=<file> -unattended -nosplash -nullrhi -stdout` (about 4 min start-up). New ZoneKit-side logic must be tested on scratch assets under `/<Mod>/ZZ_*` first. | Avoids further crashes in the user's session. |
| D9 | Magazines: standard one is `Default`; extended/increased, twin and drum variants are imported and named by `MAG_QUALIFIER`. | CFG and animation collections reference them. |
| D10 | Localisation stays a manual Mod Editor step, with exported JSON. | Not writable from Python. |
| D11 | Header patching covers every copied asset except skeletons: montages, sequences, AnimCollection, AnimBP and skeletal mesh. `patch_references` first dry-runs each file on disk and only loads, force-saves, patches and reloads those that change. Skeleton copies are not remapped; everything keeps the template skeleton `SKEL_udp`. | The Jellyfish audit (`zonekit_tools/audit_mod.py`) showed the AnimBP loaded the template's `AnimCollection_fp_udp`, and the mod's AnimCollection listed the template's 53 `MG_fp_udp_*` montages, so none of the new animations could ever play. The mod's `SK_` mesh and all sequences already use `SKEL_udp`, so remapping skeletons would only add a second skeleton. |
| D12 | The weapon prototype now sets `MeshPrototypeSID = Gun<weapon>_Skeletal`, a mesh prototype (`MeshType = EMeshSubType::Skeletal`) pointing at the mod's `SK_<weapon>`. `export_check.path_warnings` also checks the SkeletalMesh FBX exists. | The weapon inherited `MeshPrototypeSID = UDP_Skeletal` (vanilla `SK_udp`), so the mod's skeletal mesh was dead data and edits to it would never show. |

### D6 test record

- Parser bugs fixed: an extra 4-byte skip mislabelled the tail of the summary (so `asset_registry_offset`, `bulk_data_offset`, `payload_toc_offset` were not shifted; UE reported `InvalidObjectCount`); also the thumbnail-table entry offsets and the asset-registry `DependencyDataOffset` (absolute) must shift. A guard now raises if the parsed summary does not end at `name_offset`, and `verify()` re-parses and checks all offsets and identical export data.
- Offline: 45 of the Hyena montages patched with 0 errors (46th tested in ZoneKit).
- Headless ZoneKit (UE 5.5.4), `probe_montage_patch.py`: file patched before first load, cold-loaded with `MainActionSlot`, length 0.4, section `Default`, 1 notify, first reference `/HyenaMod/.../AS_fp_hyenagun_empty_click`. Restore + `reload_packages` shows the `/Game` reference again; patch + reload shows the mod reference; a forced editor save keeps the patch. `ReloadPackagesInteractionMode` members: `ASSUME_NEGATIVE`, `ASSUME_POSITIVE`, `INTERACTIVE`.
- Not tested: the complete setup script run end to end inside the interactive ZoneKit, and in-game playback.
### Jellyfish diagnosis (2026-10-25)

Mod: `Mods/JellyfishMod`, UDP imported, unchanged, re-exported; `Gunjellyfishgun_HG` loads but does not fire or reload. Built before the montage patching.

- CFG compared with vanilla `GunUDP_HG`: same fire/ammo/reload data, mags and `WeaponStaticMeshParts`; nothing that blocks firing. Differences: silencer/laser entries dropped, and the weapon inherited the vanilla skeletal mesh prototype (D12).
- Asset audit (`python zonekit_tools/audit_mod.py <ModFolder> udp`): no dangling mod references, but `AnimBP_jellyfishgun_fp` referenced the template `AnimCollection_fp_udp`, template `SKEL_udp` and `AS_udp_fp_*`; `AnimCollection_fp_jellyfishgun` referenced 53 template `MG_fp_udp_*` montages; montages referenced template sequences. So the AnimBP ran entirely on vanilla data and the mod's animations were unused (D11).
- Applied D11 to a copy of the Jellyfish mod offline: 120 copied assets checked, 72 patched, 0 errors. Remaining template references are the intentional `SKEL_udp` and vanilla `MI_p_udp*` materials.
- Headless ZoneKit (`probe_reference_patch.py`) on the patched mod: AnimBP, AnimCollection, SK and a montage all load; the AnimBP now depends on 7 mod assets and the AnimCollection on 53 mod assets, with no template references except `SKEL_udp`. The patched files were left in `Mods/JellyfishMod`; the original is archived in the session `files/JellyfishMod_original` folder.
- Not proven: that this makes the weapon fire/reload. The retail game log was not available (the logs on this machine are ZoneKit's). Retest needs the patched Jellyfish pak (or a rebuilt mod), the game log if it still fails, and a note of whether .45 ammo was in the inventory.
- Also fixed: `uasset_patch` now accepts packages with no thumbnail table (`thumbnail_offset` 0, e.g. the generated localisation database).
## Roadmap

Ordered by value to an artist. "Needs test" means it cannot be validated without the user running ZoneKit or the game.

1. **Reference repointing (D6, D11): implemented and probe-verified.** Remaining: user re-runs a setup script and checks the report; confirm in game. Needs test.
2. **Attachment naming and magazine SIDs**: checked, cosmetic only, no change (known issue 2).
3. **Invisible/unfireable weapon**: static diagnosis done and two defects fixed (D11, D12); waiting for an in-game retest. If it still fails: game log, ammo check, then compare the AnimBP and AnimCollection property values against vanilla in the editor.
4. **Silencer and laser attachments**: import meshes from CFG, place on exported sockets, export their transforms.
5. **Pre-flight validation panel**: single "Check Everything" button covering skeleton/bone names, action coverage per montage, attachment list, naming rules, CFG sanity, and the montage status; output as a plain-language checklist.
6. **Weapon control editor** (create controls from selected weapon bones) and **arbitrary cameras** from the previous plan.
7. **Localisation helper**: open the JSON folder and show the exact SIDs to paste in the Mod Editor.
8. **Regression matrix and release**: run the animation matrix on all five templates; produce the release zip only when the user decides (zips are git-ignored).

## Acceptance criteria

- An artist can go from "choose template and name" to a packaged, working weapon following only the panel instructions, with no manual file renaming.
- No step crashes ZoneKit; every ZoneKit script is idempotent and reports what it did and what remains manual.
- Blender-side tests pass headless on Blender 5.2.2 for all five templates.
- Documentation in `Arsenal/doc/` matches the panels.
