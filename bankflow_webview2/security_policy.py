"""Offline browser policy for the in-memory frontend document."""

from __future__ import annotations


CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src 'none'; "
    "connect-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


FRONTEND_GUARD_SCRIPT = r"""
<script>
(() => {
  const allowed = (raw) => {
    try {
      const url = new URL(String(raw), window.location.href);
      return ['data:', 'blob:', 'about:'].includes(url.protocol);
    } catch (_) { return false; }
  };
  document.addEventListener('click', (event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (link && !allowed(link.getAttribute('href'))) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
  window.open = () => null;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => allowed(typeof input === 'string' ? input : input.url)
    ? nativeFetch(input, init)
    : Promise.reject(new Error('External network is disabled'));
  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    if (!allowed(url)) throw new Error('External network is disabled');
    return nativeOpen.call(this, method, url, ...rest);
  };
  window.WebSocket = class { constructor() { throw new Error('External network is disabled'); } };
  window.EventSource = class { constructor() { throw new Error('External network is disabled'); } };
})();
</script>
"""
