/* Service worker de Falcón Live Ratings.
   - Precarga el esqueleto de la app para que abra al instante y funcione sin datos.
   - Las páginas se sirven "network first" (con copia en cache) para que arrive
     rápido la version nueva y siga funcionando sin conexion.
   - /api nunca se cachea: los datos en vivo se piden siempre a la red. */

const VERSION = "falcon-v1";
const CACHE = VERSION;

const PRECACHE = [
  "/",
  "/index.html",
  "/admin.html",
  "/manifest.webmanifest",
  "/manifest-admin.webmanifest",
  "/fonts/inter.css",
  "/fonts/inter-latin.woff2",
  "/fonts/inter-latin-ext.woff2",
  "/vendor/chart.umd.min.js",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/apple-touch-icon.png",
  "/icons/favicon-32.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skipWaiting") self.skipWaiting();
});

function putInCache(request, response) {
  const copy = response.clone();
  caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  let url;
  try { url = new URL(request.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) putInCache(request, response);
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          if (url.pathname.startsWith("/admin")) {
            const admin = await caches.match("/admin.html");
            if (admin) return admin;
          }
          const home = await caches.match("/index.html");
          if (home) return home;
          return new Response("Sin conexion", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok && response.type === "basic") putInCache(request, response);
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
