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

# Low clouds ~80 km offshore block the sunlight path before it arrives.
OFFSHORE = {'lat': 32.85, 'lon': -118.10}

FOG_CODES = {45, 48}


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


def fetch_cloud_layers():
    """One multi-location request: every spot plus the offshore point (last)."""
    pts = SPOTS + [OFFSHORE]
    r = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': ','.join(str(p['lat']) for p in pts),
            'longitude': ','.join(str(p['lon']) for p in pts),
            'hourly': 'cloud_cover_low,cloud_cover_mid,cloud_cover_high,weather_code',
            'forecast_days': 2,
            'timezone': 'America/Los_Angeles',
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def clouds_at(result, local_dt):
    """local_dt must already be in America/Los_Angeles; rounds to nearest hour."""
    rounded = local_dt + dt.timedelta(minutes=30)
    key = rounded.strftime('%Y-%m-%dT%H:00')
    h = result['hourly']
    try:
        i = h['time'].index(key)
    except ValueError:
        return None
    return {
        'low': h['cloud_cover_low'][i],
        'mid': h['cloud_cover_mid'][i],
        'high': h['cloud_cover_high'][i],
        'fog': h['weather_code'][i] in FOG_CODES,
    }


# ── Scoring (mirrors index.html) ─────────────────────────────────────
def score_sunset(c):
    canvas = min(100, c['high'] + 0.5 * c['mid'])
    canvas_score = 100 * math.exp(-((canvas - 65) ** 2) / 4900)
    blockage = max(c['low'], 0.35 * c['offshore_low'])
    score = round(canvas_score * (1 - blockage / 100))
    if c['fog']:
        score = min(score, 15)

    if c['fog']:                    label = 'Fog'
    elif c['low'] >= 60:            label = 'Marine layer'
    elif c['offshore_low'] >= 60:   label = 'Light blocked offshore'
    elif c['low'] >= 30:            label = 'Patchy low clouds'
    elif canvas >= 80:              label = 'Overcast high clouds'
    elif canvas >= 15:              label = 'High clouds — good color'
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
    today = dt.date.today()
    today_iso = today.isoformat()
    state = load_state()

    if state.get('last_alert_date') == today_iso:
        print(f'Already alerted today ({today_iso}); exiting.')
        return

    sunset_dt = fetch_sunset(today_iso)
    sunset_local = sunset_dt.astimezone(PACIFIC)
    print(f'Sunset {today_iso}: {sunset_local.isoformat()}')

    cloud_data = fetch_cloud_layers()
    offshore = clouds_at(cloud_data[-1], sunset_local)
    offshore_low = offshore['low'] if offshore else 0

    a_plus = []
    for spot, result in zip(SPOTS, cloud_data):
        c = clouds_at(result, sunset_local)
        if c is None:
            print(f"  {spot['name']}: no forecast")
            continue
        c['offshore_low'] = offshore_low
        score, label = score_sunset(c)
        grade = grade_from_score(score)
        print(f"  {spot['name']}: {grade} ({score} — {label}, "
              f"low {c['low']}% / high {c['high']}%, offshore {offshore_low}%)")
        if grade == 'A+':
            a_plus.append({'spot': spot['name'], 'score': score})

    if not a_plus:
        print('No A+ spots tonight; no alert.')
        return

    spot_list = ', '.join(r['spot'] for r in a_plus)
    time_str = sunset_local.strftime('%-I:%M%p').lower()
    title = '🌅 A+ sunset tonight'
    message = f'{spot_list} · sunset {time_str} · high clouds over a clear horizon'

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
