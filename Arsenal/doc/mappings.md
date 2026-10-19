# Mappings and armature renaming

Stalker 2 Arsenal uses a bone mapping system internally, and you can use it to rename bones. You can create and edit your own mappings for different skeletons.

## Rename armature by mapping

Usage: Select an armature. Choose the mapping and run operator. 

Bones in the mapping will be renamed according to the selected mapping.

Props:
1. Revese - rename backwards. E.g. if you choose uemannequin_rigify mapping, it will rename rigify names to UE names. 

If bone name not in the mapping, the operator will not rename it. 

## Add/Remove prefix

Used mostly internaly. 

But you can fix with it some Mixamo characters. Some of them have redundant prefixes in bones, for example `Boy:Head`. If you keep them, other operators won't work.

Props: 
1. Prefix - prefix to add/remove.

## Generate a mapping

Select the source armature in Object Mode and click **Guess mapping from armature** in **STALKER 2 > 2. Mapping Setup**. The editor shows all Rigify target bones; the source column contains best guesses and stays blank when a match is uncertain.

Edit the source names as needed. Changes are saved automatically to the generated mapping, which is selected internally for **Convert Character by Mapping**. Use **Add entry** to add additional source-to-target pairs.
