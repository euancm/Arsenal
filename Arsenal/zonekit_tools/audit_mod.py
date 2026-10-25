"""Offline audit of a generated weapon mod: dangling references and leftover template references.

    python audit_mod.py <ModFolder> [template-token]

Example: python audit_mod.py X:\\...\\Mods\\JellyfishMod udp
"""
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'stalker2_arsenal'))
import uasset_patch as patcher  # noqa: E402


def main():
    mod_dir = sys.argv[1]
    token = (sys.argv[2] if len(sys.argv) > 2 else 'udp').lower()
    mod = os.path.basename(mod_dir.rstrip('\\/'))
    root = os.path.join(mod_dir, 'Content')
    files = {}
    for path in glob.glob(root + '\\**\\*.uasset', recursive=True):
        rel = os.path.relpath(path, root)[:-len('.uasset')].replace(os.sep, '/')
        files['/%s/%s' % (mod, rel)] = path
    dangling = collections.defaultdict(set)
    template = collections.defaultdict(set)
    skipped = []
    for package, path in sorted(files.items()):
        try:
            with open(path, 'rb') as handle:
                parsed = patcher.Package(handle.read())
        except Exception as error:
            skipped.append((package, str(error)))
            continue
        for name, _children in parsed.referenced_packages():
            if name.startswith('/' + mod + '/') and name not in files:
                dangling[package].add(name)
            elif name.startswith('/Game/') and token in name.lower():
                template[package].add(name)
    print('%d packages in %s' % (len(files), mod))
    for package, names in dangling.items():
        print('DANGLING  %s -> %s' % (package, sorted(names)))
    for package, names in template.items():
        print('TEMPLATE  %s -> %d refs, e.g. %s' % (package.split('/')[-1], len(names), sorted(names)[:2]))
    for package, reason in skipped:
        print('SKIPPED   %s (%s)' % (package, reason))


if __name__ == '__main__':
    main()
