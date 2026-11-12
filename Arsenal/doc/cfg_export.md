# Weapon CFG files

Panel **4. Create Your Custom Weapon** configures the CFG files a weapon mod needs.
**Export All** writes them. A CFG-writing failure blocks the export and new import-script
generation. Do not run an older script after a failed export; old CFG files can remain in the output folder.

Files are written under the Output Folder, in `GameLite/ModGameData/<Mod>/`:

- `ItemPrototypes/<ID>WeaponPrototypes.cfg`
- `ItemPrototypes/<ID>AttachPrototypes.cfg`
- `MeshPrototypes/<ID>MeshPrototypes.cfg`
- `WeaponData/CharacterWeaponSettingsPrototypes/PlayerWeaponSettingsPrototypes/<ID>PlayerWeaponSettingsPrototypes.cfg`
- `WeaponData/WeaponAttributesPrototypes/PlayerWeaponAttributesPrototypes/<ID>PlayerWeaponAttributesPrototypes.cfg`
- `WeaponData/WeaponGeneralSetupPrototypes/<ID>WeaponGeneralSetupPrototypes.cfg`

Trader/NPC distribution settings are included in the generated import manifest. The ZoneKit
importer automatically combines every weapon in the mod into
`GameLite/GameData/ItemGeneratorPrototypes/<Mod>_ArsenalDistribution.cfg`.
It patches each base-game generator once and defines combined private pools in the same
namespace. These patches must not be loaded as new prototypes under `ModGameData`.

Custom upgrade trees additionally write `UpgradePrototypes/<ID>UpgradePrototypes.cfg` and
`EffectPrototypes/<ID>UpgradeEffects.cfg`.

## You set (panel)

- Name & Description is the first section, above Weapon.
- Template (in Set Up): choose an individual standard base-game firearm. The 38 donors cover pistols, SMGs, rifles, shotguns, DMRs/snipers, the machine gun and launcher; named/unique variants are excluded. Choosing one fills in its stats, donor asset names, export category and trader/NPC defaults. The refresh button resets stats. Everything you enter is stored in the .blend. Only the pistol replacement workflow has been tested end to end; other donors are experimental.
- Weapon: ID, base weapon, name SID, cost, weight, durability.
- **Weapon SID** in **Weapon** and **Magazine SID** for the selected entry in
  **Ammo & Magazines** show the exact exported item identifiers. Use the copy
  button beside either SID to paste it into another mod or blend. They update
  when the English weapon name, weapon template or magazine ID changes;
  reference-mode magazines show the existing SID instead of a generated one.
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

### Sharing an existing magazine

In **Ammo & Magazines**, add/select a magazine entry and tick **Reference Existing
Magazine**. Enter the exact **Existing Magazine SID**, for example
`GunE9_MagExtended`. Keep the local ID descriptive (`Extended` or `Increased` for
an extended magazine): it selects the corresponding donor animation role; it
does not create another item SID.

Set **Socket** to this weapon's game magazine bone/socket (usually `jnt_magazine`,
but template names vary). **Preinstalled** and the two reload multipliers remain
weapon-specific. Mesh selectors, capacity, cost/weight, text and image controls
are hidden because the owning item supplies those. Their previous values remain
stored if the checkbox is later cleared, but are not used to define the reference.

Export writes the existing SID into compatible attachments, reload settings and,
if selected, preinstalled attachments. The generated import manifest also uses
it for AnimCollection reload/attach maps and montage attachment notifies. No new
magazine item, mesh prototypes, localisation or images are generated for the
referenced entry. No weapon-specific geometry override is added.

On the **owning weapon**, leave **Reference Existing Magazine** unchecked and enter
the other weapons' item SIDs in **Extra Weapon SIDs**, separated by commas (for
example `GunE18, GunE19`). The current weapon is included automatically; use item
SIDs, not mod names, mesh names or magazine SIDs. Export writes these into the
magazine's `FittingWeaponsSIDs`, removes duplicates and preserves the list on
subsequent exports. This also works for preinstalled magazines. A blank field
keeps the previous export behaviour.

The original magazine must already exist and its `FittingWeaponsSIDs` must include
the new weapon's item SID. Re-export the owning weapon after editing its list.
**Extra Weapon SIDs** is hidden in reference mode, because referencing a magazine
does not modify the owner's definition or automatically add compatibility. Saved
extra SIDs are retained when toggling reference mode. If supplied
by another mod, that mod must be installed/enabled too. Only one mod should own
the magazine definition. Default behaviour for unchecked entries is unchanged.

Regenerate the import script after exporting, and run it to update animation SID
maps. Switching an existing entry to reference mode removes its generated definition
on the next CFG export; old assets or definitions already copied into ZoneKit are
not automatically deleted. Review those obsolete items before packaging.

## Trader and NPC inventories

Both sections initially load the selected weapon template's distribution from the bundled game
CFG catalogue, including which traders, roles and ranks use it. Settings are saved in the blend.
Selecting a different trader or faction switches the settings being edited; it does not discard
the previous selection's rules. **Changing the weapon Template resets trader and NPC distribution
settings to that template**, including previously edited traders and factions. Reset Stats to Template
does not reset distribution. The global **Stock Custom Attachments** setting is retained when
changing templates. Existing saved distribution edits remain until the template changes.
Defaults also apply on export when the sections have never been opened.

**Trader Inventories** selects a base-game weapon trader, then offers:

- **Stock Custom Attachments** applies to all traders for this weapon. When enabled (the default),
  each purchasable custom magazine, silencer and laser gets an independent stock roll at each
  enabled weapon trader, at half the weapon's **effective** stock chance. For example, a 50%
  effective weapon chance gives each attachment a 25% chance; a 40% weapon-entry chance behind a
  50% pool gate gives each attachment a 10% chance. A successful roll stocks one item. The rolls
  are independent, so an attachment can appear without the weapon, or vice versa.
  Preinstalled magazines, referenced existing magazines and base-game attachments are not added.
  Turn this off to remove this weapon's automatic attachment stock on the next import.
- **Stocks this weapon** and **Stock chance %**: an independent weapon-entry roll in the trader's
  existing stock pool, not a change to the refresh interval. **Effective stock chance** includes
  the original pool's activation chance. Icarus retains its 50% weapon-pool gate, so a 40% entry
  chance means 20% overall. The template's matching weapon pool is preferred; if several routes
  contain it, an always-active route is preferred. A gated template pool keeps its original gate.
- **Min/Max quantity**, **Min/Max condition %**, and **Sell unloaded**.

Minimums must not exceed maximums; invalid ranges block CFG export. The catalogue follows NPC
trade prototypes to their shop generators, not the trader's personal loot. Armor-only vendors,
unused trade definitions and DLC shops are excluded. Some entries use location-based names.
Trader defaults copy the template gun's Chance, count, durability and unloaded fields.
If the template is absent, that trader starts unchecked with zero chance. Omitted count/condition
fields use the base item-generator prototype's values (including zero counts where specified);
they are not replaced with invented quantities. An omitted unloaded flag means false.

**NPC Inventories** selects a faction. Enable the desired **Roles** and **Ranks** and enter their
percentages. Unavailable roles are disabled. The nominal share within the selected weapon pool is
**role % x rank %**: Close Combat 20% and Veteran 15% means 3%, not 35% or 20%.
Unchecked roles/ranks and zero percentages add nothing.

**Template NPC percentages are approximate**, because separate role/rank columns cannot express
all the game's role/rank/difficulty combinations. For each combination, defaults calculate the
template gun's weight divided by the pool's total weight, then average equally across the four
difficulties. Each role percentage is its largest rank share. Each rank percentage is the mean
of `rank share / role maximum` across roles that contain the template. Roles/ranks with no template
occurrences start unchecked at zero. These defaults describe the weapon pool, excluding the
separate chance of receiving a pistol. They are editable and are not an exact reproduction of
the template's complete spawn distribution.

- Pistol templates use the pistol slot; other weapon templates use the primary slot. Animation
  and firing-sound donors do not affect this choice.
- Condition and spare rounds copy the **template weapon's** generator entry for that rank and
  difficulty. When the target pool lacks that weapon, export uses the same template weapon in
  another matching reference loadout, preferring the same faction, and reports this reuse.
  It does not substitute the first unrelated gun's values. Missing template defaults block export.
- Existing weights are retained. For multiple custom weapons in a pool, each new weight is
  `p * vanilla total / (1 - sum of custom shares)`, preserving each weapon's requested share.
  At a combined 100%, only that slot/rank/difficulty's original weapon candidates are replaced;
  other gear is untouched. If combined shares exceed 100%, the importer automatically scales
  the custom weapons proportionally to fill the pool, with no remaining vanilla candidates.
  It warns with the affected pool, weapons, requested percentages and effective percentages.
  For example, three weapons each requesting 100% receive one third each. Settings are retained:
  if another weapon is later disabled, the remaining shares are recalculated.
- Shared pistol generators are specialized per selected role. Combined-rank groups are split
  while retaining unselected ranks. If inherited template ammo/condition differs by difficulty,
  the affected group is also split by difficulty rather than applying one difficulty's defaults
  to every mode. The original chance of receiving a pistol remains unchanged:
  a 3% pistol-pool share behind a 30% pistol-generation roll is about 0.9% of those NPCs overall.

The generated distribution file patches existing generators rather than replacing their roots.
For trader-owned weapon groups it appends directly. For shared trader gun pools it specializes
one existing pool containing all applicable custom weapons and repoints only that trader's
existing route, avoiding an extra stock roll or changes to other traders. Each weapon retains
its own stock chance, quantity and condition. Shared-pool specializations and split rank groups retain the
bundled reference defaults, so they do not automatically incorporate another mod's edits to those
same pools. Other mods changing weights or routes can also change the effective share.

The structured catalogue is generated from installed ZoneKit CFGs by
`zonekit_tools/build_distribution_defaults.py`. Users do not need the game data path configured
in Blender. Developers must regenerate and validate this catalogue after game updates that
change generator paths or defaults.

Export All, run the generated importer as usual, then repackage. No additional buttons, open
Blender projects or import order are required. The importer remembers each weapon's structured
distribution plan in `<mod folder>/Arsenal/distribution.json`, outside packaged Content. Importing
one weapon replaces only its record and rebuilds the combined CFG; disabling all its rules
removes only its distribution entries. Back up this state file with the mod project.

On the first updated import, recognized old Arsenal-generated per-weapon distribution CFGs
already installed in the mod are migrated automatically. Their stock settings and NPC shares
are recovered, then the obsolete generated files are removed after the combined CFG and state
are saved. Unrelated CFGs are left alone. Invalid migration or incompatible settings stop with
an error; write failures roll back the distribution changes. Old exports' distribution files
are not recopied over the combined result.

Reload the add-on and use **Export All** to regenerate an import script with this support before
running it in ZoneKit. Do not mix older generated import scripts into the updated workflow.
Re-export and import each existing weapon to add its custom attachment stock; other weapons'
previous distribution records remain unchanged until they are re-imported.
If you rename a weapon or mod, its old identity is not automatically removed: treat it as a
separate weapon and remove its old files/state record when intentionally retiring it.

These rules target generic faction/role loadouts, not every named or quest NPC. Inherited,
baked named-NPC copies and quest overrides are outside this MVP. Existing spawned inventories
do not reroll immediately. Verify fresh NPC spawns and a trader stock refresh in game, including
different ranks/difficulties; CFG regression tests do not establish runtime spawn frequencies.

## Custom upgrade tree

**Use Base Weapon Upgrade Tree** retains the existing behaviour: the weapon references the
template's unmodified upgrades. Uncheck it to populate an editable tree from that template
(the selected individual weapon). All template upgrades appear, with their original effects,
costs, weapon parts, positions, prerequisites and mutually exclusive branches.
Weapons with no base upgrades, such as Gauss and RPG-7, seed an empty tree.

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

## Fire modes and recoil

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

## Import namespace safety

The importer copies only the manifest's own `ModGameData/<Mod>` namespace. Stale export folders
for a previous mod name are skipped with a warning so they cannot reintroduce competing CFGs.
Already installed duplicate CFG copies still need removal before packaging; changing one copy
does not guarantee that its settings win when two files define the same SID.

## Set automatically

- Mod name (the **Mod Name** in Set Up, e.g. `MonkeyMod`; STALKER 2 repeats it as `GameLite/ModGameData/<Mod>`), weapon ID (or the weapon's English name), all SIDs (`Gun<ID>_...`), projectile SID (from caliber).
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

### Recovering missing ZoneKit setup

Fresh **Export All** import scripts embed the donor setup and reference patcher.
Before importing Blender assets, they create missing mod-owned sequences, additive
companions, montages, AnimCollections, AnimBPs and weapon mesh/skeleton copies,
then repair references between those copies. Existing target assets are not
duplicated or replaced by donor assets. The mod itself must already exist.
No donor FBXs are exported during recovery, and shared `/Game` assets are not saved.
Missing donors, failed saves or failed reference repairs stop recovery explicitly.

Regenerate the import script after updating the add-on; older generated scripts
cannot acquire this behaviour by reloading Blender. Continue to save the Mod
Editor's AnimCollection options before packaging.

## Notes

### Firing sound donor

Under **Handling & Fire**, choose **Firing Sound -> APB (automatic pistol)** for
a complete existing automatic-pistol sound set. The choice is saved in the blend.
It changes only `FireEventOneShot`, `FireEventLoop`, `FireEventBreak` and
`WeaponTypeSoundSwitch` in the generated general-setup CFG. Stats, fire rate,
animation templates, rattles and unload sounds remain unchanged. Viper and AK-74
are also available as complete automatic sound sets; UDP is single-shot only.

Existing blends default to **Follow Weapon Template**, preserving their sound.
Resetting stats does not reset an explicitly selected sound donor. Selecting UDP
explicitly clears the loop/break fields rather than retaining another donor's loop.
Missing automatic audio still warns in the panel and at export.

Select APB, save the blend, and export the CFGs (or **Export All**), then package the
updated CFGs using your normal workflow. No new audio files, Blueprint edits or
manual ZoneKit asset changes are required. APB sounds replace UDP firing sounds
in both semi-auto and automatic modes. Verify suppressed/unsuppressed fire, short
bursts, sustained fire and trigger release in game.

- Automatic-capable SMG/rifle sound presets export the donor's full Wwise
  `FireEventOneShot`, `FireEventLoop` and `FireEventBreak` set. Enabling automatic/burst
  fire on a single-shot donor such as UDP does not create a looping sound event.
  Export warns if the selected sound preset has no loop/break pair; it does not silently
  replace UDP with another weapon's sound. A UDP one-shot event assigned to
  `FireEventLoop` is not a verified repeating-fire solution.
- Stock silencer/laser inventory layers can be rendered or selected under
  **Attachments & Upgrades**. Use these aligned layers with a custom weapon icon;
  donor artwork/offsets can otherwise change the scale of the whole composed icon.

- The AnimBP is copied and repointed by setup, or recovered by a fresh generated importer; you do not create it by hand.
- Weapon and purchasable attachment text SIDs are generated from their IDs; no manual SID entry is needed.
- Verified in game with the pistol template: the weapon loads with its CFG stats, takes normal and extended magazines, fires and reloads.
