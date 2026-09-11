#!/usr/bin/env python3
"""One-off PROBE (read-only). Discover partner API capability across keys/params.
Prints structure + unit counts only; redacts anything with USD. Delete after use."""
import os, json, datetime, urllib.request, urllib.error

CANDIDATES = ["STEAM_FINANCIAL_KEY","STEAM_PARNTER_KEY","STEAM_PARTNER_KEY","STEAM_API_KEY","STEAM_KEY"]
KEYS = {n: os.environ.get(n,"").strip() for n in CANDIDATES if os.environ.get(n,"").strip()}
APP = 3966510  # scorchpot
PARTNER = "https://partner.steam-api.com"

def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"if-probe"}), timeout=30) as r:
            return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")[:200]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def safe(b):
    lo=b.lower()
    return "[REDACTED: has usd/gross/net]" if ("usd" in lo or "gross_" in lo or "net_sales" in lo) else b[:220]

def summarize(body):
    try:
        j=json.loads(body); r=j.get("response",j)
        if not isinstance(r,dict): return f"resp type={type(r).__name__}"
        items=r.get("sales") or r.get("line_items") or r.get("results") or r.get("detailed_sales") or []
        units=sum(int(it.get("net_units_sold",it.get("units",0)) or 0) for it in items) if items else None
        flds=list(items[0].keys()) if items else None
        return f"keys={list(r.keys())} items={len(items)} units={units} fields={flds}"
    except Exception:
        return f"non-json: {safe(body)}"

def main():
    print("=== STEAM PROBE ===")
    print("keys present:", {k: f"len{len(v)}" for k,v in KEYS.items()} or "NONE")
    if not KEYS:
        return
    any_key=next(iter(KEYS.values()))

    # full interface dump (names only) — find any financial/sales interface
    st,body=get(f"{PARTNER}/ISteamWebAPIUtil/GetSupportedAPIList/v1/?key={any_key}")
    try:
        names=[i.get("name") for i in json.loads(body).get("apilist",{}).get("interfaces",[])]
        print(f"\nAll {len(names)} interfaces:")
        print(", ".join(names))
    except Exception as e:
        print("apilist parse err:", e)

    d1=(datetime.datetime.utcnow()-datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    d0=(datetime.datetime.utcnow()-datetime.timedelta(days=17)).strftime("%Y-%m-%d")

    for name,key in KEYS.items():
        print(f"\n################ KEY: {name} ################")
        # wishlist sanity
        st,body=get(f"{PARTNER}/IPartnerFinancialsService/GetAppWishlistReporting/v001/?key={key}&appid={APP}&date={d1}")
        wa=None
        try: wa=json.loads(body).get("response",{}).get("wishlist_summary",{}).get("wishlist_adds")
        except Exception: pass
        print(f"  Wishlist GetAppWishlistReporting: HTTP {st} adds={wa}")
        # sales variations
        variants = {
          "DetailedSales v001 date+hwm":      f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={key}&date={d1}&highwatermark_id=0",
          "DetailedSales v001 date+appid":    f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={key}&date={d1}&appid={APP}&highwatermark_id=0",
          "DetailedSales v001 range":         f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={key}&date_start={d0}&date_end={d1}&highwatermark_id=0",
          "DetailedSales v001 hwm-only":      f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v001/?key={key}&highwatermark_id=0",
          "DetailedSales v1 date":            f"{PARTNER}/IPartnerFinancialsService/GetDetailedSales/v1/?key={key}&date={d1}&highwatermark_id=0",
          "GetPartnerBalances v001":          f"{PARTNER}/IPartnerFinancialsService/GetPartnerBalances/v001/?key={key}",
        }
        for label,url in variants.items():
            st,body=get(url)
            print(f"  {label}: HTTP {st} len {len(body)} | {summarize(body)}")
    print("\n=== END PROBE ===")

if __name__ == "__main__":
    main()
