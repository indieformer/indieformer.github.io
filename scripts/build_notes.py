#!/usr/bin/env python3
"""
build_notes.py — Fetch all Indieformer Beehiiv posts via API, generate a
per-post HTML page for every post, and emit three tabbed index pages:

    /notes/            — Publog  (special tag + journey content)
    /notes/frontline/  — Frontline case studies
    /notes/archive/    — Curator Archive (Showcase + Indievelopment monthlies)

Routing
-------
Default: Beehiiv content_tag → category
    frontline      → frontline
    showcase       → archive
    indievelopment → archive
    special        → publog
Overrides per slug live in SLUG_OVERRIDES below — append entries to move
individual posts between tabs without code changes elsewhere.

Caching
-------
A small manifest at notes/.posts.json records each post's updated_at and the
TEMPLATE_VERSION it was built against. Pages are regenerated when the
post's updated_at differs OR the template version has been bumped.

Requires
--------
Environment variable BEEHIIV_API_KEY (also exposed via GitHub Actions
secret of the same name). Run with NO arguments — the script is the entry
point both locally and in CI:

    BEEHIIV_API_KEY=... python3 scripts/build_notes.py
"""
import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import html as html_lib
from datetime import datetime, timezone

# Reuse the post-page template + sanitization passes
from build_post import build_post_page, sanitize_body  # noqa: F401


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

PUB_ID = "pub_46dc4e51-4f9d-4b04-80e5-a5714a53bc93"
API_BASE = "https://api.beehiiv.com/v2"
MANIFEST_PATH = "notes/.posts.json"
TEMPLATE_VERSION = 6  # bump when the post or index template changes materially

TAG_TO_CATEGORY = {
    "frontline":      "frontline",
    "showcase":       "archive",
    "indievelopment": "archive",
    "special":        "publog",
}

# Per-slug routing overrides — these were curated lists that landed under the
# "special" tag but editorially belong in the archive.
SLUG_OVERRIDES = {
    "upcoming-indie-games-2026": "archive",
    "best-indie-games-2025":     "archive",
    "hidden-gems-2025":          "archive",
}

CATEGORY_CONFIG = {
    "publog": {
        "url":    "/notes/",
        "title":  "The Publog.",
        "lede":   "from inside the publishing house.",
        "desc":   "Notes on what we're trying, what's working, what isn't. The journey of running a small indie publisher — written while we're in it.",
        "out":    "notes/index.html",
        "og":     "/og-image.png",
    },
    "frontline": {
        "url":    "/notes/frontline/",
        "title":  "Frontline.",
        "lede":   "how indie games actually get made.",
        "desc":   "Case studies of the devs and studios we think are doing it right. Tactics, trade-offs, and the hard parts they're willing to talk about.",
        "out":    "notes/frontline/index.html",
        "og":     "/og-image.png",
    },
    "archive": {
        "url":    "/notes/archive/",
        "title":  "Curator Archive.",
        "lede":   "what we used to do.",
        "desc":   "Monthly Showcase and Indievelopment curation from when Indieformer was a curator. We're a publisher now — these are kept for posterity.",
        "out":    "notes/archive/index.html",
        "og":     "/og-image.png",
    },
}

CATEGORIES_IN_ORDER = ["publog", "frontline", "archive"]
CATEGORY_LABELS = {"publog": "Publog", "frontline": "Frontline", "archive": "Curator Archive"}


# ─────────────────────────────────────────────────────────────────────────────
# Beehiiv API client (no extra deps — plain stdlib)
# ─────────────────────────────────────────────────────────────────────────────

def _http_get(url: str, token: str, retries: int = 3) -> dict:
    """GET with retries + basic error handling. Returns parsed JSON."""
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/json",
                "User-Agent":    "indieformer-build/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Retry only on 5xx and 429
            if e.code in (429, 500, 502, 503, 504):
                last_err = e
                wait = 2 ** attempt
                print(f"  api: {e.code} on {url} — retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            wait = 2 ** attempt
            print(f"  api: URLError {e} — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
    raise RuntimeError(f"giving up on {url}: {last_err}")


def list_all_posts(token: str) -> list[dict]:
    """Page through every published post. Request as many expansions as we
    might need so we don't have to refetch per post for metadata."""
    all_posts = []
    page = 1
    while True:
        qs = urllib.parse.urlencode([
            ("limit", "100"),
            ("page", str(page)),
            ("status", "published"),
            ("expand[]", "content_tags"),
            ("expand[]", "thumbnail"),
            ("expand[]", "seo_settings"),
            ("expand[]", "web_settings"),
        ])
        data = _http_get(f"{API_BASE}/publications/{PUB_ID}/posts?{qs}", token)
        all_posts.extend(data.get("data", []))
        total_pages = data.get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1
    return all_posts


def parse_post_date(post: dict) -> str:
    """Return an ISO date string from whichever Beehiiv date field is present.

    Beehiiv's API v2 returns dates as **unix timestamps** (integers) on the
    posts resource — most importantly `publish_date` and `displayed_date`.
    Earlier versions of this builder probed `scheduled_at` / `created_at`
    which only get populated for scheduled-but-unpublished posts and
    returned empty for everything in production. Empty date strings sort
    equally → stable sort preserves API order (oldest first), which is
    why the index pages came out backwards on the first backfill."""
    for field in ("publish_date", "displayed_date", "scheduled_at", "created_at"):
        v = post.get(field)
        if not v:
            continue
        # unix timestamp (int or numeric string)
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
            except (ValueError, OSError):
                continue
        if isinstance(v, str):
            if v.isdigit():
                try:
                    return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
                except (ValueError, OSError):
                    continue
            return v
    return ""


def extract_thumbnail(post: dict, content_html: str = "") -> str:
    """Best-effort thumbnail URL extraction. Beehiiv's API has used different
    field names across versions; try several, fall back to first <img> in
    content if all else fails."""
    candidates = [
        post.get("thumbnail_url"),
        (post.get("thumbnail") or {}).get("src") if isinstance(post.get("thumbnail"), dict) else post.get("thumbnail"),
        (post.get("images") or {}).get("thumbnail", {}).get("url") if isinstance(post.get("images"), dict) else None,
        (post.get("seo_settings") or {}).get("og_image"),
        (post.get("web_settings") or {}).get("thumbnail_url"),
    ]
    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c
    # fall back: first <img src="…"> in the post HTML
    if content_html:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_html)
        if m:
            url = m.group(1)
            if "1x1" not in url and "pixel" not in url.lower():
                return url
    return ""


def fetch_post_content(post_id: str, token: str) -> str:
    """Fetch the free web HTML content for a single post."""
    qs = urllib.parse.urlencode([("expand[]", "free_web_content")])
    data = _http_get(f"{API_BASE}/publications/{PUB_ID}/posts/{post_id}?{qs}", token)
    post = data.get("data") or {}
    content = post.get("content") or {}
    return (content.get("free") or {}).get("web", "") or ""


# ─────────────────────────────────────────────────────────────────────────────
# Routing + manifest
# ─────────────────────────────────────────────────────────────────────────────

def categorize(post: dict) -> tuple[str, str]:
    """Return (category, primary_tag_slug).

    Beehiiv's API returns content_tags as a list of slug *strings* (e.g.
    ['frontline']). Some clients/wrappers normalise this to dicts, so we
    handle both shapes."""
    tags = post.get("content_tags") or []
    primary_tag = "special"
    if tags:
        first = tags[0]
        if isinstance(first, str):
            primary_tag = first or "special"
        elif isinstance(first, dict):
            primary_tag = first.get("slug") or "special"
    slug = post.get("slug") or ""
    if slug in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[slug], primary_tag
    return TAG_TO_CATEGORY.get(primary_tag, "publog"), primary_tag


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"template_version": 0, "posts": {}}
    try:
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    except Exception:
        return {"template_version": 0, "posts": {}}


def save_manifest(manifest: dict) -> None:
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


# ─────────────────────────────────────────────────────────────────────────────
# Index page rendering
# ─────────────────────────────────────────────────────────────────────────────

INDEX_CSS = """  :root {
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

  /* ── Page header ───────────────────────────────────── */
  .section { position: relative; width: 100%; max-width: 1000px; margin: 0 auto; padding: 40px 56px 16px; z-index: 1; }
  .col { max-width: 720px; position: relative; z-index: 2; }
  h1 { font-size: clamp(38px, 6vw, 56px); font-weight: 800; line-height: 1.05; letter-spacing: -0.025em; margin-bottom: 14px; }
  .page-lede { font-family: 'Caveat', cursive; font-size: 26px; color: var(--coral); transform: rotate(-1deg); display: inline-block; margin-bottom: 18px; }
  .page-desc { color: var(--text-secondary); line-height: 1.65; font-size: 16px; max-width: 560px; }
  .subscribe-inline { margin: 22px 0 4px; max-width: 560px; }
  .subscribe-inline iframe { max-width: 100% !important; }

  /* ── Tabs ──────────────────────────────────────────── */
  .notes-tabs {
    max-width: 1000px; margin: 16px auto 0; padding: 0 56px;
    display: flex; gap: 0; border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .notes-tabs a {
    font-family: 'Sora'; font-size: 15px; font-weight: 500;
    color: var(--text-secondary); text-decoration: none;
    padding: 12px 0; margin-right: 28px;
    border-bottom: 2px solid transparent;
    transition: color 0.2s, border-color 0.2s;
  }
  .notes-tabs a:hover { color: var(--text-primary); }
  .notes-tabs a.current {
    color: var(--text-primary); font-weight: 600;
    border-bottom-color: var(--emerald);
  }

  /* ── Card list ─────────────────────────────────────── */
  .notes-list { max-width: 1000px; margin: 0 auto; padding: 24px 56px 8px; position: relative; z-index: 2; }
  .notes-list .note-card:first-of-type { border-top: 1px solid var(--border); }
  .note-card { padding: 22px 0; border-bottom: 1px solid var(--border); max-width: 720px; }
  .note-link { display: grid; grid-template-columns: 1fr; gap: 0; text-decoration: none; color: inherit; }
  .note-card.has-thumb .note-link { grid-template-columns: 140px 1fr; gap: 22px; align-items: start; }
  .note-thumb { width: 140px; aspect-ratio: 1200 / 630; overflow: hidden; border-radius: 8px; background: var(--shadow-mid); border: 1px solid var(--border); transition: border-color 0.2s ease; }
  .note-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.4s ease; }
  .note-link:hover .note-thumb { border-color: var(--emerald); }
  .note-link:hover .note-thumb img { transform: scale(1.04); }
  .note-meta { display: flex; gap: 14px; align-items: baseline; margin-bottom: 6px; font-size: 13px; color: var(--text-tertiary); }
  .note-tag { font-family: 'Caveat', cursive; font-size: 18px; color: var(--coral); transform: rotate(-1.5deg); display: inline-block; line-height: 1; }
  .note-title { font-family: 'Sora'; font-size: 21px; font-weight: 700; line-height: 1.3; color: var(--text-primary); margin-bottom: 6px; transition: color 0.2s ease; }
  .note-link:hover .note-title { color: var(--emerald); }
  .note-excerpt { font-size: 15px; line-height: 1.6; color: var(--text-secondary); }
  .empty-state { padding: 40px 0; color: var(--text-tertiary); font-size: 16px; max-width: 560px; }

  /* ── Footer ─────────────────────────────────────────── */
  .site-footer {
    max-width: 1000px; margin: 60px auto 0; padding: 44px 56px 28px;
    border-top: 1px solid var(--border);
    display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 40px;
    font-size: 14px; line-height: 1.65; color: var(--text-secondary);
    position: relative; z-index: 2;
  }
  .footer-col.brand-col { display: flex; gap: 18px; align-items: flex-start; }
  .footer-logo { flex: 0 0 auto; height: 92px; width: auto; display: block; }
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
    .section, .notes-list, .notes-tabs { padding-left: 24px; padding-right: 24px; }
    .site-nav { padding: 10px 24px; flex-wrap: wrap; gap: 12px 18px; }
    .primary-nav { gap: 18px; }
    .primary-nav a { font-size: 14px; }
    .site-footer { grid-template-columns: 1fr; gap: 28px; padding: 36px 24px 24px; margin-top: 48px; }
    .note-title { font-size: 19px; }
    .note-card.has-thumb .note-link { grid-template-columns: 100px 1fr; gap: 14px; }
    .note-thumb { width: 100px; }
  }
  @media (max-width: 500px) {
    .note-card.has-thumb .note-link { grid-template-columns: 1fr; gap: 12px; }
    .note-thumb { width: 100%; }
  }
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Indieformer</title>

<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://media.beehiiv.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=Caveat:wght@500;600;700&display=swap">

<meta name="description" content="{description}">
<link rel="canonical" href="https://indieformer.com{path}">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Indieformer">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="https://indieformer.com{path}">
<meta property="og:image" content="https://indieformer.com{og_image}">
<meta name="twitter:card" content="summary_large_image">

<style>
{css}
</style>
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

<section class="section">
  <div class="col">
    <h1>{heading}</h1>
    <p class="page-lede">{lede}</p>
    <p class="page-desc">{description}</p>
    <div class="subscribe-inline">
      <script async src="https://subscribe-forms.beehiiv.com/v3/loader.js" data-beehiiv-form="23908dcc-ff1f-4876-95a9-61a164fb3893"></script>
    </div>
  </div>
</section>

<nav class="notes-tabs" aria-label="Notes categories">
{tabs_html}
</nav>

<main class="notes-list" id="notes">
{cards_html}
</main>

<footer class="site-footer">
  <div class="footer-col brand-col">
    <img class="footer-logo" src="/logo-stacked.png" alt="Indieformer">
    <p>A small indie game publisher. Run by Josh &amp; Clem in Melbourne, Australia.</p>
  </div>
  <div class="footer-col">
    <p class="footer-label">Guides &amp; reads</p>
    <ul>
      <li><a href="https://indieformer.com/essay/">How to Really Make a Game</a></li>
      <li><a href="/press-kit-guide/">Press Kit Guide</a></li>
      <li><a href="/steam-marketing-guide/">Steam Marketing Guide</a></li>
    </ul>
  </div>
  <div class="footer-col">
    <p class="footer-label">Elsewhere</p>
    <ul>
      <li><a href="/notes/">Notes</a></li>
      <li><a href="/notes/archive/">Curator archive</a></li>
    </ul>
  </div>
  <p class="footer-meta">© {year} Indieformer. · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a></p>
</footer>

</body>
</html>
"""


def _excerpt(subtitle: str, max_chars: int = 200) -> str:
    text = re.sub(r"\s+", " ", subtitle or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def _format_human_date(date_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        return date_iso


def _render_card(post: dict) -> str:
    slug = post["slug"]
    title_human, _ = _split_issue(post["title"])
    excerpt = _excerpt(post.get("subtitle", ""))
    tag_display = (post.get("primary_tag") or "").lower()
    og_image = post.get("og_image", "")
    date_iso = post.get("date_iso", "")
    date_human = _format_human_date(date_iso)
    date_iso_short = date_iso.split("T", 1)[0]

    thumb = ""
    if og_image:
        thumb = (
            f'<div class="note-thumb">'
            f'<img src="{og_image}" alt="" loading="lazy" decoding="async">'
            f'</div>'
        )
    has_thumb = " has-thumb" if og_image else ""
    tag_html = f'<span class="note-tag">{html_lib.escape(tag_display)}</span>' if tag_display else ""

    return (
        f'    <article class="note-card{has_thumb}">\n'
        f'      <a class="note-link" href="/notes/{slug}/">\n'
        f'        {thumb}\n'
        f'        <div class="note-body">\n'
        f'          <div class="note-meta">\n'
        f'            {tag_html}\n'
        f'            <time datetime="{date_iso_short}">{html_lib.escape(date_human)}</time>\n'
        f'          </div>\n'
        f'          <h3 class="note-title">{html_lib.escape(title_human)}</h3>\n'
        f'          <p class="note-excerpt">{html_lib.escape(excerpt)}</p>\n'
        f'        </div>\n'
        f'      </a>\n'
        f'    </article>'
    )


def _split_issue(title: str) -> tuple[str, str]:
    m = re.match(r"^\s*(#\d+)\s*\|\s*(.+?)\s*$", title)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return title.strip(), ""


def _render_tabs(current: str) -> str:
    lines = []
    for cat in CATEGORIES_IN_ORDER:
        cfg = CATEGORY_CONFIG[cat]
        cls = ' class="current"' if cat == current else ""
        label = CATEGORY_LABELS[cat]
        lines.append(f'  <a href="{cfg["url"]}"{cls}>{label}</a>')
    return "\n".join(lines)


def render_index_page(category: str, posts_in_cat: list[dict]) -> str:
    cfg = CATEGORY_CONFIG[category]
    cards = [_render_card(p) for p in posts_in_cat]
    cards_html = "\n".join(cards) if cards else (
        '    <p class="empty-state">Nothing here yet. Subscribe above — '
        'the first one lands in your inbox.</p>'
    )

    return INDEX_TEMPLATE.format(
        title=cfg["title"].rstrip("."),
        og_title=cfg["title"].rstrip("."),
        heading=cfg["title"],
        lede=cfg["lede"],
        description=cfg["desc"],
        path=cfg["url"],
        og_image=cfg["og"],
        cards_html=cards_html,
        tabs_html=_render_tabs(category),
        css=INDEX_CSS,
        year=datetime.now(timezone.utc).year,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    token = os.environ.get("BEEHIIV_API_KEY", "").strip()
    if not token:
        print("ERROR: BEEHIIV_API_KEY env var not set.", file=sys.stderr)
        return 2

    print("→ listing posts via Beehiiv API …", file=sys.stderr)
    raw_posts = list_all_posts(token)
    print(f"  got {len(raw_posts)} published posts", file=sys.stderr)

    # Normalise and categorise every post
    posts = []
    for p in raw_posts:
        category, primary_tag = categorize(p)
        posts.append({
            "id":          p["id"],
            "slug":        p.get("slug") or "",
            "title":       p.get("title") or "",
            "subtitle":    (p.get("seo_settings") or {}).get("default_description")
                           or p.get("subtitle") or "",
            "date_iso":    parse_post_date(p),
            "updated_at":  parse_post_date({
                "publish_date": p.get("updated_at") or p.get("modified_at"),
                "created_at":   p.get("created_at"),
            }) or parse_post_date(p),
            "og_image":    extract_thumbnail(p),
            "_raw":        p,            # kept for content-based thumbnail fallback later
            "primary_tag": primary_tag,
            "category":    category,
        })

    # Sort newest-first for the index pages
    posts.sort(key=lambda x: x["date_iso"] or "", reverse=True)

    # ── Per-post pages (rebuild only when needed) ─────────────────────────
    manifest = load_manifest()
    posts_manifest = manifest.get("posts", {})
    template_version_changed = manifest.get("template_version", 0) != TEMPLATE_VERSION

    rebuilt = 0
    skipped = 0
    for p in posts:
        m_entry = posts_manifest.get(p["slug"]) or {}
        out_path = f"notes/{p['slug']}/index.html"
        needs_rebuild = (
            template_version_changed
            or not os.path.exists(out_path)
            or m_entry.get("updated_at") != p["updated_at"]
            or m_entry.get("category")   != p["category"]
        )
        if not needs_rebuild:
            skipped += 1
            continue

        print(f"  + {p['slug']:40s} → {p['category']}", file=sys.stderr)
        content_html = fetch_post_content(p["id"], token)
        if not content_html:
            print(f"    WARN: empty content for {p['slug']}; skipping", file=sys.stderr)
            continue

        # If we still don't have a thumbnail, fish one from the content
        if not p["og_image"]:
            p["og_image"] = extract_thumbnail(p["_raw"], content_html)

        build_post_page(
            title=p["title"],
            subtitle=p["subtitle"],
            slug=p["slug"],
            tag_slug=p["primary_tag"],
            date_iso=p["date_iso"],
            og_image=p["og_image"],
            content_html=content_html,
            category=p["category"],
            out_root=".",
        )

        posts_manifest[p["slug"]] = {
            "id":         p["id"],
            "title":      p["title"],
            "category":   p["category"],
            "tag":        p["primary_tag"],
            "date_iso":   p["date_iso"],
            "updated_at": p["updated_at"],
        }
        rebuilt += 1
        # be polite to the API
        time.sleep(0.15)

    print(f"  posts: rebuilt={rebuilt} skipped={skipped}", file=sys.stderr)

    # ── Index pages (always rebuild — they're cheap and may change ordering) ──
    by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES_IN_ORDER}
    for p in posts:
        by_cat[p["category"]].append(p)

    for cat in CATEGORIES_IN_ORDER:
        out = CATEGORY_CONFIG[cat]["out"]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        page = render_index_page(cat, by_cat[cat])
        with open(out, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"  ✓ index → {out} ({len(by_cat[cat])} posts)", file=sys.stderr)

    # ── Persist manifest ─────────────────────────────────────────────────
    manifest = {"template_version": TEMPLATE_VERSION, "posts": posts_manifest}
    save_manifest(manifest)
    print(f"  manifest → {MANIFEST_PATH}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
