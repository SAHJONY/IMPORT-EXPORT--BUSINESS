/* SAHJONY first-touch attribution (public intake pages).
 * Captures utm_source / utm_medium / utm_campaign + referrer ONCE per
 * browser session (first touch wins) and exposes them for intake POSTs.
 * Capture only — never invents attribution: empty values stay empty.
 */
(() => {
  'use strict';
  const KEY = 'sahjony.first_touch.v1';
  function capture() {
    let stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (_) {}
    if (stored && typeof stored === 'object') return stored;
    const q = new URLSearchParams(location.search);
    const first = {
      utm_source: (q.get('utm_source') || '').slice(0, 200),
      utm_medium: (q.get('utm_medium') || '').slice(0, 200),
      utm_campaign: (q.get('utm_campaign') || '').slice(0, 200),
      referrer: (document.referrer || '').slice(0, 500),
      landing: location.pathname.slice(0, 200),
      captured_at: new Date().toISOString()
    };
    try { sessionStorage.setItem(KEY, JSON.stringify(first)); } catch (_) {}
    return first;
  }
  function get() {
    const f = capture();
    const out = {};
    for (const k of ['utm_source', 'utm_medium', 'utm_campaign', 'referrer']) {
      if (f[k]) out[k] = f[k];
    }
    return out;
  }
  window.SAHJONY_ATTRIBUTION = { get: get, read: capture };
})();
