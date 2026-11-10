/* ═══════════════════════════════════════════════════════════════
   Falcón Live Ratings · Service Worker (plantilla de despliegue)
   Estrategia:
   · HTML + manifest → network-first: los usuarios reciben cada
     despliegue en el siguiente lanzamiento, sin recarga fuerte.
     El cache queda como respaldo offline.
   · Estáticos (fuentes, Chart.js, iconos) → cache-first.
   · API (/api) → nunca se intercepta: siempre red fresca.
   · skipWaiting + clients.claim: la nueva versión toma el control
     de las pestañas abiertas apenas se instala.
   DESPLIEGUE: subir este archivo y BUMPEAR la constante CACHE
   (p. ej. falcon-v3.7) en cada despliegue. Nada más.
   ═══════════════════════════════════════════════════════════════ */
const CACHE = 'falcon-v3.8'; // ← BUMPEAR en cada despliegue
const PRECACHE = [
  '/',
  '/index.html',
  '/admin.html',
  '/manifest.webmanifest',
  '/manifest-admin.webmanifest',
  '/fonts/inter.css',
  '/fonts/inter-latin.woff2',
  '/fonts/inter-latin-ext.woff2',
  '/vendor/chart.umd.min.js',
  '/icons/favicon-32.png',
  '/icons/apple-touch-icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-512.png',
  '/icons/icono-atajo-torneos.png',
  '/icons/icono-atajo-comparar.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c =>
      // add individual (tolerante): un icono que falte no rompe la instalación
      Promise.all(PRECACHE.map(u => c.add(u).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', e => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;      // cross-origin: no interceptar
  if (url.pathname.startsWith('/api')) return;     // API: siempre red

  const cachePut = r => {
    const cp = r.clone();
    caches.open(CACHE).then(c => c.put(e.request, cp));
    return r;
  };

  // Navegaciones y manifest: network-first (updates llegan solos)
  if (e.request.mode === 'navigate' || url.pathname === '/manifest.webmanifest') {
    e.respondWith(
      fetch(e.request)
        .then(cachePut)
        // offline (o deep link con query): cache ignorando la query
        .catch(async () => {
          const hit = await caches.match(e.request, { ignoreSearch: true });
          if (hit) return hit;
          if (url.pathname.startsWith('/admin')) {
            const admin = await caches.match('/admin.html');
            if (admin) return admin;
          }
          const home = await caches.match('/index.html');
          if (home) return home;
          return new Response('Sin conexion', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
        })
    );
    return;
  }

  // Estáticos: cache-first con relleno por red
  e.respondWith(
    caches.match(e.request).then(hit =>
      hit || fetch(e.request).then(cachePut)
    )
  );
});
