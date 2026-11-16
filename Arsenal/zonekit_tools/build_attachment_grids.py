"""Build resources/attachment_grids.json: the inventory grid of every attachment that is not 1x1.

python build_attachment_grids.py X:\\STALKER2ZoneKit\\Stalker2\\Content\\GameLite\\GameData
Standalone inventory icons follow this grid, so a custom attachment inherits its template's icon size.
"""
import json
from pathlib import Path
import sys

from build_upgrade_defaults import parse, resolve

DESTINATION = Path(__file__).parents[1] / 'stalker2_arsenal' / 'resources' / 'attachment_grids.json'


def build(game_data, destination=DESTINATION):
    blocks = parse(game_data / 'ItemPrototypes.cfg')
    attachments = parse(game_data / 'ItemPrototypes' / 'AttachPrototypes.cfg')
    blocks.update(attachments)
    grids = {}
    for sid in attachments:
        block = resolve(blocks, sid)
        size = [int(block.get('ItemGridWidth', 1)), int(block.get('ItemGridHeight', 1))]
        if size != [1, 1]:
            grids[sid] = size
    destination.write_text(json.dumps(dict(sorted(grids.items())), indent=1) + '\n', encoding='utf-8')
    return grids


if __name__ == '__main__':
    print(f'{len(build(Path(sys.argv[1])))} attachments larger than 1x1')
