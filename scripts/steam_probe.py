#!/usr/bin/env python3
# One-off: reveal how units/returns are structured in GetDetailedSales. Units + types only, no USD.
import os, json, datetime, urllib.request
from zoneinfo import ZoneInfo
KEY=os.environ.get("STEAM_FINANCIAL_KEY","").strip()
if not KEY: print("NO KEY"); raise SystemExit
date=(datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date()-datetime.timedelta(days=2)).isoformat()
rows=[]; hwm=0
for _ in range(500):
    u=f"https://partner.steam-api.com/IPartnerFinancialsService/GetDetailedSales/v001/?key={KEY}&date={date}&highwatermark_id={hwm}"
    r=json.loads(urllib.request.urlopen(u,timeout=30).read().decode()).get("response",{})
    rr=r.get("results",[]) or []; rows+=rr
    mx=r.get("max_id")
    if not rr or not mx or mx==hwm: break
    hwm=mx
def s(f): return sum(int(x.get(f,0) or 0) for x in rows)
print("=== PROBE date",date,"rows",len(rows),"===")
print("sum net_units_sold   :", s("net_units_sold"))
print("sum gross_units_sold :", s("gross_units_sold"))
print("sum gross_units_returned:", s("gross_units_returned"))
print("rows with net<0      :", sum(1 for x in rows if int(x.get('net_units_sold',0) or 0)<0))
print("line_item_types      :", sorted(set(str(x.get('line_item_type')) for x in rows)))
for x in rows[:5]:
    print("row:", {k:x[k] for k in x if ('unit' in k.lower()) or k in ('line_item_type','primary_appid','package_sale_type')})
print("=== END ===")
