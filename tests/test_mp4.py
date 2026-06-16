"""Basic tests for tiktok-quality transform."""

from __future__ import annotations

import struct
from tiktok_quality.mp4.parser import find_box, parse_stts, parse_stsz, read_u32
from tiktok_quality.mp4.builder import build_box, build_ftyp, build_stts, build_stco, build_udta_comment


def test_build_box():
    box = build_box('test', b'\x01\x02\x03')
    assert len(box) == 11
    assert struct.unpack('>I', box[:4])[0] == 11
    assert box[4:8] == b'test'
    assert box[8:] == b'\x01\x02\x03'


def test_build_ftyp():
    ftyp = build_ftyp()
    assert len(ftyp) == 32
    assert ftyp[8:12] == b'isom'


def test_build_stts():
    stts = build_stts([(1494, 1500), (13446, 1500)])
    # header(8) + version/flags(4) + count(4) + 2*8 = 32
    assert len(stts) == 32
    assert struct.unpack('>I', stts[:4])[0] == 32


def test_build_stco():
    stco = build_stco([100, 200, 300])
    # header(8) + version/flags(4) + count(4) + 3*4 = 28
    assert len(stco) == 28


def test_build_udta_comment():
    udta = build_udta_comment('TestTag123')
    assert b'TestTag123' in udta
    assert b'\xa9cmt' in udta


def test_find_box():
    box1 = build_box('aaaa', b'\x00' * 4)
    box2 = build_box('bbbb', b'\x01' * 8)
    data = box1 + box2

    pos, size = find_box(data, 'bbbb')
    assert pos == len(box1)
    assert size == len(box2)


def test_parse_stts():
    entries = [(1494, 1500), (13446, 1500)]
    stts = build_stts(entries)
    parsed = parse_stts(stts, 0)
    assert parsed == entries


def test_parse_stsz():
    from tiktok_quality.mp4.builder import build_stsz
    sizes = [519, 145, 67, 67, 190]
    stsz = build_stsz(sizes)
    parsed = parse_stsz(stsz, 0)
    assert parsed == sizes
