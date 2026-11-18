'use strict';

// The standalone UI and the ARGUS frame share the same application and API.
(function (root) {
  const views = Object.freeze({chat: 'research', build: 'research', candidates: 'library', database: 'evidence', tools: 'model'});
  function context(location, framed) {
    const prefix = /^\/research(?:\/|$)/.test(location.pathname) ? '/research' : '';
    const parameters = new URLSearchParams(location.search);
    const embedded = Boolean(prefix && framed && parameters.get('embed') === 'argus');
    return {prefix, embedded, compact: embedded && parameters.get('compact') === '1'};
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
  function layoutMessage(event, parent, origin) {
    if (event.origin !== origin || event.source !== parent) return null;
    const data = event.data;
    return data?.type === 'argus:research-layout' && typeof data.expanded === 'boolean' ? {expanded: data.expanded} : null;
  }
  const integration = Object.freeze({views, context, apiPath, localApiUrl, selectionMessage, layoutMessage});
  if (typeof module !== 'undefined' && module.exports) module.exports = integration;
  else root.LanMIntegration = integration;
})(globalThis);
