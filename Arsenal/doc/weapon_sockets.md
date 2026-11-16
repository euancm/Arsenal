# Weapon sockets

Use **4. Create Your Custom Weapon > Weapon Sockets** to position existing weapon
sockets in Blender. No SKEL, skeletal-mesh or animation-preview editor needs to be
opened in ZoneKit.

## Authoring

1. Generate and run a **new** ZoneKit setup script. It exports every mesh and
   inherited skeleton socket, ownership and reference-bone transforms to
   `ZoneKit Export/weapon_sockets.json`.
2. **Import Weapon** creates a separate **Weapon Sockets** collection of named
   Empty arrows. For an existing blend, select the weapon/Rigify rig and press
   **Import / Refresh Sockets** instead.
3. Choose a socket in the list and press **Select Socket**. Translate or rotate
   its marker with Blender's normal viewport tools. Mount, view/aim and effect
   sockets are identified in the list; all are editable.
4. Save the blend. The socket identity, original game bone, donor baseline, local
   reference frame, marker and enabled state persist with it. Markers follow
   their bones, including after Rigify conversion. Changing the template does
   not reset existing socket edits.
5. **Export All**, then run the newly generated import script in ZoneKit.
   The importer applies socket edits after skeletal-mesh import. Package and
   check the weapon in game.

Socket names and parent bones are fixed. Renaming an Empty does not rename its
socket. Do not duplicate, reparent, animate or scale markers; invalid or missing
markers block export rather than silently leaving a stale socket in the mod.
Export All checks every marker before writing any files and lists all affected markers.
If Auto Keying (or **I**) keyed a moved marker, select the listed markers and use
**Object > Animation > Clear Keyframes**: this keeps their current placement. Do not use
Reset Socket for this, because it restores the donor placement.
Shear, mirroring and nonuniform scale are unsupported.

**Reset Socket** restores the donor placement; **Reset All** asks for confirmation.
Reset also recreates a deleted marker, and removes keyframes, drivers and constraints.
It also restores the marker's parent and relinks it to the scene. Unchecking **Use Edits** retains the authored
marker but requests restoration of the donor placement. Export and import again
to apply either action. An older manifest with no socket section changes nothing.
Refresh reconciles existing markers without discarding edits; a changed donor
baseline or bone is reported for review.

**SilencerMuzzleSocket** is the silencer attachment mount. **SilencerMuzzle** is
the suppressed muzzle-effect point, so it normally sits farther forward, near the
end of the fitted silencer rather than at the bare barrel.

Imported attachments mounted on named sockets are parented to their markers, so moving
or rotating a marker moves the preview too. Rigid socket parenting supplies animation
without a second armature deformation. Custom static attachments export in socket-local
coordinates, so moving the marker does not bake its offset into the mesh a second time.
Export uses the mesh/socket assignments in **Attachments & Upgrades**, even for an older
custom mesh still parented directly to the rig rather than its marker. Rear/front sight meshes
use their respective configured sockets. A missing configured marker blocks export with a
refresh instruction instead of exporting weapon-space geometry that the game would offset again.
Direct bone-mounted parts, including most magazines and pump grips, still follow their bones.
Reference-existing previews are excluded from the generated mesh and material exports.
The markers are Empty objects, not new bones, and are excluded from FBX exports.
Scope eye points can be aligned automatically; see [Aligning scope eye points](#aligning-scope-eye-points).

For an existing project, assign each attachment's mesh and socket in **Attachments &
Upgrades**, then press **Import / Refresh Sockets**. This parents the configured previews
while preserving their current world placement and enables marker names. Repeat after
changing a preview's socket. Do this in the reference/rest pose; it does not automatically
correct an already misplaced attachment. The generated first-person camera now enables
the **Center** composition guide by default.

## Updating an existing project safely

After updating the add-on, regenerate both setup and import scripts: they embed
their Python source. Merely reloading the add-on does not update old scripts.

If custom iron sights or a flash hider look correctly placed in Blender but float above or
ahead of the weapon in game, reload the updated add-on and **Export All**, run the fresh
importer and repackage. Older exports of rig-parented custom attachments included their
weapon-space placement in geometry that the game then mounted on a socket a second time.
Do not lower the socket or move the mesh to compensate for that export error. The correction
does not require changing the blend or reimporting the donor; existing marker edits are retained.

If export reports duplicate markers that are actually Arsenal's hidden retarget
backup copies, reload the updated add-on and export again. The backup copies are
recognised automatically; do not delete the backup or your socket markers.
Actual duplicated markers still block export.

If sockets imported into an existing Rigify scene appear near the floor, reload
the updated add-on and press **Import / Refresh Sockets** once, then save the blend.
Refresh repairs the donor-to-Rigify reference space while preserving marker
identities, enabled states and authored game-relative offsets. Do not manually
move all markers upward to compensate. Existing socket catalogues remain usable
for this correction; no new ZoneKit export is needed. Export is blocked until
older marker frames have been refreshed.

To refresh only the donor catalogue without recopying assets or overwriting
animations in an existing mod, run the regenerated setup script in ZoneKit:

```text
py "<working folder>/zonekit_setup_<weapon>.py" --sockets-only
```

Then select the weapon rig and use **Import / Refresh Sockets** in Blender.
Legacy flat socket JSON still works for the previous attachment import, but
cannot supply the reference frames needed for editable markers.

To update sockets without reimporting meshes, animations, CFG or textures:

```text
py "<Blender Export>/import_<weapon>.py" --sockets-only
```

The destination mesh must already exist for a socket-only import.

## Safety and runtime scope

The importer writes only the exact mod-owned weapon mesh used by the exported CFG.
Inherited sockets are copied through an independent, temporary skeleton duplicate,
then re-owned by the destination mesh and added as mesh-only overrides. The temporary
copy is deleted without saving it. The original socket, its skeleton, all bones,
skeleton assignments and animation references remain unchanged. No shared `/Game`
or other mod assets are modified, and the socket writer saves no skeleton.

The installed ZoneKit bindings protect socket arrays and expose no removal API.
Reset therefore restores donor **placement**, retaining a baseline mesh-only
override and its ownership record when Arsenal created it. The importer warns
about this distinction; it does not pretend to delete the override or switch back
to live inheritance. Pre-existing mesh sockets are restored without deletion.
If a later donor catalogue changes, review the baseline rather than silently
adopting it.

The importer validates all entries before socket writes, preserves unrelated
sockets, detects external edits, verifies transforms before saving, and rolls
back captured values on failure. Only the destination mesh and its Arsenal
metadata are saved. If a failure occurs after creating an override, the importer
restores its original placement and explicitly reports that the binding cannot
remove the new object during rollback.

The destination mesh is explicitly marked dirty before changing its socket
subobjects, so an editor save cannot silently skip the owning package. Regenerate
the importer and reapply edits after updating the add-on. Verify the saved mesh
in a fresh ZoneKit process as well as aiming and attachment placement in game;
a socket readback in the original editor session alone is not persistence proof.

## Aligning scope eye points

Each scope has an **eye point**: a socket on `jnt_wpn_m160` named after the scope SID
(for example `EN_GoloScope_1`, `M701_Colim_Scope`). When aiming, the camera sits at this
socket and looks along its +X arrow. The marker therefore sits well behind the optic,
roughly where the player's eye is, not on the scope itself. Its mount socket on
`jnt_offset` is the one that moves the optic.

1. Move the **mount** socket markers until the optics sit where you want them.
2. Press **Align Eye Points to Sights** (or **Align Selected** for the active entry). Each
   eye point keeps the donor's eye distance and moves sideways and vertically by exactly
   as much as the centre of its scope's reticle surface moved from the donor placement.
   An unedited scope therefore stays put. The reticle is the faces using a material whose
   name contains `mark`; scopes without one are listed and left unchanged.
3. Select an eye point and press **View Through Eye Point** to look along it. The reticle
   should sit in the centre of the view. Orbit or press Numpad 0 to leave the view.
4. Export and import as usual.

The calibration comes from a referenced scope with the same SID or, failing that, the
imported donor entry named after it, even with **Reference Existing** turned off. Only
referenced (Reference Existing) scopes have their markers moved. For custom scopes the
marker is shared with the donor, so it is left unchanged and the Info log reports the
location and rotation of the mesh socket to add in ZoneKit (see below). A custom copy of a
game scope (an imported entry whose **Reference Existing** was turned off) is reported in
the same way. Turn **Reference Existing** back on unless you intend to ship a separate copy.

## Custom scope eye sockets

Base-game scopes derived from another scope have their own eye socket on the weapon mesh,
named after the scope SID (for example `M701_Scope`). When a custom scope is copied from
a donor that has an eye socket on your weapon, the importer warns if your scope has none.
Adding it is a manual step: ZoneKit can create such a socket only by renaming a socket
on the shared skeleton, which would leave a base-game asset modified. To add it by hand:

1. Open your mod's weapon skeletal mesh in ZoneKit and note the donor socket's bone and
   transform (for example `EN_GoloScope_1`).
2. Create a **mesh** socket (not a skeleton socket) on that bone named exactly your scope
   SID, with the donor transform, or with the aligned transform reported by **Align Eye
   Points to Sights**. Renaming a socket that shares its name with a skeleton
   socket also renames the skeleton socket, so do not rename the donor socket itself.
3. Save only the weapon mesh. If the shared `/Game/...` skeleton is marked modified,
   do not save it; restart ZoneKit without saving it.

Socket coordinates are relative to the original game bone, in Unreal centimeters.
JSON rotations are `[roll, pitch, yaw]` in degrees; reference-bone quaternions are
`[x, y, z, w]`. Blender bone-axis correction, bone-tail parenting, handedness and
full reference transforms are accounted for. Animation frames and armature-object
placement do not get baked into the authored offset.
FBX component-root sockets use the **Weapon** control as their Blender preview
anchor; their exported game parent remains the original component-root bone.
The new catalogue identifies this root for older blends too.

If a new mesh or reimport has no sockets, the importer recreates the catalogue's
existing sockets from independent donor copies, including unchanged baseline
sockets. It first verifies that their original bones exist on the destination
and that the donor still matches the catalogue. It never writes to the donor.

Check silencer/laser attachment and detach animations, muzzle/ejection effects,
iron sights, optic mounts and optic eye points in game. First-person, NPC,
third-person and dropped/world views must be checked separately: a consumer using
the destination mesh sees its mesh-only overrides, but a separate static mesh or
a consumer reading skeleton sockets directly is not modified automatically. Cooking and in-game
behavior remain acceptance checks; a correct Blender or Python preview is not
proof that every game consumer uses that socket.
