'use strict';

// The standalone UI and the ARGUS frame share the same application and API.
(function (root) {
  const views = Object.freeze({chat: 'research', build: 'research', candidates: 'library', database: 'evidence', tools: 'model'});
  function context(location, framed) {
    const prefix = /^\/research(?:\/|$)/.test(location.pathname) ? '/research' : '';
    return {prefix, embedded: Boolean(prefix && framed && new URLSearchParams(location.search).get('embed') === 'argus')};
  }
  function apiPath(path, prefix) {
    return prefix && path.startsWith('/api/') ? prefix + path : path;
  }
  function localApiUrl(value, origin, prefix) {
    try {
      const url = new URL(value, origin);
      if (url.origin !== origin || url.username || url.password || url.search || url.hash) return null;
      const path = prefix && url.pathname.startsWith(prefix + '/api/') ? url.pathname.slice(prefix.length) : url.pathname;
      if (!path.startsWith('/api/')) return null;
      return {path, href: origin + apiPath(path, prefix)};
    } catch { return null; }
  }
  function selectionMessage(event, parent, origin) {
    if (event.origin !== origin || event.source !== parent) return null;
    const data = event.data;
    if (!data || typeof data !== 'object' || data.type !== 'argus:research-select') return null;
    if (data.view !== undefined && !Object.hasOwn(views, data.view)) return null;
    if (data.projectId !== undefined && data.projectId !== null && (typeof data.projectId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(data.projectId))) return null;
    if (!data.view && !data.projectId) return null;
    return {projectId: data.projectId || null, view: data.view || null};
  }
  const integration = Object.freeze({views, context, apiPath, localApiUrl, selectionMessage});
  if (typeof module !== 'undefined' && module.exports) module.exports = integration;
  else root.LanMIntegration = integration;
})(globalThis);
