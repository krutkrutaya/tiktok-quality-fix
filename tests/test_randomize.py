from tiktok_quality.randomize import (
    RandomOptions, make_filler_pool, expand_stts, compress_stts,
    jitter_durations, random_comment,
)
from tiktok_quality.detect import stco_uniqueness, size_entropy, check


def test_filler_pool_disabled_is_identical():
    opts = RandomOptions(enabled=False)
    pool = make_filler_pool(opts, 3)
    assert len(pool) == 3
    assert len(set(pool)) == 1
    assert pool[0] == b'\x00\x00\x00\x04\x00\x00\x00\x00'


def test_filler_pool_enabled_is_varied():
    opts = RandomOptions(enabled=True, seed=1)
    pool = make_filler_pool(opts, 50)
    assert len(set(pool)) > 10
    for b in pool:
        size = int.from_bytes(b[:4], 'big')
        assert size == len(b) - 4
        assert size >= 1


def test_filler_pool_reproducible_with_seed():
    a = make_filler_pool(RandomOptions(enabled=True, seed=42), 20)
    b = make_filler_pool(RandomOptions(enabled=True, seed=42), 20)
    assert a == b


def test_expand_compress_roundtrip():
    entries = [(3, 1500), (2, 1499)]
    assert compress_stts(expand_stts(entries)) == entries


def test_jitter_preserves_sum():
    opts = RandomOptions(enabled=True, seed=1, ts_jitter=2)
    src = [1500] * 100
    out = jitter_durations(src, opts)
    assert len(out) == len(src)
    assert all(d >= 1 for d in out)
    assert sum(out) == sum(src)


def test_jitter_disabled_is_identity():
    opts = RandomOptions(enabled=False)
    src = [1500] * 10
    assert jitter_durations(src, opts) == src


def test_random_comment_unique():
    a, b = random_comment(), random_comment()
    assert a != b
    assert len(a) == 16


def test_stco_uniqueness():
    assert stco_uniqueness([1, 2, 3, 4]) == 1.0
    assert stco_uniqueness([1, 1, 1, 1]) == 0.25
    assert stco_uniqueness([]) == 1.0


def test_size_entropy():
    assert size_entropy([8, 8, 8, 8]) == 0.0
    assert size_entropy([8, 16, 24, 32]) == 2.0


def test_check_flags_legacy_signature():
    fake = b'....TK8vY5VqBA6hUlo1yuGvNA....'
    res = check(fake, [1, 2, 3], [10, 20, 30])
    assert not res['ok']
    assert any('legacy signature' in f for f in res['findings'])


def test_check_flags_uniform_stco():
    res = check(b'no sig here', [100, 100, 100, 100], [10, 20, 30, 40])
    assert not res['ok']
    assert any('stco uniqueness' in f for f in res['findings'])


def test_check_ok_on_healthy_file():
    res = check(b'no sig', [10, 20, 30, 40, 50], [10, 20, 30, 40, 50, 60])
    assert res['ok']


def test_filler_pool_zero_count():
    assert make_filler_pool(RandomOptions(enabled=True, seed=0), 0) == []
    assert make_filler_pool(RandomOptions(enabled=False), 0) == []
