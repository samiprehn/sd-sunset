# San Diego Sunset

Tonight's best San Diego sunset viewpoint, ranked.

**Live:** https://samiprehn.github.io/sd-sunset/

For each evening of the week, ranks 10 SD viewpoints by how good their sunset is likely to be. Each spot shows a letter grade (A+ through F), forecast cloud %, a verdict ("Cirrus — best color", "Marine layer", etc.), Google Maps directions, and a nearby live webcam.

## How the grade works

Two data sources are combined per spot:

1. **NWS gridpoint cloud cover** at the moment of sunset (one gridpoint per spot, hardcoded)
2. **TAF** (terminal aerodrome forecast) from the nearest airport — gives layered cloud info that NWS doesn't expose

The TAF classifier is the interesting bit: it categorizes clouds into very-low (<3,000 ft, marine layer), low-mid (3,000–5,000 ft, blocks color from below), and high (≥20,000 ft, catches and reflects pink/gold). When TAF says "high cirrus over a clear lower sky," that's an A+ — the sweet spot.

Cloud-percentage falls back to NWS only:

| Range | Verdict | Grade |
|---|---|---|
| <20% | Clear & golden | C |
| 20–50% | Great for color | A |
| 50–75% | Partly cloudy | B |
| 75–90% | Hazy | D |
| 90%+ | Socked in | D |

The full A+ tier is reserved for the TAF "high cirrus over clear" case. Note that fully-clear is graded *worse* than partly-cloudy — sunset color needs clouds to catch the light.

## Stack

Single-file HTML, fully client-side. No build, no dependencies.

- **NWS gridpoint API** — keyless, CORS-friendly
- **TAF data via a small Cloudflare Worker** at `sd-sunset-taf.sami-prehn.workers.dev` (CORS-proxies aviationweather.gov)
- **GOES-18 satellite imagery** as a live cloud-check before driving out
- **Sunrise-sunset.org** for the moment of sunset per day
- **Inline SVG map** of San Diego with viewpoints positioned by lat/lon

## Sunset alerts

Optional GitHub Actions workflow that pings ntfy when any spot grades A+ on the day:

- `check_sunset.py` — Python port of the verdict logic, runs on a cron at 7am / 11am / 3pm Pacific
- `seen.json` — committed back by the action so you only get one notification per day
- Requires `NTFY_TOPIC` repo secret

The notification links straight to the live page.

## Run locally

```sh
open index.html
```

NWS and the TAF Worker both send CORS headers, so `file://` works.

## Files

- `index.html` — the site
- `worker.js` — Cloudflare Worker source for the TAF proxy
- `check_sunset.py` — alert script
- `.github/workflows/sunset-alerts.yml` — cron config
- `seen.json` — alert de-dup state
