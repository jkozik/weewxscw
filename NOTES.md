# Development notes / history

A chronological log of what was built and why, including the problems hit
along the way. `README.md` explains how to install and check the station;
this file records how we got here and what we learned.

Background: the Florida house has two Davis Envoys receiving the same
Vantage Vue outdoor unit (ISS), each with its own WiFiLogger behind the
home router's NAT:

| Port | Envoy | Polled by |
|---|---|---|
| 22222 | original Envoy | Cumulus 1 on a Windows 10 VM (192.168.100.173, `C:\Cumulus`) |
| 22223 | second Envoy (from my father's station) | this project |

The goal is to replace Cumulus with weewx and retire the Windows VM.
Modeled on `weewxrtlsdr` (Naperville); nothing is shared with it or with
`weewx51`.

## 2026-11-14: connectivity check and first weewx instance

- Checked the path from the VM, read-only: the DDNS name resolves, TCP 22223
  is open, and the Envoy answers the Davis wake-up (`\n` → `\n\r`), `TEST`
  and `NVER` (firmware **3.83**).
- Checked VM resources: 2 vCPU, 7.8 GB RAM (6.1 GB available), 24 GB free.
  Plenty of room for a Seasons-only weewx.
- Generated a stock config with
  `weectl station create --driver=weewx.drivers.vantage --units=us ...`.
  Changes to `[Vantage]`: `type = ethernet`, `host`, `tcp_port`, and
  `timeout = 8` (instead of 4) because the Envoy is reached over the
  internet. Page name: "Weewx.SanCapWeather.com".
- Secrets: the live `data/weewx.conf` is git-ignored, and a tracked
  `weewx.conf.example` uses `replace_me` placeholders. This is the same
  pattern as weewxrtlsdr.
- **Problem:** the config created by `weectl` logs to syslog, and the
  container has no `/dev/log`, so every log line produced a traceback.
  **Fix:** added a `[Logging]` section with `handlers = console,`.
- First start: weewx downloaded the Envoy's archive memory (records from
  2026-08-11 on). **Mistake:** I restarted weewx in the middle of that
  download. Afterwards the WiFiLogger accepted TCP but answered nothing
  ("Unable to wake up Vantage console") for about 5 minutes. Lesson: the
  WiFiLogger allows **one client** and holds a dropped session for minutes,
  so restart rarely and never during the catch-up download.
- **Problem:** `data/public_html` was owned by root, because Docker created
  it for nginx's bind mount before weewx ran. **Fix:** `chown 1000:1000` via
  a throwaway alpine container.
- **Problem:** every archive record had indoor temperature and barometer
  readings but **no outdoor data**, with `rxCheckPercent` = 0, for three
  months. There were also no live readings at all and the WiFiLogger hung
  (fixed by a power-cycle).
- Port 22222 couldn't be used for comparison: Cumulus holds that
  WiFiLogger's only connection.

### Envoy channel

- `weectl device --info` (read-only) on 22223 showed the Envoy listening on
  **channel 3**, the setting from my father's station, with 0 packets
  received. The Vue is on channel 1, the default.
- Fix, with weewx stopped:
  ```
  weectl device --set-transmitter-type=1,0 -y    # channel 1 = ISS
  weectl device --set-transmitter-type=3,10 -y   # channel 3 = none
  ```
  Back out: `--set-transmitter-type=3,0` and `--set-transmitter-type=1,10`.
- Two minutes later: 50 packets received, 0 missed. Live readings showed
  outdoor temperature, humidity and wind, and the 12:45 EST archive record
  had outdoor data. The Seasons page appeared on :8090.
- The Envoy's clock was 1 hour slow after the power-cycle; weewx set it.
  This turned out to be a recurring problem (see 2026-11-17).
- Trimmed the database to start at 2026-11-14 12:45 EST, the first record
  with outdoor data. Earlier records had indoor readings only. Kept a
  backup (`weewx.sdb.pre-wipe-20261114`) and moved the old web pages aside.
  Deleted rows directly rather than emptying the database: an empty
  database would make weewx re-download the Envoy's whole indoor-only
  archive memory.
- Set altitude to 14 ft, the value stored in the Envoy, so it matches the
  Envoy's barometer correction.
- Cloudflare: `weewx.sancapweather.com` → VM port 8090 (set up by the user).

## 2026-11-17: Cumulus history import

- **Transfer:** the Windows VM has no sshd. In PowerShell, the user copied
  `C:\Cumulus\data` and `Cumulus.ini` to a staging folder (Cumulus keeps the
  current month's log open, so zipping the live folder can fail), zipped
  them with `Compress-Archive`, and sent the zip with Windows' built-in
  `scp` to `~/cumulus-import-scw/`. That folder is outside git, because
  `Cumulus.ini` can hold passwords. The host key fingerprint was checked.
  The host has no `unzip`, so I extracted with Python; PowerShell 5.1 zips
  may store paths with backslashes.
- **Cumulus.ini:** 10-minute log interval; °F, mph, inches and inHg; the
  standard 27-field log format with dd/mm/yy dates. It also gave the
  house's exact location, 26.4686, -82.16. Cumulus stores the longitude
  without the minus sign, so its calculated maximum solar peaked at local
  midnight.
- **Data:** 64,884 records from 2025-06-30 to 2026-11-17. Cleaner than
  Naperville's: no 158 °F "sensor lost" values and no stuck humidity.
  Problems:
  - A 43-day gap, 2026-08-17 to 09-29, during an internet outage at the
    house while we were in Naperville.
  - `Aug26log.txt` contains 132 NUL bytes from a Windows crash or power
    loss.
  - About 3% of timestamps appear twice: exact copies, the repeated hour
    when daylight saving ended, and stray out-of-order rows around Cumulus
    restarts.
  - The UV column is junk (14.2 or 0.0) and solar is always 0. The Vue has
    neither sensor, so both are left out.
- **`clean_cumulus.py`:**
  - strips NUL bytes;
  - drops exact duplicates;
  - keeps the longest strictly increasing run of timestamps, which drops the
    1,195 stray rows without losing any timestamp;
  - cuts off at 2026-11-14 12:45 EST.
- **Rain problem found by the first trial:** this Cumulus resets "rain since
  midnight" (field 27) *on* the 00:00 row. weewx's 00:00 record covers
  23:50 to 00:00, so rain in each day's last 10 minutes was lost; for
  example 0.15 in on 2026-06-07. The importer treats a drop in a cumulative
  value as a reset. Simply adding the missing amount to the 00:00 row could
  undercount the next interval. **Fix:** rewrite field 27 as one running
  total that never resets. The 23:50 to 00:00 increment comes from the rain
  counter (field 12), which added 0.34 in over 17 months.
- **Import config (`cumulus.conf`):** copied from weewxrtlsdr. In weewx
  5.5 the indoor temperature field is `cur_in_temp`; weewx 5.1 called it
  `curr_in_temp`. Wrong spellings produce only a warning and blank values.
  `UV_sensor` and `solar_sensor` are False.
- **Trial import** into a copy of the database (online snapshot), in a
  throwaway container with `TZ=America/New_York` and `data/bin` mounted
  read-only for the calc-missing step. 64,460 records in about 19 minutes,
  with no warnings.
- **Verification** (`verify_trial.py` against Cumulus's `dayfile.txt`,
  466 full days):
  - weewxscw's own records unchanged.
  - High temperature within 1 °F on 466 of 466 days.
  - Low temperature within 1 °F on 465 of 466 days. The exception,
    2026-02-16, is Cumulus's own 0.0 °F glitch.
  - Rain within 0.01 in on 466 of 466 days.
  - Gust within 2 mph on 459 of 466 days. Cumulus takes gusts every
    2 seconds; the logs hold 10-minute values.

  Left out: Cumulus's 5.87 in on 2026-09-29, which is six weeks of outage
  rain lumped into one day.
- **Live swap** (weewx down about 3 minutes):
  1. Stopped weewx and backed up the live database
     (`~/cumulus-import-scw/backup/weewx.sdb.pre-live-swap-20261117`).
  2. Copied the records logged since the snapshot, and the daily summaries
     for Nov 15 onward (built from live readings), into the trial copy.
     The first attempt failed on `archive_day__metadata`, which has no
     dateTime column; it rolled back cleanly.
  3. Swapped the trial copy in. Result: 64,749 records.
  4. Set the exact location.

  NOAA reports from 2025-06 onward generated on the first report cycle.

  Back out: stop weewx, copy the backup back, delete the NOAA files for
  2025 and for 2026-01 through 2026-10, start.

## 2026-11-17: health check, backup, Envoy clock

- Health check: the weewx container is healthy if the Seasons `index.html`
  has been rewritten in the last **35 minutes**: two 15-minute intervals
  plus 5 minutes. It was 65 minutes before the interval was known.
- Backup: `weewxscwbck.sh` is a separate script per project, like weewx51
  and weewxrtlsdr. A failure stays contained, and retiring the project means
  deleting one script and one cron line. It takes an online SQLite snapshot
  (no container stop, which would free the WiFiLogger and invite the
  lockout), writes a tarball to `/backup`, FTPs a copy to .143, and keeps
  84 days. Test run: the snapshot passed its integrity check with 64,749
  records, a 6.75 MB tarball, and an FTP copy whose size matched to the
  byte. Root cron: Sunday 23:45, which is UTC on this host.
- **Envoy clock jumping back 1 hour.** It happened on 2026-11-14 after the
  power-cycle and on 2026-11-17 during the database swap, always while
  weewx was disconnected. weewx's 4-hourly clock checks while connected were
  within 4 seconds. The VM's location doesn't matter: weewx runs on
  America/New_York. **Cause:** the WiFiLogger syncs the Envoy's clock using
  its own time zone setting, which was **Central**.
  - Changed it to Eastern in the WiFiLogger dashboard (192.168.0.107 on the
    Florida LAN). It reverted until saved **and rebooted**. The reboot itself
    caused one last jump (-3617 s), which weewx corrected.
  - Test: weewx stopped for 5 minutes, then restarted. The clock error was
    **-0.19 s**. Fixed.

## Still to do

- Watch weewxscw for a few days, then retire Cumulus and the Windows VM
  (.173). The 22222 Envoy can then be repurposed.
- Zabbix monitoring items and triggers.
- An M5Stick sensor pack (via MQTT, like weewxrtlsdr) to add readings the
  Vue lacks.
