#!/usr/bin/env python3
"""Clean the Florida (SanCap) Cumulus 1 monthly logs before importing them
into weewxscw. Adapted from weewxrtlsdr/cumulus-import/clean_cumulus.py; the
Florida data is much cleaner, so only these fixes are needed:

  1. Corrupt bytes: Aug26log.txt has a run of NUL bytes (Windows crash/power
     loss while Cumulus was writing). Strip NULs; drop any line that then
     doesn't have 27 fields or a valid dd/mm/yy hh:mm timestamp.
  2. Exact duplicate lines: keep the first.
  3. Out-of-order stray rows (e.g. a 06:30 row logged between 06:00 and 06:10,
     probably around Cumulus restarts): keep the longest strictly increasing
     run of timestamps in file order and drop the rest. This also keeps only
     one copy of the repeated hour when daylight saving ends (weewx can't
     store both; the importer would drop one anyway).
  4. Stop before CUTOFF, the first record weewxscw logged itself.

  5. Rain. The importer reads field 27 (rain since midnight) as a cumulative
     value. Here it resets to 0 ON the 00:00 record, but weewx's 00:00 record
     covers 23:50-00:00 of the previous day, so rain in each day's last
     10 minutes was lost (e.g. 0.15 in on 2026-06-07). Rewrite field 27 as one
     running total that never resets; each record's increase is its own
     interval's rain:
       - same day as the previous row: increase of the original field 27;
       - a 00:00 row 10 min after the previous row: increase of the rain
         counter (field 12), if it is between 0 and 2 in;
       - first row of a new day after a gap: its original field 27 (rain
         from the end of the previous day into the gap is unknowable).

Other values are not altered.

Usage: python3 -I clean_cumulus.py RAW_DATA_DIR CLEAN_DIR
Reads RAW_DATA_DIR/MMMyylog.txt (never modified), writes CLEAN_DIR/MMMyylog.txt
and CLEAN_DIR/report.txt.
"""

import bisect
import collections
import datetime
import glob
import os
import sys

CUTOFF = datetime.datetime(2026, 11, 14, 12, 45)   # first weewxscw record, EST
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DATE, TIME, TEMP, HUM, BARO, RAINCOUNTER, MIDNIGHTRAIN = 0, 1, 2, 3, 10, 11, 26
TEN_MIN = datetime.timedelta(minutes=10)


def month_files(src):
    out = []
    for f in glob.glob(os.path.join(src, "*log.txt")):
        b = os.path.basename(f)
        if b[:3] in MONTHS and b[3:5].isdigit() and len(b) == 12:
            out.append((int(b[3:5]), MONTHS.index(b[:3]), f))
    return [f for _, _, f in sorted(out)]


def longest_increasing(keys):
    """Indices of a longest strictly increasing subsequence of keys."""
    tails, tails_idx, prev = [], [], [None] * len(keys)
    for i, k in enumerate(keys):
        j = bisect.bisect_left(tails, k)
        if j == len(tails):
            tails.append(k); tails_idx.append(i)
        else:
            tails[j] = k; tails_idx[j] = i
        prev[i] = tails_idx[j - 1] if j else None
    out, i = [], tails_idx[-1] if tails_idx else None
    while i is not None:
        out.append(i); i = prev[i]
    return out[::-1]


def main(src, dst):
    os.makedirs(dst, exist_ok=True)
    rep = []
    rows = []            # (timestamp, line, source month file)
    nul_total = bad_total = 0
    for f in month_files(src):
        raw = open(f, "rb").read()
        nul = raw.count(b"\x00")
        nul_total += nul
        bad = 0
        for line in raw.replace(b"\x00", b"").decode("latin-1").splitlines():
            if not line.strip():
                continue
            r = line.split(",")
            try:
                if len(r) != 27:
                    raise ValueError
                ts = datetime.datetime.strptime(r[DATE] + " " + r[TIME], "%d/%m/%y %H:%M")
                float(r[TEMP]); float(r[BARO]); float(r[MIDNIGHTRAIN])
            except ValueError:
                bad += 1
                rep.append(f"  bad line dropped in {os.path.basename(f)}: {line[:80]!r}")
                continue
            rows.append((ts, line, os.path.basename(f)))
        bad_total += bad
    n_in = len(rows)

    # 2. exact duplicate lines
    seen, uniq = set(), []
    for row in rows:
        if row[1] in seen:
            continue
        seen.add(row[1]); uniq.append(row)
    n_exact = n_in - len(uniq)

    # 3. out-of-order strays
    keep = longest_increasing([r[0] for r in uniq])
    kept = [uniq[i] for i in keep]
    kept_ts = {r[0] for r in kept}
    dropped = [uniq[i] for i in sorted(set(range(len(uniq))) - set(keep))]
    lost_ts = sorted({r[0] for r in dropped} - kept_ts)

    # 4. cutoff
    before = len(kept)
    kept = [r for r in kept if r[0] < CUTOFF]
    n_cut = before - len(kept)

    # rain check: field 27 non-decreasing within a day. In this Cumulus the
    # 00:00 record already belongs to the new day (it resets to 0 there).
    decreases = []
    last = {}
    for ts, line, _ in kept:
        day = ts.date()
        v = float(line.split(",")[MIDNIGHTRAIN])
        if day in last and v < last[day] - 1e-9:
            decreases.append((ts, last[day], v))
        last[day] = max(v, last.get(day, v))

    # 5. rain: rewrite field 27 as a running total that never resets
    total = 0.0
    midnight_added = 0.0
    midnight_rows = midnight_skipped = 0
    rewritten = []
    prev = None
    for ts, line, src in kept:
        f = line.split(",")
        mr, ctr = float(f[MIDNIGHTRAIN]), float(f[RAINCOUNTER])
        if prev is None:
            inc = 0.0
        elif ts.date() == prev[0].date():
            inc = max(0.0, mr - prev[1])
        elif ts.time() == datetime.time(0, 0) and ts - prev[0] == TEN_MIN:
            d = ctr - prev[2]
            midnight_rows += 1
            if 0.0 <= d <= 2.0:
                inc = d + mr          # mr is 0 here, but keep anything logged
                midnight_added += d
            else:
                inc = mr
                midnight_skipped += 1
                rep.append(f"  rain counter jump at {ts} ignored: {prev[2]} -> {ctr}")
        else:
            inc = mr
        total = round(total + inc, 3)
        f[MIDNIGHTRAIN] = f"{total:.3f}"
        rewritten.append((ts, ",".join(f), src))
        prev = (ts, mr, ctr)
    kept = rewritten

    # write per month of the record's own date
    by_month = collections.defaultdict(list)
    for ts, line, _ in kept:
        by_month[(ts.year, ts.month)].append(line)
    for f in glob.glob(os.path.join(dst, "*log.txt")):
        os.remove(f)
    for (y, m), lines in sorted(by_month.items()):
        name = f"{MONTHS[m - 1]}{y % 100:02d}log.txt"
        with open(os.path.join(dst, name), "w", encoding="latin-1", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")

    summary = [
        f"source rows parsed:            {n_in}",
        f"NUL bytes stripped:            {nul_total}",
        f"bad lines dropped:             {bad_total}",
        f"exact duplicate lines dropped: {n_exact}",
        f"out-of-order rows dropped:     {len(dropped)}",
        f"  ...timestamps lost entirely: {len(lost_ts)}",
        f"rows at/after cutoff dropped:  {n_cut}  (cutoff {CUTOFF})",
        f"rows written:                  {len(kept)}",
        f"first / last:                  {kept[0][0]} / {kept[-1][0]}",
        f"monthly files written:         {len(by_month)}",
        f"rain-since-midnight decreases: {len(decreases)}",
        f"00:00 rows given 23:50-00:00 rain: {midnight_rows - midnight_skipped} "
        f"(+{midnight_added:.2f} in total; counter jumps ignored: {midnight_skipped})",
        f"rain running total (field 27): {total:.2f} in",
    ]
    detail = ["", "per source month: out-of-order rows dropped"]
    c = collections.Counter(r[2] for r in dropped)
    detail += [f"  {k}: {v}" for k, v in sorted(c.items())]
    detail += ["", "timestamps lost entirely (all copies out of order):"]
    detail += [f"  {t}" for t in lost_ts[:50]]
    detail += ["", "rain decreases (ts, previous, now):"]
    detail += [f"  {d}" for d in decreases[:50]]
    out = "\n".join(summary + detail + [""] + rep) + "\n"
    open(os.path.join(dst, "report.txt"), "w").write(out)
    print("\n".join(summary))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
