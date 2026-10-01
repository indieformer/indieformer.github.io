#!/usr/bin/env python3
"""Self-check for build_notes.reap_orphan_posts. It deletes directories on the
live site, so it gets a test. Run with: python3 scripts/test_reap.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_notes import reap_orphan_posts, INDEX_DIRS  # noqa: E402


def make_notes(tmp, slugs):
    """Build a notes/ tree with a page per slug, plus the index dirs."""
    root = os.path.join(tmp, "notes")
    for d in list(slugs) + [d for d in INDEX_DIRS if d != "notes"]:
        os.makedirs(os.path.join(root, d), exist_ok=True)
        open(os.path.join(root, d, "index.html"), "w").close()
    return root


def test_removes_renamed_slug():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_notes(tmp, ["82-s-s", "82-we-keep-2-of-every-15-sale", "84-x"])
        manifest = {"82-s-s": {}, "82-we-keep-2-of-every-15-sale": {}, "84-x": {}}
        n = reap_orphan_posts({"82-we-keep-2-of-every-15-sale", "84-x"}, manifest, root)
        assert n == 1, n
        assert not os.path.exists(os.path.join(root, "82-s-s"))
        assert os.path.exists(os.path.join(root, "82-we-keep-2-of-every-15-sale"))
        assert "82-s-s" not in manifest
        assert set(manifest) == {"82-we-keep-2-of-every-15-sale", "84-x"}


def test_never_touches_index_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_notes(tmp, ["84-x"])
        reap_orphan_posts({"84-x"}, {"84-x": {}}, root)
        for d in INDEX_DIRS:
            if d == "notes":
                continue
            assert os.path.exists(os.path.join(root, d)), d


def test_circuit_breaker_stops_a_bad_listing():
    """An empty or truncated API listing must not wipe the archive."""
    with tempfile.TemporaryDirectory() as tmp:
        slugs = [f"post-{i}" for i in range(20)]
        root = make_notes(tmp, slugs)
        manifest = {s: {} for s in slugs}
        n = reap_orphan_posts(set(), manifest, root)
        assert n == 0, n
        assert len(os.listdir(root)) == len(slugs) + len([d for d in INDEX_DIRS if d != "notes"])
        assert len(manifest) == 20


def test_noop_when_everything_is_live():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_notes(tmp, ["a", "b"])
        manifest = {"a": {}, "b": {}}
        assert reap_orphan_posts({"a", "b"}, manifest, root) == 0
        assert len(manifest) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all good")
