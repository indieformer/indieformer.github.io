# indieformer.com

The Indieformer marketing site. Hand-built static HTML on GitHub Pages, served at **[indieformer.com](https://indieformer.com)**.

## What's here

- `index.html` — homepage
- `how-we-make-a-game-popular.html` — how we approach publishing a game
- `CNAME` — pins the custom domain to `indieformer.com`

## Related properties (separate repos)

- **Newsletter** — runs on beehiiv. Archive at `indieformer.beehiiv.com`.
- **Essay** — [`essay.indieformer.com`](https://essay.indieformer.com) → [`indieformer/essay`](https://github.com/indieformer/essay)
- **Waypoint archive** — [`waypoint.indieformer.com`](https://waypoint.indieformer.com) → [`indieformer/waypoint-archive`](https://github.com/indieformer/waypoint-archive) — the decommissioned indie game release tracker

## Local development

The pages are self-contained. No build step, no dependencies — just open the files in a browser, or serve locally:

```bash
python3 -m http.server 8000
# then http://localhost:8000
```

## Deployment

Pushes to `main` trigger GitHub Pages to rebuild automatically. The custom domain is pinned by the `CNAME` file at the repo root.

— Josh & Clem
