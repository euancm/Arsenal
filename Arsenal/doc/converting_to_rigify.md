# Converting to rigify

## Unreal characters workflow
### Convert UE character to rigify

A combination of 5 operators:

1. Rename armature by mapping to the rigidy names. The default `uemannequin_rigify` mapping will be used. If you delete `uemannequin_rigify` mapping, the script won't work. 
2. Generate metarig from armature
3. Rigify generate rig. Standart rigify button. 
4. Rename the original armature backwards to the original UE names.
5. Bind the rigify rig to the armature

Usage: select unreal armature and run operator

If you want to edit the metarig for characters that don't match the unreal mannequin bone structure, then you need to run this operators separately.

### Rename armature by mapping. 
Go to [mappings page](./mappings.md)

### Generate metarig from armature

Creates rigify metarig using as input other armature with rigify names.

Usage: select an armature and run operator. 

Props: 
head_chain_length - you can specify the length of rigify `spines.super_head` sample. E.g. for unreal mannequin it will be default 2 (`neck_01` and `head` bones).

Features: 
1. Auto align and roll bones. 
2. For hand the script will compute rolls accordingly to position of `hand.{Suffix}`, `f_index.{Suffix}`, `f_middle.{Suffix}`, `f_ring.{Suffix}` bones. 
If one of the bones is missing, the script won't work.
3. For toes the script will try to compute position of the end toe bone accordingly to the child mesh object.
If mesh object doesn't have weight painted toes, they size and position likely will be wrong. 

### Bind rigify rig to armature

Copies the unreal armature to the rigify rig and makes constraints. 

Original unreal armature will be copied on 24 layer of rigify rig. And will copy all transforms from the rigify.

Usage: 
1. select unreal armature
2. select rigify rig.
3. run operator. 

Only unreal armatures supported for now.

## Other characters workflow

Prepare character for the script. 

1. Spine should contain 4 bones, and one neck bone and one head. 
2. 2 shoulder bones are required
3. 2 arms, 2 legs. 3 bones for the each limb is required. Also the armature can have twist bones for limbs.
4. An armature need to have 10 fingers, 3 bones each. 
5. Separated toes and face rig is not supported for now. 
6. Character can have breast bones.

If bones with this structure is named properly, and you have related mapping. You can just select related mapping and press `Convert character to rigify by mapping`

### Convert character to rigify by mapping

A combination of 4 operations:

1. Rename armature by mapping. You must have selected active mapping that matching the armature bones names. You can [create custom mappings](./mappings.md)
2. Generate metarig from armature. Same as unreal.
3. Rigify generate rig. Standart rigify button. 
4. Then the script will add rigify `DEF-` prefix to the armature bones and replace it with generated rigify rig. 

Now you have a rigify character. 

## STALKER 2 appended weapon rig

For the STALKER 2 workflow, an authored weapon rig (any object name, with a root bone named `Weapon`) can be appended as a separate armature object before conversion. The rig is only merged when its bones have mapping entries. In **Mapping Setup**, keep the character guesses and add source-to-target entries for the weapon controls. For the supplied Step C weapon rig, the entries are:

| Source bone | Target bone |
| --- | --- |
| `jnt_offset` | `Weapon` |
| `jnt_shutter` | `Slide` |
| `jnt_trigger` | `Trigger` |
| `jnt_titing_barrel` | `Barrel` |
| `jnt_magazine` | `Magazine` |
| `jnt_bullet_shell` | `Shell` |
| `jnt_bullet` | `Bullet` |

Then run **Convert Character by Mapping**. The converter requires every non-root bone in the appended `Weapon` armature to have a mapping to a bone on the character skeleton. It reuses the mapped `Weapon` root generated from `jnt_offset`, merges the appended child controls into the generated Rigify armature, retains their custom shapes and constraints, and rebinds the `UDP` mesh's Armature modifier. The original weapon rig and mesh are kept in the hidden **Arsenal Retarget Backups** collection, like the source armature. Retargeting reads the saved weapon mappings from the generated rig and bakes those controls with the character and camera actions.


## Generated rig tidying

- The eight forearm "star" bones (`jnt_*_fore_arm_*`) are parented to `ORG-hand.L/R` so they follow the hand in both FK and IK.
- Helper bones (star, knee, bag, armor, elbow, shoulder, neck, head, weapon-joint bones) are moved to a hidden **Hidden Helpers** bone collection. They can still be keyed.
- `hand_ik`/`hand_fk` custom shapes on both sides are scaled to the same visual size.

## Weapon rig placement

The weapon rig's root bone must be named `Weapon`. You do not need to place the rig by hand: **Snap weapon rig to jnt_offset** (Mapping panel), and **Convert Character by Mapping** automatically, translate the rig and its bound meshes so the `Weapon` bone sits exactly on the character's `jnt_offset`. Only translation is applied, so author the rig in the weapon's native ZoneKit orientation and scale.
