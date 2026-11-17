#!/usr/bin/env python3
"""Check a trial Cumulus import into a copy of the weewxscw database.

Usage: python3 -I verify_trial.py TRIAL_DB BACKUP_DB DAYFILE

- weewxscw's own records (those in BACKUP_DB) must be unchanged in TRIAL_DB.
- For each day in Cumulus's dayfile.txt (fields: 0 date dd/mm/yy, 1 high gust,
  4 low temp, 6 high temp, 14 rain total), compare with the imported archive
  records of that local (America/New_York) day. Cumulus's dayfile highs/lows
  come from its 2-second readings, the archive from 10-minute averages, so
  small differences (archive high a bit lower, low a bit higher) are normal.
"""
import collections
import datetime
import sqlite3
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
trial, backup, dayfile = sys.argv[1:4]

t = sqlite3.connect(f"file:{trial}?mode=ro", uri=True)
b = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)

cols = [r[1] for r in b.execute("pragma table_info(archive)")]
own = b.execute("select * from archive order by dateTime").fetchall()
same = sum(1 for row in own
           if t.execute(f"select * from archive where dateTime=?", (row[0],)).fetchone() == row)
print(f"weewxscw's own records unchanged: {same}/{len(own)}")

n, first, last = t.execute("select count(*), min(dateTime), max(dateTime) from archive").fetchone()
print(f"trial archive: {n} records, {datetime.datetime.fromtimestamp(first, TZ)} .. "
      f"{datetime.datetime.fromtimestamp(last, TZ)}")
nd = t.execute("select count(*) from archive_day_outTemp").fetchone()[0]
print(f"daily summary days (outTemp): {nd}")

days = collections.defaultdict(lambda: {"hi": None, "lo": None, "rain": 0.0, "gust": None, "n": 0})
for ts, ot, rain, gust in t.execute(
        "select dateTime, outTemp, rain, windGust from archive"):
    # archive timestamp marks the END of the interval
    d = (datetime.datetime.fromtimestamp(ts, TZ) - datetime.timedelta(seconds=1)).date()
    x = days[d]; x["n"] += 1
    if ot is not None:
        x["hi"] = ot if x["hi"] is None else max(x["hi"], ot)
        x["lo"] = ot if x["lo"] is None else min(x["lo"], ot)
    if rain is not None:
        x["rain"] += rain
    if gust is not None:
        x["gust"] = gust if x["gust"] is None else max(x["gust"], gust)

stats = collections.Counter(); bad = []
for line in open(dayfile, encoding="latin-1"):
    f = line.strip().split(",")
    if len(f) < 15:
        continue
    d = datetime.datetime.strptime(f[0], "%d/%m/%y").date()
    if d not in days or days[d]["n"] < 100:     # skip partial days (gaps, cutoff)
        stats["skipped (partial/no data)"] += 1
        continue
    x = days[d]; stats["days compared"] += 1
    hi, lo, rain, gust = float(f[6]), float(f[4]), float(f[14]), float(f[1])
    dhi, dlo, drain = hi - x["hi"], x["lo"] - lo, abs(rain - x["rain"])
    stats["temp hi within 1F"] += dhi <= 1.0
    stats["temp lo within 1F"] += dlo <= 1.0
    stats["rain within 0.01in"] += drain <= 0.011
    stats["gust within 2mph"] += abs(gust - (x["gust"] or 0)) <= 2
    if dhi > 2 or dlo > 2 or drain > 0.05:
        bad.append(f"  {d}: hi {hi} vs {x['hi']}, lo {lo} vs {x['lo']}, "
                   f"rain {rain} vs {x['rain']:.2f}, records {x['n']}")
for k, v in stats.items():
    print(f"{k}: {v}")
print(f"days with a bigger difference (hi/lo > 2F or rain > 0.05in): {len(bad)}")
print("\n".join(bad[:40]))
