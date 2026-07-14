// Self-destructing service worker.
// The app no longer uses a service worker — this file's only job is to
// unregister itself and clear its old caches for anyone whose browser
// still has the previous version installed. Safe to delete this file
// entirely once you're confident no one has the old worker anymore
// (e.g. a few weeks after this deploy).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.registration.unregister())
      .then(() => self.clients.matchAll())
      .then(clients => clients.forEach(client => client.navigate(client.url)))
  );
});
