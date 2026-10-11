/* FOOTBALL INTELLIGENCE service worker: app shell cached for installability
   and offline opens; data JSONs are always network-first so predictions
   stay fresh. */
var SHELL_CACHE = "fi-shell-v1";
var DATA_CACHE = "fi-data-v1";
var SHELL = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./i18n/my.json",
  "./i18n/en.json",
  "./i18n/teams_my.json"
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(SHELL_CACHE).then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== SHELL_CACHE && k !== DATA_CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (url.pathname.indexOf("/data/") !== -1) {
    // data: network first, fall back to cache
    e.respondWith(
      fetch(e.request).then(function (res) {
        var copy = res.clone();
        caches.open(DATA_CACHE).then(function (c) { c.put(e.request, copy); });
        return res;
      }).catch(function () { return caches.match(e.request); })
    );
    return;
  }
  // shell: cache first, fall back to network
  e.respondWith(
    caches.match(e.request).then(function (hit) {
      return hit || fetch(e.request);
    })
  );
});
