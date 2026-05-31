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


def _strip_beehiiv_wrappers(content: str) -> str:
    """Extract just the article body from a Beehiiv content payload.

    The API's `content.free.web` field returns a *full standalone HTML
    page* (DOCTYPE, <head> with fonts, page chrome, `<div class='beehiiv'>`
    containing `<div class='beehiiv__body'>...article...</div>`, then
    closing tags). Earlier versions of this function tried to match the
    whole thing with one regex anchored to end-of-string and silently
    failed on the live API response — the entire standalone Beehiiv page
    was getting nested inside the Indieformer page wrapper. Now we walk
    the div tags and track depth properly."""
    start_m = re.search(r"<div\s+class=['\"]beehiiv__body['\"]>", content)
    if not start_m:
        return content.strip()
    inner_start = start_m.end()

    depth = 1
    for m in _DIV_TAG_RE.finditer(content, inner_start):
        if m.group(1) == "/":
            depth -= 1
            if depth == 0:
                return content[inner_start:m.start()].strip()
        else:
            depth += 1
    # didn't balance — give up and return what's there
    return content[inner_start:].strip()


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


def _strip_waypoint(body: str) -> str:
    """Remove any paragraph or button that links to waypoint, plus inline waypoint links."""
    out = body

    # Remove <p class="paragraph"> that contains a waypoint link
    while True:
        m = re.search(
            r'<p[^>]*class="paragraph"[^>]*>(?:(?!</p>).)*?waypoint\.indieformer\.com.*?</p>',
            out,
            re.DOTALL,
        )
        if not m:
            break
        out = out[: m.start()] + out[m.end():]

    # Remove "Every game above came from Waypoint" paragraphs even if their link was stripped above
    out = re.sub(
        r'<p[^>]*class="paragraph"[^>]*>[^<]*Every game above came from Waypoint.*?</p>',
        '',
        out,
        flags=re.DOTALL,
    )

    # Remove Beehiiv button blocks pointing to waypoint
    out = re.sub(
        r'<div\s+class="button"[^>]*>(?:(?!</div>).)*?waypoint\.indieformer\.com(?:(?!</div>).)*?</div>',
        '',
        out,
        flags=re.DOTALL,
    )

    # Unwrap any remaining <a href="...waypoint...">text</a> → text
    out = re.sub(
        r'<a[^>]+href="[^"]*waypoint\.indieformer\.com[^"]*"[^>]*>(.*?)</a>',
        r'\1',
        out,
        flags=re.DOTALL,
    )

    return out


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
    body = _strip_waypoint(body)
    body = _lazy_load_images(body)
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
  .post-content .paragraph, .post-content p { margin: 0 0 1.1em; color: var(--text-secondary); line-height: 1.7; }
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
    .post-header, .post-content { padding-left: 24px; padding-right: 24px; }
    .site-nav { padding: 10px 24px; flex-wrap: wrap; gap: 12px 18px; }
    .primary-nav { gap: 18px; }
    .primary-nav a { font-size: 14px; }
    .site-footer { grid-template-columns: 1fr; gap: 28px; padding: 36px 24px 24px; margin-top: 48px; }
    .post-content { font-size: 16px; }
  }
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://media.beehiiv.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=Caveat:wght@500;600;700&display=swap">

<meta name="description" content="{description}">
<link rel="canonical" href="{canonical_url}">
<meta name="robots" content="index, follow">

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
    <img class="footer-logo" src="/logo-stacked.png" alt="Indieformer">
    <p>A small indie game publisher. Run by Josh &amp; Clem in Melbourne, Australia.</p>
  </div>
  <div class="footer-col">
    <p class="footer-label">Guides &amp; reads</p>
    <ul>
      <li><a href="https://essay.indieformer.com">How to Really Make a Game</a></li>
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

    page = PAGE_TEMPLATE.format(
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
