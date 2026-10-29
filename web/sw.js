"use strict";

// Bump this version whenever any shell asset below changes.
const CACHE_VERSION = "gl-shell-v36-2026-10-30";
// Previous cache generations: gl-shell-v35-2026-10-30, gl-shell-v34-2026-10-29, gl-shell-v33-2026-10-29, gl-shell-v32-2026-10-28, gl-shell-v31-2026-10-28, gl-shell-v30-2026-10-28, gl-shell-v29-2026-10-28, gl-shell-v28-2026-10-28, gl-shell-v27-2026-10-28, gl-shell-v26-2026-10-28, gl-shell-v25-2026-10-27
const SHELL = [
  "/",
  "/index.html",
  "/style.css?v=36",
  "/app.js?v=36",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/apple-touch-icon.png",
  "/assets/frames/frame_ember.png",
  "/assets/frames/frame_clown.png",
  "/assets/tiers/bronze.png",
  "/assets/tiers/silver.png",
  "/assets/tiers/gold.png",
  "/assets/tiers/sapphire.png",
  "/assets/tiers/ruby.png",
  "/assets/tiers/emerald.png",
  "/assets/tiers/amethyst.png",
  "/assets/tiers/pearl.png",
  "/assets/tiers/obsidian.png",
  "/assets/tiers/diamond.png",
  "/assets/tiers/material/bronze.png",
  "/assets/tiers/material/silver.png",
  "/assets/tiers/material/gold.png",
  "/assets/tiers/material/sapphire.png",
  "/assets/tiers/material/ruby.png",
  "/assets/tiers/material/emerald.png",
  "/assets/tiers/material/amethyst.png",
  "/assets/tiers/material/pearl.png",
  "/assets/tiers/material/obsidian.png",
  "/assets/tiers/material/diamond.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function isApiRequest(url) {
  return (
    url.pathname.startsWith("/v1/") ||
    url.pathname === "/health" ||
    url.pathname.startsWith("/avatars/")
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isApiRequest(url)) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put("/index.html", copy));
          }
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_VERSION);
          return (
            (await cache.match("/index.html")) ||
            (await cache.match("/")) ||
            new Response(
              "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>联赛</title><body style='background:#080b16;color:#f4f7ff;font-family:system-ui;display:grid;place-items:center;min-height:100vh;margin:0'><main style='text-align:center;padding:2rem'><h1>联赛</h1><p>当前离线，请恢复网络后重新打开。</p></main></body>",
              { headers: { "Content-Type": "text/html; charset=utf-8" } }
            )
          );
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    })
  );
});
