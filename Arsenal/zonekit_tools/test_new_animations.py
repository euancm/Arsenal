"""Check Import New Animations on a converted blend, in Blender.

blender --background --factory-startup --python-exit-code 1 --python test_new_animations.py -- <blend> [library] [clip]

The blend must contain an Arsenal rig and backup. <clip> (default idle) must be an unedited clip the blend
already has: it is renamed away so the operator imports it again, and the fresh retarget has to reproduce the
original action. Before running, the rig is left with posed unkeyed controls and the left arm switched to IK, as
editing another clip leaves it; none of it may leak into the new actions. Nothing is saved.
"""
import importlib
import math
import os
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_animation_export import angular_error, engine_worlds


def curves(action):
    found = {}
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    found[(curve.data_path, curve.array_index)] = curve
    return found


def fingerprint(action):
    return sorted((key, tuple(tuple(point.co) for point in curve.keyframe_points))
                  for key, curve in curves(action).items())


def sample(importer, path):
    objects, actions, armature, clip = importer._import_fbx(path)
    try:
        frames = []
        for frame in range(int(round(clip.frame_range[0])), int(round(clip.frame_range[1])) + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            frames.append(engine_worlds(armature))
        return frames
    finally:
        importer._remove_imported(objects, actions)


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    importlib.import_module('stalker2_arsenal').register()
    ex = importlib.import_module('stalker2_arsenal.export_animation')
    b_fun = importlib.import_module('stalker2_arsenal.bone_functions')
    importer = ex.importer
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args[0]))
    context = bpy.context
    settings = context.scene.stalker2_animation_importer
    if len(args) > 1 and args[1]:
        settings.animation_root = args[1]
    library = bpy.path.abspath(settings.animation_root)
    clip = args[2] if len(args) > 2 else 'idle'
    rig, backup = ex.find_export_rig(context)
    assert rig and backup, 'No Arsenal export rig/backup'

    original = bpy.data.actions[clip]
    original.name = clip + '__test_original'
    original.pop('arsenal_source_action', None)
    before = {action.name: fingerprint(action) for action in bpy.data.actions}
    hidden = {collection.name: collection.hide_viewport for collection in bpy.data.collections}
    prior_action = rig.animation_data.action

    leftover = rig.pose.bones['f_index.01_master.L']
    leftover.rotation_mode = 'QUATERNION'
    leftover.rotation_quaternion = (0.9, 0.3, 0.2, 0.1)
    # Unkeyed by retargeted clips, but a parent of most of the arm controls.
    tweak = rig.pose.bones.get('tweak_spine.003')
    if tweak is not None:
        tweak.location = (0.0, 0.02, 0.01)
        tweak.rotation_mode = 'QUATERNION'
        tweak.rotation_quaternion = (0.98, 0.1, 0.1, 0.1)
    for curve in curves(prior_action).values() if prior_action else ():
        if curve.data_path.endswith('["IK_FK"]'):
            curve.mute = True
    rig.pose.bones['upper_arm_parent.L']['IK_FK'] = 0.0

    assert bpy.ops.stalker2.import_new_animations() == {'FINISHED'}
    after = {action.name: action for action in bpy.data.actions}
    added = sorted(set(after) - set(before))
    assert clip in added, f'{clip} was not imported again'
    changed = [name for name in before if name in after and fingerprint(after[name]) != before[name]]
    assert not changed, f'Existing actions changed: {changed}'
    assert not set(before) - set(after), 'Existing actions were removed'
    assert rig.animation_data.action == prior_action, 'Rig action was not restored'
    assert hidden == {c.name: c.hide_viewport for c in bpy.data.collections}, 'Collection visibility changed'
    assert not any(action.get(importer.ACTION_MARKER) for action in bpy.data.actions), 'Source actions left behind'

    for name in added:
        switches = {key: curve for key, curve in curves(after[name]).items() if key[0].endswith('["IK_FK"]')}
        assert len(switches) == len(b_fun.ik_prop_bones), f'{name}: IK/FK switches are not keyed'
        assert all(abs(curve.evaluate(1) - b_fun.IK_FK_DEFAULT) < 1e-6 for curve in switches.values()), name

    # The fresh retarget of an unedited clip reproduces the original.
    fresh, old = curves(after[clip]), curves(original)
    worst = 0.0
    first, last = (int(v) for v in original.frame_range)
    for key in set(fresh) & set(old):
        if key[0].endswith('["IK_FK"]'):
            continue
        worst = max(worst, max(abs(fresh[key].evaluate(f) - old[key].evaluate(f)) for f in range(first, last + 1)))
    assert worst < 1e-4, f'{clip}: fresh retarget differs from the original by {worst}'
    print(f'{clip}: fresh retarget matches the original (worst curve difference {worst:.2e})')

    pairs = importer._scan_library(library, settings.weapon_name)[0]
    by_key = {pair[0]: pair for pair in pairs}
    with tempfile.TemporaryDirectory(prefix='arsenal-new-animations-test-') as folder:
        weapon_only = []
        for name in added:
            outputs, status = ex.plan_export(name, '', '', pairs, settings.weapon_name, 'test', folder, library)
            assert status.startswith('Matches an original animation'), (name, status)
            if importer.stand_in_half(by_key[name]) == 'player':
                weapon_only.append((name, outputs))
        # A weapon-only clip has no character edits to make, so its export must equal the donor. A master that
        # was not evaluated while baking (it sits in a hidden collection) exports the idle instead.
        for name, outputs in weapon_only:
            action = after[name]
            written, failures = ex.run_exports(context, rig, backup, [(action, ex.rig_action_slot(action, rig), outputs)])
            assert not failures, failures
            assert len(written) == 1, written
            (_kind, template, target), = [output for output in outputs if output[2] is not None]
            donor, result = sample(importer, template), sample(importer, target)
            assert len(donor) == len(result), (name, len(donor), len(result))
            error = max(
                max((a[bone].translation - b[bone].translation).length,
                    math.degrees(angular_error(a[bone].to_quaternion(), b[bone].to_quaternion())))
                for a, b in zip(donor, result) for bone in a if bone in b)
            assert error < 0.01, f'{name}: weapon-only export differs from the donor by {error}'
            print(f'{name}: weapon-only export matches the donor ({error:.2e})')

    assert bpy.ops.stalker2.import_new_animations() == {'FINISHED'}
    assert len(bpy.data.actions) == len(after), 'Second run imported again'
    print(f'PASS: imported {len(added)} new clips: {", ".join(added)}')


if __name__ == '__main__':
    main()
