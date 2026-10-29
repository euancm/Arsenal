# STALKER 2 Rigify conversion

**Import Weapon** runs conversion automatically. Enable Blender's Rigify add-on before importing.
There is no separate general-purpose Unreal/Mixamo/DAZ character workflow.

## What conversion does

1. Generates a mapping from the imported STALKER skeleton to Rigify names.
2. Preserves the original character and weapon armatures, meshes and source animation in the hidden **Arsenal Retarget Backups** collection.
3. Creates a metarig from the mapped skeleton and generates the Rigify rig.
4. Merges the weapon controls, retaining their custom shapes and constraints, and rebinds the meshes.
5. Parents the preview camera to the rig's `Camera` control and stores the mappings on the rig for retargeting and export.

The internal **Convert character to rigify by mapping** operator remains available for development.
It requires a matching source-to-Rigify mapping, a child character mesh and an enabled Rigify add-on.
Do not run it on an already converted rig.

## Weapon controls

An appended weapon armature needs a root named `Weapon`. Every non-root control must map to a
source bone on the character skeleton. For a UDP-style weapon:

| Source bone | Target control |
| --- | --- |
| `jnt_offset` | `Weapon` |
| `jnt_shutter` | `Slide` |
| `jnt_trigger` | `Trigger` |
| `jnt_titing_barrel` | `Barrel` |
| `jnt_magazine` | `Magazine` |
| `jnt_bullet_shell` | `Shell` |
| `jnt_bullet` | `Bullet` |

Conversion translates the weapon rig and its bound meshes so `Weapon` sits on `jnt_offset`.
It does not change their orientation or scale; author them in the template's ZoneKit coordinates.
The normal importer creates these mappings and controls automatically.

## Generated rig tidying

- The forearm "star" helper bones follow `ORG-hand.L/R` in both FK and IK.
- Helper bones are moved to the hidden **Hidden Helpers** bone collection. They can still be keyed.
- Hand IK/FK custom shapes on both sides are scaled to the same visual size.

See [bone mappings](./mappings.md) and [animation retargeting](./animation.md).
