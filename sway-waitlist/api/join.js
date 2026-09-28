// Saves a waitlist sign-up to Supabase.
// Runs on Vercel's servers, so the secret key below never reaches the browser.
// Set these in Vercel → Project → Settings → Environment Variables:
//   SUPABASE_URL          e.g. https://abcdefgh.supabase.co
//   SUPABASE_SECRET_KEY   Supabase → Project Settings → API Keys → secret key

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const AGE_RANGES = ['18–21', '22–25', '26–30', '30+'];
const ACTIVITIES = ['Coffee', 'Brunch', 'Pilates/gym', 'Walks', 'Shopping', 'Nights out', 'Other'];
const CONSENT_TEXT = 'I agree to Sway emailing me about the launch.';
const MIN_FILL_MS = 2000; // real people take longer than 2 seconds to fill the form

function clean(value, max) {
  return typeof value === 'string' ? value.trim().replace(/\s+/g, ' ').slice(0, max) : '';
}

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

async function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') return JSON.parse(req.body);
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 10000) throw new Error('Body too large');
  }
  return JSON.parse(raw || '{}');
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return send(res, 405, { ok: false, error: 'Method not allowed' });
  }

  let data;
  try {
    data = await readBody(req);
  } catch (e) {
    return send(res, 400, { ok: false, error: 'Something went wrong. Please try again.' });
  }

  // Spam protection: bots fill the hidden field or submit instantly.
  // Pretend it worked so they don't learn anything, but save nothing.
  if (clean(data.website, 200) || (Number(data.elapsedMs) > 0 && Number(data.elapsedMs) < MIN_FILL_MS)) {
    return send(res, 200, { ok: true });
  }

  const firstName = clean(data.firstName, 60);
  const email = clean(data.email, 254).toLowerCase();
  const city = clean(data.city, 80);
  const ageRange = AGE_RANGES.includes(data.ageRange) ? data.ageRange : null;
  const activities = Array.isArray(data.activities)
    ? ACTIVITIES.filter((a) => data.activities.includes(a))
    : [];
  const handle = clean(data.handle, 60) || null;

  if (!firstName) return send(res, 400, { ok: false, field: 'firstName', error: 'Please add your first name.' });
  if (!EMAIL_RE.test(email)) return send(res, 400, { ok: false, field: 'email', error: "That email doesn't look quite right. Can you check it?" });
  if (!city) return send(res, 400, { ok: false, field: 'city', error: 'Which city are you in?' });
  if (data.consent !== true) return send(res, 400, { ok: false, field: 'consent', error: 'Please tick this so we can email you when Sway launches.' });

  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY;
  if (!url || !key) {
    console.error('Missing SUPABASE_URL or SUPABASE_SECRET_KEY environment variable');
    return send(res, 500, { ok: false, error: "Sorry, sign-ups aren't working right now. Your answers are still here, so please try again in a little while." });
  }

  const headers = {
    apikey: key,
    'Content-Type': 'application/json',
    // Same email twice? Keep the first sign-up, don't save a duplicate.
    Prefer: 'resolution=ignore-duplicates,return=minimal',
  };
  // Older Supabase projects use JWT-style keys, which also go in the Authorization header.
  if (key.startsWith('eyJ')) headers.Authorization = `Bearer ${key}`;

  try {
    const r = await fetch(`${url.replace(/\/$/, '')}/rest/v1/waitlist?on_conflict=email`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        first_name: firstName,
        email,
        city,
        age_range: ageRange,
        activities: activities.join(', ') || null,
        social_handle: handle,
        consent: true,
        consent_text: CONSENT_TEXT,
      }),
    });

    if (!r.ok) {
      console.error('Supabase error', r.status, await r.text());
      return send(res, 502, { ok: false, error: 'Oops, something went wrong on our side. Your answers are still here, so just tap the button again.' });
    }
    return send(res, 200, { ok: true });
  } catch (e) {
    console.error('Supabase request failed', e);
    return send(res, 502, { ok: false, error: 'Oops, something went wrong on our side. Your answers are still here, so just tap the button again.' });
  }
};
