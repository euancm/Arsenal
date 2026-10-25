"""Development helper: load the add-on straight from this repository.

Open this file in Blender's Text Editor and press Run Script, or start Blender with
`blender --python dev_load_addon.py`. Running it again reloads every module, so code
edits show up without reinstalling the zip.
"""
import os
import sys

import addon_utils
import bpy

PACKAGE = 'stalker2_arsenal'


def repo_dir():
    # Blender sets __file__ to the text block's name when run from the Text Editor,
    # so find the block's real path instead.
    candidates = [globals().get('__file__', '')]
    candidates += [bpy.path.abspath(t.filepath) for t in bpy.data.texts
                   if t.filepath and os.path.basename(t.filepath) == 'dev_load_addon.py']
    for path in candidates:
        folder = os.path.dirname(os.path.abspath(path)) if path else ''
        if os.path.isdir(os.path.join(folder, PACKAGE)):
            return folder
    raise RuntimeError(
        f"Can't find the '{PACKAGE}' folder. Open dev_load_addon.py from the Arsenal folder "
        "of the repository (Text > Open), rather than pasting it into a new text block.")


def unload():
    # The installed zip copy and an earlier dev load both register the same classes.
    addon_utils.disable(PACKAGE, default_set=True)
    module = sys.modules.get(PACKAGE)
    if module is not None and hasattr(module, 'unregister'):
        try:
            module.unregister()
        except Exception:
            pass
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + '.')]:
        del sys.modules[name]


folder = repo_dir()
unload()
if folder in sys.path:
    sys.path.remove(folder)
sys.path.insert(0, folder)

import stalker2_arsenal  # noqa: E402

if not os.path.abspath(stalker2_arsenal.__file__).startswith(folder):
    raise RuntimeError(f"Loaded {stalker2_arsenal.__file__} instead of the copy in {folder}.")
stalker2_arsenal.register()
print(f"Stalker 2 Arsenal loaded from {folder}")
