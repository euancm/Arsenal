# Stalker 2 Arsenal Development Plan

## Goal

One Blender 5.2.2+ add-on that lets a 3D artist, with minimal technical input, take a STALKER 2 template weapon from ZoneKit, make it their own, and get it back into the game:

1. **Seamless import** from ZoneKit (animations, meshes, attachments, textures, sockets, CFG data).
2. **Simple editing** of weapon, mesh and animation data (Rigify rig, retargeting, controls).
3. **Seamless re-export and packaging** (FBX, ZoneKit import script, CFG, localisation, mod assets).

This repository is dedicated to the add-on, its resources, developer tools and documentation. The add-on lives in `Arsenal/stalker2_arsenal/`; install it by zipping that folder. Weapon projects, extracted template libraries, generated exports and packaged mods belong in separate working folders, not in this checkout. The former standalone Glock/custom-pistol assets have been removed; named mods below are historical test cases, not bundled examples.

Legacy-only character tools and their resources have also been removed: Mixamo/DAZ presets, mannequin pose and reverse skeleton conversion (including the neck2 mapping/templates), rig reset/scale, weight-paint shortcuts and vertex placement. The STALKER importer still uses mapping-based Rigify conversion and metarig generation. Keep `mappings/uemannequin_rigify.json`, `animation_mappings/rigify_uemannequin.json` and the weapon shape library: these are live workflow dependencies, despite the inherited mannequin names. Generated STALKER mappings now live in Blender's `DATAFILES/stalker2_arsenal/mappings` user directory, not the addon; existing checkout copies were migrated there. Bundled references remain read-only.

## Workflow (as built)

```text
Blender panel 1 "Set Up"   choose template + weapon name + folders  -> writes zonekit_setup_<weapon>.py
ZoneKit (Python bar)       run the setup script: exports template assets, creates mod-owned copies,
                           batch-renames them to the new weapon name, tidies redirectors, writes a report
Blender panel 2 "Import"   imports skeletal mesh (full quality), attachments (all magazines), animations,
                           materials/textures, sockets; Detect Magazines runs automatically
Blender panel 3 "Retarget" retarget character, weapon and camera animation onto the generated Rigify rig
Blender panel 4 "Create Your Custom Weapon"  edit meshes/animation, weapon presets, CFG values
Blender panel 5 "Export"   FBX animations (baked at 4 substeps/frame), skeletal/static meshes, CFG,
                           localisation JSON, ZoneKit import script (import_<weapon>.py)
ZoneKit (Python bar)       run the import script: recovers missing donor copies/references first,
                           imports textures/materials/meshes, imports animations
                           through the legacy FBX path, applies sockets, syncs additive idles,
                           writes localisation text and composes mod-wide trader/NPC distribution
ZoneKit Mod Editor         package (cook) the mod, then install/replace the pak and test in game
```

## State of each stage

| Stage | State |
|---|---|
| Template selection (Pistol, SMG, Rifle, Shotgun, Sniper) and setup-script generation | Done. Verified offline for all five templates. |
| ZoneKit export of sequences, additive sequences, skeletal/static meshes, magazines, sockets, textures | Done; ran in ZoneKit for the pistol. Native socket reference frames and mod-owned writes have disposable ZoneKit coverage; cooked gameplay acceptance remains separate. |
| ZoneKit mod copy + batch rename | Done. Uses `duplicate_asset` directly; revision-control checkout does not create a mod copy and caused unnecessary warning dialogs. |
| Blender import (pairing, LOD1/collision skip, smoothing, vertex-group attachments, DirectX normals, RMA split) | Done; materials tested with synthetic data only. |
| Rigify conversion, retargeting, weapon/camera controls | Done and validated in Blender 5.2.2. |
| Animation / mesh / CFG / localisation export | Done. |
| Inventory image rendering/export | Asset-free three-camera/sun/sky/compositor template; automatic scene creation/recreation, rest-mesh refresh and camera assignment; packed previews. Standard for inventory layers and standalone accessories, Upgrade for large upgrade layers, MagazineStandalone for standalone magazines. Authored transforms and clipping retained; no fitting or scene-management controls. Manual edits via Blender's scene selector. Temporary weapon holdouts for attachment layers. Export PNGs and inventory CFG references; import mod-owned UI textures. Custom magazine/silencer/laser localisation. PDA/module close-ups and per-class dimensions remain pending. |
| Selected images / custom upgrade trees | Image-file selection creates resized, packed RGBA previews without changing source files. Unchecked base-tree option seeds all five templates' upgrade entries; editable layout, text, module images, dependencies and existing/custom numerical effects export with mod-owned SIDs. Shared donor assets/CFGs untouched. 64 focused Blender and 67 importer tests pass; technician layout and effects still need in-game verification. |
| Trader / NPC distribution | Per-trader stock and per-faction role/rank controls; blend-persistent defaults load from the selected template, and changing template resets trader/NPC rules. The global custom-attachment toggle is retained. Trader values copy matching stock entries and base prototype defaults; NPC columns approximate the template's weighted shares (difficulty mean, role peak, mean normalized rank share). Role and rank percentages multiply. Slot follows weapon template; condition/spare rounds copy matching template entries, with difficulty-specific splitting where needed. The importer composes one mod-wide CFG with combined private pools and one patch per generator root. Template-matching stock routes retain activation gates; UI shows effective weapon and attachment chances. Purchasable custom attachments follow enabled weapon traders at half the effective weapon chance. Structured catalogue covers 18 traders and 50 generic role loadouts, with live NPC-to-trade links verified. Fresh-spawn/stock-refresh gameplay verification pending. |
| ZoneKit import script | Done; sequences and collections update, additive idles are resynchronised, montages keep their slots/notifies (header-patched at setup). |
| Reference repointing (montages, AnimCollection, AnimBP, sequences) | **Automated in setup and recovered by fresh import scripts** (header patching, D6, extended by D11); the original setup path is gameplay-confirmed with LadybugMod. |
| Localisation into the mod | **Automated native text upserts** by the import script: reuses the mod's text asset or creates `<Mod>TextToolAsset`, supports empty arrays without exposed entry/enum classes, preserves other SIDs/languages, verifies before saving and skips unchanged saves. Offline regression coverage; live ZoneKit/in-game verification of this path pending. Export All must regenerate older import scripts. |
| Weapon visible and fireable in game | **Verified in Ladybug by the user:** visible model, CFG stats, normal/extended magazines, firing, reloading, edited reload fingers and fire/aim transitions all work. Bird (blank-slate rerun) reproduced the same result, and confirmed the aim pose, crouch lean (D22) and aim transitions (D24). |
| Fire, equip, empty click, offset aim and weapon-only clips in Blender | **Done (D25, D26)**; gameplay-confirmed with Bird. |

### Repository validation (2026-11-12)

The pre-push audit removed extracted inventory texture references and outdated UI mockups
from the checkout, preserving them in an external local archive. Required shape and inventory
scene libraries remain bundled through Git LFS. Ignore rules now also exclude extracted Unreal
assets, FBXs, packaged mods and numbered Blender backups. Existing Git history is unchanged.

Validation: 182 asset-free plain-Python tests pass. Nine disposable Blender 5.2.2 suites run
134 tests, with one optional real-donor socket-marker test skipped because its external FBX
and catalogue were not supplied; all other cases pass. Two manifest-export test fixtures were
updated to supply the rig/context data required by world magazine sockets and distribution.
Python syntax, JSON catalogues, local documentation links/anchors, Git LFS integrity and
whitespace checks pass. This does not revalidate native ZoneKit persistence, cooking or gameplay.
See the README's developer-validation section for runtimes and external fixture requirements.

### Automatic custom attachment stock (2026-11-12)

**Stock Custom Attachments** is enabled by default and applies to all of a weapon's enabled
traders. Each purchasable custom magazine, silencer and laser gets a separate one-item stock
roll at half the weapon's effective stock chance. Weapon-pool gates are included: a 40% entry
behind a 50% gate gives the attachment a 10% roll. Preinstalled magazines, references to
existing magazine items and stock game attachments are excluded. There are no separate
attachment trader rules or NPC attachment-distribution controls.

The manifest stores these additions with the weapon's distribution record. Composition appends
to an existing direct attachment group or creates one independent attachment group for that
trader, combining all custom weapons without repeated roots or duplicate per-import entries.
Shared base-game attachment pools are unchanged. Re-importing replaces that weapon's plan;
turning the option off or disabling a trader removes only its automatic additions.

Regression checks cover direct and gated routes, all 18 traders, multi-weapon composition,
repeat import, disabling stock and the generated import path. In-game stock refresh remains
an acceptance check. Re-export each existing weapon and run its fresh importer to opt its
stored plan into attachment distribution.

### World magazine mount sockets (2026-11-11)

The ECM E9 world mesh package had no `jnt_magazine` socket/name. Its CFG correctly referenced
the shared Gen7 magazine's bone-local AnimMesh, but the world carrier had no corresponding
mount. In the saved E9OG project the magazine joint is (-0.936825, 0, -3.549240) cm relative
to the world root, explaining a raised magazine when attached at the root instead.

Exports now include a validated world static-mesh socket payload for the configured magazine
mounts, including shared existing SIDs. Positions use the same rest heads/source-unit conversion
as static geometry; socket rotation stays identity because part export subtracts translation
only. The importer creates/updates mesh-owned static sockets after static FBX import, marks
the owner dirty, verifies readback, saves and rolls back failures. First-person animation,
skeletal sockets and shared magazine geometry are unchanged.

Validation: 117 focused plain-Python socket/import regressions and six Blender checks
(static geometry plus generated manifest) pass. A read-only check of the actual E9OG project
reconstructs all four standard/extended, full/empty magazine meshes at the world position
with zero measured vertex error after adding the socket offset. The blend and real mod
were not saved or changed. In-game world-model alignment still requires a fresh import/package test.
Native ZoneKit transient assertions also passed for mesh-owned socket creation, transform
readback and repeat-import no-op. Enumerate via `get_socket_names()` / `find_socket()`:
the native `sockets` property is protected. The commandlet returned nonzero for existing
DDC/DLC errors and unavailable real-mod asset-registry mounts; native save/restart persistence
of these new world sockets was not tested.

### Automatic mod-wide distribution composition (2026-11-11)

The three-weapon ECM Pistols test exposed 32 repeated generator roots (22 NPC, 10 trader).
Per-weapon shared-pool route assignments competed even within one mod, triggering the game's
same-entities conflict warning and potentially hiding weapons from stock/spawn pools.

Fresh import scripts embed the self-contained distribution composer and reference catalogue.
Manifests carry per-weapon structured distribution plans. The importer migrates installed,
recognized Arsenal-generated legacy CFGs, persists all weapon records outside Content, and
transactionally rebuilds one mod-wide CFG with one patch per generator and shared combined
caller-owned pools. Reimporting/disabling one weapon preserves the others; no extra UI steps.
Joint NPC weights preserve requested shares when their sum is at most 100%. Higher totals are
proportionally scaled to 100% with explicit requested/effective-share warnings, as requested
after migration exposed existing per-weapon 100% selections in the same pool.
The installed test data includes one such conflict: Mercenary Close Combat / Master requests
50% + 33.33% + 50%; the importer warns and uses 37.5% + 25% + 37.5%. Gameplay confirmation that a newly
packaged combined CFG removes the warning remains necessary.

Validation: 122 plain-Python distribution/import tests and 79 Blender CFG/image/registration
tests pass. A disposable copy of the actual three-weapon CFG set migrated into one file with
103 unique roots (50 private pools); all three weapons remain reachable through the shared
Chemical Plant trader and Monolith Recon routes. Repeat import is byte-identical. No real mod
files were changed by validation.

### Setup recovery and native SID save correction (2026-11-11)

Fresh import scripts embed setup plus the `.uasset` reference patcher, with the
actual donor animation/mesh tokens captured from Blender. Recovery creates only
missing renamed targets, preserves existing mod-owned assets and repairs stale
references before any Blender FBX import. It does not re-export donor files or
save shared base-game assets. A repeat normal setup also skips existing renamed
targets rather than creating another donor-named copy.

A disposable ZoneKit run exposed the magazine persistence failure: property
reads returned shared native struct/map views, so editing the planned maps also
mutated the original used for readback/rollback. Validation failed with
`GunUDP_MagDefault` missing from the original, leaving changed in-memory values
without a save. SID updates now copy the native struct explicitly and stage maps
as detached dictionaries. Generic collection text import skips internal maps;
existing target values still win over obsolete donor duplicates. Both collection
and socket writes explicitly mark their owning asset dirty.

Focused plain-Python tests cover aliasing, dirty-owner saves, repeat imports,
recovery order, preserved existing assets and failure reporting. A synthetic
Blender test validates generated importer syntax and both embedded sources.
`zonekit_tools/test_collection_sids_zonekit.py` exercises real native wrappers
and fresh-process persistence on the disposable ArsenalSocketProbe mount.
The live recovery run created/repointed the missing UDP donor copies, succeeded
again without recreating them, and saved the corrected collection. A subsequent
fresh process verified its complete internal-animation text and the independent
mesh-only socket owners/transforms. The offline audit found no dangling mod
references; recovered weapon assets retain only the intended donor skeleton
reference. 126 focused plain-Python tests and the Blender generation test pass.
ZoneKit commandlets report existing missing DDC host/DLC asset-domain startup
errors (exit 1), but both final Python scripts explicitly completed successfully.
The reported in-game aiming/packaging behaviour still requires a fresh export,
import, package and gameplay check; in-session socket readback is not proof.

### Distribution packaging correction (2026-11-10)

The initial distribution export put partial base-generator `{bpatch}` blocks in the weapon's
`ModGameData` namespace. The reported cook loaded those as additional prototypes and rejected
missing `SID`, `Category` and `ItemPrototypeSID` fields. The wiki's trader/CFG guides require
base-generator patches under `GameData/ItemGeneratorPrototypes`, not `ModGameData`.

Distribution now writes `GameLite/GameData/ItemGeneratorPrototypes/<Mod>_<ID>Distribution.cfg`.
Private shared-pool specializations remain beside their callers in this base namespace; their
SIDs already include the mod and weapon IDs. Weapon/attachment definitions remain in ModGameData.
Every export also writes a comment-only legacy `<ID>Distribution.cfg` in the old ModGameData
location, so the normal importer overwrites the invalid file in an existing mod. Disabling all
rules clears the live patch file too. No shared ZoneKit content or real mod was edited for testing.

Validation: 26 asset-free distribution tests, 71 importer tests (including legacy-file migration),
and 36 Blender CFG tests pass; the exporter has no Pylance syntax errors. Native cook validation
was attempted with a disposable CFG-only mod, but it lacks the GameFeatureData asset required to
activate its namespace. Those attempts therefore do **not** validate the corrected parser output
or a successful package. Re-export/import and a full package of the user's mod remain the
integration acceptance check, followed by fresh NPC/trader inventory checks in game.

## Current status: version 1 (2026-10-27)

Bird Mod (UDP template, `D:\Euan\3D\Stalker Mods\Bird Mod Working Folder`) is the reference test: a blank-slate rerun of the whole pipeline that reproduced LadybugMod's results exactly, with reload and other animations matching a viewport screenshot overlay.

Works in game:

- Weapon visible, uses its own `SK_` mesh and static meshes; vanilla UDP and Gambit are no longer replaced (D18).
- CFG stats, normal and extended magazines, firing and reloading.
- Edited reload (left hand in IK, edited fingers) matches the viewport, including sleeves and wrist roll (D16/D17).
- Fire → idle recovery has no finger or hand jumps (D19); aim in/out transitions are smooth (D19/D20).
- Aimed pose centred and crouch lean correct (D22, game-confirmed with Bird).
- Sprint → aim and aim after reload are smooth (D24, game-confirmed with Bird).

Watch: right after loading, the user once saw fire → reload → aim give a jerky first aim, with later aims normal. After a few minutes in game, and after reloading the save, it could not be reproduced. Treated as a loading glitch (streaming or first-use compression), not an animation bug. If it comes back, note whether it only happens on the first reload after loading.

- Fire, aim fire, empty click, equip/unequip, offset aim, `idle_boltlock` and `break_bullet_idle` are imported into Blender and exported like the other clips (D25, D26); no problems found in game with Bird.

This is **version 1**: the complete round trip for the pistol template. The other four templates
remain untested in game. Manual socket authoring is implemented; automatic sight alignment and
cooked attachment/effect placement still require the work/checks listed in the Roadmap.

History of the sprint → aim fix: sprint comes from the shared pistol collection, and at that
time fire and equip were untouched vanilla overlays (they are now editable; see D25/D26).
The game blends them with ours bone by bone in local space. Our `jnt_l_arm`/`jnt_r_arm` were
47–60° / 26–30° twisted off the donor (positions exact, children compensating), because
Rigify's `DEF-upper_arm` copies the twist-free `upper_arm_tweak`. Blending two clips whose arm
frames disagree swings the hand off its path. Reload's last frame already matched
idle/idle_aim/idle_to_aim's first frame as closely as vanilla's, so the clips themselves had no seam.

The mesh-space additive conversion tried for these (D21) made things much worse and is rolled back. Measuring Bird's export against the donor found the cause the plan below predicted: the lower spine's local frames were twisted 19° and stretched, which only the game's procedural spine layers expose (D22). A second bug, one clip's control edits leaking into other clips, was found and fixed on the way (D23).

## Known issues

E9 automatic audio and inventory composition (2026-11-10):

- The exported UDP-based setup has `FireEventOneShot` but no loop/break pair.
  The installed Wwise event banks contain `SFX_UDP_Oneshot`, not a UDP loop or
  break event. No verified CFG-only one-shot retrigger option was found.
  UDP audio is deliberately unchanged at the user's request; a previous working
  export or editable Wwise project is unavailable. Automatic UDP sound remains
  unresolved, and export now warns for automatic/burst modes on one-shot presets.
- Follow-up: the user selected a CFG-only donor sound solution. **Handling & Fire ->
  Firing Sound** now selects APB, UDP, Viper, AK-74 or the existing template sound,
  independently of stats/animations. APB exports its complete one-shot/loop/break/
  sound-switch set, without replacing rattles or unload audio. The blend stores
  the selection; existing projects default to following the template. APB must be
  selected explicitly for E9 and the updated CFGs packaged. Runtime validation is pending.
- SMG/Viper and Rifle/AK74 presets had omitted their existing donor loop/break
  events. Both now export the complete three-event set; these are not substituted
  into the UDP preset.
- A read-only ZoneKit probe measured the Integral stock silencer overlay at
  648 x 258 and the UDP stock overlay at 258 x 128. Generated pistol images use
  258 x 128, but the stock silencer CFG fallback uses Integral artwork and offsets.
  Stock silencer/laser preview settings now support shared-camera inventory and
  upgrade layers, exported as mod-owned textures with zero offsets. Preview
  meshes do not alter the runtime attachments. Missing aligned stock layers warn
  when using a custom body icon. Render/select the layers and regenerate the
  import script; the final composed inventory icon still needs in-game validation.

E9 aimed-fire recovery investigation (2026-11-05): a read-only Blender/ZoneKit comparison found
`shoot_aim_end` missing `upper_arm_ik.R` transform keys while the aimed idle/fire use about
0.992179 rad local Y rotation. Saved recovery differs from aimed idle by about 54.41 degrees at
the right upper arm; the hand IK keys alone do not repair it. An in-memory test copying that
control's intended frame-1 transforms from `idle_aim` reduces the end-pose upper-arm difference
to 0.617 degrees. No weapon project or mod assets were saved. The failed clip's older FBX was
still discovered by the next import script: Export All now stops before generating the script
when any selected animation fails. Camera recovery is separately exposed as delay/time controls,
preserving the old 0.0/0.06-second output; UDP uses the same values. Manual action repair and
fresh export/import/package/in-game verification remain required.

1. **Fixed and gameplay-confirmed (D6/D11).** The mod's `MG_fp_<weapon>_*` copies used to reference the `/Game` `AS_*` sequences, so the weapon animated with the original animation. Python in ZoneKit (UE 5.5.4) cannot rewrite montage slot tracks/composite sections, so references are rewritten on disk instead (the one-off montage probes have been removed; see git history). Attachment notify SIDs are separately writable and now synchronized by the importer (D27).
2. **Fixed (D13).** Attachment mesh names had a doubled `SM_` and kept the template name (`SM_wpn_jaguargun_SM_SM_pt_udp_mag_full`), and the export check reported every template-named file left in the output folder by earlier exports.
3. **Implemented; gameplay checks pending.** Blender imports attachment placement and editable
   socket markers; the generated importer writes mod-owned mesh overrides. Verify attachment,
   effect, first-/third-person and dropped/world consumers separately; see the socket implementation record.
4. **Fixed and gameplay-confirmed (D14/D15).** `cannot merge bone tree with the existing skeleton`: the skeletal-mesh export renamed the armature and exported an outer empty as an extra root bone. D14 alone did not remove that extra root. A missing `/<Mod>/_STALKER2/SkeletalMeshes/SK_Stalker` in ZoneKit (it exists only under `/Game`) is unrelated.
5. **Superseded.** The Jellyfish test (unmodified UDP through an older build) did not fire or reload; the causes were D11/D12/D14/D15, all fixed and confirmed in LadybugMod.
6. Triangle-count effect of Nanite-off export is untested.
7. No in-add-on pre-flight check covering the whole pipeline.
8. **Fixed and gameplay-confirmed (D22):** final aim pose high/left of centre in game.
9. **Fixed and gameplay-confirmed (D22):** crouch lean went right instead of slightly left while holding the weapon.
10. The Ladybug blend was saved at 25 FPS; exports use the template's 30 FPS timebase. Set the viewport to 30 FPS when comparing timing with the game.
11. **Fixed (D23):** controls keyed only in one action (Bird's `reload` keys left finger masters, `palm.L`, `hand_ik.L`, `upper_arm_ik.L`) leaked that pose into every other exported clip, depending on export order. Unedited idle/idle_aim left index fingers were 30–50° off the donor. Blender's viewport shows the same leak when switching actions, which is why a viewport overlay did not reveal it.
12. **Fixed and gameplay-confirmed (D24):** sprint → aim drifted down/left; the first aim after reload was jerky. A one-off jerky first aim right after loading a save could not be reproduced (see Current status).
13. Residuals vs the donor, left alone: finger base twist (`*_meta`, `*_01`, `thumb_01`, 11–32°, constant across clips; no rig bone carries it) and the leaf sleeve helpers `jnt_*_arm_roll` (10–29°) and `jnt_*_fore_arm_*` (≤2°). Revisit only if a game test points at fingers or sleeves. Because of these, a clip exported unedited is not bit-identical to the donor; compare new clips against an accepted export (as `test_new_animations.py` does), not against the donor.
14. Exporting an asset from the headless ZoneKit commandlet with `export_preview_mesh=True` crashes it (`EXCEPTION_ACCESS_VIOLATION`, any sequence, including `AS_fp_udp_idle`). The setup script runs in the editor, where the same option has always worked; headless probes must pass `export_preview_mesh=False`.

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
| D10 | *Superseded:* localisation was a manual Mod Editor step. The import script now writes the entries into the mod's `LocalizationModTextToolAsset` and only falls back to the manual step (with the exported JSON) if the editor's Python cannot edit it. | Removes the manual step when the editor exposes the asset class; the fallback keeps older editors working. |
| D11 | Header patching covers every copied asset except skeletons: montages, sequences, AnimCollection, AnimBP and skeletal mesh. `patch_references` first dry-runs each file on disk and only loads, force-saves, patches and reloads those that change. Skeleton copies are not remapped; everything keeps the template skeleton `SKEL_udp`. | The Jellyfish audit (`zonekit_tools/audit_mod.py`) showed the AnimBP loaded the template's `AnimCollection_fp_udp`, and the mod's AnimCollection listed the template's 53 `MG_fp_udp_*` montages, so none of the new animations could ever play. The mod's `SK_` mesh and all sequences already use `SKEL_udp`, so remapping skeletons would only add a second skeleton. |
| D12 | The weapon prototype now sets `MeshPrototypeSID = Gun<weapon>_Skeletal`, a mesh prototype (`MeshType = EMeshSubType::Skeletal`) pointing at the mod's `SK_<weapon>`. `export_check.path_warnings` also checks the SkeletalMesh FBX exists. | The weapon inherited `MeshPrototypeSID = UDP_Skeletal` (vanilla `SK_udp`), so the mod's skeletal mesh was dead data and edits to it would never show. |
| D13 | Attachment meshes are named by `export_static_mesh.attachment_stem`: the object's own `SM_` prefix and Blender `.001` suffix are dropped and the template name is replaced by the weapon name, so `SM_pt_udp_mag_full` becomes `SM_wpn_<weapon>_SM_pt_<weapon>_mag_full` (world mesh `SM_<weapon>_pt_<weapon>_mag_full`). Shared attachments such as `SM_sc01_en_silen_1` keep their name. The CFG writer uses the same function. The export check now only flags template names in files written by this export, and summarises leftovers from earlier exports in one line. | The old names triggered template-name warnings on every export, and the warnings buried real problems under leftovers the import script never uses. Existing mods built with the old names will get new asset names on their next export. |
| D14 | `export_skeleton` keeps the template's root bone name (`jnt_wpn_udp`) in `SK_<weapon>.FBX`; it no longer renames the armature object (which the FBX exporter writes as the root bone), and strips a Blender `.001` suffix by moving a clashing scene object aside for the export. | JaguarMod (first run with D11/D12): `SK_jaguargun` had root `jnt_wpn_jaguargun` while its skeleton `SKEL_udp` and every weapon sequence use `jnt_wpn_udp`. The reimport could not merge the bone tree (known issue 4), and with D12 pointing the weapon at that mesh it was invisible and could not fire or reload. The working Glock's `SK_E9Gen7` has `jnt_wpn_udp`. |
| D15 | Detach the donor armature from its outer FBX empty, preserve its world transform, and export only armature/mesh objects. | Ladybug still failed after D14. ZoneKit confirms its mesh's actual root was `SK_ladybuggun` (index 0), with `jnt_wpn_udp` at index 1; vanilla and the working Glock start at `jnt_wpn_udp` (index 0). Keeping the armature name was necessary but insufficient. The Blender regression and scratch ZoneKit import verify that removing the wrapper produces the correct hierarchy. |
| D16 | Bake final `ORG-` poses where available, including fingers, and retain mapped translation/rotation/scale regardless of the input retarget mapping kind. | The saved Ladybug reload uses left-arm IK and edited fingers. Finger controls differ from their constrained deform result, and discarding local translations moves the IK wrist. Before the fix, its imported wrist/index differs from the saved viewport by up to 1.685 cm / 31.59 degrees; after the fix, a scratch Unreal import differs by under 0.00014 cm / 0.00042 degrees over 94 frames. |
| D17 | Bake mesh-driving `DEF-` bones, including palms, roll joints and helpers; save the complete deform binding separately from control retarget mappings. Solve locals with Unreal TRS composition and import animations with explicit `FbxFactory` / `preserve_local_transform=True`. Repair unbound wrist groups and Blender-only B-bone segments in old scenes before export. | D16 verified selected ORG joints, not mesh deformation. The saved rig has omitted twist/palm mappings, unbound sleeve groups and 8-segment spine B-bones. Matrix-local decomposition introduces shear errors; Interchange further rebuilds locals even when asked to preserve them. Full weighted-bone and evaluated-vertex regressions catch these distinct problems. |
| D18 | Temporarily disable Interchange's FBX route around animation batches and restore its prior flag in `finally`. Resolve a main mesh still named after the template to the custom weapon namespace, consistently across static FBX/manifest/CFG. Reject planned or stale mod static meshes that collide with `/Game` packages. | A factory alone did not override existing Interchange reimport data. The latest Ladybug idle/aim clips had roughly 4.5–4.8 cm hand errors despite a correct reload, corrupting its additive reference. ZoneKit's classifier explicitly listed the exported `p_udp` meshes as vanilla overrides, affecting UDP/Gambit. |
| D19 | Preserve donor component-space tracks for unmapped weapon hand sockets. Regenerate the runtime additive idles from the exported reference idles. Restore original base references only on copied overlays whose complete raw tracks and additive settings remain unchanged. | Visible-joint fidelity missed a 127.35 cm / 151.57-degree weapon-socket discrepancy. The live collection uses untouched `idle_add` / `idle_aim_add`, while shooting overlays were subtracting modified mod idles from unchanged vanilla tracks. Partial blends and clip handoffs must share a consistent local-bone representation. |
| D20 | Bake evaluated rig poses and solved socket compensation at four substeps per action frame; retain subframes in FBX and detect their sample rate on import. Use RAW pose evaluation for comparisons, not legacy raw-track array getters. | A direct Unreal-style TRS interpolation repro produced 2.268869 cm of between-key socket drift at 30 Hz versus 0.000185 cm with the 120 Hz bake. Native-key-only tests missed it. ZoneKit's legacy `get_raw_track_data` returned empty arrays even for populated tracks, so using it would falsely identify edited overlays as unchanged. RAW evaluation at every native key plus matching interpolation mode verifies the actual data instead. |
| D21 (rejected) | Do not convert idle/aim assets to mesh-space rotation extraction. Preserve the pre-D21 donor additive modes. | The isolated mesh-space composition model passed, but the user's gameplay test produced a tilted default view and severely deformed arms. A node name and partial graph composition do not establish the runtime contract. The conversion, generated importer change and four saved assets are rolled back; the model is not a gameplay regression oracle. |
| D22 | `jnt_spine_01` and `jnt_spine_02` (`TORSO_AIM_CHAIN` in `export_animation.py`) are exported as the donor's local transform, swung only as far as needed to point at the rig's next spine joint. They keep the donor's translation, twist and scale. `jnt_spine_03` and everything below it are solved from the rig as before. | Bird's export matched every visible bone exactly, but `jnt_spine_01` was twisted 19°, `jnt_spine_02` rotated 19° with scale (1.22, 0.90, 0.90), and `jnt_spine_03`'s local compensated. That is Rigify's stretchy DEF spine reproducing joint positions, not frames. The game's look-pitch and stance layers rotate those bones in their local frames, so wrong frames move the camera/weapon (virtual bones under `jnt_spine_03`) and flip the crouch lean. After the fix, Bird's idle, idle_aim, idle_to_aim and reload match the donor exactly on the whole spine chain, while `jnt_spine_03`, the arms, hands and sockets are unchanged. Spine bends still export (via the swing); twist edits on spine_01/02 are dropped. Chest vertices weighted to spine_01/02 now follow the donor rather than the Rigify viewport (about 4.6 cm on Bird's chest, outside the first-person view). |
| D23 | Before exporting each action, every pose channel that action does not key is reset to rest, and the pose is restored afterwards. An unkeyed `IK_FK` switch counts as FK (1.0), the mode retargeted clips are baked in (amended by D26; a muted curve still counts as keyed). | Blender leaves unkeyed controls where the previous action left them, so a reload-only finger edit leaked into idle, aim and every later clip. |
| D24 | `DEF-upper_arm.L/R` copies `ORG-upper_arm` (full twist) instead of Rigify's twist-free `upper_arm_tweak`. Applied by conversion and by **Repair Deformation Preview**; export refuses an unrepaired rig. | The game's `jnt_*_arm` carries the arm's twist; ours lacked it, which was invisible alone but bent local-space blends with vanilla clips. Locking the export to the donor's twist instead (tried first) moved edited-reload upper-arm skin up to 11 cm from the viewport. With the rig change, viewport, export and donor agree. |
| D25 | Setup exports every additive sequence except the `*_add` idle companions, which the import script rebuilds (`export_additive_overlays`). The Blender importer also reads `AS_FP_Player_<w>_*` (offset aim) and pairs a one-sided clip with the other side's `idle` as a stand-in; export writes only the real half (status "weapon only" / "character only") and keeps the template's filename with the weapon token swapped. Overlays are exported like every other clip, edited or not. | Supersedes "export only edited overlays" in the plan below: reload, melee, `break_bullet` and the aim transitions are overlays (local and mesh space) and have always been exported unedited, game-confirmed. Fire, equip and offset aim follow the same path, so one rule covers all. `idle_boltlock` / `break_bullet_idle` place the weapon object exactly like the weapon idle, so the player idle is a valid stand-in. |
| D26 | **Import New Animations** (Import panel) imports and retargets only the clips a converted blend does not have yet; existing actions are untouched. The importer reveals the master armature (kept in a hidden collection after conversion) while it bakes. The retarget rests every control on a fresh output action before baking and keys each limb's `IK_FK` to FK. | A hidden armature is not evaluated, so the visual-keyed bake recorded the idle instead of the clip (weapon `idle_boltlock` came out equal to idle). An unkeyed control posed by another clip was baked in as compensation (a posed `tweak_spine.003` changed the fresh `idle` curves by up to 5.8), and an unkeyed IK switch left at IK by an edited reload would play the new clip's arm through rest IK controls. |
| D27 | The import script (`sync_collection_sids`) replaces donor magazine SID keys in `reloading`, `one_hand_reloading` and `attaching_by_sid`, and donor silencer/laser SID keys in `attaching_by_sid`, using manifest magazines/attachments. It moves the full struct value to the configured SID and removes the donor key. An existing target value is preserved; obsolete donor duplicates from earlier imports are removed. Explicit nested editor properties and `export_text` readback verify the exact keys and values before saving; readback/save failures restore the original. It never uses `import_text`. | E9Mod's donor magazine and silencer SIDs caused stuck reload/attach states. The initial insert-only approach left obsolete keys behind; the user reported these duplicate entries did not work properly. Replacement, rather than adding aliases, is required. `dir()` in ZoneKit does not list the internal map fields. Silencer detach remains unanimated, matching the base game. |

### Attachment notify SID follow-up (D27)

- E9Mod's exported UDP player silencer montage backup contains two
  `AnimNotify_AttachItem` objects with `BindedAttachSid = EN_Silen_1`, for
  `JoinAttachToHand` and `RemoveAttachFromHandAndAttachToWeapon`. Adding the
  `EN_Silen_2` collection key does not change these donor bindings. The exported
  CFG uses attachment `EN_Silen_2` with mounted mesh override `EN_Silen_5`, as
  the base-game Integral does.
- `sync_attachment_notifies` remaps donor magazine and silencer/laser notify SIDs
  on mod-owned montages, even when animation references already need no changes.
  Only the notify's SID changes; failed readback/save restores the original.
  Ambiguous same-kind attachment targets warn instead of choosing arbitrarily.
  The mounted mesh override remains unchanged. Check the hand-to-weapon model
  transition in game after re-export/import/package.
- A read-only ZoneKit probe confirmed `AnimMontage.notifies` is protected and
  cannot be read with `get_editor_property`, while `binded_attach_sid` is
  writable on a transient `AnimNotify_AttachItem`. The importer therefore uses
  `AnimationLibrary.get_animation_notify_events` (the public AnimSequenceBase
  API) to retrieve events rather than reading the protected property.

### D6 test record

- Parser bugs fixed: an extra 4-byte skip mislabelled the tail of the summary (so `asset_registry_offset`, `bulk_data_offset`, `payload_toc_offset` were not shifted; UE reported `InvalidObjectCount`); also the thumbnail-table entry offsets and the asset-registry `DependencyDataOffset` (absolute) must shift. A guard now raises if the parsed summary does not end at `name_offset`, and `verify()` re-parses and checks all offsets and identical export data.
- Offline: 45 of the Hyena montages patched with 0 errors (46th tested in ZoneKit).
- Headless ZoneKit (UE 5.5.4), `probe_montage_patch.py` (since removed): file patched before first load, cold-loaded with `MainActionSlot`, length 0.4, section `Default`, 1 notify, first reference `/HyenaMod/.../AS_fp_hyenagun_empty_click`. Restore + `reload_packages` shows the `/Game` reference again; patch + reload shows the mod reference; a forced editor save keeps the patch. `ReloadPackagesInteractionMode` members: `ASSUME_NEGATIVE`, `ASSUME_POSITIVE`, `INTERACTIVE`.
- Not tested: the complete setup script run end to end inside the interactive ZoneKit, and in-game playback.
### Jellyfish diagnosis (2026-10-25)

Mod: `Mods/JellyfishMod`, UDP imported, unchanged, re-exported; `Gunjellyfishgun_HG` loads but does not fire or reload. Built before the montage patching.

- CFG compared with vanilla `GunUDP_HG`: same fire/ammo/reload data, mags and `WeaponStaticMeshParts`; nothing that blocks firing. Differences: silencer/laser entries dropped, and the weapon inherited the vanilla skeletal mesh prototype (D12).
- Asset audit (`python zonekit_tools/audit_mod.py <ModFolder> udp`): no dangling mod references, but `AnimBP_jellyfishgun_fp` referenced the template `AnimCollection_fp_udp`, template `SKEL_udp` and `AS_udp_fp_*`; `AnimCollection_fp_jellyfishgun` referenced 53 template `MG_fp_udp_*` montages; montages referenced template sequences. So the AnimBP ran entirely on vanilla data and the mod's animations were unused (D11).
- Applied D11 to a copy of the Jellyfish mod offline: 120 copied assets checked, 72 patched, 0 errors. Remaining template references are the intentional `SKEL_udp` and vanilla `MI_p_udp*` materials.
- Headless ZoneKit (`probe_reference_patch.py`, since removed) on the patched mod: AnimBP, AnimCollection, SK and a montage all load; the AnimBP now depends on 7 mod assets and the AnimCollection on 53 mod assets, with no template references except `SKEL_udp`. The patched files were left in `Mods/JellyfishMod`; the original is archived in the session `files/JellyfishMod_original` folder.
- Not proven: that this makes the weapon fire/reload. No gameplay runtime log was available. Retest needs the patched Jellyfish pak (or a rebuilt mod), a gameplay log if it still fails, and a note of whether compatible ammo was in the inventory.
- The user's first in-game retest still failed to fire or reload. The supplied `Stalker2-backup-2026.10.25-08.27.57.log` is a ZoneKit/Mod Editor packaging log, not a gameplay runtime log: it shows the Jellyfish config path being activated and packaging, and ends with editor world cleanup. The current on-disk `jellyfishgunWeaponPrototypes.cfg` still has no `MeshPrototypeSID`, and the cook reports `SKEL_jellyfishgun` as unused, confirming that this package did not include D12's generated CFG change. A fresh run from the updated add-on is therefore needed before judging D11/D12.
- That packaging log has 35 `LogAnimation` warnings where montage segment lengths differ from their referenced sequence lengths by one frame (for example 2.500000 vs 2.533333); it also reports 42 unused preloadable files. The duration warnings should be checked in the fresh build, but do not by themselves explain why firing and reloading are both unavailable. The unused preload warnings are cook-efficiency diagnostics, not proof of missing runtime assets.
- Also fixed: `uasset_patch` now accepts packages with no thumbnail table (`thumbnail_offset` 0, e.g. the generated localisation database).
### JaguarMod diagnosis (2026-10-25)

First full run with D11/D12. Weapon is added to the inventory but has no visible model and cannot fire or reload.

- CFGs are correct: the weapon uses `Gunjaguargun_Skeletal` -> `/JaguarMod/.../SK_jaguargun`, and the AnimBP and mags point at mod assets.
- Cause: `SK_jaguargun`'s root bone is `jnt_wpn_jaguargun`, but its skeleton `SKEL_udp` is `jnt_wpn_udp` (fixed by D14).
- The AnimBP still referenced the six template `AS_udp_fp_*` idle / break-bullet-idle sequences, although `uasset_patch` patches it cleanly offline (12 names). Most likely the patched file was overwritten by a later editor save of the unpatched in-memory AnimBP. Not proven, and harmless in game (those sequences use `SKEL_udp`).
- Offline repair on copies (session `files/JaguarMod_patched`): renaming the `jnt_wpn_jaguargun` FName to `jnt_wpn_udp` in `SK_jaguargun`, and the idle references in the AnimBP, both pass `verify()`. Not yet tested in game.
### LadybugMod diagnosis (2026-10-25)

- The supplied game log has no Ladybug, linker or animation error explaining the failure. The editor log `Stalker2-backup-2026.10.25-14.45.45.log` does show an Interchange bone-tree merge error at 13:57:25 during the skeletal-mesh import.
- Cold-loaded the blueprint and read its generated-class default: `weapon_anim_collection` points at Ladybug's collection, and its target skeleton is `SKEL_udp`. Equip sequence lengths and sampled poses match vanilla. This does not establish gameplay success, but it is not the earlier stale-collection-reference defect.
- Examined the actual mesh hierarchy with a transient skeletal-mesh component: Ladybug has 15 bones (`SK_ladybuggun` -> `jnt_wpn_udp` -> `jnt_offset`), while vanilla and Glock have 14 (`jnt_wpn_udp` -> `jnt_offset`). The outer FBX empty became an extra bone. D14's earlier diagnosis checked bone names, not the complete hierarchy.
- D15's Blender 5.2.2 regression (`zonekit_tools/test_skeleton_export.py -- <donor.fbx>`) checks the root, all bone parents and positions, armature world transform, absence of wrapper empties, and scene/name restoration with a clashing root object. Passed with Ladybug's UDP donor.
- Scratch ZoneKit import of the corrected FBX produces the 14-bone hierarchy with `jnt_wpn_udp` first. Switching to the legacy FBX importer alone does not remove the wrapper; the fix belongs in the exporter.
- Repaired Ladybug's exported skeletal FBX and reimported its actual `SK_ladybuggun` in ZoneKit, after backing up both originals in the session folder. Validated all 14 mesh bones, root parent `None`, and the unchanged `SKEL_udp` association before saving. The reimport has no bone-tree merge error. The old cooked containers are unchanged; recook is required.
- User subsequently confirmed Ladybug works in game: visible gun, CFG values, normal/extended magazines, firing and reloading.

### Ladybug reload fidelity (2026-10-25)

- Tested the saved `Ladybug Mod.blend` reload action (94 frames): left-arm `IK_FK=0`, edited index finger. Existing export reads the final arm blend but reads finger controls before their master/stretch constraints, and replaces local translation/scale with template values for rotation-only mappings.
- D16 fixes both. Measured the actual reimported FBX and scratch ZoneKit sequence, not only the control transforms. The Unreal wrist/index comparison covers 376 poses; max error is 0.000132 cm / 0.000415 degrees. The prior installed source sequence has 0.447 cm wrist displacement and 31.59 degrees of index-base orientation error.
- `zonekit_tools/test_animation_export.py` exercises the saved action in FK, IK and half-blended modes, including FBX reimport. All 94 frames pass: left-hand/finger positions within 0.001 cm, wrist/index rotations within 0.002 radians, all finger rotations within 0.01 radians. Nonuniform scale/shear leaves a 0.49-degree residual on the pinky tip; arbitrary shears are not exactly representable in FBX/Unreal TRS animation.
- The paired weapon FBX is also reimported and checked in each mode: root/wrist positions remain within 0.001 cm and rotations within 0.002 radians. The test temporarily mutes the action's keyed IK/FK curve so each mode is genuinely evaluated, and asserts that FK/IK wrist positions differ.
- Repaired and saved Ladybug's actual player/weapon `reload` sequences and their exported FBX files, with originals backed up in the session folder. Verified the actual imported player clip over all 376 wrist/index poses before saving; both existing reload montages already reference the repaired assets. No other action or the saved blend was overwritten. Recook and final in-game comparison are still required.
- No base-game skeleton is saved by the probes or repair. Declining checkout of `SK_stalker_Skeleton` is correct; sampled animation evaluation after a cold load of that skeleton does not require saving it.

### Ladybug deformation follow-up (D17)

- The user reported improved but still incorrect finger extension, wrist twist and sleeve movement. The D16 measurements above compare selected ORG joints, not the complete deformation, and were insufficient to establish viewport fidelity.
- Probed the actual mesh groups against the backed-up original mesh: conversion preserves group indices and weights, so their renamed groups independently identify the driving DEF bones. The old export leaves palm/arm-roll/forearm-roll bones on the donor animation. A sampled left-arm vertex differs by 9.845 cm.
- The saved rig also has eight `DEF-jnt_*_fore_arm_*` groups with no corresponding deform bones. Conversion now creates the missing wrist deform copies. Its five deforming spine B-bones have eight segments each; new rigs use one segment per game joint. **Repair Deformation Preview** upgrades old scenes without changing animation keys, and export explicitly rejects an unrepaired preview. The viewport's unsupported torso bending intentionally changes.
- Baking all deform matrices alone leaves a roughly 1.59 cm error from matrix shear. Solving parent/child TRS as Unreal's `FTransform` avoids that accumulation. Interchange still changes the imported clip; a scratch import with explicit `FbxFactory` and local-transform preservation matches all 7,144 weighted-bone poses over 94 frames within 0.000438 cm / 0.000207 degrees (scale error below 0.000082).
- The expanded Blender regression independently compares 4,510 **evaluated viewport vertices**, not just reconstructed joint positions, against the FBX tracks composed as Unreal TRS. All 94 frames pass in FK, half-blended and IK modes; max errors are 0.025049, 0.021371 and 0.019398 cm respectively. The worst vertex is the non-uniformly scaled pinky tip; arbitrary off-axis shear remains unrepresentable on the unchanged retail skeleton.
- Two normal-Python tests cover explicit per-task factories, local-transform preservation, multi-animation imports and skipped imports. Pylance MCP was unavailable; actual Blender execution and Python syntax compilation provide validation instead.
- Saved a separate `Ladybug Mod - deformation fixed.blend`, with repaired bindings and complete deformation metadata. The original blend is untouched. Existing generated import scripts must be regenerated; they embed a copy of the runtime, not an import of the updated source.
- Reimported the actual player/weapon reload pair through the production importer, delaying saves until verification. Both raw and compressed evaluation pass all 14,852 poses: max position 0.000438 cm, rotation 0.000207 degrees, scale 0.000082. Saved only the two mod-owned sequences and replaced their exported FBXs, with separate pre-D17 backups.
- Compared those actual Unreal poses against the repaired blend's evaluated mesh over all 94 frames / 4,510 vertices: index max 0.000374 cm, sleeve max 0.000684 cm, all-vertex max 0.025082 cm (scaled pinky tip). Raw and compressed results agree. These checks do not include runtime montage/procedural layers; recook and in-game retest remain required.

### Ladybug additive/reference and vanilla overrides (D18)

- The user reopened the original blend, ran Repair Deformation Preview, keyed the left-arm IK/FK switch per action, scaled the attached ladybug, then re-exported. The current original blend (saved 21:50) was inspected, not the earlier repaired copy.
- Actual imported reload thumb/index raw poses match this latest blend within 0.000226 cm / 0.000089 degrees. However idle and aim transitions retain `InterchangeAssetImportData` and their hand tips differ by 4.4–4.8 cm. The log confirms these clips still used Interchange; only the previously repaired reload used the legacy atomic reimport path. Several additive clips refer to the distorted mod idle. This invalidates the earlier assumption that a correct raw reload alone proves its final additive playback.
- Scratch reimport with the FBX flag disabled successfully converts an existing Interchange clip to `FbxAnimSequenceImportData` with local-transform preservation. The prior flag is restored. Directly replacing import-data objects was not safe in this editor and is not used in production. Scratch cleanup after the successful import also crashed this editor; no cleanup/delete operations are part of the production routing fix.
- The classifier's `OverridePackages.txt` lists `p_udp/SM_udp` and ten `SM_wpn_udp_SM_*` packages. CFG SIDs were unique, but static package paths were not. Retaining artist custom mesh names still works; only an unchanged template mesh name uses the custom weapon namespace instead. The importer explicitly rejects stale vanilla static overrides left in the mod.
- Backed up the latest 48 FBXs, all 48 mod animation packages and six mod CFGs. Archived the 23 old mod-owned `p_udp` static packages outside `Content`, regenerated the static assets under `p_ladybuggun`, and updated all six SDK mod CFGs. No base-game asset or skeleton was saved.
- Re-exported all 24 selected action pairs from the latest original blend, preserving the user's scaled mesh and keyed FK/IK edits. Reimported/saved 48 sequences through the updated production importer. Additive modes, reference types, sequences and frame indices remain unchanged; no blanket additive disable or camera damping was applied.
- Raw and compressed evaluation pass 14,020 camera/spine/wrist/thumb/index poses over every exported player-action frame, including transition midpoints: maximum position 0.000226 cm, rotation 0.000193 degrees. All 23 new static mesh packages have zero vanilla package collisions. The latest original blend is byte-identical before/after.
- Six focused normal-Python tests cover scoped flag restoration on success/failure, preserving an already-disabled flag, skipped imports, explicit factories and planned/stale vanilla mesh collision rejection. The latest-blend FK/blended/IK evaluated-mesh regression also passes (maximum residual 0.025042 cm at the scaled pinky).
- Regenerated the user's import script with the routing and collision guards. Cooked/staged containers were not rebuilt. The user must recook and replace the previous installed Ladybug package; final runtime camera/additive layering and thumb/index ordering still require that gameplay test.

### Ladybug fire recovery and aim transitions (D19/D20, 2026-10-26)

- Traced the actual runtime idle companions and additive bases. Untouched runtime idles and edited transitions can show matching wrists yet have incompatible local transforms: blending their old representations displaced the right wrist by 0.6635 cm halfway through a handoff. Synchronizing the additive idle removes that excursion.
- Unmapped, unweighted weapon-hand sockets were being sampled from static hidden raw-copy bones: left-socket error was 127.35 cm / 151.57 degrees. Preserve donor component trajectories and solve locals against the edited parents; explicit socket mappings still win.
- Between-key compensation needs dense evaluation, not just denser FBX interpolation. The direct TRS repro fell from 2.268869 cm at 30 Hz to 0.000185 cm at 120 Hz. Actual ZoneKit aim/reload imports report 120 Hz for both player and weapon clips.
- Re-exported 48 FBXs and regenerated the user's embedded importer. Saved exactly 57 mod-owned animation sequences: those 48 imports, two derived additive idles, and seven unchanged overlays with original references restored. Original additive modes, base-pose settings, idle durations and curves are preserved; no blanket additive disable, camera damping, base-game package or skeleton save.
- Direct evaluated source-rig versus RAW/COMPRESSED Unreal comparison at 60 Hz covers 44,480 poses. Aim/reload/idles: maximum 0.000222096 cm / 0.000165183 degrees. Other actions: 0.012806946 cm / 0.013851652 degrees, concentrated in right-hand melee action 02. The independent exported-FBX comparison covers 55,600 poses and passes; native-frame checks cover another 14,020 poses.
- Blender FK/half-blended/IK regressions retain evaluated hand/sleeve vertex coverage and now check native/subframe socket paths and restored scene subframes. Twelve normal-Python importer tests pass, including untouched/custom overlays, explicit additive exports, source sampling and quaternion-sign equivalence.
- Repeated additive reconstruction rounds some local translations by up to 0.000047088 cm. Position equality uses a measured 0.0001 cm tolerance; rotation/scale tolerances stay tighter. Tests reject changes above these bounds. Identical playback synchronization now makes no changes.
- A fresh, read-only ZoneKit process cold-loaded all 57 saved sequences: metadata and seven untouched-overlay raw tracks match, all 44,480 viewport comparisons pass again, and playback synchronization requests no writes. Both additive idles also pass 60-Hz RAW/COMPRESSED full-pose comparisons against their references (maximum 0.000173772 cm / 0.001066153 degrees). The commandlet exits 1 from the existing missing DDC Host / S2_DLC1 errors, not a verification failure. No scratch validation packages were persisted.
- The original blend remains byte-identical, including the smaller ladybug and keyed FK/IK switch. Its saved viewport rate is 25 FPS; importing the UDP donor temporarily uses 30 FPS, as before. These comparisons match action frames to the existing 30-FPS export timebase, not 25-FPS wall-clock playback. Use 30 FPS in the viewport for real-time comparisons; no retiming or blend overwrite was performed.
- Cooked containers are unchanged. Final montage/procedural layering still requires recooking, replacing the installed package and an in-game comparison.

### D21 record: mesh-space additive conversion (rejected, 2026-10-26)

- Tried converting `idle_add`, `idle_aim_add`, `idle_to_aim` and `aim_to_idle` to `AAT_ROTATION_OFFSET_MESH_SPACE` because the WeaponLayer AnimBP feeds idle/aim into an `ApplyMeshSpaceAdditive` node and a partial composition model "reproduced" a 3.24 cm lateral aim drift.
- In game the default view was tilted and both arms were mangled. A node name plus an isolated model of part of the graph does not establish the runtime contract; neither is a gameplay oracle.
- Rolled back: importer conversion removed (a regression test now asserts aim-transition modes and references are left alone), the four packages restored SHA256-identical from the pre-D21 backups (rejected copies archived outside the repo), the user's generated importer refreshed, `test_animation_playback.py` deleted. The 13 importer tests pass.
- Facts from that investigation that still hold: the WeaponLayer graph copies the virtual bones `VB jnt_camera`, `VB jnt_weapon` (and `VB jnt_item`), all parented to `jnt_spine_03`; crouch uses shared stance clips (`fp_ar_idle_crouch`, `fp_ar_idle_lowcrouch`, `AS_fp_ar_crouch_idle_long`) and a `jnt_spine_03` BlendBoneByChannel; the mod's raw `jnt_camera` / `jnt_weapon` tracks and the paired idle/aim endpoints match vanilla.

## Plan: final aim offset and crouch lean

### Leading hypothesis

The retarget reproduces every visible **world** pose, but not the donor's **local** transforms on the torso. Measured on Ladybug's idle/aim clips: `jnt_spine_01` local rotation differs by about 19°, `jnt_spine_02`/`jnt_spine_03` carry non-unit local scales (components of roughly 0.82–1.22), and the arm chain locals differ by 30–47°, all cancelling out in world space. Anything the game applies on top of our clips in local or parent space then lands differently:

- the stance (crouch) layer adds a rotation to the spine in that bone's local frame, so a 19°-different frame can turn a slight left lean into a right lean;
- the virtual camera/weapon bones hang off `jnt_spine_03`, so a scaled or re-oriented `spine_03` moves the aimed weapon and camera off-centre once aim offsets, sway or recoil are added.

Making the unedited torso match the donor **exactly in local space** removes the dependency on how the graph composes layers. Identical inputs give vanilla behaviour whatever the graph does. That is why this is preferred over modelling the graph again (D21).

### Steps

1. **Baseline (the user's blank-slate run).** Confirm both problems reproduce with the current code from a fresh import/export, so later results are compared against a clean mod.
2. **Measure, read-only.** Add a Blender test that compares each exported FBX's per-frame **local** TRS with the donor FBX for `root`, `jnt_hips`, `jnt_spine_01..03`, neck/head, clavicles, `jnt_camera`, `jnt_weapon` and non-deform helpers, on `idle`, `idle_aim`, `idle_to_aim`, `aim_to_idle`, shoot and equip. Report the largest rotation/translation/scale difference per bone. Confirm the same numbers in ZoneKit by cold-loading the imported sequences (RAW pose evaluation, read-only). If the torso chain already matches, stop and return to the hypothesis before changing code. Also compare the mod's `SK_<weapon>` sockets with `SK_udp`'s (see the sight-alignment survey). If the aimed camera is placed from `CameraSocket`, an off-centre aim can only come from the weapon's orientation or a differing socket, not from `jnt_camera`'s translation.
3. **Fix in the exporter** (`export_animation.py`, `solve_armature` / `export_action`):
   - For each frame, a torso/helper bone whose evaluated world matrix matches the donor's within tolerance is written with the **donor's local TRS** for that frame instead of a re-solved one.
   - A torso bone the artist did edit is written as the donor local times an edit delta in the donor's parent frame, keeping the donor's scale, so procedural layers still rotate about vanilla axes.
   - Arm, hand and finger bones are then solved against these parents as now, so the viewport's visible arms, sleeves and weapon are unchanged.
   - If step 2 shows the difference comes from the spine mapping itself (bone roll or B-bone segments in the Rigify conversion), fix the mapping instead and keep this as a guard.
4. **Verify before any game test.**
   - The new local-TRS test passes for unedited bones (0.001 cm / 0.001° / 1e-5 scale).
   - The existing FK/IK/half-blended viewport, evaluated-vertex and socket tests still pass.
   - The ZoneKit cold-load comparison shows torso locals equal to the donor, and the regenerated `idle_add` / `idle_aim_add` keep their original modes.
5. **Gameplay test (the only real oracle).** Recook, replace the installed pak, then check:
   - hip-fire crouch and low-crouch lean direction against vanilla UDP;
   - aimed centring after aim-in;
   - regressions in fire recovery, reload fingers, aim transitions, equip, and vanilla UDP/Gambit.

### Outcome so far (2026-10-27)

- Steps 1–4 are done. Bird reproduced both bugs from a blank slate. The measurement confirmed the hypothesis for the lower spine: only `jnt_spine_01`/`02` frames differed. `jnt_spine_03`, the camera, the weapon and the hands already matched, so the step 3 rule was narrowed to D22. The upper-arm twist (26–60° off the donor, with positions and hands exact) is left alone; nothing links it to aim or crouch.
- `test_animation_export.py` passes on Bird's reload in FK, blended and IK modes and now also checks `jnt_spine_03`. It skips vertices weighted to the D22 bones, which deliberately follow the donor.
- Step 5 done: Bird's game test confirmed aim and crouch. It exposed sprint → aim drift and a jerky first aim after reload; the upper-arm twist was the measured cause candidate and is fixed by D24 (needs game test).

### Do not
- Add position offsets, rotation sign flips or camera damping to compensate.
- Save base-game assets or the shared `SK_stalker_Skeleton`. Declining its checkout prompt after packaging is correct.


## Plan: authoring weapon sockets in Blender without opening SKEL (2026-11-10)

**Status: Blender authoring, socket transport and a mesh-only writer are implemented;
native persistence and mesh reimport pass; gameplay acceptance remains outstanding.** The user's ZoneKit skeleton editor crashes,
blocking socket placement. The proposed workaround is to author socket markers in Blender
and apply their transforms as **mesh-only sockets on the mod-owned skeletal mesh**, without
opening or saving the shared skeleton.

This section is the implementation plan for the socket transport/writer required by the
older **Plan: sight alignment for custom weapon models** below. Retain its measurements as
evidence, but do not depend on its proposed manual **Create Mesh Socket** step: the workaround
must work without opening either asset editor. Automatic sight-line calibration is a later,
separate feature; first deliver reliable manual socket placement.

### Implementation record (2026-11-10)

- Versioned setup catalogue enumerates `num_sockets()` / `get_socket_by_index()`,
  including inherited and shadowed records, source ownership and reference-bone frames.
  An AnimPose evaluated with an explicit source mesh supplies **reference** bone frames
  (not the sequence's animated pose). A bare unregistered component returned uninitialized
  transforms in the native probe; no skeleton-editing API or committed bone edits are involved.
- Named Empty arrows, fixed donor identity/bone, persistent local frame, selection,
  visibility, per-socket enable/reset, confirmed reset-all and edit-preserving refresh.
  Markers transfer with the weapon controls into Rigify; template changes do not reset them.
  The catalogue identifies the FBX component root: its markers preview on the Weapon
  control while preserving the original game parent in the manifest.
- Import manifests carry explicit enabled/reset entries. The generated writer validates
  the whole payload, refuses unmanaged/external changes, copies inherited sockets
  independently into the exact mod-owned destination mesh, verifies before saving and
  preserves all unrelated sockets. It never saves a skeleton or changes bone/animation references.
  Fresh/reimported meshes without sockets receive independent donor copies, including
  baseline sockets, after validating destination bones and unchanged donor placement.
- Installed bindings: socket arrays are protected for both reads and writes; no removal
  method is exposed. `Object.rename` accepts `name` and `outer`, not `new_name` /
  `new_outer`. A distinct socket from a duplicated skeleton can be re-owned by a mesh;
  mesh lookup then resolves it. Source socket values remained unchanged in the probe.
- **Intentional deviation from the proposed removal contract:** reset restores the donor
  transform but retains an Arsenal-created baseline mesh override and its management
  record, with an explicit importer warning. Do not describe this as live inheritance
  or physical deletion. Failed additions likewise report the rollback limitation.
- Both generated scripts accept `--sockets-only`: setup refreshes only the source JSON,
  while import updates sockets without reimporting assets or copying CFG.
- Asset-free Python and Blender regression tests cover schema, ownership, no-op/repeat,
  reset, rollback, quaternion tolerances, full bone/object transforms, moving-child
  animation, Rigify transfer and blend save/reload. Native checks use only the external
  disposable `ArsenalSocketProbe` mod. No user's mod is a write target.
- Verification: 111 focused plain-Python tests, 14 Blender marker tests (including the
  real UDP FBX/reference catalogue), and 7 registration/reload tests pass. Production
  reference frames agree with the donor FBX within 0.001 cm.
- Native disposable-mod checks pass add/update/repeat/reset/save and a fresh-process
  reload with the shared donor unchanged. A production-exported FBX also passes fresh
  import with a new mod-owned skeleton, all 14 donor sockets, mesh reimport/reapplication
  and a second fresh-process reload.
  ZoneKit still exits 1 for the installation's existing Cloud DDC Host / S2_DLC1 errors;
  the Python commandlet reports successful execution and writes explicit proof reports.
- Cook and first-/third-person runtime consumers remain acceptance gates. A persisted
  mesh override or correct Blender preview is not proof of every game's socket consumer.

### Existing Rigify scene placement correction (2026-11-10)

- E9's saved late socket import reproduced a missing donor-to-rig rest-space
  transform: `SilencerMuzzleSocket` was at Z=6.05 cm while the barrel bone was at
  Z=153.00 cm. Tests on an origin-centred donor did not cover this path.
- Socket conversion now retains the reference-space embedding during Rigify merge.
  Older rigs recover it from the weapon backup and the preserved child-bone rest
  frames, not the current animation pose or the differently oriented Weapon control.
- Refresh migrates old marker frames while preserving their authored game-relative
  transforms and enabled states. Stale frames block export until refreshed.
- Read-only validation against E9 places `SilencerMuzzleSocket` at
  (56.342, -10.835, 154.132) cm, beside the barrel, and `SilencerMuzzle` at
  (77.638, -10.618, 154.097) cm, ahead at the suppressed muzzle-effect point.
  All 14 game-relative socket transforms remain unchanged. The user's blend is not saved.
- 16 Blender socket tests, 7 registration tests and 111 focused Python tests pass.
  New coverage compares early and late socket import on a raised/rotated/scaled
  generated rig, old-frame migration, edit preservation and armature-object movement.

### Outcome and boundaries

- The artist can see, select, translate and rotate existing donor socket markers against
  their weapon in Blender, save the blend, and use the normal Export All/import/package flow.
- The generated ZoneKit importer applies the changes without opening SKEL, the skeletal-mesh
  editor or an animation preview. No recurring manual ZoneKit edits are required.
- Preserve donor bone names, reference-pose hierarchy, animation tracks, montage/collection
  references and additive playback settings. Socket edits are not bone edits.
- Never save, rename, reparent or otherwise mutate a shared `/Game` socket, skeleton or mesh,
  even temporarily. Only verified mod-owned destination assets may be written.
- Initial scope: transforms of **existing named sockets on their original bones**. Include
  mount, muzzle/ejection, camera/eye-point and other donor sockets, not just silencer/laser.
  Their runtime consumers must still be verified individually.
- New socket names, parent-bone changes, static world-mesh sockets and automatic sight/rail
  alignment are distinct follow-up capabilities unless explicitly approved for the first release.
- Do not substitute animation-camera offsets, attachment vertex shifts or speculative CFG
  fields for a failed socket update.

### Evidence, limitations and references

- Epic documents mesh-specific sockets on a SkeletalMesh, separate from its shared Skeleton:
  [Skeletal Mesh Sockets](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine).
- Epic's [SkeletalMesh Python API](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/SkeletalMesh?application_version=5.1)
  documents `add_socket(socket, add_to_skeleton=False)`, `num_sockets()` and
  `get_socket_by_index()`. These are reference signatures, not proof of this ZoneKit build's
  save/cook behavior; feature-test the installed bindings.
- [SkeletalMeshSocket](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/SkeletalMeshSocket?application_version=5.1)
  documents editor-writable relative location/rotation/scale, but read-only socket/bone names.
  Earlier local investigation found these names reject `set_editor_property` and
  `unreal.duplicate_object` is unavailable. Correctly cloning a donor socket is the first blocker.
- The supplied ZoneKit wiki's `guides/assets/animations-and-attachments.md` reports mesh socket
  overrides and a socket re-outering technique. Treat that as a lead to test, **not permission
  to move a socket object out of a shared skeleton**. Use only a proven independent copy.
  Its `guides/zone-kit/python-scripting.md` documents headless scripting and binding limitations.
- Epic's [FBX static-mesh pipeline](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine)
  documents `SOCKET_` helper naming. Do not assume this automatically imports skeletal sockets
  from Blender. Prefer explicit socket metadata plus the generated Python importer.
- No verified public fix for the particular SKEL editor crash was established. Bypassing the
  asset editor may avoid an editor-preview crash, but loading, saving or cooking the same
  asset could still fail. The proof-of-concept must distinguish these cases.

### Existing integration points

- [unreal_setup.py](stalker2_arsenal/unreal_setup.py), `export_sockets`: currently exports a flat
  `weapon_sockets.json` with name, bone, location, rotation and scale, using owner properties
  and two named lookups. The earlier socket survey found this misses skeleton sockets.
  Replace enumeration with verified effective-socket enumeration and retain ownership/source data.
- [import_weapon.py](stalker2_arsenal/import_weapon.py), `_socket_offset` and `_import_attachments`:
  currently use a Y-reflected translation plus the bone head, ignoring full socket/bone
  rotation. This approximation is not a suitable foundation for editable socket round-trips.
- [export_static_mesh.py](stalker2_arsenal/export_static_mesh.py) and
  [export_animation.py](stalker2_arsenal/export_animation.py): reuse the existing mapped game
  joints, backup/rest skeleton and source-unit conversions. Do not build a second incompatible
  mapping system or change established mesh/animation export conventions.
- [export_unreal.py](stalker2_arsenal/export_unreal.py): extend the versioned import manifest
  with validated socket overrides; keep editable state in the blend.
- [unreal_import.py](stalker2_arsenal/unreal_import.py): apply sockets after destination mesh
  creation/reimport, including on runs that skip mesh reimport. Validate that no later import
  step replaces the mesh or removes its socket overrides.
- Generated setup/import scripts embed their source modules. Regenerate them after changes;
  updating the installed add-on alone does not update old generated scripts.

### Phase 0: evidence pack and disposable fixtures

Keep all extracted assets, example blends, generated scripts/reports and test-mod output outside
the checkout. No user's real mod is a test target.

**Extract from ZoneKit, read-only:**

1. The actual donor weapon skeletal mesh and its associated skeleton path, plus an inventory
   of every effective socket: name, parent bone, relative location/rotation/scale, object path,
   actual owner/outer and whether it is mesh-owned or skeleton-owned. Preserve both records
   if a name exists on both owners and record which lookup resolves.
2. The donor reference-pose bone hierarchy and complete bone transforms needed to reproduce
   socket placement, including the weapon root and a moving child such as the shutter.
3. Representative socket records: `SilencerMuzzleSocket`, `LaserSocket` where present,
   `CameraSocket`, `AimSocket`, one optic eye socket named after its attachment SID, and one
   socket on a non-root/moving bone. Use actual donor names; do not require a missing laser/optic.
4. The compatible stock attachment meshes needed for visual checks, their original pivots,
   and the CFG fields identifying attachment mesh/socket and any effect socket names.
5. A known-good idle, aim and silencer-attach sequence sufficient to check that markers follow
   bones, and the mod-owned SK path actually referenced by the exported weapon CFG.
6. ZoneKit build/version, the precise crash trigger (opening SKEL, selecting a socket, saving,
   etc.), and the relevant crash/log excerpt if available. Avoid collecting unrelated logs.

**Create in Blender, using synthetic geometry where possible:**

- An unedited donor round-trip scene, plus a disposable custom-weapon scene with imported
  rest rig and recognizable muzzle/sight reference geometry.
- A marker on the root bone and another on a translated/rotated child. Test zero offset,
  a +1 cm move on each source axis, and a known 15-degree rotation on each source axis.
- A raised-sight example (+1 cm), a moved silencer mount, a rotated laser/muzzle direction,
  and an animated shutter example. These can share one test blend.
- A scene with translated/rotated armature-object transforms and a uniformly scaled scene;
  include unsupported nonuniform/mirrored/sheared cases for explicit validation errors.
- Do not add exported bones named after sockets. Markers must remain non-bone authoring objects.

**Prepare a disposable ZoneKit test mod:**

- Own a weapon mesh copy, with paths clearly distinct from base-game and real-mod assets.
  Create the mod through the normal Mod Editor workflow if needed; do not assume a mod-creation
  Python API exists.
- Record baseline socket values, asset references and on-disk hashes of the donor packages.
  Record whether source packages are dirty before the test so pre-existing dirty state is not
  misattributed to the probe.
- A tiny package/game test must identify the scratch weapon independently of the real weapon.
  Do not overwrite or unsubscribe the user's working mod as an unannounced test step.

### Phase 1: prove the ZoneKit writer before building UI

1. Run a read-only capability probe: enumerate sockets and available copy/add/remove/rename
   APIs, read transforms and owners, and identify the destination mesh's bone names.
   Never assume ordinary Unreal Python helpers are present in ZoneKit.
2. Establish a safe independent socket-copy method. Prefer a supported duplication mechanism
   if exposed. If unavailable, test copying through a **disposable skeleton/mesh duplicate**
   and moving only that duplicate's socket into the destination mesh. Confirm the socket
   object is distinct and the base asset's arrays/ownership remain unchanged.
3. If independent copying is not available, stop this approach and document the failing
   bindings. Evaluate a mod-owned skeleton alternative only with explicit approval and an
   animation-reference/cook compatibility test; do not silently replace the donor skeleton.
   Do not resort to hand-patching serialized asset bytes as the default solution.
4. Add a mesh-only copy of one existing socket, preserving its name/bone and using
   `add_to_skeleton=False`. Change location by a known 1 cm, then rotation independently.
   Check mesh lookup resolves the new socket rather than the inherited one.
5. Save **only** the scratch mod-owned mesh and reload it in a fresh process. Verify name,
   bone, transform and ownership after reload, and confirm the donor skeleton is unchanged.
6. Re-run the same operation: exactly one mesh override remains; no `.001` names or duplicate
   effective sockets. Restore the original transform and explicitly remove the test override,
   confirming inherited socket lookup returns the donor again.
7. Reimport the scratch mesh and repeat socket application. Prove the final persisted result
   survives the actual importer order, not just a one-off console edit.
8. Cook/package and verify one attachment and one camera/effect socket in game. Mesh lookup
   success in Python alone does not prove that every game subsystem honors mesh overrides.
   Do not change animations to mask a failed runtime socket consumer.

**Gate:** do not implement the full authoring UI until independent copy, save/reload,
idempotence, source isolation and at least one runtime mesh-override path are established.
Use the console without opening asset editors, or a headless commandlet if asset loading permits.
Close an editor holding the same test assets before a saving commandlet; never run two writers.

### Phase 2: socket data contract and full transform conversion

- Version the setup socket catalogue and import-manifest section. Identify source mesh/skeleton,
  stable socket name, source parent game bone, source ownership, baseline transform and override
  transform. Qualify identities by source mesh; a global name-only deduplication can mix weapons.
- Define units as Unreal centimeters and transforms as **socket relative to parent game bone**.
  Store location, an unambiguous rotation representation and scale, documenting component order.
  Prefer quaternion/matrix math internally; convert to Unreal Rotator with named arguments at
  the boundary. Do not treat Blender XYZ Euler angles as Unreal roll/pitch/yaw.
- Derive the basis conversion from existing import/export behavior and the donor rest transforms.
  Conceptually, convert the marker's world transform to the exported parent bone's frame using
  `inverse(parent_bone_world) @ marker_world`, then apply the verified Blender/Unreal basis/unit
  conversion. Validate multiplication order and handedness with fixtures, not a guessed Y flip.
- Blender bone parenting includes parent inverses and bone-tail conventions. Use evaluated full
  matrices, not `head_local + offset`, and anchor to the exported game joint frame rather than
  a Rigify control's display axes or tail.
- Define the reference frame independently of the current animation frame. A posed rig must
  not bake an animation pose into the stored rest-relative socket transform. Marker previews
  follow animation while the authored local offset remains unchanged.
- Preserve all untouched effective donor sockets and the existing hierarchy. Export only explicit
  overrides; a baseline-only blend produces no socket mutations.
- Reject unknown/ambiguous bones, duplicate names, nonfinite values, singular transforms and
  unsupported shear/mirroring/nonuniform scale. Do not silently normalize or use identity fallbacks.
  Preserve donor scale; initially restrict scale editing unless its runtime behavior is verified.
- Legacy flat socket JSON remains readable. Missing socket data in an older blend/export means
  unchanged behavior, not removal of every mesh socket.

### Phase 3: Blender authoring and persistence

- Add a dedicated socket-marker collection and a **Weapon Sockets** section in Create Your
  Custom Weapon. Store marker identity, parent game bone, source/baseline and edit state in
  registered properties saved with the blend, not in object-name parsing alone.
- Import existing sockets as named Empty arrows/axes. Clearly distinguish mount points,
  camera/eye points and effects; show both socket name and parent bone.
- Provide selection/focus, visibility, reset selected to donor and reset all with confirmation.
  Preserve unchanged baseline markers; do not put custom weapon/attachment meshes in this collection.
- Re-import/refresh must reconcile by stable identity without duplicating markers or discarding
  edits. If the donor/bone mapping changes, flag affected overrides for explicit review.
- Initial UI edits transform only; socket renaming and reparenting are disabled. New sockets
  should not be implied by duplicating or renaming an Empty.
- Disabling an override/resetting to inherited behavior is explicit. Deleting a marker must
  either request override removal or report a missing required marker; never leave stale writes.
- Keep marker transforms separate from preview attachment geometry. Audit the existing simplified
  attachment-placement path so adding markers cannot double-translate the silencer or change
  established mesh pivots. Any corrected preview placement needs targeted compatibility tests.

### Phase 4: generated importer, safe updates and removal

- Validate the entire socket payload and destination ownership before the first mutation.
  The destination must be the mod-owned mesh used by the weapon CFG, not a similarly named donor.
- Capture old mesh socket state for affected names. Create/update only Arsenal-managed overrides,
  preserving unrelated mesh sockets and any user-authored entries; conflicts require an explicit
  diagnostic rather than overwriting silently.
- Include managed-name metadata and explicit removal requests so resetting a previously exported
  socket actually removes its old override on the next import. An absent legacy payload is not
  a removal request. Never remove an inherited skeleton socket.
- Apply after mesh import and before the final save; support existing-mesh/socket-only imports.
  If later reimport recreates the mesh, reapply from the same authoritative payload.
- Verify expected effective name, parent, owner and transform before saving; save only on change.
  Report socket counts, before/after transforms, removed overrides, destination path and failures.
- Fail the socket step explicitly on unsupported APIs/readback/save failure; never report success
  after skipping a requested socket. Restore captured destination state where safely possible.
  Do not use blanket Save All or allow a source-skeleton checkout prompt as normal behavior.
- Keep `unreal_import.py` self-contained when embedded. Older manifests lacking socket settings
  continue to work. Regenerated scripts carry the new implementation.

### Validation and acceptance

**Automated, plain Python:** schema/version handling; duplicate and unknown-bone errors;
mod-path guards; supported/missing binding mocks; complete validation before mutation; no-op,
add, update and managed removal; unrelated socket preservation; save failure/rollback reporting;
repeat import without duplication; missing legacy payload produces no writes.

**Automated, Blender 5.2.2+:** marker import/display and full transform round-trip; no-op donor
export; axis/rotation fixtures on root and moving child; arbitrary supported object transforms;
frame-independent local offsets under animation; no marker bones in FBX; blend save/reload;
reset/removal manifest; refresh preserves edits; unchanged mesh pivots and existing attachments.

**Real ZoneKit:** retain a probe report for API capabilities, distinct object ownership,
pre/post/reloaded socket values, unchanged source packages and final runtime mesh path. Run
repeat import, mesh reimport, socket-only update, reset and cook on disposable content.

**Game:** silencer and laser alignment where available, attach animation versus final mounted
position, muzzle flash and shell ejection, iron sights, scope mount versus scope eye point,
aim/hip-fire transitions and moving-part behavior. Test world/dropped/NPC views separately:
their static or third-person meshes may not consume the first-person mesh's sockets.
Confirm the vanilla donor weapon and another weapon using its skeleton remain unchanged.

**Proposed numeric thresholds:** no-op/round-trip translation error <= 0.001 cm and angular error
<= 0.01 degrees; repeat save/reload within the same thresholds and scale within 0.00001.
Compare orientations through matrices/quaternions, not raw Euler equality. Record any engine
quantization that requires an evidence-based tolerance adjustment.

**Done means:** a saved blend can drive repeated export/import/package cycles, the requested
socket is correct in game without opening SKEL, disabling an override restores donor behavior,
and shared assets, bone hierarchy and unrelated animation behavior remain unchanged.

### Questions for the user before implementation

These are pending decisions, not assumed permissions:

1. Which sockets block the current weapon: silencer/laser mounts, muzzle/ejection, iron-sight
   camera, optic mounts/eye points, or others? Supply exact names if known; otherwise provide
   a screenshot of the misalignment and the donor weapon/template name.

   All related sockets need manual re-alignment.

2. Does the crash occur on opening SKEL, opening the skeletal mesh, selecting a socket, changing
   its transform or saving? Can the ordinary Mod Editor and Python console load the mod normally?
   Provide the ZoneKit build and focused crash excerpt if available.

   A: The crash is specific to my PC and does not happen for other users. It happens on opening SKEL or a Skeletal mesh file.

3. May the test use a new disposable mod and an external copy of the weapon project? Identify
   the working blend/export folder and mod-owned SK to copy, or approve synthetic fixtures first.
   No permission to modify the real working mod is implied.

   A: I have backups of all files, the current E9Mod is fine for testing.

4. Is editing transforms of existing sockets sufficient for the first release, or are brand-new
   names/parent-bone changes required? If new names are needed, list the intended game consumers.

   A: The names should be kept, only placement needs to be user editable.

5. Confirm the proposed Blender UI: named Empty arrows, a socket list with parent bone,
   per-socket override/reset, plus optional attachment previews. Should camera/aim sockets be
   editable immediately or protected behind an advanced toggle?

   A: Named empties are fine, and everything should be editable immediately.

6. Is first-person behavior sufficient initially, or must dropped/world and NPC views also be
   delivered at the same time? Identify any separate world/third-person mesh assets in use.

   A: First person and third person behaviour should be correct.

7. Should template changes preserve authored socket edits for review or reset them after
   confirmation? Distribution defaults currently reset on template changes; socket edits may
   refer to entirely different donor bones, so this needs an explicit policy.

   A: As they will be based on the initial imported model, changing the template should not affect them after that section is complete.

8. If mesh sockets are ignored by a required runtime consumer, is a separately owned skeleton
   acceptable as a researched fallback, or must this remain a strict no-skeleton-change feature?

   A: I'm happy with any solution that works and results in a correct in game function.

9. Can the user run the disposable cooked test and supply screenshots for attachment, ADS and
   vanilla-donor checks? In-editor preview alone cannot close the runtime acceptance gate.

   A: Yes

**Suggested first deliverable after answers:** a read-only socket/capability report, followed
by one disposable mesh-only `SilencerMuzzleSocket` or `CameraSocket` save/reload/runtime experiment.
Only then implement the full Blender authoring/export workflow.

## Plan: sight alignment for custom weapon models

A new model whose sights are higher or lower (or further left/right) than the template's will aim through the wrong point, because the camera's aimed position is set by the weapon skeleton's sockets, and those are the template's.

### How the game lines up the sights (checked, 2026-10-26)

Probe: `num_sockets()` / `get_socket_by_index()` on all 63 vanilla weapon meshes (read-only). The earlier claim that `SK_udp` has only two sockets was wrong: `export_sockets` reads the mesh's `sockets` property plus two lookups by name, and skeleton sockets are not exposed that way.

- **`CameraSocket` sets the iron-sight eye point.** 42 of the 63 weapons have one, always on the weapon root bone `jnt_wpn_<x>`. On `SKEL_udp` it is at (-9.000, 1.603, 9.300) with zero rotation. `CameraSocket` is not named in any CFG, so the game looks it up by that name.
- **Each optic has its own eye-point socket, named after the attachment SID.**
  - Same root bone, at almost the same Y (about 1.60 cm), for example `UDP_Deadeye_Colim` (-9.000, 1.603, 10.400). This is the UDP's scope eye point, 1.1 cm above the iron-sight one. It is the SID of the Deadeye's collimator in `AttachPrototypes.cfg`.
  - Other weapons use template SIDs (`EN_X4Scope_1`, `RU_ColimScope_1`, `EN_GoloScope_1`…) or unique ones (`SVDM_Scope`, `GunG37V2_Scope`).
- **Mount sockets are a separate group.** `ColimScopeSocket`, `X4ScopeSocket`, `TopRailSocket` and others position the optic mesh on the gun, usually on another bone (UDP: `jnt_shutter`). The CFG `Socket = IronSightFront/IronSightRear` entries are folding-sight meshes, not eye points.
- **Other aim sockets:**
  - `AimSocket` is set globally in `CoreVariables.cfg` (`AimSocketName = AimSocket`). On the UDP it sits at the muzzle top (13.546, 0, 6.905 on `jnt_offset`), likely the aim direction or trace point.
  - `OffsetAimingSocket` (`OffsetAimingDefaultSocketName`) is the eye point for offset aiming, only on some weapons.
- **The manual vanilla workflow confirms this.**
  1. In `Actor_Packaging_Test_Map_WP`, play with a gun in each hand.
  2. Move the camera offset and save, then switch guns; the camera updates.
  3. Repeat until the view is right, then note the new socket position.
  4. Apply the same delta to the scope sockets.
- **The constraint:** these sockets live on the **skeleton**, and the mod uses the base-game `SKEL_udp` (D11). Editing them, including saving from that play-test workflow, would change vanilla UDP and Gambit (the D18 class of bug).
- **The fix:** add *mesh-only* sockets with the same names on the mod's own `SK_<weapon>`. UE's `USkeletalMesh::FindSocket` checks mesh sockets before skeleton sockets, so a mesh-only `CameraSocket` overrides the skeleton's for this weapon only. Step 1 verifies that the game honours this.

### Design

1. **Export every socket from ZoneKit.**
   - Fix `export_sockets` (`unreal_setup.py`) to enumerate with `num_sockets()` / `get_socket_by_index()`.
   - Record name, bone, location, rotation, scale and owner (skeleton or mesh) into `weapon_sockets.json`.
   - Group the sockets:
     - **eye points:** `CameraSocket`, `OffsetAimingSocket`, and every socket on the root bone whose name is an attachment SID in `AttachPrototypes.cfg`;
     - **mounts:** `*ScopeSocket`, `*RailSocket`, `GripSocket`;
     - **effects:** `Muzzle*`, `ShellShutter*`, `Aim*`, `MagEject*`;
     - **attachments:** `SilencerMuzzleSocket`, `LaserSocket`…
2. **Show them in Blender (panel 4 "Sight Alignment").**
   - Import the eye points as empties parented to the weapon root bone, drawn as small eye/arrow gizmos, with `CameraSocket` highlighted.
   - **Add Sight Markers** places `Rear Sight` and `Front Sight` on the template's sight line, which runs through `CameraSocket` along the root bone's +X. The artist snaps them onto the new model's rear-notch centre and front-post tip.
3. **Compute the iron-sight delta.**
   - Intersect the new sight line (rear → front) with the plane of `CameraSocket`'s X. The delta is that point minus `CameraSocket`, in Y and Z only, so eye relief is unchanged.
   - If the sight line pitches or yaws more than about 0.25° from +X, warn. Vanilla eye-point rotations are all zero, so a tilted sight line means a modelling problem, not a socket rotation.
   - Show the delta in cm; the artist can also type it directly.
4. **Scope eye points.**
   - Default, as in the manual workflow: apply the same delta to every scope eye-point socket.
   - Option: a separate rail delta, measured from a `Rail Top` marker against the template's mount socket, for models whose rail sits differently from their iron sights. It then moves both the mount sockets and the scope eye points.
5. **Write the override sockets in ZoneKit.**
   - The import script adds mesh-only sockets on the mod's `SK_<weapon>` (never `bAddToSkeleton`) with the template socket's name, bone and rotation and the corrected location.
   - It only adds sockets whose delta is non-zero, is idempotent (it replaces its own previous sockets), and logs before/after values.
   - `SK_<weapon>` is mod-owned and already saved by the import (the save prompt is expected). Declining the `SK_stalker_Skeleton` checkout stays correct.
6. **Optional fine-tune with the vanilla play-test workflow.**
   - Use it only to *measure*: read off the socket position, **do not save `SKEL_udp`**, and type the delta into step 3's field.
   - The add-on writes it as a mesh socket. Fine-tuning then becomes one number, not a round trip through Blender.
7. **Animations are not touched.** The aim clips stay as the template's. The previous idea of offsetting `jnt_camera` in the aim clips is dropped: with an eye-point socket the camera correction would be applied twice. It is kept only as a fallback if step 1 shows the game ignores mesh sockets.

### E9Mod measurement (2026-10-29)

- The current `idle_aim` FBX weapon attachment matches the authored Blender pose (0 cm / 0 degrees in the first-frame check). The static part pivot calculation matches the evaluated rigid weapon vertices within 0.00004 cm. These checks do not evaluate the complete runtime graph.
- The saved player aim/additive poses and weapon aim pose were read in ZoneKit. `SK_e9gen7` still inherits UDP's `CameraSocket` on `jnt_wpn_udp`: (-9.000, 1.603, 9.300).
- Blender's bone-parented preview camera is at the Camera bone's **tail**, 1 cm sideways from the exported camera bone's origin. In Unreal coordinates, the authored preview eye is (0, -1, 160.338013), while composing the aimed weapon attachment with the inherited socket gives (0.589, 0, 160.089993).
- Controlled test, not yet verified in game: make `CameraSocket` mesh-only on the mod-owned mesh and set its relative location to (-9.000, 0.603, 9.548013). This preserves the existing X/eye relief and rotation, and matches the preview's Y/Z eye line. Do not edit the animation or the shared skeleton. Package and test settled aim before implementing automatic calibration or generalizing the socket writer.
- The 1 cm preview-camera offset is a confirmed discrepancy, but it does not by itself establish the cause of the reported vertical misalignment. Both runtime use of the mesh override and the final visual alignment still require an in-game test.

### Steps

1. **Read-only checks in ZoneKit.** Done: socket survey. Still to do:
   - **Mesh sockets via Python:** `add_socket` is exposed in this ZoneKit build, but creating a correctly named/parented socket is not yet verified: `socket_name` and `bone_name` reject `set_editor_property`, and `unreal.duplicate_object` is unavailable. Use the editor's **Create Mesh Socket** command for the first runtime test rather than changing the shared skeleton or relying on unverified Python calls.
   - **Mesh-socket override:** confirm `find_socket('CameraSocket')` on that scratch mesh returns the mesh socket.
   - **Play-test tool:** find which tool the workflow uses to move the camera offset, and which asset it saves (expected: the weapon's skeleton).
2. **Socket export fix plus Blender display.**
   - **Test:** the regenerated UDP `weapon_sockets.json` lists all 14 sockets, with `CameraSocket` at (-9.000, 1.603, 9.300).
   - **Test:** importing places the eye-point empties at those positions in the template blend.
3. **Delta maths.** Test with synthetic markers: a sight line raised 1 cm gives a delta of (0, 0, +1.000) ±0.001 cm, and markers left untouched give exactly zero.
4. **ZoneKit writer.** Test on a scratch mesh, then on a disposable mod:
   - the mesh has a mesh-only `CameraSocket` with the new location;
   - `SKEL_udp`'s sockets are unchanged and the asset is not dirty.
5. **Game test, after "Plan: final aim offset and crouch lean" is fixed,** since both affect the aimed view.
   - **Raised sight:** build a model with the sight raised 1 cm. Check that the iron sights line up, aimed shots land on the sights, and hip-fire and transitions are unchanged.
   - **Scope:** attach the Deadeye collimator to check the scope eye point.
   - **Vanilla:** check that vanilla UDP and Gambit still aim exactly as before.

### Do not

- Edit or save `SKEL_udp`, `SK_stalker_Skeleton` or any other `/Game` skeleton or mesh, including from the play-test workflow.
- Use `bAddToSkeleton` when adding sockets.
- Invent CFG fields for sight height; vanilla has none.
- Offset `jnt_camera` in the aim clips on top of a socket override.

## Plan: importing the clips the add-on skips (2026-10-27)

**Status (2026-10-27): implemented as D25/D26 and gameplay-confirmed with Bird.** The user chose: fire and equip yes, `idle_boltlock` / `break_bullet_idle` yes, shared clips such as sprint no, and generally every clip that can reasonably be customised. Step 4 below was dropped (see D25). Verification:

- Additive FBX exports are full poses (step 1). Setup selection: `test_unreal_setup.py`. A scratch library with all 69 UDP first-person FBX scans to 37 pairs, none unmatched.
- **Import New Animations** on Bird added 13 clips, left every existing action byte-identical and is idempotent. `test_new_animations.py` re-imports an unedited clip with leftover poses on the rig and checks it reproduces the original (7.6e-06), and that weapon-only exports equal the donor (≤0.0003 cm).
- Unedited new clips carry the same differences from the donor as Bird's accepted exports (known issue 13): shoot and empty_click_aim within 8° on roll bones, like `idle_to_aim`; equip and offset aim within the range of `melee_action_01`.

Bird's blend has 24 actions. Three groups of clips the weapon plays never reach Blender:

| Group | Clips (UDP) | Why skipped | Mode |
|---|---|---|---|
| Weapon-specific overlays | `shoot`, `shoot_end`, `shoot_aim`, `shoot_aim_end`, `empty_click`, `empty_click_aim` (player and weapon) | Setup writes no FBX for additive sequences | `AAT_LocalSpaceBase` |
| | `equip`, `unequip`, `IdleToOffsetAim`, `OffsetAim-Idle`, `OffsetAimToIdle` (player); `equip`, `unequip` (weapon) | same | player `AAT_RotationOffsetMeshSpace`, weapon `AAT_LocalSpaceBase` |
| Weapon-only clips | `idle_boltlock`, `break_bullet_idle` | No player clip of the same name, so `_scan_library` does not pair them | `AAT_None` |
| Shared pistol clips | sprint, walk, jump, cover lean, left-hand detector and common reload overlays | Not UDP assets: they come from `/Game/.../AnimCollection_fp_pt`, which every pistol's collection points at | various |

The mod already owns copies of the first two groups (setup duplicates them), but they are untouched vanilla data. The game plays them on top of our clips. That is why the hidden bone frames had to match the donor (D22, D24): an edited clip has to blend with unedited ones.

### Decision

- **Weapon-specific overlays: yes, import them.** Fire and equip are the most visible animations after reload, and a custom model with different slide travel or a different hold needs its own. The setup copies are mod-owned, so editing them cannot touch vanilla weapons.
- **Weapon-only clips: yes.** `idle_boltlock` holds the slide back on an empty gun, so a model whose slide travels differently needs it. Cheap: pair a weapon clip with no player clip, and export only the weapon armature.
- **Shared pistol clips: no, not as editable clips.** They are shared by every pistol. Owning them would mean copying them into the mod and overriding entries the weapon's collection inherits from `AnimCollection_fp_pt`. Whether that override works per weapon is unverified, and an artist making a new pistol rarely needs a custom sprint. Consistency with them is already handled by matching the donor's bone frames. A later option is to import a few (sprint, sprint-to-idle) as read-only reference actions, to preview transitions in Blender, never exported.
- Importing sprint would **not** have fixed the sprint → aim drift: the blend is between our aim clip and the shared sprint either way.

### Steps

1. **Check what an additive FBX contains.** In UE, an additive sequence stores a full pose in its raw tracks and subtracts its reference pose at compression (D19 relies on this). Export one (`AS_fp_udp_shoot`) from ZoneKit and confirm in Blender that it is a full pose, matching `idle` at its reference frame, not deltas. If it is deltas, stop: the plan needs a bake step instead.
2. **Setup:** export FBX for additive sequences too, and record each one's mode, reference sequence, reference type and frame in the import manifest.
3. **Blender import:** pair weapon-only clips. Tag overlay actions with their mode and reference so the panel can show it. Retarget exactly as for full-pose clips.
4. **Export only edited overlays.** An unedited overlay keeps its vanilla bytes and original reference (the D19 rule). Detect edits by comparing the action with the keys recorded at import, not by name.
5. **ZoneKit import:** keep each overlay's additive mode (never convert between local and mesh space: D21). An edited overlay must subtract a reference from the same rig, so point it at the mod's exported reference clip (frame and type unchanged). Extend `test_animation_import.py` for both cases.
6. **Do local-space overlays first** (shoot, empty click). Game-test fire, fire → idle recovery and aim fire with an edited and an unedited `shoot`. Then do the mesh-space ones (player equip/unequip, offset aim). These are the D21 risk, so they need their own game test.
7. Docs: `exporting_animations.md` (which clips are overlays and how their reference works) and the README.

### Do not

- Convert additive modes, or bake overlays into deltas in Blender: UE already computes the delta from the full pose and reference.
- ~~Re-export unedited overlays~~: superseded by D25, all overlays are exported, edited or not.
- Copy or override the shared `AnimCollection_fp_pt` clips by default.

## Roadmap

Ordered by value to an artist. "Needs test" means it cannot be validated without the user running ZoneKit or the game.

1. **Final aim offset and crouch lean**: fixed and confirmed (D22, D23). **Sprint → aim and first aim after reload**: fixed and confirmed (D24).
2. **Blank-slate regression run**: done with Bird Mod; D11–D20 held without hand repairs.
3. **Sight alignment for new models**: mesh-only `CameraSocket` and scope eye-point overrides on `SK_<weapon>`. See "Plan: sight alignment for custom weapon models". After item 1.
4. **Fire, equip and weapon-only clips in Blender**: done and confirmed (D25, D26).
5. **Silencer and laser attachments**: mesh import/placement, custom definitions and socket-marker
   authoring are implemented. Verify cooked placement, attach/detach behaviour and effects in game;
   moving markers does not automatically reposition Blender attachment-preview geometry.
6. **Pre-flight validation panel**: single "Check Everything" button covering skeleton/bone names, action coverage per montage, attachment list, naming rules, CFG sanity, and the montage status; output as a plain-language checklist.
7. **Weapon control editor** (create controls from selected weapon bones) and **arbitrary cameras** from the previous plan.
8. **Regression matrix and release**: run the animation matrix on all five templates (only the pistol has been tested in game); produce the release zip only when the user decides (zips are git-ignored).
9. **Completion notifications (implemented)**: Blender import, retarget and Export All show one completion popup per operation, including warnings or failure; nested import steps do not create extra popups. Generated ZoneKit setup/export and import scripts show an OK dialog using `EditorDialog`, with success/warning/error categories. Detailed reports and exceptions remain available. Background Blender runs log instead of opening a popup; Unreal's unattended mode handles dialogs without waiting. ZoneKit dialogs still need an interactive editor check.

## Acceptance criteria

- An artist can go from "choose template and name" to a packaged, working weapon following only the panel instructions, with no manual file renaming.
- No step crashes ZoneKit; every ZoneKit script is idempotent and reports what it did and what remains manual.
- Blender-side tests pass headless on Blender 5.2.2 for all five templates.
- Documentation in `Arsenal/doc/` matches the panels.
