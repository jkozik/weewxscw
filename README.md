# weewxscw

WeeWX for the Sanibel/Captiva (Florida) home station:
Davis **Vantage Vue** ISS → Davis **Envoy** → **WiFiLogger** → home NAT port
forward → this VM (weewx `Vantage` driver, `type = ethernet`).
Web page: stock **Seasons** skin, nginx on host port **8090** →
`weewx.sancapweather.com` via a Cloudflare reverse proxy.
Modeled on `~/projects/weewxrtlsdr` (independent; shares nothing with it or weewx51).

| Link | What | Where configured |
|---|---|---|
| Station | Envoy via WiFiLogger, TCP, host/port in live config | `data/weewx.conf` `[Vantage]` |
| Web | Seasons skin, :8090 | `docker-compose.yml` nginx; `[StdReport][[SeasonsReport]]` |

Containers: `weewx-scw`, `nginx-scw` (compose project `weewxscw`).
Timezone America/New_York. Archive interval comes from the Envoy (15 min).

## Secrets

`data/weewx.conf` is git-ignored (holds the DDNS host/port and any future
passwords). `data/weewx.conf.example` is the tracked template with
`replace_me` placeholders. Copy any non-secret config change into both.

## Bring up

```bash
cp data/weewx.conf.example data/weewx.conf   # then set [Vantage] host / tcp_port
docker compose up -d --build
docker logs -f weewx-scw
```
Local page: http://<vm>:8090/

## Gotchas

- **Envoy channel.** This Envoy came from another station and listened on
  channel 3; the Vue ISS is on channel 1, so it received nothing (archive had
  indoor/barometer only, rxCheckPercent 0). Fixed 2026-11-14 with weewx stopped:
  `weectl device --set-transmitter-type=1,0 -y` and `--set-transmitter-type=3,10 -y`
  (back out: `3,0` and `1,10`). Check with `weectl device --info` →
  TRANSMITTERS / RECEPTION STATS.
- Port 22222 is a *different* Envoy (same Vue ISS) polled by Cumulus on a
  Windows VM. Never connect to it — its WiFiLogger allows one client.
- Records before 2026-11-14 12:45 EST have no outdoor data.

- **The WiFiLogger allows one TCP client and holds a dropped session for
  minutes.** After stopping/restarting weewx (or any test connection) it may
  answer nothing for ~5+ minutes ("Unable to wake up Vantage console").
  Don't restart repeatedly; wait. Don't restart during the first-run catch-up
  (download of the Envoy's archive memory).
- `data/public_html` must be owned by uid 1000 (weewx in the container). If
  Docker creates it first (nginx bind mount) it is root-owned and reports fail:
  `docker run --rm -v "$PWD/data:/data" alpine:3 chown 1000:1000 /data/public_html`
- **Envoy clock jumps back 1 hour while weewx is disconnected** (seen
  2026-11-14 and 2026-11-17, both during restarts). Likely the WiFiLogger's
  own time sync using a Central time zone. weewx resets the clock on reconnect
  and every 4 h. Fix: WiFiLogger dashboard (192.168.0.107 on the Florida LAN)
  time zone -> Eastern, or disable its console clock sync.
- Logging goes to stdout (`[Logging]` at end of weewx.conf); the container has
  no syslog.

## Cumulus history import (2025-06-30 to 2026-11-14)

Done 2026-11-17. The Florida Cumulus 1 (Windows 10 VM 192.168.100.173,
`C:\Cumulus`, polling the 22222 Envoy) logs were zipped with PowerShell
(`Compress-Archive` of `C:\Cumulus\data` + `Cumulus.ini`) and scp'd to
`~/cumulus-import-scw/` (outside git; Cumulus.ini can hold passwords).
Scripts in `cumulus-import/`:

1. `clean_cumulus.py raw/data clean`: strips NUL bytes (Aug 2026 crash),
   drops exact duplicates and out-of-order stray rows, cuts off at
   2026-11-14 12:45 EST (first weewxscw record), and rewrites the rain field
   as a running total so the 23:50-00:00 rain isn't lost (this Cumulus resets
   "rain since midnight" on the 00:00 row).
2. Trial import into a copy (`weectl import`, ~19 min, `TZ=America/New_York`,
   `data/bin` mounted for calc-missing) with `cumulus.conf`. weewx 5.5 calls
   indoor temperature `cur_in_temp` (5.1 used `curr_in_temp`).
3. `verify_trial.py` against Cumulus's dayfile.txt: temp highs 466/466,
   lows 465/466 (Cumulus's own 0.0 F glitch on 2026-02-16), rain 466/466.
4. Live swap: stop weewx, copy newer records + Nov 15+ daily summaries from
   live into the trial copy, swap in, start.

Not imported: UV/solar (the Vue has neither; Cumulus logged junk), the
2026-08-17..09-29 internet outage gap, and Cumulus's 5.87 in on 2026-09-29
(six weeks of rain lumped into one day).

Back-out: `docker compose stop weewx`, copy
`~/cumulus-import-scw/backup/weewx.sdb.pre-live-swap-20261117` to
`data/archive/weewx.sdb`, delete `data/public_html/NOAA/NOAA-2025*` and
`NOAA-2026-0[1-9]*`/`NOAA-2026-10*`, start.

## Back out

`docker compose down` — nothing outside this directory is touched
(images `weewxscw-weewx`, `nginx:1.27-alpine`, `alpine:3` can be removed).
