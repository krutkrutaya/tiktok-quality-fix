"""
patcher.py
----------
Recursive ISOBMFF box-walker and binary patch utilities for CompressBase.
Handles:
  1. ftyp box rewrite (major_brand=isom, minor_version=512, brands=isom,iso2,avc1,mp41)
  2. Recursive zeroing of creation_time and modification_time in mvhd/tkhd/mdhd
  3. Binary find/replace of Lavf encoder tag to Lavf59.27.100
  4. Insertion of Pascal-length byte in hdlr names (VideoHandler, SoundHandler) with
     full moov chunk offset recalculation (stco/co64)
  5. Audio track 2 sample inflation (nb_frames x10) via stsz/stts/stsc table rebuilding
"""

from __future__ import annotations

import re
import struct
from typing import Optional, List, Tuple


# ---------------------------------------------------------------------------
# Low-level box primitives
# ---------------------------------------------------------------------------

def read_box_header(data: bytes, offset: int) -> Optional[Tuple[int, str, int]]:
    """Return (size, fourcc, header_len) at given offset, or None at EOF."""
    if offset + 8 > len(data):
        return None
    size = struct.unpack_from(">I", data, offset)[0]
    fourcc = data[offset + 4: offset + 8].decode("latin-1")
    header_len = 8
    if size == 1:
        if offset + 16 > len(data):
            return None
        size = struct.unpack_from(">Q", data, offset + 8)[0]
        header_len = 16
    elif size == 0:
        size = len(data) - offset
    return size, fourcc, header_len


def iter_boxes(data: bytes, start: int = 0, end: Optional[int] = None):
    """Yield (offset, size, fourcc, header_len) for each box in range."""
    if end is None:
        end = len(data)
    offset = start
    while offset < end:
        result = read_box_header(data, offset)
        if result is None:
            break
        size, fourcc, header_len = result
        if size < header_len:
            break
        yield offset, size, fourcc, header_len
        offset += size


# ---------------------------------------------------------------------------
# ftyp rewrite
# ---------------------------------------------------------------------------

def build_ftyp(major_brand: str, minor_version: int, compatible_brands: List[str]) -> bytes:
    """Build a serialized ftyp box."""
    major = major_brand.encode("latin-1").ljust(4)[:4]
    mv = struct.pack(">I", minor_version)
    compat = b"".join(b.encode("latin-1").ljust(4)[:4] for b in compatible_brands)
    payload = major + mv + compat
    size = 8 + len(payload)
    return struct.pack(">I", size) + b"ftyp" + payload


def patch_ftyp(
    data: bytearray,
    major_brand: str = "isom",
    minor_version: int = 512,
    compatible_brands: Optional[List[str]] = None,
) -> bytearray:
    """Replace existing ftyp box or prepend a new one."""
    if compatible_brands is None:
        compatible_brands = ["isom", "iso2", "avc1", "mp41"]

    raw = bytes(data)
    for offset, size, fourcc, _ in iter_boxes(raw):
        if fourcc == "ftyp":
            new_ftyp = build_ftyp(major_brand, minor_version, compatible_brands)
            result = bytearray()
            result += data[:offset]
            result += new_ftyp
            result += data[offset + size:]
            return result

    new_ftyp = build_ftyp(major_brand, minor_version, compatible_brands)
    return bytearray(new_ftyp) + data


# ---------------------------------------------------------------------------
# creation_time zeroing
# ---------------------------------------------------------------------------

CREATION_TIME_BOXES = {"mvhd", "tkhd", "mdhd"}


def _zero_creation_time_in_fullbox(data: bytearray, offset: int, fourcc: str):
    """Zero creation_time and modification_time in mvhd/tkhd/mdhd."""
    box_start = offset
    result = read_box_header(bytes(data), offset)
    if result is None:
        return
    size, _, header_len = result
    full_offset = box_start + header_len
    if full_offset + 4 > len(data):
        return
    version = data[full_offset]
    times_offset = full_offset + 4
    if version == 1:
        if times_offset + 16 <= len(data):
            struct.pack_into(">Q", data, times_offset, 0)
            struct.pack_into(">Q", data, times_offset + 8, 0)
    else:
        if times_offset + 8 <= len(data):
            struct.pack_into(">I", data, times_offset, 0)
            struct.pack_into(">I", data, times_offset + 4, 0)


def _walk_and_zero_times(data: bytearray, start: int, end: int):
    """Recursively walk boxes and zero creation/modification times."""
    for offset, size, fourcc, header_len in iter_boxes(bytes(data), start, end):
        if fourcc in CREATION_TIME_BOXES:
            _zero_creation_time_in_fullbox(data, offset, fourcc)
        if fourcc in ("moov", "trak", "mdia", "minf", "stbl", "udta", "edts",
                      "dinf", "meta", "ilst"):
            _walk_and_zero_times(data, offset + header_len, offset + size)


def zero_creation_times(data: bytearray) -> bytearray:
    """Zero all creation_time and modification_time fields recursively in-place."""
    _walk_and_zero_times(data, 0, len(data))
    return data


# ---------------------------------------------------------------------------
# Binary find/replace for encoder tag
# ---------------------------------------------------------------------------

_ENCODER_RE = re.compile(rb"Lavf\d{2}\.\d{1,3}\.\d{1,3}")


def fix_encoder_tag(data: bytearray, target: bytes = b"Lavf59.27.100") -> bytearray:
    """
    In-place binary replacement of the Lavf encoder version string.
    Ensures container atom sizes remain intact.
    """
    matches = list(_ENCODER_RE.finditer(data))
    if not matches:
        return data
    for m in matches:
        found = m.group(0)
        if found == target:
            continue
        if len(found) != len(target):
            continue
        data[m.start():m.end()] = target
    return data


# ---------------------------------------------------------------------------
# Recursive ISOBMFF tree parser
# ---------------------------------------------------------------------------

CONTAINER_TYPES = {
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"edts", b"dinf",
}

HANDLER_NAMES = (b"VideoHandler", b"SoundHandler")


class Box:
    __slots__ = ("type", "children", "payload")

    def __init__(self, box_type: bytes):
        self.type = box_type
        self.children: Optional[List[Box]] = None
        self.payload: Optional[bytes] = None

    def serialize(self) -> bytes:
        if self.children is not None:
            body = b"".join(c.serialize() for c in self.children)
        else:
            body = self.payload or b""
        size = 8 + len(body)
        return struct.pack(">I4s", size, self.type) + body


def parse_boxes(data: bytes, start: int, end: int) -> List[Box]:
    """Parse boxes recursively into a tree structure."""
    boxes: List[Box] = []
    pos = start
    while pos < end:
        if pos + 8 > end:
            break
        size, box_type = struct.unpack(">I4s", data[pos:pos + 8])
        header_len = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header_len = 16
        if size == 0:
            size = end - pos
        box_start = pos + header_len
        box_end = pos + size
        b = Box(box_type)
        if box_type in CONTAINER_TYPES:
            b.children = parse_boxes(data, box_start, box_end)
        else:
            b.payload = data[box_start:box_end]
        boxes.append(b)
        pos = box_end
    return boxes


def find_box(boxes: List[Box], box_type: bytes) -> Box:
    """Find the first box with matching box_type."""
    for b in boxes:
        if b.type == box_type:
            return b
    raise KeyError(f"Box {box_type.decode('latin-1', errors='replace')} not found")


def find_all_boxes_by_type(boxes: List[Box], box_type: bytes) -> List[Box]:
    """Recursively find all boxes of a given type."""
    found = []
    for b in boxes:
        if b.type == box_type:
            found.append(b)
        if b.children is not None:
            found.extend(find_all_boxes_by_type(b.children, box_type))
    return found


def shift_all_chunk_offsets(top_boxes: List[Box], delta: int) -> None:
    """Add delta to all absolute offsets in stco and co64 across entire moov tree."""
    moov = find_box(top_boxes, b"moov")
    if moov.children is None:
        return

    for stco in find_all_boxes_by_type(moov.children, b"stco"):
        if stco.payload is None or len(stco.payload) < 8:
            continue
        entry_count = struct.unpack(">I", stco.payload[4:8])[0]
        expected_len = 8 + 4 * entry_count
        if len(stco.payload) < expected_len:
            continue
        offsets = list(struct.unpack(f">{entry_count}I", stco.payload[8:expected_len]))
        offsets = [o + delta for o in offsets]
        stco.payload = struct.pack(">II", 0, entry_count) + struct.pack(f">{entry_count}I", *offsets)

    for co64 in find_all_boxes_by_type(moov.children, b"co64"):
        if co64.payload is None or len(co64.payload) < 8:
            continue
        entry_count = struct.unpack(">I", co64.payload[4:8])[0]
        expected_len = 8 + 8 * entry_count
        if len(co64.payload) < expected_len:
            continue
        offsets = list(struct.unpack(f">{entry_count}Q", co64.payload[8:expected_len]))
        offsets = [o + delta for o in offsets]
        co64.payload = struct.pack(">II", 0, entry_count) + struct.pack(f">{entry_count}Q", *offsets)


# ---------------------------------------------------------------------------
# Handler names patch
# ---------------------------------------------------------------------------

def patch_hdlr_box(b: Box) -> bool:
    """Insert Pascal-length byte before handler name if not already present."""
    if b.type != b"hdlr" or b.payload is None:
        return False
    payload = b.payload
    fixed_header_len = 1 + 3 + 4 + 4 + 12
    if len(payload) <= fixed_header_len:
        return False
    name = payload[fixed_header_len:]
    name_stripped = name.rstrip(b"\x00")
    for hn in HANDLER_NAMES:
        if name_stripped == hn:
            new_name = bytes([len(hn)]) + hn
            b.payload = payload[:fixed_header_len] + new_name
            return True
        if name_stripped == bytes([len(hn)]) + hn:
            return False
    return False


def walk_and_patch_hdlr(boxes: List[Box]) -> bool:
    """Walk tree and patch any hdlr boxes."""
    changed = False
    for b in boxes:
        if b.type == b"hdlr":
            if patch_hdlr_box(b):
                changed = True
        elif b.children is not None:
            if walk_and_patch_hdlr(b.children):
                changed = True
    return changed


def patch_handler_names(data: bytearray) -> bytearray:
    """
    Patch handler_name in hdlr boxes with Pascal-length byte,
    and adjust all stco/co64 chunk offsets for the moov growth.
    """
    top_boxes = parse_boxes(bytes(data), 0, len(data))
    try:
        moov_before = find_box(top_boxes, b"moov")
    except KeyError:
        return data

    size_before = len(moov_before.serialize())
    changed = walk_and_patch_hdlr(top_boxes)
    if changed:
        size_after = len(find_box(top_boxes, b"moov").serialize())
        delta = size_after - size_before
        if delta:
            shift_all_chunk_offsets(top_boxes, delta)
        new_data = b"".join(b.serialize() for b in top_boxes)
        return bytearray(new_data)
    return data


# ---------------------------------------------------------------------------
# Inflate nb_frames on second audio track (x10)
# ---------------------------------------------------------------------------

def _split_evenly(total: int, parts: int) -> List[int]:
    """Split total into parts integers as evenly as possible."""
    base = total // parts
    rem = total % parts
    return [base + 1] * rem + [base] * (parts - rem)


def _parse_stts(payload: bytes) -> List[Tuple[int, int]]:
    entry_count = struct.unpack(">I", payload[4:8])[0]
    entries = []
    off = 8
    for _ in range(entry_count):
        cnt, delta = struct.unpack(">II", payload[off:off + 8])
        entries.append((cnt, delta))
        off += 8
    return entries


def _build_stts(entries: List[Tuple[int, int]]) -> bytes:
    out = bytearray(struct.pack(">II", 0, len(entries)))
    for cnt, delta in entries:
        out += struct.pack(">II", cnt, delta)
    return bytes(out)


def _parse_stsz(payload: bytes) -> Tuple[int, List[int]]:
    sample_size, sample_count = struct.unpack(">II", payload[4:12])
    if sample_size != 0:
        return sample_size, [sample_size] * sample_count
    sizes = list(struct.unpack(f">{sample_count}I", payload[12:12 + 4 * sample_count]))
    return 0, sizes


def _build_stsz(sizes: List[int]) -> bytes:
    out = bytearray(struct.pack(">III", 0, 0, len(sizes)))
    out += struct.pack(f">{len(sizes)}I", *sizes)
    return bytes(out)


def _parse_stsc(payload: bytes) -> List[Tuple[int, int, int]]:
    entry_count = struct.unpack(">I", payload[4:8])[0]
    entries = []
    off = 8
    for _ in range(entry_count):
        first_chunk, samples_per_chunk, sdi = struct.unpack(">III", payload[off:off + 12])
        entries.append((first_chunk, samples_per_chunk, sdi))
        off += 12
    return entries


def _build_stsc(entries: List[Tuple[int, int, int]]) -> bytes:
    out = bytearray(struct.pack(">II", 0, len(entries)))
    for fc, spc, sdi in entries:
        out += struct.pack(">III", fc, spc, sdi)
    return bytes(out)


def inflate_second_audio_track(top_boxes: List[Box], multiplier: int = 10) -> bool:
    """Find second audio track and inflate its sample count."""
    try:
        moov = find_box(top_boxes, b"moov")
    except KeyError:
        return False
    if moov.children is None:
        return False

    audio_traks = []
    for b in moov.children:
        if b.type == b"trak" and b.children is not None:
            try:
                mdia = find_box(b.children, b"mdia")
                if mdia.children is not None:
                    hdlr = find_box(mdia.children, b"hdlr")
                    if hdlr.payload and hdlr.payload[8:12] == b"soun":
                        audio_traks.append(b)
            except KeyError:
                continue

    if len(audio_traks) < 2:
        return False

    trak2 = audio_traks[1]
    if trak2.children is None:
        return False
    mdia = find_box(trak2.children, b"mdia")
    if mdia.children is None:
        return False
    minf = find_box(mdia.children, b"minf")
    if minf.children is None:
        return False
    stbl = find_box(minf.children, b"stbl")
    if stbl.children is None:
        return False

    stts_box = find_box(stbl.children, b"stts")
    stsz_box = find_box(stbl.children, b"stsz")
    stsc_box = find_box(stbl.children, b"stsc")
    stco_box = find_box(stbl.children, b"stco")

    if not (stts_box.payload and stsz_box.payload and stsc_box.payload and stco_box.payload):
        return False

    stco_count = struct.unpack(">I", stco_box.payload[4:8])[0]
    _, sizes = _parse_stsz(stsz_box.payload)
    if stco_count != len(sizes):
        return False

    stts_entries = _parse_stts(stts_box.payload)
    deltas = []
    for cnt, delta in stts_entries:
        deltas.extend([delta] * cnt)
    if len(deltas) != len(sizes):
        return False

    n = len(sizes)
    last_is_leftover = len(stts_entries) >= 2 and stts_entries[-1][0] == 1
    n_inflate = n - 1 if last_is_leftover else n

    new_sizes: List[int] = []
    new_deltas: List[int] = []
    for i in range(n_inflate):
        sub_sizes = [sizes[i]] + [0] * (multiplier - 1)
        sub_deltas = _split_evenly(deltas[i], multiplier)
        new_sizes.extend(sub_sizes)
        new_deltas.extend(sub_deltas)
    if last_is_leftover:
        new_sizes.append(sizes[-1])
        new_deltas.append(deltas[-1])

    stsz_box.payload = _build_stsz(new_sizes)

    stts_entries_new = []
    cur_delta, cur_count = new_deltas[0], 0
    for d in new_deltas:
        if d == cur_delta:
            cur_count += 1
        else:
            stts_entries_new.append((cur_count, cur_delta))
            cur_delta, cur_count = d, 1
    stts_entries_new.append((cur_count, cur_delta))
    stts_box.payload = _build_stts(stts_entries_new)

    new_stsc_entries = [(1, multiplier, 1)]
    if last_is_leftover:
        new_stsc_entries.append((n_inflate + 1, 1, 1))
    stsc_box.payload = _build_stsc(new_stsc_entries)

    return True


def inflate_audio2_nb_frames(data: bytearray, multiplier: int = 10) -> bytearray:
    """Inflate nb_frames on second audio track by patching stsz/stts/stsc."""
    top_boxes = parse_boxes(bytes(data), 0, len(data))
    try:
        moov_before = find_box(top_boxes, b"moov")
    except KeyError:
        return data

    size_before = len(moov_before.serialize())
    changed = inflate_second_audio_track(top_boxes, multiplier)
    if not changed:
        return data

    size_after = len(find_box(top_boxes, b"moov").serialize())
    delta = size_after - size_before
    if delta:
        shift_all_chunk_offsets(top_boxes, delta)

    new_data = b"".join(b.serialize() for b in top_boxes)
    return bytearray(new_data)


# ---------------------------------------------------------------------------
# Full patch pipeline
# ---------------------------------------------------------------------------

def apply_isobmff_patches(
    input_path: str,
    output_path: str,
    major_brand: str = "isom",
    minor_version: int = 512,
    compatible_brands: Optional[List[str]] = None,
    remove_creation_time: bool = True,
    encoder: str = "Lavf59.27.100",
    audio_multiplier: int = 10,
) -> None:
    """
    Apply full CompressBase binary ISOBMFF patches:
      1. Rewrite ftyp box with target brands (isom, iso2, avc1, mp41)
      2. Zero all creation_time / modification_time fields in mvhd/tkhd/mdhd
      3. Fix encoder tag via binary find/replace to target Lavf version
      4. Patch handler names with Pascal-length prefix and adjust chunk offsets
      5. Inflate nb_frames on second audio track (multiplier x10)
    """
    if compatible_brands is None:
        compatible_brands = ["isom", "iso2", "avc1", "mp41"]

    with open(input_path, "rb") as f:
        data = bytearray(f.read())

    # 1. Rewrite ftyp
    data = patch_ftyp(
        data,
        major_brand=major_brand,
        minor_version=minor_version,
        compatible_brands=compatible_brands,
    )

    # 2. Zero creation / modification times
    if remove_creation_time:
        data = zero_creation_times(data)

    # 3. Fix encoder tag in-place
    data = fix_encoder_tag(data, target=encoder.encode("latin-1"))

    # 4. Patch handler names and shift moov offsets
    data = patch_handler_names(data)

    # 5. Inflate nb_frames on second audio track
    if audio_multiplier > 1:
        data = inflate_audio2_nb_frames(data, multiplier=audio_multiplier)

    with open(output_path, "wb") as f:
        f.write(data)


def dump_boxes(data: bytes, start: int = 0, end: Optional[int] = None, depth: int = 0) -> List[str]:
    """Human-readable dump of box tree."""
    lines = []
    if end is None:
        end = len(data)
    containers = {"moov", "trak", "mdia", "minf", "stbl", "udta", "edts", "dinf", "meta", "ilst"}
    for offset, size, fourcc, header_len in iter_boxes(data, start, end):
        lines.append("  " * depth + f"[{fourcc}] offset={offset} size={size}")
        if fourcc in containers:
            lines.extend(dump_boxes(data, offset + header_len, offset + size, depth + 1))
    return lines
