#!/usr/bin/env python3
"""
Build a single Indieformer post page from Beehiiv post metadata + HTML content.

Pure library — no API calls. Consumed by build_notes.py which fetches data
from the Beehiiv API and feeds it in. Also runnable standalone for testing:
    python3 scripts/build_post.py POST_CONTENT_FILE.html

The page chrome (nav, footer, color tokens, fonts) is kept in lock-step with
notes/index.html so editorial styling decisions only happen in one place.
"""
import os
import re
import json
import html as html_lib
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
# Sanitization — strip everything Beehiiv-flavoured that shouldn't ship
# ─────────────────────────────────────────────────────────────────────────────

# Sign-off boundary markers — first match wins. We strip from the start of the
# enclosing element (paragraph or preceding <hr>) onward.
SIGNOFF_MARKERS = [
    # Frontline sign-off — keep the "The Indieformer Team" line as closer,
    # strip everything that follows.
    {"pattern": r'id="the-indieformer-team"', "mode": "after_p"},
    # Indievelopment / Showcase sign-off
    {"pattern": r'>\s*Come find us\s*—', "mode": "from_preceding_hr_or_p"},
    # Frontline alt phrasing (older posts)
    {"pattern": r'>\s*Thanks for reading\s*—', "mode": "from_preceding_p"},
    # Footer guides line (catches stragglers)
    {"pattern": r"We[’']ve also put together a few free guides", "mode": "from_preceding_p"},
]

# Always strip the Beehiiv "Powered by beehiiv" footer block.
BEEHIIV_FOOTER_RE = re.compile(
    r"<div class=['\"]beehiiv__footer['\"]>.*?</div>", re.DOTALL
)


_DIV_TAG_RE = re.compile(r"<(/?)div\b[^>]*>", re.IGNORECASE)


def _extract_wrapped(content: str, open_pattern: str) -> str | None:
    """Find the open tag matching `open_pattern` and return everything inside
    its balanced-div close. Returns None if the open tag isn't found."""
    m = re.search(open_pattern, content)
    if not m:
        return None
    inner_start = m.end()
    depth = 1
    for tag in _DIV_TAG_RE.finditer(content, inner_start):
        if tag.group(1) == "/":
            depth -= 1
            if depth == 0:
                return content[inner_start:tag.start()].strip()
        else:
            depth += 1
    # didn't balance — return what we have
    return content[inner_start:].strip()


def _strip_beehiiv_wrappers(content: str) -> str:
    """Extract just the article body. Beehiiv returns content in two shapes:

    1. RSS feed-style: wrapped in <div class='beehiiv'><div class='beehiiv__body'>…
       (this is what the public RSS feed publishes and was what earlier
       versions of this script were calibrated against)
    2. Current API standalone web page (content.free.web): a full HTML
       document with <div class='rendered-post'> containing
       <div id='web-header'> (duplicated title/subtitle/byline/share-
       buttons/hero — all of which we already render natively) and
       <div class='content-blocks'>…ACTUAL ARTICLE…</div>.

    We probe for content-blocks first (current API). Falls back to
    beehiiv__body (RSS), then to raw content."""
    for pattern in (
        # Current API: <div id='content-blocks'> inside <div class='rendered-post'>
        r"<div\b[^>]*\bid=['\"]content-blocks['\"][^>]*>",
        # RSS feed shape: <div class='beehiiv'><div class='beehiiv__body'>
        r"<div\b[^>]*\bclass=['\"][^'\"]*\bbeehiiv__body\b[^'\"]*['\"][^>]*>",
    ):
        inner = _extract_wrapped(content, pattern)
        if inner is not None:
            return inner
    return content.strip()


def _strip_leading_eyebrow_and_title(body: str) -> str:
    """
    Remove the in-body <h6 class="heading">EYEBROW</h6> and the first
    <h1>/<h2 class="heading">TITLE</h1> that follows it. These are rendered
    natively in the page header instead.
    """
    body = re.sub(r'^\s*<h6\s+class="heading"[^>]*>.*?</h6>\s*', '', body, count=1, flags=re.DOTALL)
    body = re.sub(r'^\s*<h[12]\s+class="heading"[^>]*>.*?</h[12]>\s*', '', body, count=1, flags=re.DOTALL)
    return body


def _strip_signoff(body: str) -> str:
    """Find the first sign-off marker and strip everything from there to end."""
    for marker in SIGNOFF_MARKERS:
        m = re.search(marker["pattern"], body)
        if not m:
            continue
        idx = m.start()
        mode = marker["mode"]
        if mode == "after_p":
            # Find the start of the marker's enclosing element AND keep through its </p>
            # then strip everything after.
            p_end = body.find("</p>", idx) + 4
            return body[:p_end].rstrip()
        if mode == "from_preceding_hr_or_p":
            # Walk back from idx to find the immediately preceding <hr ... or <p ...
            # whichever is closer, and strip from there. Prefer collecting any
            # consecutive <hr class="content_break"> sequence too.
            p_start = body.rfind("<p", 0, idx)
            # walk back over trailing <hr class="content_break"> just before p_start
            cut = p_start
            while True:
                m2 = re.search(r'<hr\s+class="content_break"[^>]*>\s*$', body[:cut])
                if not m2:
                    break
                cut = m2.start()
            return body[:cut].rstrip()
        if mode == "from_preceding_p":
            p_start = body.rfind("<p", 0, idx)
            return body[:p_start].rstrip()
    return body


def _strip_utm(body: str) -> str:
    """Drop utm_* query params from every href in the body."""
    def repl(m):
        url = m.group(1)
        if "?" in url:
            base, qs = url.split("?", 1)
            kept = "&".join(p for p in qs.split("&") if not p.startswith("utm_"))
            url = base + ("?" + kept if kept else "")
        return f'href="{url}"'

    return re.sub(r'href="([^"]+)"', repl, body)


WAYPOINT_RE = re.compile(r"waypoint\.indieformer\.com", re.IGNORECASE)


_CUSTOM_HTML_OPEN_RE = re.compile(
    r"<div\b[^>]*\bclass=['\"][^'\"]*\bcustom_html\b[^'\"]*['\"][^>]*>",
    re.IGNORECASE,
)

_TABLE_TAG_RE = re.compile(r"<(/?)table\b[^>]*>", re.IGNORECASE)
_TABLE_OPEN_RE = re.compile(r"<table\b[^>]*>", re.IGNORECASE)


def _strip_blocks_containing(
    body: str,
    patterns: list,
    open_re,
    tag_re,
    close_tag_len: int,
) -> str:
    """Generic walker: find each block opened by `open_re`, balance with
    `tag_re`, and drop any whose inner content matches any pattern."""
    pattern_res = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]
    out_parts = []
    pos = 0
    while True:
        opener = open_re.search(body, pos)
        if not opener:
            out_parts.append(body[pos:])
            break
        end_pos = None
        depth = 1
        for tag in tag_re.finditer(body, opener.end()):
            if tag.group(1) == "/":
                depth -= 1
                if depth == 0:
                    end_pos = tag.end()
                    break
            else:
                depth += 1
        if end_pos is None:
            out_parts.append(body[pos:])
            break
        inner = body[opener.end():end_pos - close_tag_len]
        if any(pr.search(inner) for pr in pattern_res):
            out_parts.append(body[pos:opener.start()])
        else:
            out_parts.append(body[pos:end_pos])
        pos = end_pos
    return "".join(out_parts)


def _strip_custom_html_blocks_containing(body: str, patterns: list) -> str:
    """Walk the body, find every <div class='custom_html'> block, and drop
    any whose inner content matches any of the given regex patterns. Used
    for Beehiiv polls and Waypoint promo widgets — they're always rendered
    in custom_html containers we can identify reliably."""
    pattern_res = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]

    out_parts = []
    pos = 0
    while True:
        opener = _CUSTOM_HTML_OPEN_RE.search(body, pos)
        if not opener:
            out_parts.append(body[pos:])
            break

        # Find matching </div> via depth-tracking
        end_pos = None
        depth = 1
        for tag in _DIV_TAG_RE.finditer(body, opener.end()):
            if tag.group(1) == "/":
                depth -= 1
                if depth == 0:
                    end_pos = tag.end()
                    break
            else:
                depth += 1
        if end_pos is None:
            # unbalanced — bail safely
            out_parts.append(body[pos:])
            break

        inner = body[opener.end():end_pos - 6]  # exclude the closing </div>
        if any(pr.search(inner) for pr in pattern_res):
            # Drop this block entirely
            out_parts.append(body[pos:opener.start()])
        else:
            # Keep this block
            out_parts.append(body[pos:end_pos])
        pos = end_pos

    return "".join(out_parts)


def _strip_waypoint(body: str) -> str:
    """Remove every Waypoint reference. Waypoint is the deprecated curator
    tracker; under the new publisher identity, no mention of it should
    leak through. Strips:
      1. Any <div class='custom_html'> block containing the word Waypoint
         (catches the 'Browse on Waypoint' button promo and the Waypoint
         CTA cards).
      2. Any <p> containing the word Waypoint (catches preamble text like
         'Every game above came from Waypoint…' even when the URL has
         been removed upstream).
      3. Any standalone <button> with Waypoint in its text.
      4. Any <a href> pointing at waypoint.indieformer.com — link removed
         entirely (not just unwrapped — the surrounding text usually only
         exists to label the link)."""
    out = body

    # 1. Strip custom_html blocks that mention Waypoint at all
    out = _strip_custom_html_blocks_containing(out, [r'\bWaypoint\b'])

    # 2. Paragraphs containing 'Waypoint' as a word
    out = re.sub(
        r'<p\b[^>]*>(?:(?!</p>).)*?\bWaypoint\b.*?</p>',
        '',
        out,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 3. Standalone buttons (in case any escape the custom_html sweep)
    out = re.sub(
        r'<button\b[^>]*>(?:(?!</button>).)*?\bWaypoint\b.*?</button>',
        '',
        out,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 4. Any leftover <a href="…waypoint.indieformer.com…">…</a>: remove entirely
    out = re.sub(
        r'<a[^>]+href="[^"]*waypoint\.indieformer\.com[^"]*"[^>]*>.*?</a>',
        '',
        out,
        flags=re.DOTALL,
    )

    return out


def _strip_polls(body: str) -> str:
    """Remove every Beehiiv poll widget. Beehiiv emits polls in two layouts:
    1. Custom-html div container (older posts / inline votes)
    2. Email-style <table> with 'HOW DID THIS ISSUE HIT YOU?' headings
       (wrap-up posts — Showcase / Indievelopment endings)
    Both contain at least one <a href> pointing at beehiiv.com/polls/.
    We sweep both wrapper types."""
    patterns = [r'beehiiv\.com/polls/']
    body = _strip_custom_html_blocks_containing(body, patterns)
    body = _strip_blocks_containing(
        body, patterns, _TABLE_OPEN_RE, _TABLE_TAG_RE, close_tag_len=8
    )
    return body


def _lazy_load_images(body: str) -> str:
    """Add loading='lazy' + decoding='async' to every <img> in the body that
    doesn't already specify them. Body images are below the hero — lazy is
    safe and noticeably reduces initial paint cost on long Indievelopment
    posts that pack 30+ Steam thumbnails."""
    def repl(m):
        tag = m.group(0)
        if "loading=" not in tag:
            tag = tag[:-1] + ' loading="lazy"' + tag[-1]
        if "decoding=" not in tag:
            tag = tag[:-1] + ' decoding="async"' + tag[-1]
        return tag
    return re.sub(r'<img\b[^>]*>', repl, body)


def sanitize_body(content_html: str) -> str:
    """Run every cleanup pass on raw Beehiiv content HTML."""
    body = _strip_beehiiv_wrappers(content_html)
    body = BEEHIIV_FOOTER_RE.sub("", body)
    body = _strip_leading_eyebrow_and_title(body)
    body = _strip_signoff(body)
    body = _strip_utm(body)
    body = _strip_polls(body)        # strip Beehiiv poll widgets
    body = _strip_waypoint(body)     # strip Waypoint promos (must run after polls
                                     # so the Waypoint block-strip doesn't trip on
                                     # any shared parent container)
    body = _lazy_load_images(body)
    # The 'line-height:1.6' rule is hoisted into the shared stylesheet — drop it.
    body = re.sub(
        r'<style>\s*p span\[style\*="font-size"\]\s*\{\s*line-height:\s*1\.6;?\s*\}\s*</style>',
        "", body)
    # Beehiiv re-emits the SAME <style> block (embed widgets etc.) once per
    # element — 20-40x/page. Keep the first copy of each unique block, drop
    # the identical repeats (declarative CSS, so collapsing is behaviour-safe).
    _seen = set()
    def _dedup_style(m):
        key = re.sub(r"\s+", " ", m.group(1)).strip()
        if key in _seen:
            return ""
        _seen.add(key)
        return m.group(0)
    body = re.sub(r"<style[^>]*>(.*?)</style>", _dedup_style, body, flags=re.DOTALL)
    # collapse runs of blank lines
    body = re.sub(r"\n\s*\n\s*\n+", "\n\n", body)
    return body.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Page template
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_BACK = {
    "publog":   ("/notes/",          "All notes"),
    "frontline": ("/notes/frontline/", "All Frontline"),
    "archive":  ("/notes/archive/",  "All Archive"),
}

PAGE_CSS = """  :root {
    --emerald: #28E291; --coral: #F78154; --periwinkle: #9381FF;
    --shadow: #262730; --shadow-mid: #2F3040;
    --text-primary: #F0EEE8; --text-secondary: #C9C7B8; --text-tertiary: #8B8970;
    --border: rgba(255, 255, 255, 0.08); --border-mid: rgba(255, 255, 255, 0.16);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { min-height: 100%; }
  body {
    position: relative;
    background: var(--shadow);
    background-image: radial-gradient(circle, rgba(255,255,255,0.045) 1px, transparent 1.4px);
    background-size: 26px 26px;
    font-family: 'Sora', Arial, sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    padding: 28px 20px;
    overflow-x: hidden;
  }

  .crop { position: absolute; width: 18px; height: 18px; opacity: 0; animation: fade 0.6s ease 0.2s forwards; z-index: 5; pointer-events: none; }
  .crop::before, .crop::after { content: ''; position: absolute; background: var(--text-tertiary); }
  .crop::before { left: 0; right: 0; top: 50%; height: 1.5px; transform: translateY(-50%); }
  .crop::after  { top: 0; bottom: 0; left: 50%; width: 1.5px; transform: translateX(-50%); }
  .crop.bl { bottom: 20px; left: 20px; }
  .crop.br { bottom: 20px; right: 20px; }

  .site-nav { display: flex; align-items: center; justify-content: space-between; max-width: 1000px; margin: 0 auto; padding: 14px 56px; position: relative; z-index: 4; }
  a.brand { display: inline-flex; align-items: center; text-decoration: none; transition: opacity 0.2s ease; }
  a.brand img { display: block; height: 40px; width: 40px; }
  a.brand:hover { opacity: 0.82; }
  .primary-nav { display: flex; gap: 26px; align-items: center; }
  .primary-nav a { font-family: 'Sora'; font-size: 15px; font-weight: 500; color: var(--text-secondary); text-decoration: none; position: relative; transition: color 0.2s; }
  .primary-nav a:hover { color: var(--text-primary); }
  .primary-nav a.current { color: var(--text-primary); font-weight: 600; }
  .primary-nav a.current::after { content: ''; position: absolute; left: 0; right: 0; bottom: -7px; height: 2px; background: var(--emerald); border-radius: 2px; }

  /* ── Post header ───────────────────────────────────────── */
  .post-header { max-width: 720px; margin: 0 auto; padding: 32px 56px 18px; position: relative; z-index: 2; }
  .back-link { display: inline-block; margin-bottom: 22px; font-size: 14px; color: var(--text-tertiary); text-decoration: none; transition: color 0.2s; }
  .back-link:hover { color: var(--text-primary); }
  .post-meta {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    font-size: 13px; color: var(--text-tertiary);
    border-top: 1px solid var(--border); padding-top: 14px; margin-top: 20px;
  }
  .post-tag { font-family: 'Caveat', cursive; font-size: 20px; color: var(--coral); transform: rotate(-1deg); display: inline-block; line-height: 1; }
  .post-tag .dot { color: var(--text-tertiary); margin: 0 8px; font-family: 'Sora', sans-serif; font-size: 13px; vertical-align: 2px; }
  .post-tag .num { color: var(--text-tertiary); font-family: 'Sora', sans-serif; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }
  .post-title { font-size: clamp(34px, 5vw, 50px); font-weight: 800; line-height: 1.08; letter-spacing: -0.025em; margin-bottom: 14px; }
  .post-subtitle { font-size: 18px; line-height: 1.55; color: var(--text-secondary); margin-bottom: 18px; }
  .post-hero {
    margin: 22px 0 6px;
    border-radius: 8px; overflow: hidden;
    border: 1px solid var(--border);
    background: var(--shadow-mid);
  }
  .post-hero img { display: block; width: 100%; height: auto; aspect-ratio: 1200 / 630; object-fit: cover; }

  /* ── Post body — scopes Beehiiv content to fit our design ── */
  .post-content {
    max-width: 720px; margin: 0 auto; padding: 24px 56px 8px;
    font-family: 'Sora', Arial, sans-serif; color: var(--text-primary);
    line-height: 1.7; font-size: 17px; position: relative; z-index: 2;
  }
  /* Beehiiv hardcodes 'DM Sans' as inline style on every paragraph & list
     item, which beats our class-level rule. Force Sora with !important
     across the elements Beehiiv touches. Embed-card text inherits Sora
     from the card's own inline style so we don't need to touch .custom_html. */
  .post-content .paragraph, .post-content p,
  .post-content li, .post-content ul, .post-content ol,
  .post-content figcaption, .post-content td, .post-content th {
    font-family: 'Sora', Arial, sans-serif !important;
  }
  .post-content .paragraph, .post-content p {
    margin: 0 0 1.1em; color: var(--text-secondary); line-height: 1.7;
  }
  .post-content .heading, .post-content h2, .post-content h3, .post-content h4, .post-content h5, .post-content h6 {
    font-family: 'Sora' !important; color: var(--text-primary); line-height: 1.25; letter-spacing: -0.01em; margin: 2em 0 0.6em;
  }
  .post-content h2, .post-content h2.heading { font-size: 28px; font-weight: 700; }
  .post-content h3, .post-content h3.heading { font-size: 22px; font-weight: 700; }
  .post-content h4, .post-content h4.heading { font-size: 18px; font-weight: 600; color: var(--periwinkle); text-transform: uppercase; letter-spacing: 0.06em; }
  .post-content h6, .post-content h6.heading { font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }

  /* Only restyle Beehiiv's inline-text links — embed cards keep their own styles */
  .post-content .link { color: var(--coral) !important; text-decoration: none; border-bottom: 1px solid rgba(247, 129, 84, 0.35); transition: color 0.2s, border-color 0.2s; }
  .post-content .link:hover { color: var(--text-primary) !important; border-bottom-color: var(--text-primary); }
  .post-content em, .post-content i { color: var(--text-secondary); }

  /* Images */
  .post-content .image { margin: 28px 0; }
  .post-content .image__image, .post-content img { max-width: 100%; height: auto; display: block; border-radius: 6px; border: 1px solid var(--border); }
  .post-content .image__source { display: block; margin-top: 8px; font-size: 13px; color: var(--text-tertiary); font-style: italic; }
  .post-content .image__source_text p { margin: 0; color: var(--text-tertiary); font-style: italic; }

  /* Blockquote — only style inner element so nested wrappers don't double up */
  .post-content .blockquote { margin: 28px 0; padding: 0; border: none; background: none; }
  .post-content blockquote, .post-content .blockquote__quote {
    display: block; margin: 0; padding: 6px 0 6px 22px;
    border-left: 3px solid var(--periwinkle);
    color: var(--text-primary); font-family: 'Caveat', cursive;
    font-size: 24px; line-height: 1.4; font-style: normal;
  }

  /* Dividers — handle both <hr class="content_break"> and <div class="content_break"> */
  .post-content hr.content_break { border: none; border-top: 1px solid var(--border); height: 0; margin: 36px 0; }
  .post-content div.content_break { height: 1px; background: var(--border); margin: 36px 0; }

  /* Embed cards (link previews) */
  .post-content .embed { display: block; border: 1px solid var(--border-mid); border-radius: 10px; overflow: hidden; margin: 28px 0; background: var(--shadow-mid); transition: border-color 0.2s; }
  .post-content .embed:hover { border-color: var(--emerald); }
  .post-content .embed__image { display: block; }
  .post-content .embed__image img { border-radius: 0; border: none; }
  .post-content .embed__content { padding: 14px 18px; }
  .post-content .embed__title { font-weight: 700; margin-bottom: 4px; color: var(--text-primary); }
  .post-content .embed__description { font-size: 14px; color: var(--text-secondary); margin-bottom: 6px; line-height: 1.5; }
  .post-content .embed__url { font-size: 12px; color: var(--text-tertiary); }
  .post-content .embed__link { display: block; color: inherit !important; border: none; text-decoration: none; }

  /* Hide any Beehiiv footer leakage */
  .post-content .beehiiv__footer { display: none !important; }

  /* ── Footer ──────────────────────────────────────────────── */
  .site-footer {
    max-width: 1000px; margin: 60px auto 0; padding: 44px 56px 28px;
    border-top: 1px solid var(--border);
    display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 40px;
    font-size: 14px; line-height: 1.65; color: var(--text-secondary);
    position: relative; z-index: 2;
  }
  .footer-col.brand-col { display: flex; flex-direction: column; gap: 14px; align-items: flex-start; }
  .footer-logo { flex: 0 0 auto; height: 32px; width: auto; display: block; }
  .footer-col.brand-col p { flex: 1; margin: 0; line-height: 1.65; color: var(--text-secondary); }
  .footer-label { font-family: 'Caveat'; font-size: 22px; color: var(--text-tertiary); margin-bottom: 6px; transform: rotate(-1deg); display: inline-block; }
  .footer-col ul { list-style: none; }
  .footer-col li { margin-bottom: 6px; }
  .footer-col a { color: var(--text-secondary); text-decoration: none; border-bottom: 1px solid transparent; transition: color 0.2s, border-color 0.2s; }
  .footer-col a:hover { color: var(--text-primary); border-bottom-color: var(--text-primary); }
  .footer-meta { grid-column: 1 / -1; border-top: 1px solid var(--border); margin-top: 22px; padding-top: 18px; font-size: 13px; color: var(--text-tertiary); }
  .footer-meta a { color: var(--text-tertiary); border-bottom: 1px solid transparent; text-decoration: none; }
  .footer-meta a:hover { color: var(--text-primary); border-bottom-color: var(--text-primary); }

  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }

  @media (max-width: 820px) {
    body { padding: 20px 14px; }
    .post-header, .post-content { padding-left: 24px; padding-right: 24px; }
    .site-nav { padding: 10px 24px; flex-wrap: wrap; gap: 12px 18px; }
    .primary-nav { gap: 18px; }
    .primary-nav a { font-size: 14px; }
    .site-footer { grid-template-columns: 1fr; gap: 28px; padding: 36px 24px 24px; margin-top: 48px; }
    .post-content { font-size: 16px; }
  }

  .social-icons { display: flex; gap: 12px; align-items: center; margin-top: 2px; }
  .social-icons a {
    color: var(--text-tertiary) !important;
    border: none !important;
    border-bottom: none !important;
    text-decoration: none !important;
    display: inline-flex; align-items: center; justify-content: center;
    transition: color 0.2s ease, transform 0.2s ease;
  }
  .social-icons a:hover { color: var(--text-primary) !important; transform: translateY(-2px); }
  .social-icons svg { display: block; }

  /* hoisted from per-post Beehiiv content (it repeated this inline 20-40x/page) */
  p span[style*="font-size"] { line-height: 1.6; }
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_html_escaped} — Indieformer</title>

<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">

<!-- Warm up DNS+TLS for the origins every page hits — fonts + Beehiiv image CDN. -->
<link rel="preconnect" href="https://media.beehiiv.com" crossorigin>
<link rel="stylesheet" href="/fonts/fonts.css">

<meta name="description" content="{description}">
<link rel="canonical" href="{canonical_url}">
<meta name="robots" content="index, follow">
<script type="application/ld+json">{blogposting_jsonld}</script>
<script type="application/ld+json">{breadcrumb_jsonld}</script>

<meta property="og:type" content="article">
<meta property="og:site_name" content="Indieformer">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical_url}">
<meta property="og:image" content="{og_image}">
<meta property="article:published_time" content="{date_iso}">
<meta property="article:section" content="{tag_slug}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{og_image}">

<link rel="stylesheet" href="/notes-post.css">
</head>
<body>

<span class="crop bl"></span><span class="crop br"></span>

<header class="site-nav">
  <a class="brand" href="/" aria-label="Indieformer home">
    <img src="/logo.png" alt="Indieformer" width="40" height="40">
  </a>
  <nav class="primary-nav" aria-label="Primary">
    <a href="/how-we-make-a-game-popular/">The Approach</a>
    <a href="/notes/" class="current">Notes</a>
    <a href="/scorchpot/">Scorchpot</a>
  </nav>
</header>

<section class="post-header">
  <a href="{back_url}" class="back-link">← {back_label}</a>
  <h1 class="post-title">{post_title_html_escaped}</h1>
  <p class="post-subtitle">{subtitle_html_escaped}</p>
  <figure class="post-hero">
    <img src="{og_image}" alt="{post_title_html_escaped}" loading="eager" width="1200" height="630">
  </figure>
  <div class="post-meta">
    <span class="post-tag">{tag_slug}<span class="dot">·</span><span class="num">Issue {issue_label}</span></span>
    <time datetime="{date_iso}">{date_human}</time>
  </div>
</section>

<article class="post-content">
{body}
</article>

<footer class="site-footer">
  <div class="footer-col brand-col">
    <img class="footer-logo" src="/logo-lockup.png" alt="Indieformer">
    <p>A small indie game publisher. Run by Josh &amp; Clem in Melbourne, Australia.</p>
  </div>
  <div class="footer-col">
    <p class="footer-label">Guides &amp; reads</p>
    <ul>
      <li><a href="https://indieformer.com/essay/">How to Really Make a Game</a></li>
      <li><a href="https://indieformer.beehiiv.com/press-kit-guide">Press Kit Guide</a></li>
      <li><a href="https://indieformer.beehiiv.com/steam-marketing-guide">Steam Marketing Guide</a></li>
    </ul>
  </div>
  <div class="footer-col">
    <p class="footer-label">Elsewhere</p>
    <ul>
      <li><a href="/notes/">Notes</a></li>
      <li><a href="/notes/archive/">Curator archive</a></li>
    </ul>
  </div>
  <div class="footer-col">
    <p class="footer-label">Find us</p>
    <div class="social-icons">
      <a href="https://www.threads.com/@indieformer" target="_blank" rel="noopener" aria-label="Threads">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M17.79 11.4c-.09-.04-.18-.08-.27-.12-.16-2.93-1.76-4.6-4.44-4.62h-.04c-1.6 0-2.94.69-3.76 1.94l1.47.97c.61-.93 1.59-1.13 2.28-1.13h.03c.87.01 1.51.26 1.94.74.3.34.5.83.6 1.45-.74-.12-1.54-.16-2.39-.11-2.38.14-3.91 1.53-3.81 3.45.05.86.5 1.6 1.25 2.1.66.42 1.5.62 2.39.58 1.16-.05 2.06-.49 2.68-1.3.48-.62.77-1.41.91-2.39.55.34.96.78 1.19 1.31.39.91.42 2.4-.79 3.61-1.06 1.05-2.32 1.5-4.22 1.51-2.11-.02-3.7-.71-4.74-2.05-.97-1.25-1.48-3.05-1.5-5.35.02-2.31.53-4.11 1.5-5.36 1.04-1.34 2.63-2.03 4.74-2.05 2.13.02 3.75.71 4.81 2.06.52.66.93 1.49 1.18 2.46l1.71-.46c-.3-1.2-.79-2.21-1.44-3.04-1.39-1.74-3.39-2.62-5.95-2.64h-.02c-2.56.02-4.56.91-5.92 2.64-1.22 1.54-1.85 3.66-1.86 6.31v.01c.02 2.65.65 4.78 1.86 6.31 1.37 1.74 3.36 2.62 5.92 2.64h.02c2.27-.02 3.87-.62 5.2-1.96 1.73-1.75 1.68-3.94 1.11-5.29-.41-.96-1.19-1.75-2.24-2.3z"/></svg>
      </a>
      <a href="https://bsky.app/profile/indieformer.com" target="_blank" rel="noopener" aria-label="Bluesky">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M5.84 4.94c2.31 1.74 4.79 5.26 5.7 7.15.91-1.89 3.39-5.41 5.7-7.15 1.66-1.25 4.36-2.22 4.36 .89 0 .62-.36 5.22-.57 5.96-.73 2.59-3.37 3.25-5.71 2.85 4.1.7 5.15 3.04 2.89 5.39-4.3 4.46-6.18-1.12-6.66-2.55-.09-.26-.13-.38-.13-.28 0-.11-.04.02-.13.28-.48 1.43-2.36 7.01-6.66 2.55-2.26-2.34-1.22-4.69 2.89-5.39-2.34.4-4.99-.26-5.71-2.85-.21-.74-.57-5.34-.57-5.96 0-3.11 2.7-2.14 4.36-.89z"/></svg>
      </a>
      <a href="https://discord.gg/rztz9s2wb3" target="_blank" rel="noopener" aria-label="Discord">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M20.32 4.74A19.79 19.79 0 0 0 16.06 3a.07.07 0 0 0-.07.04 13.95 13.95 0 0 0-.61 1.27 18.31 18.31 0 0 0-5.48 0c-.16-.41-.4-.91-.62-1.27a.08.08 0 0 0-.08-.04A19.74 19.74 0 0 0 4.93 4.74a.07.07 0 0 0-.03.03A20.32 20.32 0 0 0 1.04 18.21a.08.08 0 0 0 .03.05 19.93 19.93 0 0 0 6.03 3.04.07.07 0 0 0 .08-.03c.46-.63.88-1.3 1.23-2a.07.07 0 0 0-.04-.1 13.07 13.07 0 0 1-1.88-.9.07.07 0 0 1 0-.13c.13-.1.25-.2.37-.3a.07.07 0 0 1 .07-.01c3.94 1.8 8.21 1.8 12.1 0a.07.07 0 0 1 .08.01c.12.1.24.2.37.3a.07.07 0 0 1 0 .13c-.6.35-1.23.65-1.88.9a.07.07 0 0 0-.04.1c.36.7.78 1.37 1.23 2a.07.07 0 0 0 .08.03 19.86 19.86 0 0 0 6.03-3.04.08.08 0 0 0 .03-.05 20.18 20.18 0 0 0-3.86-13.44.06.06 0 0 0-.03-.03zM8.52 15.27c-1.19 0-2.17-1.09-2.17-2.43 0-1.34.96-2.43 2.17-2.43 1.22 0 2.19 1.1 2.17 2.43 0 1.34-.96 2.43-2.17 2.43zm8.03 0c-1.19 0-2.17-1.09-2.17-2.43 0-1.34.96-2.43 2.17-2.43 1.22 0 2.19 1.1 2.17 2.43 0 1.34-.95 2.43-2.17 2.43z"/></svg>
      </a>
    </div>
  </div>
  <p class="footer-meta">© {year} Indieformer. · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a></p>
</footer>

</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────────────

def parse_issue_label(title: str):
    """Given e.g. '#75 | Too niche, said everyone' return ('Too niche, said everyone', '#75').
    If no leading '#N |', the full title is the post title and the issue label is empty."""
    m = re.match(r"^\s*(#\d+)\s*\|\s*(.+?)\s*$", title)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return title.strip(), ""


def build_post_page(
    *,
    title: str,
    subtitle: str,
    slug: str,
    tag_slug: str,
    date_iso: str,
    og_image: str,
    content_html: str,
    category: str,          # 'publog' | 'frontline' | 'archive'
    out_root: str,
) -> str:
    """
    Write notes/<slug>/index.html. Returns the absolute path of the file written.
    """
    post_title, issue_label = parse_issue_label(title)
    if not issue_label:
        issue_label = "—"

    # Human date
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        date_human = dt.strftime("%-d %b %Y")
        date_iso_norm = dt.date().isoformat()
    except Exception:
        date_human = date_iso
        date_iso_norm = date_iso

    back_url, back_label = CATEGORY_BACK.get(category, CATEGORY_BACK["publog"])

    body = sanitize_body(content_html)

    canonical_url = f"https://indieformer.com/notes/{slug}/"
    description = subtitle.strip() or post_title
    og_title = f"{issue_label} | {post_title}" if issue_label and issue_label != "—" else post_title
    title_for_tab = og_title

    blogposting_jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": og_title,
        "description": description,
        "image": og_image,
        "datePublished": date_iso_norm,
        "url": canonical_url,
        "mainEntityOfPage": canonical_url,
        "author": {"@type": "Organization", "name": "Indieformer", "url": "https://indieformer.com/"},
        "publisher": {"@type": "Organization", "name": "Indieformer",
                      "logo": {"@type": "ImageObject", "url": "https://indieformer.com/logo.png"}},
    }, ensure_ascii=False)

    breadcrumb_jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://indieformer.com/"},
            {"@type": "ListItem", "position": 2, "name": "Notes", "item": "https://indieformer.com/notes/"},
            {"@type": "ListItem", "position": 3, "name": post_title, "item": canonical_url},
        ],
    }, ensure_ascii=False)

    page = PAGE_TEMPLATE.format(
        blogposting_jsonld=blogposting_jsonld,
        breadcrumb_jsonld=breadcrumb_jsonld,
        title_html_escaped=html_lib.escape(title_for_tab),
        post_title_html_escaped=html_lib.escape(post_title),
        subtitle_html_escaped=html_lib.escape(subtitle),
        description=html_lib.escape(description),
        canonical_url=canonical_url,
        og_title=html_lib.escape(og_title),
        og_image=og_image,
        date_iso=date_iso_norm,
        date_human=date_human,
        tag_slug=tag_slug,
        issue_label=issue_label,
        back_url=back_url,
        back_label=back_label,
        body=body,
        css=PAGE_CSS,
        year=datetime.now(timezone.utc).year,
    )

    # shared per-post stylesheet — identical for every post, written once,
    # cached by the browser across all notes pages (was ~10KB inline per page).
    with open(os.path.join(out_root, "notes-post.css"), "w", encoding="utf-8") as f:
        f.write(PAGE_CSS)

    out_dir = os.path.join(out_root, "notes", slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test harness
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: build_post.py CONTENT_HTML_FILE [--out OUT_ROOT]", file=sys.stderr)
        sys.exit(1)

    content_file = sys.argv[1]
    out_root = "."
    if "--out" in sys.argv:
        out_root = sys.argv[sys.argv.index("--out") + 1]

    raw = open(content_file).read()

    # Test fixture: post #76 — Indievelopment May 2026
    path = build_post_page(
        title="#76 | Indievelopment — May 2026",
        subtitle=(
            "Whether you are syncing your strikes to a multi-genre soundtrack or "
            "managing elemental synergies to break ancient curses, the focus is firmly "
            "on rewarding skill within beautifully realized, atmospheric worlds."
        ),
        slug="indievelopment0526",
        tag_slug="indievelopment",
        date_iso="2026-05-16T06:00:00Z",
        og_image=(
            "https://media.beehiiv.com/cdn-cgi/image/fit=scale-down,format=auto,"
            "onerror=redirect,quality=80/uploads/asset/file/4d351311-9b1d-4428-ae14-"
            "a9cc7acb64f5/indievelopment0526_Thumbnail.png"
        ),
        content_html=raw,
        category="archive",
        out_root=out_root,
    )
    print(f"wrote: {path}")
