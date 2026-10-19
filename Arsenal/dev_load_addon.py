"""Development helper: run from Blender's Text Editor to load the add-on from this folder."""
import sys
import os
import importlib
import bpy

blend_dir = os.path.dirname(bpy.data.filepath)
if blend_dir not in sys.path:
    sys.path.append(blend_dir)

import stalker2_arsenal
importlib.reload(stalker2_arsenal)
stalker2_arsenal.register()
