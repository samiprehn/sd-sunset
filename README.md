# San Diego Sunset

Tonight's best San Diego sunset viewpoint, ranked.

**Live:** https://samiprehn.github.io/sd-sunset/

For each evening, ranks 10 SD viewpoints by how good their sunset is likely to be. Each spot shows a letter grade (A+ through F), layered cloud %, a verdict ("High clouds — good color", "Marine layer", etc.), Google Maps directions, and a nearby live webcam.

## How the grade works

Each spot gets a 0–100 score from Open-Meteo's layered cloud forecast (low / mid / high cover, hourly), interpolated to ~15 min after sunset when color peaks:

```
horizonLow  = patchy low cloud (≤50% cover) locally + 50/100 km out   # lights up from below
canvas      = 1 − (1−high)(1−mid)(1−horizonLow)  # combined color-catching cover
canvasScore = 40 + 60·gauss(canvas; peak 55%)    # clear ≈ C
              × cut when mid > 60%               # thick altostratus = gray, not color
pathBlock   = weighted solid-deck opacity at 25–300 km along the sunset azimuth
score       = canvasScore × (1 − 0.95·localDeck) × (1 − 0.85·pathBlock)
              capped at 20 if rain, 15 if fog
```

The light-path term is the interesting bit: sunset color happens when light sneaks *under* the cloud canvas from beyond the horizon, so a solid deck out along the sunset direction (WSW in winter, WNW in summer) leaves the sky gray even when the coast itself is clear. Patchy low clouds are the opposite — they light up from below (Nov 15 2026 was the calibration case). A solid local marine layer hides the horizon directly.

Score bands: A+ ≥85, A ≥70, B ≥55, C ≥40, D ≥25, F below.

## Stack

Single-file HTML, fully client-side. No build, no dependencies.

- **Open-Meteo forecast API** — keyless, CORS-friendly; one multi-location request covers all 10 spots + the light-path points
- **GOES-18 satellite imagery** as a live cloud-check before driving out
- **Sunrise-sunset.org** for the moment of sunset per day
- **Esri World Street Map tiles** (keyless) drawn into an SVG with viewpoints positioned by Web Mercator lat/lon

## Sunset alerts

Optional GitHub Actions workflow that pings ntfy when any spot grades A+ on the day:

- `check_sunset.py` — Python port of the scoring logic, runs on a cron at 7am / 11am / 3pm Pacific
- `seen.json` — committed back by the action so you only get one notification per day
- Requires `NTFY_TOPIC` repo secret

The notification links straight to the live page.

## Run locally

```sh
open index.html
```

Open-Meteo sends CORS headers, so `file://` works.

## Files

- `index.html` — the site
- `worker.js` — Cloudflare Worker source for the old TAF proxy (no longer used; safe to undeploy)
- `check_sunset.py` — alert script
- `.github/workflows/sunset-alerts.yml` — cron config
- `seen.json` — alert de-dup state
