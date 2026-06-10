# San Diego Sunset

Tonight's best San Diego sunset viewpoint, ranked.

**Live:** https://samiprehn.github.io/sd-sunset/

For each evening, ranks 10 SD viewpoints by how good their sunset is likely to be. Each spot shows a letter grade (A+ through F), layered cloud %, a verdict ("High clouds — good color", "Marine layer", etc.), Google Maps directions, and a nearby live webcam.

## How the grade works

Each spot gets a 0–100 score from Open-Meteo's layered cloud forecast (low / mid / high cover per spot, hourly), evaluated at the hour nearest sunset:

```
canvas   = min(100, high + 0.5 × mid)        # clouds that can catch color
canvas → gaussian peaking at 45% cover        # 0% = bland, 100% = gray overcast
blockage = max(local low, 0.85 × offshore low)
score    = canvasScore × (1 − blockage/100)   # capped at 15 if fog
```

The offshore term is the interesting bit: sunset color happens when light sneaks *under* the cloud deck from beyond the horizon, so low clouds at a sample point ~80 km west block the show even when the coast itself is clear. Local low clouds (marine layer) hide the horizon directly.

Score bands: A+ ≥85, A ≥70, B ≥55, C ≥40, D ≥25, F below. Fully-clear scores ~44 (C) — sunset color needs clouds to catch the light.

## Stack

Single-file HTML, fully client-side. No build, no dependencies.

- **Open-Meteo forecast API** — keyless, CORS-friendly; one multi-location request covers all 10 spots + the offshore point
- **GOES-18 satellite imagery** as a live cloud-check before driving out
- **Sunrise-sunset.org** for the moment of sunset per day
- **Inline SVG map** of San Diego with viewpoints positioned by lat/lon

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
- `worker.js` — Cloudflare Worker source for the old TAF proxy (no longer used by the site; still deployed for the sunset_mode extension)
- `check_sunset.py` — alert script
- `.github/workflows/sunset-alerts.yml` — cron config
- `seen.json` — alert de-dup state
