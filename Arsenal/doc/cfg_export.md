# Weapon CFG files

Panel **4. Create Your Custom Weapon** writes the CFG files a weapon mod needs. **Export All** writes them. If the CFG step fails, Export All warns and carries on.

Files are written under the Output Folder, in `GameLite/ModGameData/<Mod>/`:

- `ItemPrototypes/<ID>WeaponPrototypes.cfg`
- `ItemPrototypes/<ID>AttachPrototypes.cfg`
- `MeshPrototypes/<ID>MeshPrototypes.cfg`
- `WeaponData/CharacterWeaponSettingsPrototypes/PlayerWeaponSettingsPrototypes/<ID>PlayerWeaponSettingsPrototypes.cfg`
- `WeaponData/WeaponAttributesPrototypes/PlayerWeaponAttributesPrototypes/<ID>PlayerWeaponAttributesPrototypes.cfg`
- `WeaponData/WeaponGeneralSetupPrototypes/<ID>WeaponGeneralSetupPrototypes.cfg`

## You set (panel)

- Template: Pistol (UDP), SMG (Viper), Rifle (AK-74), Shotgun (M860) or Sniper (Three-Line). Choosing one fills in every stat below from that base game weapon (the refresh button next to it resets your edits). Everything you enter is stored in the .blend, so sharing the file shares the settings.
- Weapon: ID, base weapon, name SID, cost, weight, durability.
- Damage and range: damage, armor damage, piercing, bleeding, distances, loudness, comfort, UI stat bars.
- Handling and fire: fire interval, recoil and dispersion radius, aiming times, jam values, dead-NPC ammo.
- Ammo and magazines: max ammo, caliber, and a magazine list (name, full/empty mesh objects, capacity, preinstalled, cost, weight, reload multipliers). If the list is empty, magazines are detected from extra weapon meshes (names containing `full` / `empty`).
- Attachments: silencer, laser, keep the template weapon's upgrade list.

## Set automatically

- Mod name (the **Mod Name** in the Export panel, e.g. `MonkeyMod`; STALKER 2 repeats it as `GameLite/ModGameData/<Mod>`), weapon ID (or the weapon's English name), all SIDs (`Gun<ID>_...`), projectile SID (from caliber).
- Mesh names and paths (from the mesh object names), static mesh parts and sockets (from the weapon bones), magazine sockets (from weights).
- AnimBP path (from the exported weapon animation folder), category.

## Taken from the template weapon

Recoil pattern, blend curve, camera shake, audio events and the upgrade list (not editable). The silencer and laser attachment blocks are UDP-style.

## Name and description (localisation)

The **Name & Description** box in panel 4 has a language dropdown (en, uk, fr, de, ...). Pick a language, type or paste the name and description, then pick another language and repeat. Everything is saved in the .blend.

Export All writes `Localization/<Mod>-<Weapon>-localization.json`, with `sid_items_<key>_name` and `sid_items_<key>_description` entries (the key is the weapon SID, or the Text Key Override if set). The same entries are baked into the ZoneKit import script, which adds them to the mod's `LocalizationModTextToolAsset` (named `<Mod>TextToolAsset`, created if the mod has none), replacing entries with the same SID and keeping the others. If your editor's Python can't edit that asset the script says so and you can add the JSON entries with the Mod Editor text tool. Languages you leave out fall back to English, so fill in English first. Type `\n` for a line break in the description.

## Notes

- The AnimBP is copied, renamed and repointed by the ZoneKit setup script; you do not create it by hand.
- The name SID is left out unless you set one, so the in-game name is inherited from UDP.
- Verified in game with the pistol template: the weapon loads with its CFG stats, takes normal and extended magazines, fires and reloads.
