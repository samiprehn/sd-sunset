// Cloudflare Worker — CORS-enabled proxy for aviationweather.gov TAF data.
// Consumed by samiprehn.github.io/sd-sunset/.
//
// Usage:  GET /?ids=KSAN,KNKX,KNZY,KCRQ
// Proxies to https://aviationweather.gov/api/data/taf with a real User-Agent
// and adds the Access-Control-Allow-Origin header browsers need.

const UPSTREAM = 'https://aviationweather.gov/api/data/taf';
const ID_PATTERN = /^[A-Z0-9]+(,[A-Z0-9]+)*$/i;

const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(status, body, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...cors, ...extraHeaders },
  });
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== 'GET') {
      return json(405, { error: 'Method not allowed' });
    }

    const url = new URL(request.url);
    const ids = url.searchParams.get('ids');
    if (!ids) return json(400, { error: 'Missing ids parameter' });
    if (!ID_PATTERN.test(ids)) return json(400, { error: 'Invalid ids format' });

    try {
      const upstream = await fetch(
        `${UPSTREAM}?ids=${encodeURIComponent(ids)}&format=json`,
        { headers: { 'User-Agent': 'sd-sunset (https://github.com/samiprehn/sd-sunset)' } },
      );

      const bodyText = await upstream.text();

      return new Response(bodyText, {
        status: upstream.status,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'public, max-age=300',
          ...cors,
        },
      });
    } catch (e) {
      return json(502, { error: 'Upstream fetch failed', detail: String(e) });
    }
  },
};
