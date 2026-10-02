// Mystical Service Worker — PWA
const CACHE_NAME = 'mystical-v1';
const URLS_TO_CACHE = [
    '/',
    '/static/style.css',
    '/static/theme.js',
    '/static/icon-192.png',
    '/static/icon-512.png'
];

self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(URLS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(name) {
                    if (name !== CACHE_NAME) {
                        return caches.delete(name);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', function(event) {
    if (event.request.method !== 'GET' || event.request.url.includes('/api/')) {
        return;
    }
    event.respondWith(
        fetch(event.request).then(function(response) {
            if (response.status === 200) {
                const responseClone = response.clone();
                caches.open(CACHE_NAME).then(function(cache) {
                    cache.put(event.request, responseClone);
                });
            }
            return response;
        }).catch(function() {
            return caches.match(event.request);
        })
    );
});
