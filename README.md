# indieformer.com

The Indieformer marketing site. Hand-built static HTML on GitHub Pages, served at **[indieformer.com](https://indieformer.com)**.

## Layout

Folder per page. A page served at `/scorchpot/` is committed as `scorchpot/index.html`. Assets are referenced with absolute paths so a page works at any depth.

- `index.html`, `404.html`, `CNAME`, `.nojekyll`
- `site-chrome.js` injects the top nav and main footer into `[data-shared-nav]` / `[data-shared-footer]`. **To add or remove a nav item, edit `NAV_LINKS` in that file and nowhere else.**
- `how-we-make-a-game-popular/`, `press-kit-guide/`, `steam-marketing-guide/`, `essay/`, `privacy/`, `terms/`
- `scorchpot/`, `abelina/`, `slots-slaughter/`, each with a `presskit/`. Game pages and press kits have bespoke chrome on purpose and do not use `site-chrome.js`.
- `notes/` is generated. Do not hand-edit it.
- `fonts/` holds self-hosted woff2 (Sora, Caveat, plus display faces). No Google Fonts in production.
- `data/` holds generated Steam figures the game pages read client-side.

## The daily build

`.github/workflows/refresh-notes.yml` runs at 07:00 UTC, and from the "Run workflow" button:

1. `scripts/build_notes.py` pulls published posts from the beehiiv API and writes a page per post plus the three tabbed indexes (`/notes/`, `/notes/frontline/`, `/notes/archive/`). Caches against `notes/.posts.json`. Bump `TEMPLATE_VERSION` to force a full rebuild.
2. `scripts/build_post.py` is the page template and the beehiiv sanitiser. Library only, no API calls.
3. `scripts/fetch_steam_data.py` writes `data/<game>.json`: current players, outstanding wishlists, and gross units sold. Incremental, resumes from the stored `*Through` dates.

Then it commits whatever changed as `indieformer-bot`.

Repo secrets: `BEEHIIV_API_KEY`, `STEAM_FINANCIAL_KEY`.

## Related properties

- **Newsletter** runs on beehiiv. Archive at `indieformer.beehiiv.com`.
- **Waypoint archive** at [`waypoint.indieformer.com`](https://waypoint.indieformer.com), repo [`indieformer/waypoint-archive`](https://github.com/indieformer/waypoint-archive). The decommissioned indie game release tracker.

The essay used to live on its own subdomain. It is now in this repo at `/essay/`.

## Local development

No build step, no dependencies. Serve the repo root:

```bash
python3 -m http.server 8000
```

Absolute asset paths mean you have to serve it. Opening a file directly will not load the chrome, fonts or images.

## Deployment

Push to `main`. Pages rebuilds in under a minute. The custom domain is pinned by `CNAME`.

If a push is rejected, the daily Action has moved `main` ahead of you:

```bash
git fetch origin main && git rebase origin/main
```

Content changes never conflict with its `notes/` and `data/` commits.

— Josh & Clem
