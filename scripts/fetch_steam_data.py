#!/usr/bin/env python3
"""
Fetch live Steam data for the Indieformer game pages and write per-game JSON
under data/<game>.json. The pages read these client-side.

Streams, each self-contained and stored with its own "through" date so runs are
incremental and can never double-count:

  players    - public GetNumberOfCurrentPlayers (no key). Scorchpot only.
  wishlists  - exact outstanding balance, reconstructed from the daily partner
               Wishlist reporting (adds - deletes - purchases - gifts), backfilled
               from the app's first date. Needs STEAM_FINANCIAL_KEY.
  units      - lifetime copies sold. SEEDED once from a known exact total, then
               each day's net units from GetDetailedSales is added. Needs the key.

Partner endpoints only work with a WebAPI key that has the Sales Data permission.
Run on the daily Action; safe to run more often. Backfill is capped per run and
resumes on the next run via the stored "through" dates.
"""
import os, sys, json, time, datetime, urllib.request, urllib.error

KEY      = os.environ.get("STEAM_FINANCIAL_KEY", "").strip()
DATA_DIR = os.environ.get("STEAM_DATA_DIR", "data")
PUBLIC   = "https://api.steampowered.com"
PARTNER  = "https://partner.steam-api.com"
TIMEOUT  = 30
BACKFILL_CAP = 400          # max days of wishlist history to process per run
UA = {"User-Agent": "indieformer-stats (indieformer.com)"}

# game slug -> config. Add encrafted once its page is live.
GAMES = {
    "scorchpot":       {"appid": 3966510, "players": True,  "wishlists": True, "units": True},
    "abelina":         {"appid": 3682900, "players": False, "wishlists": True, "units": False},
    "slots-slaughter": {"appid": 4504900, "players": False, "wishlists": True, "units": False},
}
# first sales date (launch) per game. Units are backfilled EXACTLY from here from
# the partner sales API, so there is no seed/boundary-date guesswork.
UNITS_START = {"scorchpot": "2026-08-20"}
UNITS_BACKFILL_CAP = 90   # sales dates per run (short history, so one run covers it)


def http_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def d(s):   # "YYYY-MM-DD" -> date
    return datetime.date.fromisoformat(s)

def ymd(dt):
    return dt.isoformat()

def yesterday_utc():
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)


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


def units_by_app_for_date(date_str):
    """({appid: net}, {appid: gross}) for a Pacific sales date, paginated over max_id."""
    net, gross, hwm = {}, {}, 0
    for _ in range(500):  # page guard
        r = http_json(f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/"
                      f"?key={KEY}&date={date_str}&highwatermark_id={hwm}").get("response", {})
        rows = r.get("results", []) or []
        for it in rows:
            aid = it.get("primary_appid")
            net[aid]   = net.get(aid, 0)   + int(it.get("net_units_sold", 0) or 0)
            gross[aid] = gross.get(aid, 0) + int(it.get("gross_units_sold", 0) or 0)
        mx = r.get("max_id")
        if not rows or not mx or mx == hwm:
            break
        hwm = mx
        time.sleep(0.1)
    return net, gross


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
    """Advance the stored cumulative wishlist balance up to `target` date."""
    status = "ok"
    # establish a starting point on first run
    if "wishlists" not in data or "wishlistsThrough" not in data:
        try:
            _, amin = wishlist_day(appid, ymd(target))
        except Exception as e:
            print(f"  wishlists: init FAILED {e}", file=sys.stderr)
            return "stale"
        start = d(amin) if amin else (target - datetime.timedelta(days=400))
        data["wishlists"] = 0
        data["wishlistsThrough"] = ymd(start - datetime.timedelta(days=1))
        print(f"  wishlists: seeding backfill from app_min_date {start}")

    cur = d(data["wishlistsThrough"])
    total = int(data["wishlists"])
    processed = 0
    while cur < target and processed < BACKFILL_CAP:
        day = cur + datetime.timedelta(days=1)
        try:
            net, _ = wishlist_day(appid, ymd(day))
        except Exception as e:
            print(f"  wishlists: stop at {day} ({e})", file=sys.stderr)
            status = "stale"
            break
        total += net
        cur = day
        processed += 1
        time.sleep(0.12)
    data["wishlists"] = total
    data["wishlistsThrough"] = ymd(cur)
    data["wishlistsAsOf"] = ymd(cur)
    caught = "caught up" if cur >= target else f"backfilling ({processed} days this run)"
    print(f"  wishlists: {total} through {cur} [{caught}]")
    return status


def update_units(slug, appid, data, target):
    """Backfill exact net units from the launch date to `target` (Pacific sales day)."""
    status = "ok"
    if "units" not in data or "unitsThrough" not in data:
        s = UNITS_START.get(slug)
        start = d(s) if s else (target - datetime.timedelta(days=30))
        data["units"] = 0
        data["unitsThrough"] = ymd(start - datetime.timedelta(days=1))
        print(f"  units: backfilling from launch {start}")

    cur = d(data["unitsThrough"])
    total = int(data["units"])
    gtotal = int(data.get("unitsGross", 0))
    processed = 0
    while cur < target and processed < UNITS_BACKFILL_CAP:
        day = cur + datetime.timedelta(days=1)
        try:
            net, gross = units_by_app_for_date(ymd(day))
        except Exception as e:
            print(f"  units: stop at {day} ({e})", file=sys.stderr)
            status = "stale"
            break
        total  += int(net.get(appid, 0))
        gtotal += int(gross.get(appid, 0))
        cur = day
        processed += 1
        time.sleep(0.1)
    data["units"] = total
    data["unitsGross"] = gtotal
    data["unitsThrough"] = ymd(cur)
    data["unitsAsOf"] = ymd(cur)
    caught = "caught up" if cur >= target else f"backfilling ({processed} days this run)"
    print(f"  units: {total} through {cur} [{caught}]")
    return status


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.datetime.now(datetime.timezone.utc).date()
    wl_target    = today - datetime.timedelta(days=1)   # wishlists finalise per GMT day
    sales_target = today - datetime.timedelta(days=2)   # sales are US Pacific; skip the day still closing
    have_key = bool(KEY)
    if not have_key:
        print("no STEAM_FINANCIAL_KEY: players only, keeping any stored wishlist/units.", file=sys.stderr)

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

        path = os.path.join(DATA_DIR, f"{slug}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"  -> {path}")


if __name__ == "__main__":
    main()
