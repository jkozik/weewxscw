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
- Logging goes to stdout (`[Logging]` at end of weewx.conf); the container has
  no syslog.

## Back out

`docker compose down` — nothing outside this directory is touched
(images `weewxscw-weewx`, `nginx:1.27-alpine`, `alpine:3` can be removed).
