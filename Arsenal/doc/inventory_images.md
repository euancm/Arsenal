# Inventory and upgrade images

Weapon import automatically creates a separate **Scene_ArsenalInventory** render scene. Clicking **Render** creates it for an existing project or recreates it if it has been deleted. No manual scene setup or camera selection is required. A scene with the same name is not overwritten; Blender adds a numeric suffix if necessary.

The bundled template contains three artist-authored cameras, four sun lamps, sky world and compositor. It contains no weapon, player model, game textures or project scripts. Its compositor uses **ViewLayer_ArsenalInventory**. Camera transforms and settings, including the authored **Clip Start = 1.0**, lighting, colour management and compositor settings are retained; transparent film and PNG RGBA output are enabled for component images.

## Render previews

- **Weapon** has **Inventory image** and **Upgrade image** previews.
- Select a magazine under **Ammo & Magazines** for its corresponding component-layer previews.
- A magazine without **Preinstalled** also has a **Standalone inventory image** preview.
- Custom silencers and lasers under **Attachments & Upgrades** have component-layer and standalone previews too.
- **Render** replaces that preview; **X** clears it. Rendered images and thumbnails are packed into the blend. Save the blend normally to retain them; rendering does not save your project.
- **Select Image** uses an existing image from your computer instead of rendering. It creates an independent RGBA copy, resizes it to this preview's canvas size and packs it with a thumbnail. The original file and other Blender image users are not changed. Selected images use the same export and CFG references as rendered images. A failed selection keeps the previous preview.

The weapon images contain the body without magazines or optional accessory meshes. Magazine layer images contain the selected full magazine, with the weapon body rendered as a **holdout**: portions behind the weapon become transparent instead of showing through it. Custom accessory layers also use the preinstalled full magazine as a holdout. This only changes temporary snapshot material slots, not the weapon's materials. Standalone images omit the holdouts so the complete attachment is visible. Empty magazines, ammunition, character meshes and control shapes are not rendered.

Sizes are 258 x 128 for **all inventory images**, including standalone attachments, and 1940 x 800 for upgrade-screen layers. "Upgrade image" here means the large weapon/component layer, not a small upgrade-module close-up. These dimensions follow the pistol references.

## Adjust the setup

The default setup is automatic. To make adjustments, select **Scene_ArsenalInventory** with Blender's normal scene selector and edit its cameras, lighting, world and compositor with Blender's normal tools. Use the same selector to return to your weapon scene.

- **Camera_ArsenalInventory_Standard** is shared unchanged by the weapon body and every attachment **Inventory image** layer. Standalone silencer/laser icons also use this camera.
- **Camera_ArsenalInventory_Upgrade** is shared unchanged by all large **Upgrade image** layers.
- **Camera_ArsenalInventory_MagazineStandalone** is shared unchanged by all magazine **Standalone inventory image** renders.

Scene creation and rendering do not automatically reframe these cameras. New scenes retain the template's exact positions, angles, lens and clipping settings, and initially show the preinstalled magazine.

The add-on assigns the three cameras internally; there are no camera-selection inputs. Existing A/B preview scenes migrate on their next render: the new named cameras are loaded from the clean template unless already present in that scene. Existing cameras with these new names keep their edits. Former camera objects, lighting and compositor edits are left untouched. The new assignments replace the A/B assignments; re-render old previews to use the updated cameras. Subsequent renders preserve camera edits.

Every render automatically refreshes independent rest-pose mesh copies from the edited weapon, without changing your animation, rig pose, frame, visibility or production render settings. Materials remain shared so material edits are reflected in the previews. Geometry refresh does not reset cameras, lights or compositor edits.

There is no automatic camera fitting or fit button. If framing needs adjustment, move the relevant camera in the render scene. Do not reframe an attachment layer independently. Re-render every image in that family so the layers still align.

Previews are snapshots, not live renders. Re-render after editing geometry, materials, cameras or lighting. Rendering is synchronous and may take time; Blender's render cancellation reports a failure without replacing the existing preview.

When using external images for weapon/component layers, align their contents before selecting
them so the inventory and upgrade layers still compose correctly. Automatic resizing does not
align the artwork or remove an opaque background.

## Export to ZoneKit

**Export All** writes the rendered images as RGBA PNGs under `UI/Arsenal/<WeaponID>/` in the output folder. It adds only currently assigned images to the generated import manifest; clearing a preview stops referencing it even if an old PNG remains on disk. Images with obsolete dimensions must be re-rendered before export. Export does not render automatically.

Run the freshly generated import script in ZoneKit. Images are imported into the mod's own content mount at `/<Mod>/UI/Arsenal/<WeaponID>/`, with UI compression, sRGB, no mipmaps and no virtual-texture streaming. Re-running the importer replaces these generated image assets. No shared base-game textures are modified.

The generated weapon CFG uses the body inventory image as `Icon`. Each compatible magazine/custom accessory uses its inventory layer as `WeaponSpecificIcon`, with zero X/Y offsets because the full canvases align. Purchasable attachments use their standalone image as `Icon`. Missing previews retain the existing donor image behaviour for weapons/magazines; a custom accessory without a layer has an empty weapon-specific icon. Render the complete set before packaging.

Large upgrade layers are exported and imported as UI textures too, using the game's paired
texture naming: `T_inv_w_<WeaponID>_<component>` for inventory and the same name with `_upgrade`
appended for the large layer. Standalone icons use `T_inv_icon_<WeaponID>_<component>`.
The UDP inventory/upgrade pairs were checked in ZoneKit's asset registry; in-game lookup for a
new custom weapon still needs verification. These layers are not the small
`UpgradePrototypes.Image` module illustrations. The importer does not edit a shared upgrade-screen
widget or the shared `DT_UpgradesSettings` asset.

PDA statistics images, upgrade-module close-ups and per-class image dimensions are not generated here.
