// Service worker registration. Kept in a file, not inline, so the Content Security Policy (script-src 'self') allows it.
// The worker caches the app shell and serves saved list data when offline. Failure is not fatal.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
