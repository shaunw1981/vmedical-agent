/* Valley Medical Dashboard — service worker.
   Precache the NEUTRAL app shell (CSS/JS/icons/offline) so the app opens
   instantly and works offline. Page HTML is deliberately never cached — it can
   contain the signed-in user's private data, and this may run on a shared
   device — so navigations are network-first and fall back to /offline.

   Bump CACHE on every release so old shells are purged. */
const CACHE = 'vm-shell-v3';

const SHELL = [
  '/static/css/app.css',
  '/static/js/app.js',
  '/offline',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon-180.png',
  '/static/icons/favicon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin GETs.
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;

  // Never touch auth / webhook / the worker itself — let the network handle them.
  const BYPASS = ['/auth', '/login', '/logout', '/webhook', '/sw.js'];
  if (BYPASS.some((p) => url.pathname === p || url.pathname.startsWith(p + '/'))) return;

  // Static assets: network-first so CSS/JS changes always reach the user when
  // online, with the cached copy as an offline fallback. (Cache-first used to
  // strand old CSS even after a release.)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Navigations (page HTML): network-first, fall back to the offline page.
  // Do NOT cache the response (may hold private data).
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/offline')));
    return;
  }

  // Anything else: network, with a best-effort cached fallback, no caching.
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});
