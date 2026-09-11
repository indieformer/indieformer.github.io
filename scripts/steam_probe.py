#!/usr/bin/env python3
"""
One-off PROBE: discover what the Steamworks partner WebAPI key can actually pull.
Read-only. Prints STRUCTURE + unit counts only — never the key, never USD revenue
(public repo = public Action logs). Delete after we know the shape of the data.
"""
import os, sys, json, datetime, urllib.request, urllib.parse, urllib.error

CANDIDATES = ["STEAM_PARTNER_KEY","STEAM_API_KEY","STEAM_WEB_API_KEY","STEAM_WEBAPI_KEY",
              "STEAMWORKS_API_KEY","STEAMWORKS_KEY","STEAM_PUBLISHER_KEY","STEAM_KEY","STEAM_SECRET"]
KEY, SRC = "", ""
for _n in CANDIDATES:
    _v = os.environ.get(_n, "").strip()
    print(f"env {_n}: {'SET (len '+str(len(_v))+')' if _v else 'empty'}")
    if _v and not KEY:
        KEY, SRC = _v, _n
if KEY:
    print(f">>> using key from: {SRC}")
APPIDS = {"scorchpot": 3966510, "abelina": 3682900, "slots": 4504900, "encrafted": 4093900}
PARTNER = "https://partner.steam-api.com"

def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"if-probe"}), timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")[:300]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def redact(u):  # never print the key
    return u.replace(KEY, "***") if KEY else u

def main():
    print("=== STEAM PROBE ===")
    if not KEY:
        print("NO KEY: env STEAM_PARTNER_KEY is empty. Check the secret name.")
        return
    print(f"key present: yes (len {len(KEY)})")

    # 1) DISCOVERY — full list of methods this key can call, with parameters.
    print("\n--- GetSupportedAPIList (partner host) ---")
    st, body = get(f"{PARTNER}/ISteamWebAPIUtil/GetSupportedAPIList/v1/?key={KEY}")
    print("status:", st)
    try:
        ifaces = json.loads(body).get("apilist", {}).get("interfaces", [])
        print("total interfaces:", len(ifaces))
        for i in ifaces:
            name = i.get("name","")
            if any(k in name.lower() for k in ("financ","sales","wishlist","partner","player")):
                print(f"\n[{name}]")
                for m in i.get("methods", []):
                    params = ",".join(p.get("name") for p in m.get("parameters", []))
                    print(f"  {m.get('name')}/v{m.get('version')} ({m.get('httpmethod')}) params: {params}")
    except Exception as e:
        print("parse error:", e, "| body[:200]:", body[:200])

    # dates: wishlist=GMT, sales=Pacific. Use a few days back so data is finalised.
    d_gmt = (datetime.datetime.utcnow() - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    d_pac = (datetime.datetime.utcnow() - datetime.timedelta(days=3)).strftime("%Y-%m-%d")

    # 2) WISHLIST reporting — shape + values (wishlist numbers are non-sensitive)
    print(f"\n--- GetAppWishlistReporting (scorchpot, {d_gmt}) ---")
    st, body = get(f"{PARTNER}/IPartnerFinancialsService/GetAppWishlistReporting/v001/?key={KEY}&appid={APPIDS['scorchpot']}&date={d_gmt}")
    print("status:", st)
    try:
        resp = json.loads(body).get("response", json.loads(body))
        print("top-level keys:", list(resp.keys()))
        print("sample:", json.dumps(resp, indent=0)[:600])
    except Exception:
        print("body[:400]:", body[:400])

    # 3) DETAILED SALES — print KEYS + summed net units only. NO USD values.
    print(f"\n--- GetDetailedSales (all apps, {d_pac}) ---")
    st, body = get(f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={KEY}&date={d_pac}&highwatermark_id=0")
    print("status:", st)
    try:
        resp = json.loads(body).get("response", json.loads(body))
        print("top-level keys:", list(resp.keys()))
        items = resp.get("sales") or resp.get("line_items") or resp.get("results") or []
        print("line-item count:", len(items))
        if items:
            print("line-item field names:", list(items[0].keys()))
            per_app = {}
            for it in items:
                aid = it.get("primary_appid") or it.get("appid")
                per_app[aid] = per_app.get(aid, 0) + int(it.get("net_units_sold", 0) or 0)
            print("net UNITS by appid (that day):", per_app)
        if "max_id" in resp or "highwatermark_id" in resp:
            print("pagination present:", resp.get("max_id", resp.get("highwatermark_id")))
    except Exception:
        print("body[:400]:", body[:400])

    print("\n=== END PROBE ===")

if __name__ == "__main__":
    main()
