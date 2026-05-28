#!/usr/bin/env python3
"""
Fetch live Steam data for Feed the Scorchpot and write it to data/scorchpot.json.

scorchpot.html reads this file client-side to populate the live tracker tile.
Run on the same daily GitHub Action cron that refreshes the notes index.

Override the output path with SCORCHPOT_DATA_OUT.
"""
import os, sys, json, datetime, urllib.request, urllib.error

DEMO_APP_ID = 4338170  # Feed the Scorchpot Demo
OUT         = os.environ.get("SCORCHPOT_DATA_OUT", "data/scorchpot.json")
TIMEOUT     = 12

def get_demo_players(app_id: int) -> int | None:
    url = (
        "https://api.steampowered.com/ISteamUserStats/"
        f"GetNumberOfCurrentPlayers/v1/?appid={app_id}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (scorchpot-tracker; indieformer.com)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
        return int(data.get("response", {}).get("player_count", 0))
    except (urllib.error.URLError, ValueError, TypeError) as e:
        print(f"warning: Steam API call failed: {e}", file=sys.stderr)
        return None


def main():
    players = get_demo_players(DEMO_APP_ID)
    now = datetime.datetime.now(datetime.timezone.utc)

    # If the API fails, keep the previous value if we can read it,
    # so a transient outage doesn't blank the tile.
    fallback_players = None
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                fallback_players = json.load(f).get("demoPlayers")
        except Exception:
            pass

    payload = {
        "demoPlayers": players if players is not None else fallback_players,
        "demoPlayersAsOf": now.isoformat(timespec="seconds"),
        "demoAppId": DEMO_APP_ID,
        "_apiStatus": "ok" if players is not None else "stale",
    }

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    print(
        f"Steam demo players: {payload['demoPlayers']}  "
        f"({payload['_apiStatus']}) → {OUT}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
