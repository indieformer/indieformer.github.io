#!/usr/bin/env python3
"""
One-off PROBE: discover what the Steamworks partner WebAPI key can actually pull.
Read-only. Prints STRUCTURE + unit counts only — never the key, never USD revenue
(public repo = public Action logs). Delete after we know the shape of the data.
"""
import os, sys, json, datetime, urllib.request, urllib.parse, urllib.error

CANDIDATES = ["STEAM_PARNTER_KEY","STEAM_PARTNER_KEY","STEAM_API_KEY","STEAM_WEB_API_KEY","STEAM_WEBAPI_KEY",
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

    # 3) SALES — diagnose shape across dates + candidate methods. Structure only; redact if monetary.
    def safe(body):
        low = body.lower()
        return "[REDACTED: contains sales/usd values]" if ("usd" in low or "gross_sales" in low or "net_sales" in low) else body[:260]
    dates = [d_pac,
             (datetime.datetime.utcnow()-datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
             (datetime.datetime.utcnow()-datetime.timedelta(days=14)).strftime("%Y-%m-%d")]
    methods = [
        f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={KEY}&date=DATE&highwatermark_id=0",
        f"{PARTNER}/IPartnerFinancialsService/GetPackageSalesData/v001/?key={KEY}&date=DATE",
        f"{PARTNER}/ISteamApps/GetSalesData/v1/?key={KEY}&date=DATE",
    ]
    for tmpl in methods:
        base=tmpl.split('?')[0]
        print(f"\n--- {base.rsplit('/',3)[-3]}/{base.rsplit('/',2)[-2]} ---")
        for dt in dates:
            st, body = get(tmpl.replace("DATE", dt))
            info=""
            try:
                j=json.loads(body); r=j.get("response", j)
                items = (r.get("sales") or r.get("line_items") or r.get("results") or r.get("detailed_sales") or []) if isinstance(r,dict) else []
                keys = list(r.keys()) if isinstance(r,dict) else type(r).__name__
                units=None
                if items:
                    units=sum(int(it.get("net_units_sold",it.get("units",0)) or 0) for it in items)
                info=f"resp keys={keys} items={len(items)} unitsThatDay={units} fields={list(items[0].keys()) if items else None}"
            except Exception:
                info=f"non-json: {safe(body)}"
            print(f"  {dt}: HTTP {st} len {len(body)} | {info}")

    print("\n=== END PROBE ===")

if __name__ == "__main__":
    main()
