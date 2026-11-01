const CACHE = "sleepscope-v9";
const ASSETS = ['./', 'index.html', 'app.js', 'engine.js', 'apple.js', 'explain.js', 'manifest.json', 'icon-192.png', 'icon-512.png', 'vendor/jszip.min.js', 'vendor/plotly.min.js'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET' || e.request.url.includes('api.anthropic.com')) return;
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request)));
});
