# Animation operators

## Retarget animation

Select the animated source armature and the generated Rigify rig, then run **Retarget animation**. The operator resolves the bundled UE mannequin mapping against the source bone names, including `jnt_*` names, and retargets each layered Object action that animates mapped bones. When the blend contains clips made by **Import Weapon** (marked `stalker2_animation_importer`), only those are retargeted; other actions, such as raw FBX takes named `jnt_root|Unreal Take|Base Layer.001`, are ignored. The bake uses the source armature's placement from when it started, so object keys in a source action cannot shift the result, and the placement is restored afterwards.

**Convert char by mapping** keeps a hidden copy of the original armature and model in the `Arsenal Retarget Backups` collection. To retarget again later, select only the generated Rigify rig and run **Retarget animation**; the operator finds and temporarily reveals its saved source automatically. You can also select a source armature and rig together to retarget a different source manually.

Each source action is baked onto the Rigify controls as a separate action with the same name as the source action (e.g. `reload`, `reload_tactical`). In Blender, an Action is assigned to the rig object; within the Action Editor, its channels are grouped by Rigify control bone. The original source actions are removed once baked (if they are kept, the baked ones get a `rig_` prefix). Temporary helper bones and constraints are removed after baking.

Only bones animated by the source action produce motion on their mapped controls. For example, a reload clip that animates only the upper body will leave the spine and leg controls static.

After retargeting, select the Rigify rig and choose the desired action in the Action Editor. **Set animation length** updates the scene range to cover the retargeted actions.

### Blends retargeted before the leftover-take fix

Older versions could leave raw FBX takes behind on some Blender setups and retarget them too. That took about three times longer, moved the hidden source armature, and corrupted every clip baked after the first `jnt_…` action (alphabetically). Signs: the action list contains `jnt_root|Unreal Take|…` or `jnt_wpn_…|Unreal Take|…` entries, or the source armature in **Arsenal Retarget Backups** is no longer at the origin. The simplest fix is to run **Import Weapon** again in a fresh blend and retarget there, then bring across any edits you made. That also picks up a later fix for rotations near 180° (for example a fire selector or magazine) that could spin the long way between frames.

The built-in animation mapping targets UE mannequin bones and Rigify FK controls, plus `jnt_offset` to `Weapon` and `jnt_camera` to `Camera`. Custom weapon sub-control mappings are not currently available.

## Add keyframe

Or `Add keyframe button`.

Bakes a constrained pose into keyframes for manual retargeting workflows. The Retarget animation operator already creates baked actions automatically.

A combination of two operators:
1. Ctrl + A -> Apply Visual Transform to pose
2. I(Insert keyframe menu) -> LocRotScale
