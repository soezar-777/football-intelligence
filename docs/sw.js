/* Football Intelligence AI Pro+ service worker */
var SHELL_CACHE = "fi-shell-v11";
var SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon.svg"
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
        if (k !== SHELL_CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  var isPage = e.request.mode === "navigate" ||
    /(^|\/)(index\.html)?$/.test(url.pathname);
  if (isPage) {
    // Network-first for the app shell: new deploys reach the user immediately;
    // the cache is only a fallback when offline.
    e.respondWith(
      fetch(e.request).then(function (resp) {
        var copy = resp.clone();
        caches.open(SHELL_CACHE).then(function (c) { c.put(e.request, copy); });
        return resp;
      }).catch(function () { return caches.match(e.request); })
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(function (hit) {
      return hit || fetch(e.request);
    })
  );
});
