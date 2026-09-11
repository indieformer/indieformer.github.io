#!/usr/bin/env python3
"""
Fetch live Steam data for the Indieformer game pages and write per-game JSON
under data/<game>.json. The pages read these client-side.

Three streams, each stored with its own "through" date so runs are incremental
and never double-count:

  players    - public GetNumberOfCurrentPlayers (no key). Scorchpot only.
  wishlists  - EXACT outstanding balance, reconstructed from the daily partner
               Wishlist reporting (adds - deletes - purchases - gifts), backfilled
               from the app's first date then kept current. Uses the GMT day.
  units      - lifetime copies sold. ANCHORED to the exact dashboard total (a
               known figure the dev reads off Steamworks), then advanced by each
               day's net_units_sold. Uses the Steamworks/Pacific sales day.

Why units are anchored, not summed from scratch: the partner sales feed's
per-line units don't reconstruct the dashboard's headline "lifetime units"
exactly (gross vs net vs bundle accounting), so the dev's dashboard number is
the source of truth. Re-seed it (bump UNIT_SEED + clear the stored fields) if it
ever drifts. Needs STEAM_FINANCIAL_KEY (Sales Data permission).
"""
import os, sys, json, time, datetime, urllib.request, urllib.error
from zoneinfo import ZoneInfo

KEY      = os.environ.get("STEAM_FINANCIAL_KEY", "").strip()
DATA_DIR = os.environ.get("STEAM_DATA_DIR", "data")
PUBLIC   = "https://api.steampowered.com"
PARTNER  = "https://partner.steam-api.com"
TIMEOUT  = 30
BACKFILL_CAP = 400          # max wishlist days to process per run (resumes next run)
PACIFIC  = ZoneInfo("America/Los_Angeles")   # Steamworks closes the sales day on Pacific time
UA = {"User-Agent": "indieformer-stats (indieformer.com)"}

GAMES = {
    "scorchpot":       {"appid": 3966510, "players": True,  "wishlists": True, "units": True},
    "abelina":         {"appid": 3682900, "players": False, "wishlists": True, "units": False},
    "slots-slaughter": {"appid": 4504900, "players": False, "wishlists": True, "units": False},
}
# exact lifetime units from the Steamworks dashboard, as of the seed's "through" day.
UNIT_SEED = {"scorchpot": 20024}


def http_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def d(s):    return datetime.date.fromisoformat(s)
def ymd(dt): return dt.isoformat()


def get_players(appid):
    try:
        r = http_json(f"{PUBLIC}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}")
        return int(r.get("response", {}).get("player_count", 0))
    except Exception as e:
        print(f"  players: FAILED {e}", file=sys.stderr)
        return None


def wishlist_day(appid, date_str):
    """(net_change, app_min_date). net = adds - deletes - purchases - gifts."""
    r = http_json(f"{PARTNER}/IPartnerFinancialsService/GetAppWishlistReporting/v001/"
                  f"?key={KEY}&appid={appid}&date={date_str}").get("response", {})
    w = r.get("wishlist_summary", {}) or {}
    net = (int(w.get("wishlist_adds", 0)) - int(w.get("wishlist_deletes", 0))
           - int(w.get("wishlist_purchases", 0)) - int(w.get("wishlist_gifts", 0)))
    return net, r.get("app_min_date")


def net_units_by_app(date_str):
    """{appid: net_units_sold} for a Pacific sales date, paginated over max_id."""
    per, hwm = {}, 0
    for _ in range(500):
        r = http_json(f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/"
                      f"?key={KEY}&date={date_str}&highwatermark_id={hwm}").get("response", {})
        rows = r.get("results", []) or []
        for it in rows:
            aid = it.get("primary_appid")
            per[aid] = per.get(aid, 0) + int(it.get("net_units_sold", 0) or 0)
        mx = r.get("max_id")
        if not rows or not mx or mx == hwm:
            break
        hwm = mx
        time.sleep(0.1)
    return per


def load(slug):
    path = os.path.join(DATA_DIR, f"{slug}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def update_wishlists(slug, appid, data, target):
    status = "ok"
    if "wishlists" not in data or "wishlistsThrough" not in data:
        try:
            _, amin = wishlist_day(appid, ymd(target))
        except Exception as e:
            print(f"  wishlists: init FAILED {e}", file=sys.stderr)
            return "stale"
        start = d(amin) if amin else (target - datetime.timedelta(days=400))
        data["wishlists"] = 0
        data["wishlistsThrough"] = ymd(start - datetime.timedelta(days=1))
        print(f"  wishlists: backfilling from app_min_date {start}")

    cur, total, processed = d(data["wishlistsThrough"]), int(data["wishlists"]), 0
    while cur < target and processed < BACKFILL_CAP:
        day = cur + datetime.timedelta(days=1)
        try:
            net, _ = wishlist_day(appid, ymd(day))
        except Exception as e:
            print(f"  wishlists: stop at {day} ({e})", file=sys.stderr)
            status = "stale"; break
        total += net; cur = day; processed += 1
        time.sleep(0.12)
    data["wishlists"], data["wishlistsThrough"], data["wishlistsAsOf"] = total, ymd(cur), ymd(cur)
    print(f"  wishlists: {total} through {cur} [{'caught up' if cur >= target else f'backfilling ({processed})'}]")
    return status


def update_units(slug, appid, data, target):
    """Anchor to the dashboard seed, then add each day's net units up to `target`."""
    if "units" not in data or "unitsThrough" not in data:
        data["units"] = int(UNIT_SEED.get(slug, 0))
        data["unitsThrough"] = ymd(target)     # seed is the total THROUGH target
        data["unitsAsOf"] = ymd(target)
        print(f"  units: anchored {data['units']} through {target}")
        return "ok"

    cur, total, status = d(data["unitsThrough"]), int(data["units"]), "ok"
    while cur < target:
        day = cur + datetime.timedelta(days=1)
        try:
            per = net_units_by_app(ymd(day))
        except Exception as e:
            print(f"  units: stop at {day} ({e})", file=sys.stderr)
            status = "stale"; break
        total += int(per.get(appid, 0)); cur = day
        time.sleep(0.1)
    data["units"], data["unitsThrough"], data["unitsAsOf"] = total, ymd(cur), ymd(cur)
    print(f"  units: {total} through {cur}")
    return status


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    wl_target    = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)  # GMT day
    sales_target = datetime.datetime.now(PACIFIC).date() - datetime.timedelta(days=1)                 # Steamworks/Pacific day
    have_key = bool(KEY)
    if not have_key:
        print("no STEAM_FINANCIAL_KEY: players only.", file=sys.stderr)

    for slug, cfg in GAMES.items():
        print(f"[{slug}] appid {cfg['appid']}")
        data = load(slug)
        data["appId"] = cfg["appid"]
        status = data.get("_status", {}) if isinstance(data.get("_status"), dict) else {}

        if cfg["players"]:
            p = get_players(cfg["appid"])
            if p is not None:
                data["players"] = p
                data["playersAsOf"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
                status["players"] = "ok"
            else:
                status["players"] = "stale"

        if have_key and cfg["wishlists"]:
            status["wishlists"] = update_wishlists(slug, cfg["appid"], data, wl_target)
        if have_key and cfg["units"]:
            status["units"] = update_units(slug, cfg["appid"], data, sales_target)

        data["_status"] = status
        data["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with open(os.path.join(DATA_DIR, f"{slug}.json"), "w") as f:
            json.dump(data, f, indent=2); f.write("\n")
        print(f"  -> data/{slug}.json")


if __name__ == "__main__":
    main()
