"""Sunset alerts.

Once per day, checks tonight's sunset forecast for every viewpoint in sd_sunset.
If any spot grades A+ ("Cirrus — best color"), sends a single ntfy notification
linking to the live site. Run from a GitHub Actions cron a few times per day;
state is de-duped via seen.json so only one alert fires per calendar date.

Mirrors the verdict logic from index.html (classifyTAF + verdictFor + gradeFor).
"""

import datetime as dt
import json
import os
import re

import requests

NTFY_TOPIC = os.environ['NTFY_TOPIC']
SITE_URL = 'https://samiprehn.github.io/sd-sunset/'
SD_LAT, SD_LON = 32.72, -117.22
SEEN_FILE = 'seen.json'

SPOTS = [
    {'name': 'Sunset Cliffs',           'grid': 'SGX/53,14', 'taf': 'KSAN'},
    {'name': 'Torrey Pines Gliderport', 'grid': 'SGX/55,22', 'taf': 'KNKX'},
    {'name': 'Mt Soledad',              'grid': 'SGX/54,20', 'taf': 'KSAN'},
    {'name': 'Coronado',                'grid': 'SGX/56,13', 'taf': 'KNZY'},
    {'name': 'OB',                      'grid': 'SGX/54,16', 'taf': 'KSAN'},
    {'name': 'La Jolla Shores',         'grid': 'SGX/54,21', 'taf': 'KSAN'},
    {'name': 'Presidio Park',           'grid': 'SGX/56,16', 'taf': 'KSAN'},
    {'name': 'Mt Helix',                'grid': 'SGX/63,15', 'taf': 'KNKX'},
    {'name': 'Ponto Beach',             'grid': 'SGX/54,31', 'taf': 'KCRQ'},
    {'name': 'Del Mar',                 'grid': 'SGX/55,26', 'taf': 'KCRQ'},
]

UA = {'User-Agent': 'sunset-alerts (sami.prehn@gmail.com)'}


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


# ── Time helpers ─────────────────────────────────────────────────────
def parse_iso(s):
    # Python <3.11 doesn't accept 'Z'; normalize
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


_DUR_RE = re.compile(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?')

def parse_duration_seconds(iso):
    m = _DUR_RE.match(iso)
    if not m:
        return 0
    d, h, mn = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mn) * 60


def value_at_time(values, target_dt):
    """NWS gridpoint values are [{validTime: 'ISO/duration', value}]."""
    for entry in values:
        start_str, dur_str = entry['validTime'].split('/')
        start = parse_iso(start_str)
        end = start + dt.timedelta(seconds=parse_duration_seconds(dur_str))
        if start <= target_dt < end:
            return entry['value']
    return None


# ── Data fetches ─────────────────────────────────────────────────────
def fetch_sunset(date_iso):
    r = requests.get(
        'https://api.sunrise-sunset.org/json',
        params={'lat': SD_LAT, 'lng': SD_LON, 'date': date_iso, 'formatted': 0},
        timeout=30,
    )
    r.raise_for_status()
    return parse_iso(r.json()['results']['sunset'])


def fetch_grid(grid):
    r = requests.get(f'https://api.weather.gov/gridpoints/{grid}', headers=UA, timeout=30)
    r.raise_for_status()
    props = r.json().get('properties', {})
    return {
        'skyCover': (props.get('skyCover') or {}).get('values', []),
        'weather':  (props.get('weather')  or {}).get('values', []),
    }


def fetch_tafs(stations):
    ids = ','.join(sorted(set(stations)))
    r = requests.get(
        'https://aviationweather.gov/api/data/taf',
        params={'ids': ids, 'format': 'json'},
        timeout=30,
    )
    r.raise_for_status()
    out = {}
    for rec in r.json():
        icao = rec.get('icaoId')
        if icao and icao not in out:
            out[icao] = rec
    return out


# ── Verdict (mirrors index.html) ─────────────────────────────────────
def taf_period_at(rec, target_unix):
    if not rec or not isinstance(rec.get('fcsts'), list):
        return None
    for p in rec['fcsts']:
        if p.get('timeFrom', 0) <= target_unix < p.get('timeTo', 0):
            return p
    return None


def classify_taf(period):
    """Returns (score_delta, verdict_label_or_None)."""
    if not period or not isinstance(period.get('clouds'), list):
        return 0, None
    clouds = [c for c in period['clouds'] if c and c.get('base') is not None]
    very_low = [c for c in clouds if c['base'] < 3000]
    low      = [c for c in clouds if c['base'] < 5000]
    high     = [c for c in clouds if c['base'] >= 20000]

    very_low_heavy = next((c for c in very_low if c['cover'] in ('BKN', 'OVC')), None)
    low_heavy      = next((c for c in low      if c['cover'] in ('BKN', 'OVC')), None)
    low_med        = next((c for c in low      if c['cover'] == 'SCT'), None)
    low_light      = next((c for c in low      if c['cover'] == 'FEW'), None)
    high_heavy     = next((c for c in high     if c['cover'] in ('BKN', 'OVC')), None)

    score = 0
    verdict = None
    if very_low_heavy:
        score += 60
        verdict = 'Marine layer'
    elif low_heavy:
        score += 40
        verdict = f"Low clouds ({low_heavy['base']}ft)"
    elif low_med:
        score += 20
        verdict = f"Patchy low clouds ({low_med['base']}ft)"
    elif low_light:
        score += 10
    if high_heavy and not very_low_heavy and not low_heavy:
        score -= 15
        if not verdict:
            verdict = 'Cirrus — best color'
    return score, verdict


def verdict_for_cloud(cloud):
    if cloud < 20: return 'Clear & golden'
    if cloud < 50: return 'Great for color'
    if cloud < 75: return 'Partly cloudy'
    if cloud < 90: return 'Hazy'
    return 'Socked in'


def grade_for(label):
    if label == 'Cirrus — best color': return 'A+'
    if label == 'Great for color':     return 'A'
    if label == 'Partly cloudy':       return 'B'
    if label == 'Clear & golden':      return 'C'
    if label == 'Hazy':                return 'D'
    if label.startswith('Low clouds'): return 'D'
    if label.startswith('Patchy low'): return 'C'
    if label == 'Marine layer':        return 'F'
    if label == 'Socked in':           return 'D'
    return 'D'


def blocking_weather(weather_val):
    if not isinstance(weather_val, list):
        return None
    for w in weather_val:
        if w and w.get('weather'):
            return w
    return None


# ── Main ─────────────────────────────────────────────────────────────
def evaluate_spot(spot, sunset_dt, grid_data, taf_record):
    cloud = value_at_time(grid_data['skyCover'], sunset_dt)
    if cloud is None:
        return None
    period = taf_period_at(taf_record, int(sunset_dt.timestamp()))
    _, taf_verdict = classify_taf(period)
    blocker = blocking_weather(value_at_time(grid_data['weather'], sunset_dt))

    if taf_verdict:
        label = taf_verdict
    elif blocker:
        label = (blocker.get('weather') or '').replace('_', ' ').capitalize() or 'Unknown'
    else:
        label = verdict_for_cloud(cloud)

    return {
        'spot': spot['name'],
        'grade': grade_for(label),
        'label': label,
        'cloud': cloud,
    }


def main():
    today = dt.date.today()
    today_iso = today.isoformat()
    state = load_state()

    if state.get('last_alert_date') == today_iso:
        print(f'Already alerted today ({today_iso}); exiting.')
        return

    sunset_dt = fetch_sunset(today_iso)
    print(f'Sunset {today_iso}: {sunset_dt.isoformat()}')

    grids = {}
    for s in SPOTS:
        if s['grid'] not in grids:
            grids[s['grid']] = fetch_grid(s['grid'])

    tafs = fetch_tafs([s['taf'] for s in SPOTS])

    a_plus = []
    for s in SPOTS:
        r = evaluate_spot(s, sunset_dt, grids[s['grid']], tafs.get(s['taf']))
        if r is None:
            print(f"  {s['name']}: no forecast")
            continue
        print(f"  {s['name']}: {r['grade']} ({r['label']}, {r['cloud']}% NWS)")
        if r['grade'] == 'A+':
            a_plus.append(r)

    if not a_plus:
        print('No A+ spots tonight; no alert.')
        return

    spot_list = ', '.join(r['spot'] for r in a_plus)
    sunset_local = sunset_dt.astimezone(dt.timezone(dt.timedelta(hours=-7)))  # PDT-ish; tz-naive display
    time_str = sunset_local.strftime('%-I:%M%p').lower()
    title = '🌅 A+ sunset tonight'
    message = f'{spot_list} · sunset {time_str} · high cirrus over a clear lower sky'

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
