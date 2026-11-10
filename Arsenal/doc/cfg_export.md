# Weapon CFG files

Panel **4. Create Your Custom Weapon** writes the CFG files a weapon mod needs. **Export All** writes them. If the CFG step fails, Export All warns and carries on.

Files are written under the Output Folder, in `GameLite/ModGameData/<Mod>/`:

- `ItemPrototypes/<ID>WeaponPrototypes.cfg`
- `ItemPrototypes/<ID>AttachPrototypes.cfg`
- `MeshPrototypes/<ID>MeshPrototypes.cfg`
- `WeaponData/CharacterWeaponSettingsPrototypes/PlayerWeaponSettingsPrototypes/<ID>PlayerWeaponSettingsPrototypes.cfg`
- `WeaponData/WeaponAttributesPrototypes/PlayerWeaponAttributesPrototypes/<ID>PlayerWeaponAttributesPrototypes.cfg`
- `WeaponData/WeaponGeneralSetupPrototypes/<ID>WeaponGeneralSetupPrototypes.cfg`

Custom upgrade trees additionally write `UpgradePrototypes/<ID>UpgradePrototypes.cfg` and
`EffectPrototypes/<ID>UpgradeEffects.cfg`.

## You set (panel)

- Template: Pistol (UDP), SMG (Viper), Rifle (AK-74), Shotgun (M860) or Sniper (Three-Line). Choosing one fills in every stat below from that base game weapon (the refresh button next to it resets your edits). Everything you enter is stored in the .blend, so sharing the file shares the settings.
- Weapon: ID, base weapon, name SID, cost, weight, durability.
- Damage and range: damage, armor damage, piercing, bleeding, distances, loudness, comfort, UI stat bars.
- Handling and fire: tick the **Available Fire Modes** checkboxes for Semi-automatic, Burst and Automatic. At least one stays enabled; the last checked mode cannot be switched off. Under **Fire Mode Settings**, the dropdown shows only enabled modes. Select a mode and tick **Default fire mode** to make it the sole starting mode; the previous default is cleared automatically. The current default cannot be unchecked without choosing another, and disabling its available-mode checkbox selects an enabled replacement automatically. Burst Length appears when Burst is selected and is at least two shots. Fire interval, recoil and dispersion radius, aiming times and jam values are shared across modes, not separate per-mode settings. Export replaces the inherited `FireTypes` list, writes `DefaultFireType`, and uses `EFireType::Queue` / `FireQueueCount` for bursts. Existing blends without these settings keep their template's inherited modes until edited.
- Ammo and magazines: max ammo, caliber, and a magazine list (name, full/empty mesh objects, capacity, preinstalled, cost, weight, reload multipliers). If the list is empty, magazines are detected from extra weapon meshes (names containing `full` / `empty`).
- Attachments: silencer, laser, and either the unchanged template upgrade tree or an editable custom tree.

Under **Attachments & Upgrades**, add custom silencer/laser entries to configure mod-owned
attachment IDs, meshes, sockets, price, weight, text and images. Each mesh must be separate and
weighted to a mapped weapon bone so static export includes it. Custom entries inherit the
matching game attachment's behaviour but restrict fitting to this weapon and use their own mesh
prototype. Adding a custom type replaces the corresponding base-game compatibility option;
without custom entries the existing checkbox behaviour is unchanged. Custom attachments are
available without the donor laser's upgrade requirement. Set the socket explicitly
(`SilencerMuzzleSocket` or `LaserSocket` normally).

Every purchasable magazine and custom attachment has its own **Language**, **Display Name**, **Description**
and optional **Text Key Override**. Its ID is not its displayed name. Text exports through the
same automatic localisation asset update as the weapon, using
`sid_items_Gun<WeaponID>_Mag<MagazineID>_name` or
`sid_items_Gun<WeaponID>_Attach<AttachmentID>_name` (and `_description`).
Blank languages remain unmodified on an existing mod text asset. Do not give distinct items the
same text override unless their entered translations agree.

**Preinstalled magazines do not need localisation.** Their name/description controls are hidden
and their text and text-key override are omitted from exports. Previously entered translations
stay in the blend in case you later make the magazine purchasable; existing ZoneKit entries are
not deleted.

Rendered images are exported and referenced automatically; see [Inventory images](inventory_images.md).

## Custom upgrade tree

**Use Base Weapon Upgrade Tree** retains the existing behaviour: the weapon references the
template's unmodified upgrades. Uncheck it to populate an editable tree from that template
(UDP, Viper, AK74, M860 or Three-Line). All template upgrades appear, with their original effects,
costs, weapon parts, positions, prerequisites and mutually exclusive branches.

Select an upgrade to edit:

- **ID**: unique within this tree. Prerequisite, exclusion and interchangeability lists use these
  IDs, separated by commas. Update those lists if you rename or remove a referenced upgrade.
- **Cost**, **Weapon Part**, **Column**, **Position** and **Connection Lines** define the technician
  screen layout. Connectors are comma-separated `Top`, `Down` or `None`.
- **Prerequisite Upgrade IDs**, **Mutually Exclusive Upgrade IDs** and **Interchangeable Upgrade IDs**
  are remapped to this weapon's mod-owned upgrade SIDs on export. Invalid IDs, self-references,
  duplicate references and prerequisite cycles block export instead of generating a broken tree.
- **Required Item SIDs**, **Required Skills** and **Keep Base Global-variable Restrictions** control
  access. The latter retains the donor's blueprint/quest variable restrictions unless unchecked.
  Clearing it does not clear the separately editable item or skill requirements.
- **Attachment SIDs** list hardware installed by the upgrade. Matching custom silencer/laser SIDs
  replace their donor attachment references automatically. Other donor hardware references are
  retained: they still need compatible meshes and weapon configuration; changing an upgrade
  does not generate new sockets or hardware geometry.
- **Name & Description** supports the same multilingual inputs as weapons. Blank fields retain
  donor text. Entered fields export as `sid_upgrades_Gun<WeaponID>_Upgrade_<ID>_name` and
  `_description`, and are imported automatically into the mod's localisation text asset.
- **Select Image** packs a custom module illustration at its original dimensions and exports a
  mod-owned UI texture. **X** restores the donor illustration. This is separate from the large
  weapon/component **Upgrade image** preview.
- **Functionality** lists existing game effects. Add/remove effects or enable **Custom Values** to
  create a mod-owned numerical version of the chosen effect. For +15% damage, select
  `DamagePos20Effect`, enable Percentage and set Minimum/Maximum to `15`; for -20% recoil,
  select `RecoilDown20Effect` and set both to `-20`. Signed values modify the affected game stat,
  not a generic "improvement" amount. Benefit controls the game's benefit/penalty presentation;
  the effect can also be hidden from upgrade details. Caliber, ammo-type and flag effects use
  their existing behaviour and cannot take numerical overrides.

The **+ / -** buttons add/remove custom upgrades and effects. An empty custom tree is permitted.
**Reset Tree to Template** replaces the custom tree, text and image assignments after confirmation.
Toggling back to the base tree preserves custom edits but excludes them from new exports. Changing
the weapon template does not discard an existing custom tree; reset explicitly to use the new one.

Generated upgrade/effect definitions inherit the donor through `@BaseGame` references and use
new SIDs. No shared base-game definitions or assets are edited. Export All, run the fresh
ZoneKit importer, package and verify the technician layout and effect behaviour in game.

The **Default fire mode** checkbox stays interactive when checked. Clicking it again keeps the existing default; to change the default, select another enabled mode and check it there.

**Recoil Recovery Delay** and **Recoil Recovery Time** control the camera's return after firing,
in seconds. They write `RecoilParams.ShootingStateParams.RadiusNormalizationModifiers`:
`RadiusNormalizationDelay` and `RadiusNormalizationInterval`. They are shared across fire modes.
The defaults retain the add-on's previous output: no delay and a 0.06-second recovery (also the
UDP donor's values). **Reset Stats to Template** restores these legacy recovery defaults for all
templates; the add-on does not infer a different recovery time for automatic fire. Increase
Recovery Time, for example to 0.3 seconds as a starting experiment, to test a slower return;
zero means immediate recovery. Re-export, run the fresh import script and repackage before
checking in game. This controls procedural camera recoil, not missing keys or arm continuity
in `shoot_aim_end`.

If the view still snaps back after the arm animation is repaired, check the exported
`RadiusNormalizationInterval`: the unchanged 0.06-second default is a very short return.
Try **Recovery Time = 0.3**, **Delay = 0**, then successfully re-export, run the fresh importer,
and repackage. Check the CFG copied into the mod as well as the Blender output. This is a
tuning test, not proof that every camera discontinuity is procedural recoil.

The importer copies only the manifest's own `ModGameData/<Mod>` namespace. Stale export folders
for a previous mod name are skipped with a warning so they cannot reintroduce competing CFGs.
Already installed duplicate CFG copies still need removal before packaging; changing one copy
does not guarantee that its settings win when two files define the same SID.

## Set automatically

- Mod name (the **Mod Name** in the Export panel, e.g. `MonkeyMod`; STALKER 2 repeats it as `GameLite/ModGameData/<Mod>`), weapon ID (or the weapon's English name), all SIDs (`Gun<ID>_...`), projectile SID (from caliber).
- Mesh names and paths (from the mesh object names), static mesh parts and sockets (from the weapon bones), magazine sockets (from weights).
- AnimBP path (from the exported weapon animation folder), category.

## Taken from the template weapon

Recoil pattern, blend curve, camera shake and audio events (not editable). The base upgrade
tree is unchanged unless custom-tree editing is enabled. The silencer and laser attachment blocks are UDP-style.

## Name and description (localisation)

The **Name & Description** box in panel 4 has a language dropdown (en, uk, fr, de, ...). Pick a language, type or paste the name and description, then pick another language and repeat. Everything is saved in the .blend.

Export All writes `Localization/<Mod>-<Weapon>-localization.json`, with `sid_items_<key>_name` and `sid_items_<key>_description` entries (the key is the weapon SID, or the Text Key Override if set). The same entries are included in the ZoneKit import manifest. Running the generated import script automatically adds or updates these SIDs and translations in the mod's `LocalizationModTextToolAsset`. **You do not need to enter the SIDs in the Mod Editor.** Export All again to regenerate existing import scripts after updating the add-on; old scripts retain the old importer.

The importer reuses `<Mod>TextToolAsset`, or the mod's sole text asset even if named differently (for example `L_<Mod>`). If none exists it creates `<Mod>TextToolAsset`. Multiple text assets without that preferred name produce a warning instead of updating an arbitrary asset; resolve the ambiguity before retrying.

Text updates use Unreal's native array and struct text APIs, without requiring the localisation entry struct or language enum to be exposed as Python classes. Empty arrays are populated without a template entry. Blank rows created by the text tool (empty SID and no meaningful translations, including ZoneKit's `UNLOCALIZED MOD STRING` placeholder) are reused for new entries, not treated as corrupt SIDs. An empty SID with real text, or duplicate nonempty SIDs, still produces a warning rather than discarding data. Existing unrelated SIDs and translations in languages not supplied by this export are preserved. Re-running an unchanged export does not duplicate entries or save the text asset again. Removing a translation from Blender does not delete it from an existing text asset.

Languages absent from the asset fall back to English, so fill in English first. Type `\n` for a line break in the description. Exported values, including non-Latin text, quotes and line breaks, are checked against the asset before saving. A failed write or save produces a warning, not a successful localisation update; the JSON and all SID/language values in the Output Log remain available for diagnosis or manual recovery. Multiline log values use literal `\n` escapes.

Before packaging, open your mod in the Mod Editor and update its AnimCollection options to use your weapon's first-person collection. Save these options. Localisation no longer needs a routine manual update; resolve any import warnings before packaging and testing in game.

## Notes

- The AnimBP is copied, renamed and repointed by the ZoneKit setup script; you do not create it by hand.
- Weapon and purchasable attachment text SIDs are generated from their IDs; no manual SID entry is needed.
- Verified in game with the pistol template: the weapon loads with its CFG stats, takes normal and extended magazines, fires and reloads.
