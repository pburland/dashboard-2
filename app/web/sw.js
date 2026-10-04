// App shell cache. API data is cached by app.js (localStorage), so the
// service worker never caches /api/* or /admin/*.
const VERSION = 'training-v7';
const SHELL = ['/', '/static/app.css', '/static/app.js', '/static/icon-192.png', '/manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin/') || url.pathname.startsWith('/oauth/')) return;
  // Network first so updates arrive; fall back to the cached shell offline.
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone();
    caches.open(VERSION).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request).then(m => m || caches.match('/'))));
});

// ── phone notifications ──────────────────────────────────────────────────
self.addEventListener('push', e => {
  let m = {title: 'Training', body: '', url: '/'};
  try { m = Object.assign(m, e.data.json()); } catch {}
  e.waitUntil(self.registration.showNotification(m.title, {
    body: m.body, tag: m.tag || undefined, icon: '/static/icon-192.png', badge: '/static/icon-192.png',
    data: {url: m.url || '/'}}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || '/', self.location.origin).href;
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const c of list) { if ('focus' in c) { c.navigate(url).catch(() => {}); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
