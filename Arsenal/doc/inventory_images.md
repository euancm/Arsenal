# Inventory and upgrade images

Weapon import automatically creates a separate **Scene_ArsenalInventory** render scene. Clicking **Render** creates it for an existing project or recreates it if it has been deleted. No manual scene setup or camera selection is required. A scene with the same name is not overwritten; Blender adds a numeric suffix if necessary.

The bundled template contains three artist-authored cameras, four sun lamps, sky world and compositor. It contains no weapon, player model, game textures or project scripts. Its compositor uses **ViewLayer_ArsenalInventory**. Camera transforms and settings, including the authored **Clip Start = 1.0**, lighting, colour management and compositor settings are retained; transparent film and PNG RGBA output are enabled for component images.

## Render previews

- **Weapon** has **Inventory image** and **Upgrade image** previews.
- Select a magazine under **Ammo & Magazines** for its corresponding component-layer previews.
- **Reference Existing Magazine** hides its image controls and skips its saved
  image selections during export; images come from the owning item. Unchecking
  the option restores the previous selections.
- A magazine without **Preinstalled** also has a **Standalone inventory image** preview.
- Custom attachments under **Attachments & Upgrades** have component-layer and standalone previews too.
  Custom iron sights render both meshes together.
- **Reference Existing** attachments (for example a game scope) have **Inventory image** and
  **Upgrade image** previews, because those layers show the item on this weapon. They have no
  standalone preview: the attachment's own icon still comes from the game. Without an inventory
  layer, the compatible-attachment entry has an empty `WeaponSpecificIcon` and export warns.
  No replacement attachment meshes or textures are exported.
- **Render All Attachment Images** (below the attachment list) renders the **Inventory image**
  and **Upgrade image** of every listed attachment, custom or referenced, in one go, replacing
  their current images. Attachments without a mesh in the weapon scene are skipped with a
  warning. Standalone images and stock silencer/laser layers are not included; render those
  individually. Cancelling a render stops the batch but keeps the images already rendered.
- Enabled stock silencers/lasers have **Stock silencer/laser image layers** in that panel.
  Select a **Preview Mesh** and render their inventory/upgrade layers with the same cameras
  as the weapon, or use **Select Image** for already aligned artwork. This mesh is used
  only for the preview; it does not change the attachment's SID, in-game mesh or behavior.
  Use the mesh corresponding to the mounted stock model, not an unrelated donor accessory.
  Stock attachment standalone icons continue to come from the game.
- **Render** replaces that preview; **X** clears it. Rendered images and thumbnails are packed into the blend. Save the blend normally to retain them; rendering does not save your project.
- **Select Image** uses an existing image from your computer instead of rendering. It creates an independent RGBA copy, resizes it to this preview's canvas size and packs it with a thumbnail. The original file and other Blender image users are not changed. Selected images use the same export and CFG references as rendered images. A failed selection keeps the previous preview.

The weapon images contain the body without magazines or optional accessory meshes. Magazine layer images contain the selected full magazine, with the weapon body rendered as a **holdout**: portions behind the weapon become transparent instead of showing through it. Custom accessory layers also use the preinstalled full magazine as a holdout. This only changes temporary snapshot material slots, not the weapon's materials. Standalone images omit the holdouts so the complete attachment is visible. Empty magazines, ammunition, character meshes and control shapes are not rendered.

Weapon and component **Inventory image** canvases use the size of the bundled template for
the weapon type:

| Weapon type | Inventory canvas |
|---|---|
| Pistol | 258 x 128 |
| Assault rifle, SMG, shotgun | 648 x 258 |
| Sniper rifle, DMR, Gauss | 908 x 258 |

Templates without a guide (PKP, RPG-7) keep the donor preset's size. Upgrade-screen layers
are **1940 x 800**. "Upgrade image" means the large weapon/component layer, not a small
upgrade-module close-up. The weapon CFG still inherits the donor's inventory grid, so an SMG
or sniper canvas can be wider than the donor's slot; check the composed icon in game.

**Standalone inventory image** canvases follow the item's inventory grid, using the game's
icon spans: 1 cell = **128**, 2 cells = **262**, 3 cells = **388** pixels. Magazines and
1 x 1 attachments are **128 x 128**; a 2 x 1 silencer is **262 x 128**. A custom attachment
uses the grid of its **Base Attachment SID**.

Export rejects images with an obsolete size. After updating the add-on, re-render or reselect
the affected images (in particular magazine and attachment standalone images, which used to be
258 x 128), then **Export All**, run the fresh ZoneKit importer and repackage.

## Adjust the setup

The default setup is automatic. To make adjustments, select **Scene_ArsenalInventory** with Blender's normal scene selector and edit its cameras, lighting, world and compositor with Blender's normal tools. Use the same selector to return to your weapon scene.

- **Camera_ArsenalInventory_Standard** is shared unchanged by the weapon body and every attachment **Inventory image** layer.
- **Camera_ArsenalInventory_Upgrade** is shared unchanged by all large **Upgrade image** layers.
- **Camera_ArsenalInventory_MagazineStandalone** renders every **Standalone inventory image**,
  for magazines and all custom attachments. Before each standalone render it is moved (and,
  for an orthographic camera, scaled) so that the item is centred and fills most of the canvas.
  Its rotation, lens and clipping are kept, so set its viewing angle once and every standalone
  icon follows it. The fitted position remains after rendering.

The Standard and Upgrade cameras show a translucent template guide as a camera background:
a silhouette traced from a game icon of the same weapon type (`<type>_inventory.png` /
`<type>_upgrade.png`). Look through the camera to line the weapon up with it. Guides are only
visible in the viewport; they are not rendered. They follow the weapon template: the guide is
replaced when the template changes. A camera that already has your own background image is left
alone, and the add-on guide is removed from it.

The Standard and Upgrade cameras are not reframed automatically. New scenes retain the template's exact positions, angles, lens and clipping settings, and initially show the preinstalled magazine.

The add-on assigns the three cameras internally; there are no camera-selection inputs. Existing A/B preview scenes migrate on their next render: the new named cameras are loaded from the clean template unless already present in that scene. Existing cameras with these new names keep their edits. Former camera objects, lighting and compositor edits are left untouched. The new assignments replace the A/B assignments; re-render old previews to use the updated cameras. Subsequent renders preserve camera edits.

Every render automatically refreshes independent rest-pose mesh copies from the edited weapon, without changing your animation, rig pose, frame, visibility or production render settings. Materials remain shared so material edits are reflected in the previews. Geometry refresh does not reset cameras, lights or compositor edits.

Inventory and upgrade layers must stay aligned. To change their framing, move the Standard or Upgrade camera, never for a single layer, and re-render every image in that family. Custom iron sights frame front and rear sights together in their standalone image, so the two parts can end up at opposite edges.

Previews are snapshots, not live renders. Re-render after editing geometry, materials, cameras or lighting. Rendering is synchronous and may take time; Blender's render cancellation reports a failure without replacing the existing preview.

When using external images for weapon/component layers, align their contents before selecting
them so the inventory and upgrade layers still compose correctly. Automatic resizing does not
align the artwork or remove an opaque background.

## Export to ZoneKit

**Export All** writes the rendered images as RGBA PNGs under `UI/Arsenal/<WeaponID>/` in the output folder. It adds only currently assigned images to the generated import manifest; clearing a preview stops referencing it even if an old PNG remains on disk. Images with obsolete dimensions must be re-rendered before export. Export does not render automatically.

Run the freshly generated import script in ZoneKit. Images are imported into the mod's own content mount at `/<Mod>/UI/Arsenal/<WeaponID>/`, with UI compression, sRGB, no mipmaps and no virtual-texture streaming. Re-running the importer replaces these generated image assets. No shared base-game textures are modified.

The generated weapon CFG uses the body inventory image as `Icon`. Each compatible magazine/custom accessory uses its inventory layer as `WeaponSpecificIcon`, with zero X/Y offsets because the full canvases align. Purchasable attachments use their standalone image as `Icon`. Referenced (**Reference Existing**) attachments also use this weapon's inventory layer as `WeaponSpecificIcon`, while their `Icon` stays the game's. Missing previews retain the existing donor image behaviour for weapons/magazines; a custom or referenced accessory without a layer has an empty weapon-specific icon. Render the complete set before packaging.

Assigned stock attachment layers also use mod-owned `WeaponSpecificIcon` textures and zero
offsets. Without a stock layer, the legacy donor overlay and offsets are retained; export
warns when this is combined with a custom weapon body image. In particular, the stock
silencer fallback uses Integral artwork, which is not aligned to a custom pistol canvas
and can alter the bounds/scale of the entire composed inventory icon. Render the stock
layer to avoid mixing these layouts. Custom attachments of the same kind take precedence;
disabled/replaced stock layers are not exported. Clear a stock preview with **X** to stop
exporting it. Re-render all layers after camera edits, regenerate the import script with
**Export All**, import in ZoneKit and repackage before checking the composed icon in game.

Large upgrade layers are exported and imported as UI textures too, using the game's paired
texture naming: `T_inv_w_<WeaponID>_<component>` for inventory and the same name with `_upgrade`
appended for the large layer. Standalone icons use `T_inv_icon_<WeaponID>_<component>`.
The UDP inventory/upgrade pairs were checked in ZoneKit's asset registry; in-game lookup for a
new custom weapon still needs verification. These layers are not the small
`UpgradePrototypes.Image` module illustrations. The importer does not edit a shared upgrade-screen
widget or the shared `DT_UpgradesSettings` asset.

PDA statistics images and upgrade-module close-ups are not generated here.
