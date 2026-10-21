#!/usr/bin/env python3
"""
Reveal the Devilcoin announcement trailer on the game page and the press kit.

One-off, written to run from .github/workflows/devilcoin-trailer.yml at 13:00
UTC on 26 Oct 2026, which is 06:00 Monday 26 Oct Pacific (PDT, UTC-7 — US
daylight time does not end until 1 Nov 2026).

Until then both trailers are held behind placeholder comments so nothing shows.
This swaps each placeholder for the real markup. On the press kit that means
both the nav link and the section. The trailer video (snpgJAzptk4) is already
public; this only controls when it appears on the site.

Safe to run twice. If a trailer is already in place it reports "already" and
leaves the file alone. It exits 1 only if a file has neither the placeholder nor
the revealed markup, so a silent half-reveal is not possible.
"""
import sys

PAGE = "devilcoin/index.html"
KIT = "devilcoin/presskit/index.html"

# ── game page: the placeholder becomes the trailer section, under the 4 cards ──
PAGE_MARK = (
    "<!-- DEVILCOIN-TRAILER: held until reveal; "
    "scripts/reveal_devilcoin_trailer.py swaps this in on 2026-10-26 -->"
)
PAGE_TRAILER = (
    '<!-- ═══════════════ TRAILER ═══════════════ -->\n'
    '<section class="wrap centered" style="padding-top:0">\n'
    '  <h2 class="sec">tHE ANNOUNCEMENt <em>tRAILER.</em></h2>\n'
    '  <div class="trailer">\n'
    '    <iframe src="https://www.youtube.com/embed/snpgJAzptk4?rel=0&modestbranding=1&playsinline=1"\n'
    '      title="Devilcoin — Official Announcement Trailer"\n'
    '      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"\n'
    '      allowfullscreen loading="lazy"></iframe>\n'
    '  </div>\n'
    '</section>'
)

# ── press kit: two placeholders, the nav link and the section ──
KIT_NAV_MARK = "<!-- DEVILCOIN-TRAILER-NAV -->"
KIT_NAV = '<a href="#trailer">Trailer</a>'

KIT_SECTION_MARK = "<!-- DEVILCOIN-TRAILER-SECTION -->"
KIT_SECTION = (
    '<section class="pk-section" id="trailer">\n'
    '      <h2 class="pk-h2">tRAILER</h2>\n'
    '      <div class="pk-trailer">\n'
    '        <iframe src="https://www.youtube.com/embed/snpgJAzptk4?rel=0&modestbranding=1&playsinline=1"\n'
    '          title="Devilcoin — Official Announcement Trailer"\n'
    '          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"\n'
    '          allowfullscreen loading="lazy"></iframe>\n'
    '      </div>\n'
    '    </section>'
)


def swap(path, mark, content, present_token):
    """Replace `mark` with `content`. Returns 'done', or 'already' if
    `present_token` is already in the file, raising if neither is found."""
    s = open(path, encoding="utf-8").read()
    if mark in s:
        open(path, "w", encoding="utf-8").write(s.replace(mark, content, 1))
        return "done"
    if present_token in s:
        return "already"
    raise SystemExit(
        f"ERROR: {path} has neither the placeholder {mark!r} nor the revealed "
        f"trailer. Refusing to guess — the file has changed since this was written."
    )


def main():
    jobs = [
        (PAGE, PAGE_MARK, PAGE_TRAILER, 'class="trailer"'),
        (KIT, KIT_NAV_MARK, KIT_NAV, 'href="#trailer"'),
        (KIT, KIT_SECTION_MARK, KIT_SECTION, 'id="trailer"'),
    ]
    for path, mark, content, token in jobs:
        print(f"  {path:30s} {swap(path, mark, content, token)}")
    print("done")


if __name__ == "__main__":
    main()
