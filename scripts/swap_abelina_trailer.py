#!/usr/bin/env python3
"""
Put the Abelina announcement trailer live on the site and the press kit.

One-off, written to run from .github/workflows/abelina-trailer.yml at 18:00 UTC
on 16 Oct 2026, which is 05:00 Saturday 17 Oct in Melbourne, when the MIX
showcase finishes.

It does three things rather than a bare id swap:

  1. abelina/index.html   the gameplay section becomes the trailer section. The
     old embed was a muted looping background with data-loop-fade on it, which
     is wrong for an announcement trailer. It becomes an ordinary player with
     sound, started by the viewer.
  2. abelina/index.html   the heading stops saying "Current gameplay footage".
  3. abelina/presskit/    the trailer section added ahead of time swaps its id.

Safe to run twice. If the new id is already in place it reports that and exits
0, so a re-run or a manual dispatch after the fact cannot damage anything.
Exits 1 only if a file is in a shape it did not expect, so a silent half-swap
is not possible.
"""
import sys

OLD = "tENYi25be7k"
NEW = "0xNoDMOlQYo"
TITLE = "Abelina — Official Announcement Trailer"

PAGE = "abelina/index.html"
KIT = "abelina/presskit/index.html"

# ── the page: whole block, because the embed's behaviour changes too ──
PAGE_OLD = (
    '  <h2 class="sec">Current gameplay <em>footage.</em></h2>\n'
    '  <div class="video-frame">\n'
    f'    <iframe data-loop-fade src="https://www.youtube.com/embed/{OLD}'
    f'?enablejsapi=1&autoplay=1&mute=1&loop=1&playlist={OLD}'
    '&rel=0&modestbranding=1&playsinline=1" title="Abelina — gameplay footage"'
    ' allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope;'
    ' picture-in-picture" allowfullscreen loading="lazy"></iframe>'
)
PAGE_NEW = (
    '  <h2 class="sec">The announcement <em>trailer.</em></h2>\n'
    '  <div class="video-frame">\n'
    f'    <iframe src="https://www.youtube.com/embed/{NEW}'
    '?rel=0&modestbranding=1&playsinline=1" title="' + TITLE + '"'
    ' allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope;'
    ' picture-in-picture" allowfullscreen loading="lazy"></iframe>'
)

# ── the press kit: plain id and title swap, the section is already shaped right ──
KIT_OLD = (
    f'<iframe src="https://www.youtube.com/embed/{OLD}?rel=0&modestbranding=1"'
    ' title="Abelina — gameplay footage"'
)
KIT_NEW = (
    f'<iframe src="https://www.youtube.com/embed/{NEW}?rel=0&modestbranding=1"'
    f' title="{TITLE}"'
)


def swap(path, old, new):
    """Returns 'done' if it swapped, 'already' if the new id is in, raises if neither."""
    s = open(path, encoding="utf-8").read()
    if new in s:
        return "already"
    if old not in s:
        raise SystemExit(
            f"ERROR: {path} contains neither the expected old block nor the new id.\n"
            f"Refusing to guess. The file has probably been edited since this was written."
        )
    open(path, "w", encoding="utf-8").write(s.replace(old, new, 1))
    return "done"


def main():
    results = {}
    for path, old, new in ((PAGE, PAGE_OLD, PAGE_NEW), (KIT, KIT_OLD, KIT_NEW)):
        results[path] = swap(path, old, new)
        print(f"  {path:30s} {results[path]}")

    # the old id should be gone from both files entirely
    leftovers = [p for p in (PAGE, KIT) if OLD in open(p, encoding="utf-8").read()]
    if leftovers:
        raise SystemExit(f"ERROR: {OLD} still present in {leftovers}")

    if all(v == "already" for v in results.values()):
        print("  nothing to do, trailer was already live")
    else:
        print(f"  Abelina trailer is now {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
