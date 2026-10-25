"""Rewrite the asset references inside an editor-saved .uasset without loading it in the editor.

ZoneKit's Python cannot edit montage slot data, a rebuilt montage loses its slot name and notifies, and replacing
references on /Game assets (consolidate_assets) crashes ZoneKit. A montage refers to the animation sequences it plays
only through its import table, and every import is spelled by FNames in the name table. Swapping those name strings
for the names of the mod's renamed copies therefore re-points the montage while its slot, sections and notifies
(in the export data) are left untouched.

Only the header changes size, so every absolute offset behind the name table is shifted by the size difference.
Written for the package layout of this ZoneKit (UE 5.5, FileVersionUE5 1013, single-file editor saves, no
PKG_FilterEditorOnly). Anything else raises PatchError instead of guessing, and nothing is written unless
verification of the patched bytes succeeds. Pure Python: no unreal or bpy imports.
"""

import os
import shutil
import stat
import struct

TAG = 0x9E2A83C1
SUPPORTED_UE5 = (1012, 1013, 1014, 1015)


class PatchError(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def i32(self):
        value = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return value

    def u32(self):
        value = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return value

    def i64(self):
        value = struct.unpack_from('<q', self.data, self.pos)[0]
        self.pos += 8
        return value

    def skip(self, count):
        self.pos += count

    def fstring(self):
        length = self.i32()
        if length == 0:
            return ''
        if length < 0:
            raw = self.data[self.pos:self.pos + (-length) * 2 - 2]
            self.pos += -length * 2
            return raw.decode('utf-16le')
        raw = self.data[self.pos:self.pos + length - 1]
        self.pos += length
        return raw.decode('latin-1')


def encode_fstring(text):
    if text == '':
        return struct.pack('<i', 0)
    try:
        raw = text.encode('ascii')
        return struct.pack('<i', len(raw) + 1) + raw + b'\0'
    except UnicodeEncodeError:
        raw = text.encode('utf-16le')
        return struct.pack('<i', -(len(raw) // 2 + 1)) + raw + b'\0\0'


def _crc_table():
    table = []
    for index in range(256):
        value = index << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if value & 0x80000000 else (value << 1) & 0xFFFFFFFF
        table.append(value)
    return table


_TABLE = _crc_table()


def name_hashes(text):
    """The two 16-bit hashes UE stores after each name. The first (case-insensitive) matches UE's own files; UE
    does not read either on load, so the second is a best effort."""
    non_case = 0
    case = 0
    for char in text:
        upper = ord(char.upper()) if len(char.upper()) == 1 else ord(char)
        non_case = ((non_case >> 8) & 0x00FFFFFF) ^ _TABLE[(non_case ^ (upper & 0xFF)) & 0xFF]
        case = ((case >> 8) & 0x00FFFFFF) ^ _TABLE[(case ^ (ord(char) & 0xFF)) & 0xFF]
    return non_case & 0xFFFF, case & 0xFFFF


class Package:
    """Parsed header: just enough to rename names and keep the offsets consistent."""

    OFFSET_FIELDS = ('total_header', 'soft_object_paths_offset', 'gatherable_offset', 'export_offset',
                     'import_offset', 'depends_offset', 'soft_package_offset', 'searchable_offset',
                     'thumbnail_offset', 'asset_registry_offset', 'bulk_data_offset', 'world_tile_offset',
                     'preload_offset', 'payload_toc_offset', 'data_resource_offset')

    def __init__(self, data):
        self.data = bytes(data)
        self.fields = {}
        self.parse()

    def field(self, name, reader, kind='i32'):
        position = reader.pos
        value = reader.i64() if kind == 'i64' else reader.i32()
        self.fields[name] = (position, kind, value)
        return value

    def parse(self):
        reader = Reader(self.data)
        if reader.u32() != TAG:
            raise PatchError('Not a package file (bad tag)')
        legacy = reader.i32()
        if legacy != -8:
            raise PatchError(f'Unsupported legacy file version {legacy}')
        reader.skip(4)
        self.ue4 = reader.i32()
        self.ue5 = reader.i32()
        reader.i32()
        if self.ue5 not in SUPPORTED_UE5:
            raise PatchError(f'Unsupported UE5 package version {self.ue5}')
        for _ in range(reader.i32()):
            reader.skip(20)
        self.field('total_header', reader)
        reader.fstring()
        self.package_flags = reader.u32()
        if self.package_flags & 0x80000000:
            raise PatchError('Package is filtered for editor-only data; not an editor-saved asset')
        self.name_count = self.field('name_count', reader)
        self.field('name_offset', reader)
        self.field('soft_object_paths_count', reader)
        self.field('soft_object_paths_offset', reader)
        reader.fstring()
        self.field('gatherable_count', reader)
        self.field('gatherable_offset', reader)
        self.field('export_count', reader)
        self.field('export_offset', reader)
        self.field('import_count', reader)
        self.field('import_offset', reader)
        if self.ue5 >= 1015:
            reader.skip(16)
        if self.ue5 >= 1014:
            self.field('metadata_offset', reader)
        self.field('depends_offset', reader)
        self.field('soft_package_count', reader)
        self.field('soft_package_offset', reader)
        self.field('searchable_offset', reader)
        self.field('thumbnail_offset', reader)
        reader.skip(16)
        reader.skip(16)
        for _ in range(reader.i32()):
            reader.skip(8)
        for _ in range(2):
            reader.skip(6)
            reader.skip(4)
            reader.fstring()
        reader.skip(4)
        if reader.i32() != 0:
            raise PatchError('Compressed chunks are not supported')
        reader.skip(4)
        for _ in range(reader.i32()):
            reader.fstring()
        self.field('asset_registry_offset', reader)
        self.field('bulk_data_offset', reader, 'i64')
        self.field('world_tile_offset', reader)
        for _ in range(reader.i32()):
            reader.skip(4)
        self.field('preload_count', reader)
        self.field('preload_offset', reader)
        reader.skip(4)
        self.field('payload_toc_offset', reader, 'i64')
        self.field('data_resource_offset', reader)
        self.summary_end = reader.pos
        if self.summary_end != self.value('name_offset'):
            raise PatchError(f'Summary layout mismatch: parsed to {self.summary_end}, '
                             f'name table at {self.value("name_offset")}')
        self.parse_names()
        self.parse_tables()
        self.parse_inner_offsets()

    def parse_inner_offsets(self):
        """Absolute file offsets stored inside header sections: the thumbnail table entries and the asset
        registry section's DependencyDataOffset."""
        reader = Reader(self.data)
        self.inner_offsets = []
        if self.value('thumbnail_offset'):
            reader.pos = self.value('thumbnail_offset')
            for _ in range(reader.i32()):
                reader.fstring()
                reader.fstring()
                self.inner_offsets.append((reader.pos, 'i32', reader.i32()))
            if reader.pos != self.value('asset_registry_offset'):
                raise PatchError('Thumbnail table does not end where the asset registry data starts')
        reader.pos = self.value('asset_registry_offset')
        self.inner_offsets.append((reader.pos, 'i64', reader.i64()))

    def value(self, name):
        return self.fields[name][2]

    def parse_names(self):
        reader = Reader(self.data)
        reader.pos = self.value('name_offset')
        self.names = []
        for _ in range(self.value('name_count')):
            text = reader.fstring()
            reader.skip(4)
            self.names.append(text)
        self.names_end = reader.pos

    def parse_tables(self):
        count = self.value('import_count')
        start = self.value('import_offset')
        size = (self.value('export_offset') - start) // count if count else 0
        if count and (self.value('export_offset') - start) % count:
            raise PatchError('Import table size is not a whole number of entries')
        self.imports = []
        reader = Reader(self.data)
        for index in range(count):
            reader.pos = start + index * size
            class_package, _n1 = reader.i32(), reader.i32()
            class_name, _n2 = reader.i32(), reader.i32()
            outer = reader.i32()
            object_name, _n3 = reader.i32(), reader.i32()
            self.imports.append({'class': self.names[class_name], 'outer': outer,
                                 'name': self.names[object_name], 'name_index': object_name})
        count = self.value('export_count')
        start = self.value('export_offset')
        end = self.value('depends_offset')
        size = (end - start) // count if count else 0
        if count and (end - start) % count:
            raise PatchError('Export table size is not a whole number of entries')
        self.export_size = size
        self.export_start = start
        self.exports = []
        for index in range(count):
            reader.pos = start + index * size + 28
            serial_size = reader.i64()
            serial_offset = reader.i64()
            self.exports.append({'size': serial_size, 'offset': serial_offset, 'at': reader.pos - 8})

    def used_name_indexes(self):
        return {entry['name_index'] for entry in self.imports}

    def referenced_packages(self):
        """(package path, [object names]) for every import that is a package, with its children."""
        found = []
        for index, entry in enumerate(self.imports):
            if entry['outer'] == 0 and entry['class'] == 'Package':
                children = [other['name'] for other in self.imports if other['outer'] == -(index + 1)]
                found.append((entry['name'], children))
        return found

    def rename(self, mapping):
        """Return new bytes with every name string in mapping replaced. Raises when nothing would change."""
        changed = {index: mapping[text] for index, text in enumerate(self.names) if text in mapping}
        if not changed:
            return self.data, 0
        rebuilt = bytearray()
        new_names = list(self.names)
        for index, text in enumerate(self.names):
            if index in changed:
                text = changed[index]
                new_names[index] = text
            rebuilt += encode_fstring(text) + struct.pack('<HH', *name_hashes(text))
        old_start = self.value('name_offset')
        old_end = self.names_end
        delta = len(rebuilt) - (old_end - old_start)
        out = bytearray(self.data[:old_start] + rebuilt + self.data[old_end:])
        if delta:
            self.shift_offsets(out, old_end, delta)
        return bytes(out), len(changed)

    def shift_offsets(self, out, cut, delta):
        for name, (position, kind, value) in self.fields.items():
            if name not in self.OFFSET_FIELDS or value < cut:
                continue
            if kind == 'i64':
                struct.pack_into('<q', out, position, value + delta)
            else:
                struct.pack_into('<i', out, position, value + delta)
        for entry in self.exports:
            if entry['offset'] >= cut:
                struct.pack_into('<q', out, entry['at'] + delta, entry['offset'] + delta)
        for position, kind, value in self.inner_offsets:
            if value >= cut:
                struct.pack_into('<q' if kind == 'i64' else '<i', out, position + delta, value + delta)


def verify(original, patched, mapping):
    """Re-parse the patched bytes and check that it is the same package with only the intended names changed."""
    before = Package(original)
    after = Package(patched)
    if len(patched) != len(original) + (after.names_end - before.names_end):
        raise PatchError('File size does not match the name table size change')
    if after.value('total_header') != before.value('total_header') + (after.names_end - before.names_end):
        raise PatchError('Header size was not updated')
    for old, new in zip(before.names, after.names):
        if old != new and mapping.get(old) != new:
            raise PatchError(f'Unexpected name change {old!r} -> {new!r}')
    delta = after.names_end - before.names_end
    for a, b in zip(before.inner_offsets, after.inner_offsets):
        if b[2] != a[2] + (delta if a[2] >= before.names_end else 0):
            raise PatchError('Thumbnail / asset registry offsets are inconsistent')
    for name in Package.OFFSET_FIELDS:
        if name in before.fields:
            old, new = before.value(name), after.value(name)
            if new != old + (delta if old >= before.names_end else 0):
                raise PatchError(f'Offset {name} is inconsistent')
    for a, b in zip(before.exports, after.exports):
        if a['size'] != b['size'] or b['offset'] != a['offset'] + (delta if a['offset'] >= before.names_end else 0):
            raise PatchError('Export offsets are inconsistent')
        if patched[b['offset']:b['offset'] + b['size']] != original[a['offset']:a['offset'] + a['size']]:
            raise PatchError('Export data changed')
    return after


def patch_file(path, mapping, backup_dir=None, write=True):
    """Apply a {old name: new name} mapping to one .uasset. Returns the number of names changed.

    backup_dir: where to keep a one-time copy of the original (never inside the mod's Content, which is packaged)."""
    with open(path, 'rb') as handle:
        original = handle.read()
    package = Package(original)
    patched, changed = package.rename(mapping)
    if not changed:
        return 0
    verify(original, patched, mapping)
    if write:
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            target = os.path.join(backup_dir, os.path.basename(path) + '.bak')
            if not os.path.exists(target):
                shutil.copy2(path, target)
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        with open(path, 'wb') as handle:
            handle.write(patched)
    return changed


def describe(path):
    package = Package(open(path, 'rb').read())
    lines = [f'{path}', f'  UE5 version {package.ue5}, {len(package.names)} names, {len(package.imports)} imports, '
                        f'{len(package.exports)} exports, header {package.value("total_header")} bytes']
    for name, children in package.referenced_packages():
        lines.append(f'  imports {name}: {", ".join(children)}')
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    for argument in sys.argv[1:]:
        print(describe(argument))
