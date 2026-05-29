#!/usr/bin/env python3
"""
Build notes.html from the Indieformer beehiiv RSS feed.

Run manually with `python3 scripts/build_notes.py`, or via the GitHub Action
.github/workflows/refresh-notes.yml on a daily schedule.

Output path defaults to ./notes/ (cwd-relative) — override with NOTES_OUT.
"""
import os, re, html, sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEED = "https://rss.beehiiv.com/feeds/2WtWfTwjg3.xml"
OUT  = os.environ.get("NOTES_OUT", "notes/index.html")
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
NS_MEDIA   = "http://search.yahoo.com/mrss/"


def fetch_feed() -> str:
    req = urllib.request.Request(
        FEED,
        headers={"User-Agent": "Mozilla/5.0 (notes-builder; indieformer.com)"}
    )
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8")


def text(elem, tag) -> str:
    v = elem.find(tag)
    return (v.text or "").strip() if v is not None else ""


def get_ns(elem, tag, ns) -> str:
    v = elem.find(f"{{{ns}}}{tag}")
    return (v.text or "").strip() if v is not None else ""


def extract_image(item) -> str | None:
    # 1. <enclosure url="...">
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        return enc.get("url")
    # 2. <media:content url="...">
    mc = item.find(f"{{{NS_MEDIA}}}content")
    if mc is not None and mc.get("url"):
        return mc.get("url")
    # 3. first <img src="..."> inside <content:encoded> HTML
    enc_html = get_ns(item, "encoded", NS_CONTENT)
    if enc_html:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', enc_html, re.I)
        if m:
            url = m.group(1)
            if "1x1" not in url and "pixel" not in url.lower():
                return url
    return None


def parse_posts(xml_str):
    root = ET.fromstring(xml_str)
    items = root.find("channel").findall("item")
    posts = []
    for it in items:
        title = text(it, "title")
        link  = text(it, "link").replace(
            "https://www.indieformer.com/",
            "https://indieformer.beehiiv.com/"
        )
        pub   = text(it, "pubDate")
        desc  = text(it, "description")
        cat   = text(it, "category")
        img   = extract_image(it)
        try:
            dt = parsedate_to_datetime(pub)
            date_human = dt.strftime("%-d %b %Y")
            date_iso   = dt.strftime("%Y-%m-%d")
        except Exception:
            date_human, date_iso = pub, ""
        excerpt = re.sub(r"\s+", " ", desc).strip()
        if len(excerpt) > 200:
            excerpt = excerpt[:200].rsplit(" ", 1)[0] + "…"
        cat = cat.lower() if cat else ""
        posts.append({
            "title": title, "link": link,
            "date_human": date_human, "date_iso": date_iso,
            "excerpt": excerpt, "cat": cat, "img": img,
        })
    return posts


def render_entries(posts) -> str:
    out = []
    for p in posts:
        tag_html = f'<span class="note-tag">{html.escape(p["cat"])}</span>' if p["cat"] else ""
        img_html = (
            f'<div class="note-thumb"><img src="{html.escape(p["img"])}" alt="" loading="lazy"></div>'
            if p["img"] else ""
        )
        out.append(f'''
    <article class="note-card{' has-thumb' if p["img"] else ''}">
      <a class="note-link" href="{html.escape(p["link"])}" target="_blank" rel="noopener">
        {img_html}
        <div class="note-body">
          <div class="note-meta">
            {tag_html}
            <time datetime="{p["date_iso"]}">{html.escape(p["date_human"])}</time>
          </div>
          <h3 class="note-title">{html.escape(p["title"])}</h3>
          <p class="note-excerpt">{html.escape(p["excerpt"])}</p>
        </div>
      </a>
    </article>''')
    return "\n".join(out)


PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Notes | Indieformer</title>

<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">

<meta name="description" content="Notes from Indieformer. We try to post at least monthly about what we're learning and doing as a publisher.">
<link rel="canonical" href="https://indieformer.com/notes/">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Indieformer">
<meta property="og:title" content="Notes | Indieformer">
<meta property="og:description" content="What we're learning and doing as a publisher.">
<meta property="og:url" content="https://indieformer.com/notes/">
<meta property="og:image" content="https://indieformer.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">

<style>
  @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=Caveat:wght@500;600;700&display=swap');

  :root {{
    --emerald: #28E291; --coral: #F78154; --periwinkle: #9381FF;
    --shadow: #262730; --shadow-mid: #2F3040;
    --text-primary: #F0EEE8; --text-secondary: #A8A6B8; --text-tertiary: #6B6980;
    --border: rgba(255, 255, 255, 0.08); --border-mid: rgba(255, 255, 255, 0.16);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ min-height: 100%; }}
  body {{
    position: relative;
    background: var(--shadow);
    background-image: radial-gradient(circle, rgba(255,255,255,0.045) 1px, transparent 1.4px);
    background-size: 26px 26px;
    font-family: 'Sora', Arial, sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    padding: 28px 20px;
    overflow-x: hidden;
  }}

  .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); border: 0; }}

  .crop {{
    position: absolute; width: 18px; height: 18px;
    opacity: 0; animation: fade 0.6s ease 0.2s forwards;
    z-index: 5; pointer-events: none;
  }}
  .crop::before, .crop::after {{ content: ''; position: absolute; background: var(--text-tertiary); }}
  .crop::before {{ left: 0; right: 0; top: 50%; height: 1.5px; transform: translateY(-50%); }}
  .crop::after  {{ top: 0; bottom: 0; left: 50%; width: 1.5px; transform: translateX(-50%); }}
  .crop.tl {{ top: 20px; left: 20px; }}
  .crop.tr {{ top: 20px; right: 20px; }}
  .crop.bl {{ bottom: 20px; left: 20px; }}
  .crop.br {{ bottom: 20px; right: 20px; }}

  .site-nav {{
    display: flex; align-items: center; justify-content: space-between;
    max-width: 1000px; margin: 0 auto; padding: 14px 56px;
    position: relative; z-index: 4;
  }}
  a.brand {{
    display: inline-flex; align-items: center;
    text-decoration: none; transition: opacity 0.2s ease;
  }}
  a.brand img {{ display: block; height: 40px; width: 40px; }}
  a.brand:hover {{ opacity: 0.82; }}
  .primary-nav {{ display: flex; gap: 26px; align-items: center; }}
  .primary-nav a {{
    font-family: 'Sora'; font-size: 15px; font-weight: 500;
    color: var(--text-secondary); text-decoration: none;
    position: relative; transition: color 0.2s;
  }}
  .primary-nav a:hover {{ color: var(--text-primary); }}
  .primary-nav a.current {{ color: var(--text-primary); font-weight: 600; }}
  .primary-nav a.current::after {{
    content: ''; position: absolute; left: 0; right: 0; bottom: -7px;
    height: 2px; background: var(--emerald); border-radius: 2px;
  }}

  .section {{
    position: relative;
    width: 100%; max-width: 1000px; margin: 0 auto;
    padding: 40px 56px 16px;
    z-index: 1;
  }}
  .col {{ max-width: 720px; position: relative; z-index: 2; }}
  h1 {{
    font-size: clamp(38px, 6vw, 56px);
    font-weight: 800; line-height: 1.05; letter-spacing: -0.025em;
    margin-bottom: 14px;
  }}
  .page-lede {{
    font-family: 'Caveat', cursive; font-size: 26px; color: var(--coral);
    transform: rotate(-1deg); display: inline-block; margin-bottom: 18px;
  }}
  .page-desc {{
    color: var(--text-secondary); line-height: 1.65; font-size: 16px; max-width: 560px;
  }}

  .notes-list {{ max-width: 780px; margin: 0 auto; padding: 24px 56px 8px; position: relative; z-index: 2; }}
  .notes-list .note-card:first-of-type {{ border-top: 1px solid var(--border); }}
  .note-card {{ padding: 22px 0; border-bottom: 1px solid var(--border); }}
  .note-link {{
    display: grid; grid-template-columns: 1fr; gap: 0;
    text-decoration: none; color: inherit;
  }}
  .note-card.has-thumb .note-link {{
    grid-template-columns: 140px 1fr; gap: 22px; align-items: start;
  }}
  .note-thumb {{
    width: 140px; height: 90px;
    overflow: hidden; border-radius: 8px;
    background: var(--shadow-mid);
    border: 1px solid var(--border);
    transition: border-color 0.2s ease;
  }}
  .note-thumb img {{
    width: 100%; height: 100%; object-fit: cover; display: block;
    transition: transform 0.4s ease;
  }}
  .note-link:hover .note-thumb {{ border-color: var(--emerald); }}
  .note-link:hover .note-thumb img {{ transform: scale(1.04); }}
  .note-meta {{
    display: flex; gap: 14px; align-items: baseline;
    margin-bottom: 6px;
    font-size: 13px; color: var(--text-tertiary);
  }}
  .note-tag {{
    font-family: 'Caveat', cursive; font-size: 18px; color: var(--coral);
    transform: rotate(-1.5deg); display: inline-block; line-height: 1;
  }}
  .note-title {{
    font-family: 'Sora'; font-size: 21px; font-weight: 700; line-height: 1.3;
    color: var(--text-primary); margin-bottom: 6px;
    transition: color 0.2s ease;
  }}
  .note-link:hover .note-title {{ color: var(--emerald); }}
  .note-excerpt {{ font-size: 15px; line-height: 1.6; color: var(--text-secondary); }}

  .archive-link {{
    max-width: 780px; margin: 0 auto; padding: 24px 56px 8px;
    font-size: 15px; color: var(--text-tertiary);
  }}
  .archive-link a {{
    color: var(--emerald); text-decoration: none; font-weight: 600;
    border-bottom: 2px solid rgba(40, 226, 145, 0.42);
    transition: color 0.2s, border-color 0.2s;
  }}
  .archive-link a:hover {{ color: var(--text-primary); border-bottom-color: var(--text-primary); }}

  .site-footer {{
    max-width: 1000px; margin: 60px auto 0;
    padding: 44px 56px 28px;
    border-top: 1px solid var(--border);
    display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 40px;
    font-size: 14px; line-height: 1.65; color: var(--text-secondary);
    position: relative; z-index: 2;
  }}
  .footer-col.brand-col {{ display: flex; gap: 18px; align-items: flex-start; }}
  .footer-logo {{ flex: 0 0 auto; height: 92px; width: auto; display: block; }}
  .footer-col.brand-col p {{ flex: 1; margin: 0; line-height: 1.65; color: var(--text-secondary); }}
  .footer-label {{ font-family: 'Caveat'; font-size: 22px; color: var(--text-tertiary); margin-bottom: 6px; transform: rotate(-1deg); display: inline-block; }}
  .footer-col ul {{ list-style: none; }}
  .footer-col li {{ margin-bottom: 6px; }}
  .footer-col a {{ color: var(--text-secondary); text-decoration: none; border-bottom: 1px solid transparent; transition: color 0.2s, border-color 0.2s; }}
  .footer-col a:hover {{ color: var(--text-primary); border-bottom-color: var(--text-primary); }}
  .footer-meta {{ grid-column: 1 / -1; border-top: 1px solid var(--border); margin-top: 22px; padding-top: 18px; font-size: 13px; color: var(--text-tertiary); }}
  .footer-meta a {{ color: var(--text-tertiary); border-bottom: 1px solid transparent; text-decoration: none; }}
  .footer-meta a:hover {{ color: var(--text-primary); border-bottom-color: var(--text-primary); }}

  @keyframes fade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}

  @media (max-width: 820px) {{
    body {{ padding: 20px 14px; }}
    .section, .notes-list, .archive-link {{ padding-left: 24px; padding-right: 24px; }}
    .site-nav {{ padding: 10px 24px; flex-wrap: wrap; gap: 12px 18px; }}
    .primary-nav {{ gap: 18px; }}
    .primary-nav a {{ font-size: 14px; }}
    .site-footer {{ grid-template-columns: 1fr; gap: 28px; padding: 36px 24px 24px; margin-top: 48px; }}
    .note-title {{ font-size: 19px; }}
    .note-card.has-thumb .note-link {{ grid-template-columns: 100px 1fr; gap: 14px; }}
    .note-thumb {{ width: 100px; height: 68px; }}
  }}
  @media (max-width: 500px) {{
    .note-card.has-thumb .note-link {{ grid-template-columns: 1fr; gap: 12px; }}
    .note-thumb {{ width: 100%; height: 160px; }}
  }}
</style>
</head>
<body>

<span class="crop tl"></span><span class="crop tr"></span>
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
    <h1>Notes.</h1>
    <p class="page-lede">the free notes we send out.</p>
    <p class="page-desc">
      We try to post at least monthly about what we're learning and doing as a publisher.
      The most recent are below.
    </p>
  </div>
</section>

<main class="notes-list" id="notes">
{posts_html}
</main>

<p class="archive-link">All {total} issues live on the <a href="https://indieformer.beehiiv.com">full archive →</a></p>

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
      <li><a href="https://waypoint.indieformer.com">Waypoint archive</a></li>
      <li><a href="https://indieformer.beehiiv.com">Newsletter archive</a></li>
    </ul>
  </div>
  <p class="footer-meta">© 2026 Indieformer.</p>
</footer>

</body>
</html>
'''


def main():
    xml_str = fetch_feed()
    posts = parse_posts(xml_str)
    print(f"parsed {len(posts)} posts ({sum(1 for p in posts if p['img'])} with images)",
          file=sys.stderr)
    page = PAGE_TEMPLATE.format(
        posts_html=render_entries(posts),
        total=77,  # NOTE: total published in the publication — bump when archive grows
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {OUT} ({len(page)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
