# weewxscw

[WeeWX](https://weewx.com/) for a Davis **Vantage Vue** weather station in
Sanibel/Captiva, Florida, served at
[weewx.sancapweather.com](https://weewx.sancapweather.com/).

```
Vantage Vue ISS ──radio, ch 1──▶ Davis Envoy ──▶ WiFiLogger (TCP) ──▶ home router
   (Florida)                                                        NAT port forward
                                                                          │ internet
                                                                          ▼
                                  Ubuntu VM (Naperville): Docker Compose
                                  ┌─────────────────────────────────────────┐
                                  │ weewx-scw   felddy/weewx 5.5, Vantage   │
                                  │             driver (type = ethernet)    │
                                  │      │ data/archive/weewx.sdb (SQLite)  │
                                  │      ▼ data/public_html (Seasons skin)  │
                                  │ nginx-scw   :8090 ──▶ Cloudflare Tunnel │
                                  └─────────────────────────────────────────┘
```

- weewx polls the Envoy over the internet through the WiFiLogger. It reads
  live readings every few seconds and the Envoy's 15-minute archive records.
- The stock **Seasons** skin is served by nginx on host port **8090**. A
  Cloudflare Tunnel maps `weewx.sancapweather.com` to that port; no router
  port forwards are needed.
- The history from **2025-06-30** comes from the station's previous
  software, Cumulus. `cumulus-import/` has the scripts used for the
  import.
- Live readings are also published over **MQTT** (`weather/scw/loop`, JSON,
  every 10 s) to the `mosquitto-scw` broker. The Florida broker on osprey
  bridges them over Tailscale for Home Assistant.
- The Vue has no solar or UV sensors.

`NOTES.md` is the log of how this was built and what went wrong along the way.

## Repository layout

| Path | What |
|---|---|
| `Dockerfile` | `felddy/weewx:5.5.6`, system time zone America/New_York |
| `docker-compose.yml` | `weewx-scw`, `nginx-scw` and `mosquitto-scw`, with health checks, log caps and resource limits |
| `mosquitto/` | broker config, tracked `acl`, and `setup.sh`, which installs the private acl/passwd copies |
| `data/weewx.conf.example` | weewx config template (tracked). Copy it to `data/weewx.conf`, which is git-ignored |
| `data/skins/`, `data/bin/` | stock skins and weewx's user directory, as created by `weectl station create` |
| `weewxscwbck.sh` | weekly backup (cron) |
| `zabbix/` | Zabbix agent UserParameters and scripts (site freshness, archive age, outdoor data, reception, container health, backup age) |
| `cumulus-import/` | one-off Cumulus history import: cleanup, import config, verification |

## Secrets

`data/weewx.conf` holds the station's DDNS host name and port, and any
passwords added later. It is git-ignored. `data/weewx.conf.example` is the
same file with `replace_me` placeholders. When you change the config, copy
non-secret changes into the example as well.

## Install

Requirements: Docker with the compose plugin. You also need a WiFiLogger
(or another Davis TCP logger) reachable at `host:port`.

1. Clone and create the live config:
   ```bash
   git clone <this repo> weewxscw && cd weewxscw
   cp data/weewx.conf.example data/weewx.conf
   # edit data/weewx.conf, section [Vantage]:
   #   host = <ddns name or IP>     tcp_port = <port>
   ```
   Set `[Station]` (location, latitude, longitude, altitude) if this is a
   different station.

2. Create the web folder owned by the container's weewx user (uid 1000).
   If Docker creates it first for nginx's mount, it is owned by root, and
   weewx can't write the pages:
   ```bash
   mkdir -p data/public_html data/archive
   sudo chown 1000:1000 data/public_html data/archive   # skip if you are uid 1000
   ```

3. Check that the Envoy listens on the same channel as the outdoor unit
   (Vue default: channel 1). Run this with no other client connected:
   ```bash
   docker compose build
   docker run --rm --entrypoint weectl -v "$PWD/data:/data" weewxscw-weewx \
     device --config /data/weewx.conf --info | sed -n '/TRANSMITTERS/,/CRC/p'
   ```
   Channel 1 should be `active ... iss`, and `Total packets received` should
   be above 0. To change channels, see "Envoy channel" in `NOTES.md`.

4. MQTT broker logins. Create `~/secrets/weewxscw-mqtt.txt` (chmod 600)
   with one `user password` line each for `weewx` and `osprey-bridge`. Put
   the `weewx` password in `[StdRESTful] [[MQTT]] server_url` in
   `data/weewx.conf`. Then install the broker's private files:
   ```bash
   mosquitto/setup.sh
   ```
   weewx-mqtt (the weewx add-on in `data/bin/user/mqtt.py`) needs
   **paho-mqtt 1.6.1**; the Dockerfile pins it.

5. Start:
   ```bash
   docker compose up -d
   ```
   On first start, weewx downloads the Envoy's stored archive before it
   starts the live loop. **Don't restart it during that download.**

6. Point the reverse proxy (or a browser) at `http://<host>:8090/`.

7. Optional: install the weekly backup in root's crontab (Sunday 23:45):
   ```
   45 23 * * 0 /home/jkozik/projects/weewxscw/weewxscwbck.sh >> /home/jkozik/projects/weewxscw/weewxscwbck.log 2>&1
   ```
   The script takes an online SQLite snapshot (weewx keeps running), writes
   a tarball to `/backup/weewxscw.YYYYMMDD.HH.tar.gz`, FTPs a copy (login
   from `~/.ncftp-backup.cfg`), and keeps 84 days of tarballs.

## Verify it's working

```bash
# 1. Both containers healthy (weewx: Seasons page rewritten in the last 35 min)
docker ps --filter name=scw --format '{{.Names}}\t{{.Status}}'

# 2. Connected, clock in sync, live loop running
docker logs weewx-scw 2>&1 | grep -E "Clock error|Starting main packet loop" | tail -2

# 3. Live readings include OUTDOOR values (outTemp/outHumidity/windSpeed).
#    If only inTemp/barometer appear, the Envoy isn't hearing the outdoor unit (step 3).
docker logs --since 2m weewx-scw 2>&1 | grep '^LOOP' | tail -1 | tr ',' '\n' | grep -E 'outTemp|outHumidity|windSpeed'

# 4. A new archive record every 15 minutes, followed by a report
docker logs --since 20m weewx-scw 2>&1 | grep -E "Added record .* to database|Generated"

# 5. The page is served
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/    # expect 200

# 6. MQTT: a live JSON message (retained, so it appears at once), as the bridge sees it
docker run --rm --network host eclipse-mosquitto:2.1.2-alpine mosquitto_sub \
  -h "$(tailscale ip -4)" -p 1884 -u osprey-bridge -P '<password>' -t 'weather/scw/#' -v -C 1
```

## Monitoring (Zabbix)

Install the agent side with sudo:
`cp zabbix/weewxscw.conf /etc/zabbix/zabbix_agentd.d/`,
`cp zabbix/scripts/weewxscw_* /etc/zabbix/scripts/`, then
`systemctl restart zabbix-agent`. Items are type "Zabbix agent" on host
weewx174.kozik.net:

| Item key | Interval | Trigger |
|---|---|---|
| `weewxscw.website.health` (0 ok / 1 banner / 2 stale / 3 down) | 5m | `min(...,#2)>0` (High) |
| `weewxscw.archive[age]` (minutes) | 5m | `last(...)>35` (High) |
| `weewxscw.archive[outtemp]` (1/0) | 5m | `max(...,30m)=0` (High) |
| `weewxscw.archive[rxcheck]` (%, Numeric float) | 5m | `avg(...,1h)<50` (Warning) |
| `weewxscw.container.health[weewx-scw]`, `[nginx-scw]` (1/0) | 5m | `max(...,15m)=0` (Average) |
| `weewxscw.backup.age` (days) | 1h | `last(...)>8` (Warning) |

## Things to know

- **The WiFiLogger accepts one TCP client.** After weewx disconnects, it can
  refuse new connections for about 5 minutes. weewx retries on its own, so
  don't restart repeatedly. Don't point other tools (WeatherLink, Cumulus,
  test scripts) at it while weewx is running.
- **WiFiLogger time zone must be Eastern.** The WiFiLogger syncs the Envoy's
  clock in its own time zone. When it was set to Central, the clock jumped
  back an hour on every disconnect. The setting only sticks after Save
  *and* a reboot.
- **Tailscale: use the 100.x addresses, never `--accept-routes` on this
  VM.** weewx174 is on the tailnet (`--accept-dns=false`). To reach osprey
  (Florida), use its **Tailscale address**: `tailscale status` lists every
  machine, and `tailscale ip -4` shows this VM's own address. **Don't**
  ping its Florida LAN address, 192.168.0.x; that only works from devices
  that accept routes, like the laptop. Never run `tailscale up
  --accept-routes` here: the Synology advertises **192.168.100.0/24, this
  VM's own LAN**, and accepting it could send local traffic (pfSense,
  Zabbix, the backup FTP server) through the tailnet. The MQTT bridge
  needs only the 100.x addresses.
- Logs go to `docker logs weewx-scw` (stdout), capped at 30 MB.

## Back out

`docker compose down`. Nothing outside this directory is touched. The images
`weewxscw-weewx` and `nginx:1.27-alpine` can be removed afterwards.
