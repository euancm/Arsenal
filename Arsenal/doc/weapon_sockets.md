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
Shear, mirroring and nonuniform scale are unsupported.

**Reset Socket** restores the donor placement; **Reset All** asks for confirmation.
Reset also recreates a deleted marker. Unchecking **Use Edits** retains the authored
marker but requests restoration of the donor placement. Export and import again
to apply either action. An older manifest with no socket section changes nothing.
Refresh reconciles existing markers without discarding edits; a changed donor
baseline or bone is reported for review.

**SilencerMuzzleSocket** is the silencer attachment mount. **SilencerMuzzle** is
the suppressed muzzle-effect point, so it normally sits farther forward, near the
end of the fitted silencer rather than at the bare barrel.

Markers are independent of attachment geometry: moving one does not bake another
offset into the attachment's vertices, change its pivot or change existing mesh
export behavior. Existing attachment previews are not live socket constraints.
The markers are Empty objects, not new bones, and are excluded from FBX exports.
Automatic sight-line calibration is not part of this feature.

## Updating an existing project safely

After updating the add-on, regenerate both setup and import scripts: they embed
their Python source. Merely reloading the add-on does not update old scripts.

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
