"""Sunset alerts.

Once per day, checks tonight's sunset forecast for every viewpoint in sd_sunset.
If any spot grades A+ (score >= 85), sends a single ntfy notification linking to
the live site. Run from a GitHub Actions cron a few times per day; state is
de-duped via seen.json so only one alert fires per calendar date.

Mirrors the scoring logic from index.html (scoreSunset + gradeFromScore).
"""

import datetime as dt
import json
import math
import os

import requests
from zoneinfo import ZoneInfo

NTFY_TOPIC = os.environ['NTFY_TOPIC']
SITE_URL = 'https://samiprehn.github.io/sd-sunset/'
SD_LAT, SD_LON = 32.72, -117.22
SEEN_FILE = 'seen.json'

SPOTS = [
    {'name': 'Sunset Cliffs',           'lat': 32.7157, 'lon': -117.2542},
    {'name': 'Torrey Pines Gliderport', 'lat': 32.8906, 'lon': -117.2528},
    {'name': 'Mt Soledad',              'lat': 32.8403, 'lon': -117.2506},
    {'name': 'Coronado',                'lat': 32.6956, 'lon': -117.1861},
    {'name': 'OB',                      'lat': 32.7521, 'lon': -117.2522},
    {'name': 'La Jolla Shores',         'lat': 32.8571, 'lon': -117.2573},
    {'name': 'Presidio Park',           'lat': 32.7583, 'lon': -117.1977},
    {'name': 'Mt Helix',                'lat': 32.7659, 'lon': -116.9990},
    {'name': 'Ponto Beach',             'lat': 33.0760, 'lon': -117.3110},
    {'name': 'Del Mar',                 'lat': 32.9700, 'lon': -117.2650},
]

# Light path: points out along the sunset azimuth. A solid deck out there
# blocks the sunlight before it can reach the cloud canvas; patchy low
# clouds within ~100 km sit on the visible horizon and light up instead.
PATH_KM = [25, 50, 100, 150, 200, 300]
PATH_WEIGHTS = [0.15, 0.25, 0.2, 0.15, 0.15, 0.1]
HORIZON_KM = {50: 0.4, 100: 0.3}  # visible-horizon weights (local low gets 0.3)

FOG_CODES = {45, 48}


def is_rain(code):
    return 51 <= code <= 67 or 80 <= code <= 82 or code >= 95


def sunset_azimuth(when):
    """Degrees clockwise from north where the sun meets the horizon."""
    rad = math.pi / 180
    d = when.timestamp() / 86400 - 0.5 + 2440588 - 2451545
    m = rad * (357.5291 + 0.98560028 * d)
    c = rad * (1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m))
    lon = m + c + rad * 102.9372 + math.pi
    dec = math.asin(math.sin(rad * 23.4397) * math.sin(lon))
    return 360 - math.acos(math.sin(dec) / math.cos(rad * SD_LAT)) / rad


def path_points(az):
    rad = math.pi / 180
    return [{
        'lat': SD_LAT + km / 111 * math.cos(az * rad),
        'lon': SD_LON + km / (111 * math.cos(SD_LAT * rad)) * math.sin(az * rad),
    } for km in PATH_KM]


def deck(cover, threshold):
    """0-1: how solid a layer is (broken below threshold, deck at 100%)."""
    return min(1, max(0, (cover - threshold) / (100 - threshold)))


def patchy(low):
    """How much low cloud reads as lit-up patches; fades as it merges into a deck."""
    return low if low <= 50 else max(0, 100 - low)


def path_opacity(c):
    return max(100 * deck(c['low'], 60), 80 * deck(c['mid'], 60), 0.3 * c['high'])


# ── State ────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(SEEN_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ── Data fetches ─────────────────────────────────────────────────────
def fetch_sunset(date_iso):
    r = requests.get(
        'https://api.sunrise-sunset.org/json',
        params={'lat': SD_LAT, 'lng': SD_LON, 'date': date_iso, 'formatted': 0},
        timeout=30,
    )
    r.raise_for_status()
    return dt.datetime.fromisoformat(r.json()['results']['sunset'].replace('Z', '+00:00'))


def fetch_cloud_layers(extra_pts):
    """One multi-location request: every spot, then each extra point in order."""
    pts = SPOTS + extra_pts
    r = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': ','.join(f"{p['lat']:.3f}" for p in pts),
            'longitude': ','.join(f"{p['lon']:.3f}" for p in pts),
            'hourly': 'cloud_cover_low,cloud_cover_mid,cloud_cover_high,weather_code',
            'forecast_days': 2,
            'models': 'ecmwf_ifs025',
            'timezone': 'America/Los_Angeles',
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def clouds_at(result, local_dt):
    """local_dt must already be in America/Los_Angeles. Evaluates 15 min after
    sunset (peak color), interpolating between the surrounding hours."""
    t = local_dt + dt.timedelta(minutes=15)
    key = t.strftime('%Y-%m-%dT%H:00')
    h = result['hourly']
    try:
        i = h['time'].index(key)
    except ValueError:
        return None
    if i + 1 >= len(h['time']):
        return None
    f = t.minute / 60
    lerp = lambda arr: round(arr[i] * (1 - f) + arr[i + 1] * f)
    code = h['weather_code'][i if f < 0.5 else i + 1]
    return {
        'low': lerp(h['cloud_cover_low']),
        'mid': lerp(h['cloud_cover_mid']),
        'high': lerp(h['cloud_cover_high']),
        'fog': code in FOG_CODES,
        'rain': is_rain(code),
    }


# ── Scoring (mirrors index.html) ─────────────────────────────────────
def score_sunset(c):
    horizon_low = 0.3 * patchy(c['low']) + c['path_patchy']
    canvas = 100 - (100 - c['high']) * (100 - c['mid']) * (100 - horizon_low) / 1e4
    canvas_score = 40 + 60 * math.exp(-((canvas - 55) ** 2) / 1600)
    if c['mid'] > 60:
        canvas_score *= 1 - 0.5 * (c['mid'] - 60) / 40
    light = (1 - 0.95 * deck(c['low'], 50)) * (1 - 0.85 * c['path_block'] / 100)
    score = round(canvas_score * light)
    if c['rain']:
        score = min(score, 20)
    if c['fog']:
        score = min(score, 15)

    if c['fog']:                    label = 'Fog'
    elif c['rain']:                 label = 'Rain'
    elif c['low'] >= 75:            label = 'Marine layer'
    elif c['path_block'] >= 50:     label = 'Horizon blocked'
    elif c['mid'] > 70:             label = 'Thick cloud deck'
    elif canvas >= 80:              label = 'Overcast'
    elif horizon_low >= 15:         label = 'Patchy low clouds to light up'
    elif canvas >= 15:              label = 'Clouds to catch color'
    else:                           label = 'Clear & golden'
    return score, label


def grade_from_score(score):
    if score >= 85: return 'A+'
    if score >= 70: return 'A'
    if score >= 55: return 'B'
    if score >= 40: return 'C'
    if score >= 25: return 'D'
    return 'F'


# ── Main ─────────────────────────────────────────────────────────────
PACIFIC = ZoneInfo('America/Los_Angeles')


def main():
    today = dt.datetime.now(PACIFIC).date()
    today_iso = today.isoformat()
    state = load_state()

    if state.get('last_alert_date') == today_iso:
        print(f'Already alerted today ({today_iso}); exiting.')
        return

    sunset_dt = fetch_sunset(today_iso)
    sunset_local = sunset_dt.astimezone(PACIFIC)
    print(f'Sunset {today_iso}: {sunset_local.isoformat()}')

    cloud_data = fetch_cloud_layers(path_points(sunset_azimuth(sunset_dt)))
    path_block = path_patchy = 0
    for km, w, result in zip(PATH_KM, PATH_WEIGHTS, cloud_data[len(SPOTS):]):
        pc = clouds_at(result, sunset_local)
        if pc:
            path_block += w * path_opacity(pc)
            path_patchy += HORIZON_KM.get(km, 0) * patchy(pc['low'])
    path_block = round(path_block)

    a_plus = []
    for spot, result in zip(SPOTS, cloud_data):
        c = clouds_at(result, sunset_local)
        if c is None:
            print(f"  {spot['name']}: no forecast")
            continue
        c['path_block'] = path_block
        c['path_patchy'] = path_patchy
        score, label = score_sunset(c)
        grade = grade_from_score(score)
        print(f"  {spot['name']}: {grade} ({score} — {label}, "
              f"low {c['low']}% / mid {c['mid']}% / high {c['high']}%, path {path_block}%)")
        if grade == 'A+':
            a_plus.append({'spot': spot['name'], 'score': score})

    if not a_plus:
        print('No A+ spots tonight; no alert.')
        return

    spot_list = ', '.join(r['spot'] for r in a_plus)
    time_str = sunset_local.strftime('%-I:%M%p').lower()
    title = '🌅 A+ sunset tonight'
    message = f'{spot_list} · sunset {time_str} · clouds to catch color, clear horizon'

    # Publish via JSON body — HTTP headers are latin-1 only, so emoji-in-title
    # breaks header-style ntfy posts. JSON body is UTF-8.
    requests.post(
        'https://ntfy.sh/',
        json={
            'topic': NTFY_TOPIC,
            'title': title,
            'message': message,
            'priority': 5,
            'click': SITE_URL,
            'tags': ['sunrise'],
        },
        timeout=30,
    )
    print(f'Alerted: {message}')

    state['last_alert_date'] = today_iso
    state['last_alert_spots'] = [r['spot'] for r in a_plus]
    save_state(state)


if __name__ == '__main__':
    main()
