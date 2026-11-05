'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {projects: [], project: null, candidates: [], methods: [], sources: [], runs: [], testingBatches: [], pool: 'all', mode: 'research', tab: 'research', job: null, stream: null, runtime: null, candidateRequest: 0};
const metals = ['La', 'Ce', 'Pr', 'Nd', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Y'];
const fieldInfo = {
  prepared_material_cost_usd_per_l: ['Prepared material cost', 'USD / L of bed'],
  collected_target_kg_per_l_cycle: ['Collected target per cycle', 'kg target / L of bed / cycle'],
  usable_lifetime_cycles: ['Useful material lifetime', 'cycles'],
  cycle_time_hours: ['Complete cycle time', 'hours / cycle'],
  target_production_kg_per_day: ['Target production', 'kg target / day'],
  operating_days_per_year: ['Operating days', 'days / year'],
  regeneration_cost_usd_per_l_cycle: ['Regeneration cost', 'USD / L of bed / cycle'],
  electricity_kwh_per_l_cycle: ['Electricity consumption', 'kWh / L of bed / cycle'],
  electricity_price_usd_per_kwh: ['Electricity price', 'USD / kWh'],
  labor_hours_per_day: ['Labor requirement', 'hours / day'],
  labor_rate_usd_per_hour: ['Labor rate', 'USD / hour'],
  equipment_cost_usd: ['Equipment investment', 'USD'],
  equipment_life_years: ['Equipment life', 'years'],
  discount_rate: ['Discount rate', 'fraction, 0–1'],
  maintenance_fraction_per_year: ['Annual maintenance', 'fraction of equipment cost'],
  product_price_usd_per_kg: ['Product price assumption', 'USD / kg target'],
  minimum_purity_fraction: ['Required product purity', 'fraction, 0–1'],
  minimum_recovery_fraction: ['Required target recovery', 'fraction, 0–1'],
  cost_ceiling_usd_per_kg: ['Separation cost allowance', 'USD / kg target'],
  purity_fraction: ['Measured purity', 'fraction, 0–1'],
  recovery_fraction: ['Measured recovery', 'fraction, 0–1'],
  cycles_observed: ['Cycles actually observed', 'cycles'],
  working_capacity_kg_per_l: ['Measured working capacity', 'kg / L of bed']
};
const assumptionGroups = [
  ['Capture material & throughput', ['prepared_material_cost_usd_per_l', 'collected_target_kg_per_l_cycle', 'usable_lifetime_cycles', 'cycle_time_hours', 'target_production_kg_per_day', 'operating_days_per_year']],
  ['Operating costs', ['regeneration_cost_usd_per_l_cycle', 'electricity_kwh_per_l_cycle', 'electricity_price_usd_per_kwh', 'labor_hours_per_day', 'labor_rate_usd_per_hour']],
  ['Equipment & product requirements', ['equipment_cost_usd', 'equipment_life_years', 'discount_rate', 'maintenance_fraction_per_year', 'product_price_usd_per_kg', 'cost_ceiling_usd_per_kg', 'minimum_purity_fraction', 'minimum_recovery_fraction']]
];

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = String(text);
  return item;
}
function replace(target, ...children) { target.replaceChildren(...children.filter(Boolean)); }
function button(text, callback, className = 'button') {
  const item = node('button', className, text); item.type = 'button'; item.addEventListener('click', callback); return item;
}
function humanize(value) { return String(value || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()); }
function displayValue(value) {
  if (value === undefined || value === null || value === '') return 'Not specified';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
function numeric(value) { return value !== null && value !== '' && Number.isFinite(Number(value)); }
function number(value, digits = 4) {
  if (!numeric(value)) return '—';
  const n = Number(value);
  if (n !== 0 && Math.abs(n) < 0.0001) return n.toExponential(2);
  return new Intl.NumberFormat('en-US', {maximumFractionDigits: digits}).format(n);
}
function money(value) { return numeric(value) ? '$' + number(value, Number(value) < 10 ? 3 : 2) : '—'; }
function date(value) {
  if (!value) return '';
  const d = new Date(typeof value === 'number' && value < 100000000000 ? value * 1000 : value);
  return Number.isNaN(d.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}).format(d);
}
function badge(text, kind = '') { return node('span', 'badge ' + kind, text); }
function asList(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function safeUrl(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } }
function testingDownloadUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    if (!state.project || url.origin !== window.location.origin || url.username || url.password || url.search || url.hash) return null;
    const match = /^\/api\/projects\/([A-Za-z0-9_-]+)\/testing-batches\/([A-Za-z0-9_-]+)\/csv$/.exec(url.pathname);
    return match && match[1] === state.project.id ? url.href : null;
  } catch { return null; }
}
function link(text, url, preview = true) {
  const download = testingDownloadUrl(url);
  if (download) { const item = node('a', '', text); item.href = download; item.download = ''; item.title = 'Download saved testing CSV'; return item; }
  const safe = safeUrl(url); if (!safe) return node('span', '', text);
  const item = node('a', '', text); item.href = safe; item.target = '_blank'; item.rel = 'noopener noreferrer';
  if (preview) {
    item.title = 'Preview source evidence';
    item.addEventListener('click', event => {
      if (!state.project || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); previewEvidence({url: safe});
    });
  }
  return item;
}
function labelFor(key) { return (fieldInfo[key] || [humanize(key)])[0]; }
function objectDetails(object, labels = {}) {
  const dl = node('dl', 'detail-key-values');
  for (const [key, value] of Object.entries(object || {})) { dl.append(node('dt', '', labels[key] || labelFor(key)), node('dd', '', displayValue(value))); }
  return dl;
}
function details(title, content, open = false) {
  const item = node('details', 'detail-section'); item.open = open;
  item.append(node('summary', '', title), content); return item;
}
function raw(value) { return node('pre', 'raw-data', typeof value === 'string' ? value : JSON.stringify(value, null, 2)); }
function textList(value, className = 'uncertainty-list') {
  const list = node('ul', className);
  for (const item of asList(value)) list.append(node('li', '', typeof item === 'object' ? item.message || item.description || item.reason || displayValue(item) : item));
  return list;
}

async function api(path, options = {}) {
  const init = {...options, headers: {'Accept': 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers}};
  if (options.body && typeof options.body !== 'string') init.body = JSON.stringify(options.body);
  let response;
  try { response = await fetch(path, init); } catch { throw new Error('The local workspace is not responding. Check that its server is running.'); }
  let data;
  try { data = await response.json(); } catch { throw new Error(`The server returned an unreadable response (${response.status}).`); }
  if (!response.ok || data.error) throw new Error(typeof data.error === 'string' ? data.error : data.error?.message || `Request failed (${response.status}).`);
  return data;
}
let toastTimer;
function toast(message, error = false) {
  const item = $('#toast'); item.textContent = message; item.classList.toggle('error', error); item.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { item.hidden = true; }, error ? 8000 : 4500);
}
function showGlobalError(message) {
  const item = $('#global-error'); replace(item, node('span', '', message), button('×', () => { item.hidden = true; }, 'icon-button')); item.hidden = false;
}
function formError(form, message = '') { const item = $('.form-error', form); if (item) { item.textContent = message; item.hidden = !message; } }
async function busy(control, work, errorHandler = null) {
  if (control?.disabled) return;
  if (control) control.disabled = true;
  try { return await work(); } catch (error) { if (errorHandler) errorHandler(error.message); else toast(error.message, true); }
  finally { if (control) control.disabled = false; }
}
function showDialog(id) { const dialog = $(id); const form = $('form', dialog); if (form) formError(form); dialog.showModal(); }
function showDetail(kicker, content) { $('#detail-kicker').textContent = kicker; replace($('#detail-content'), content); const dialog = $('#detail-dialog'); dialog.classList.toggle('evidence-dialog', content.classList.contains('evidence-preview')); if (!dialog.open) dialog.showModal(); dialog.scrollTop = 0; }
function goTab(tab) {
  state.tab = tab;
  $$('[data-tab]').forEach(item => { const active = item.dataset.tab === tab; item.classList.toggle('active', active); item.setAttribute('aria-selected', String(active)); });
  $$('.tab-panel').forEach(item => { item.hidden = item.id !== 'panel-' + tab; });
  if (tab === 'library' && state.project) { loadCandidates().catch(error => toast(error.message, true)); loadTestingBatches().catch(error => toast(error.message, true)); }
  if (tab === 'evidence' && state.project) loadSources().catch(error => toast(error.message, true));
  if (tab === 'model' && state.project) { loadMethods().catch(error => toast(error.message, true)); loadRuns().catch(error => toast(error.message, true)); loadScalePredictions().catch(error => toast(error.message, true)); }
}
function setMode(mode) {
  state.mode = mode;
  $$('[data-mode]').forEach(item => { const active = item.dataset.mode === mode; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
  $('#conversation-mode-label').textContent = mode === 'build' ? 'METHOD-BUILDING CONVERSATION' : 'RESEARCH CONVERSATION';
  $('#composer-mode').textContent = mode === 'build' ? 'Build and inspect a reusable method' : 'Research with saved evidence';
  $('#chat-input').placeholder = mode === 'build' ? 'Describe the method to build, its inputs, and the scientific assumptions it should make explicit…' : 'Ask about lanmodulins, examine an assumption, or explore the evidence…';
  if (!$('#messages .message')) renderMessages([]);
}

async function loadStatus() {
  state.runtime = await api('/api/status');
  const data = state.runtime;
  const available = data.codex_available ?? data.codex?.available ?? data.runtime?.available ?? data.available;
  $('#runtime-dot').className = 'status-dot ' + (available ? 'ready' : 'unavailable');
  $('#runtime-label').textContent = available ? (data.connected ? 'Agent connected' : 'Agent available') : 'Agent unavailable';
  $('#runtime-description').textContent = available ? 'Connects when a conversation starts' : 'Saved data and calculations available';
  $('#app-version').textContent = data.version || data.installed_version || '';
  $('#runtime-notice').textContent = available ? 'Calculations use saved inputs and explicit method versions.' : 'Agent connection is unavailable. Saved evidence and direct calculations remain accessible.';
  const modelRows = Array.isArray(data.models) ? data.models : [];
  const configured = typeof data.model === 'string' ? data.model : typeof data.default_model === 'string' ? data.default_model : '';
  const models = modelRows.map(item => typeof item === 'string' ? {id: item, name: item} : {id: item.id || item.model, name: item.display_name || item.displayName || item.name || item.id || item.model}).filter(item => item.id);
  if (configured && !models.some(item => item.id === configured)) models.unshift({id: configured, name: configured});
  replace($('#model-select'), ...models.map(item => { const option = node('option', '', item.name); option.value = item.id; return option; }));
  if (!models.length) { const option = node('option', '', 'Configured model'); option.value = ''; $('#model-select').append(option); }
  if (configured) $('#model-select').value = configured;
}
async function loadProjects() {
  const data = await api('/api/projects'); state.projects = data.projects || data; renderProjects();
}
function renderProjects() {
  const list = $('#project-list'); replace(list);
  for (const project of state.projects) {
    const item = button('', () => selectProject(project.id), 'project-button' + (state.project?.id === project.id ? ' active' : ''));
    const label = node('span'); label.append(node('strong', '', project.name), node('small', '', [project.target, project.competitor].filter(Boolean).join(' / ')));
    item.append(node('span', 'project-icon', '⌁'), label); item.title = project.name; list.append(item);
  }
  if (!state.projects.length) list.append(node('p', 'muted small', 'Your projects will appear here.'));
}
async function selectProject(id) {
  if (state.job && state.project?.id !== id) { toast('Finish or stop the active conversation before switching projects.'); return; }
  try {
    const data = await api('/api/projects/' + encodeURIComponent(id)); state.project = data.project || data; state.runs = []; state.testingBatches = []; replace($('#testing-batch-list'));
    try { localStorage.setItem('lanm-project', id); } catch {}
    $('#welcome').hidden = true; $('#workspace').hidden = false; $('#global-error').hidden = true;
    $('#ranking-result').hidden = true; $('#calculation-result').hidden = true;
    renderProjects(); renderProject();
    const results = await Promise.allSettled([loadMessages(), loadCandidates(), loadSources(), loadRuns(), loadScalePredictions(), loadTestingBatches()]);
    results.forEach(result => { if (result.status === 'rejected') toast(result.reason.message, true); });
    requestAnimationFrame(() => { $('#messages').scrollTop = $('#messages').scrollHeight; });
  } catch (error) { showGlobalError(error.message); }
}
async function refreshProject() {
  if (!state.project) return;
  const data = await api('/api/projects/' + encodeURIComponent(state.project.id)); state.project = data.project || data;
  state.runs = state.runs.map(run => ({...run, stale: run.revision !== undefined && run.revision !== state.project.revision})); renderProject();
  state.projects = state.projects.map(item => item.id === state.project.id ? {...item, ...state.project} : item); renderProjects();
}
function renderProject() {
  const p = state.project;
  $('#project-title').textContent = p.name; $('#project-breadcrumb').textContent = p.name;
  $('#project-description').textContent = p.description || 'Explore candidates and preserve the evidence behind each decision.';
  $('#project-target').textContent = p.target; $('#project-competitor').textContent = p.competitor;
  const config = p.configuration || {};
  $('#configuration-label').textContent = config.support && config.feed ? `${config.support} · ${config.feed}` : 'Support and feed: configure in project settings';
  $('#configuration-label').title = $('#configuration-label').textContent;
  $('#project-revision').textContent = p.revision !== undefined ? `Revision ${typeof p.revision === 'object' ? p.revision.id : p.revision}` : '';
  $('#experiment-count').textContent = `${p.experiment_count || 0} experimental record${p.experiment_count === 1 ? '' : 's'}`;
  replace($('#context-summary'));
  for (const [label, value] of [['Target', p.target], ['Comparison', p.competitor], ['Support', config.support || 'Not specified'], ['Feed', config.feed || 'Not specified']]) $('#context-summary').append(node('dt', '', label), node('dd', '', value));
  renderAssumptions(); renderLatest(state.runs.find(run => (run.result || run).kind !== 'rank') || p.latest_run);
}
function renderLatest(run) {
  const summary = run?.summary || run?.outputs || {};
  const target = $('#latest-summary'); replace(target);
  if (numeric(summary.cost_usd_per_kg)) { target.append(node('div', 'latest-number', money(summary.cost_usd_per_kg)), node('div', 'latest-unit', run.outputs ? 'USD / kg · conditional method estimate' : `per kg ${state.project?.target || 'target'} · conditional estimate`), node('p', '', `${state.methods.find(item => item.id === run.method_id)?.name || run.method_id || 'Saved method'}${run.method_version ? ' · v' + run.method_version : ''}. Inspect the boundary and assumptions before interpreting this result.`)); if (run.stale) target.append(badge('Project changed since this run', 'amber')); }
  else if (run?.outputs) { target.append(node('h3', '', state.methods.find(item => item.id === run.method_id)?.name || 'Registered method result'), node('p', '', 'A calculation is saved. Open the method result to inspect its outputs and assumptions.')); if (run.stale) target.append(badge('Project changed since this run', 'amber')); }
  else target.append(node('p', 'muted', 'No calculation saved for this project yet.'));
}

function appendInline(parent, text) {
  const expression = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((?:https?:\/\/[^)]+|\/api\/projects\/[A-Za-z0-9_-]+\/testing-batches\/[A-Za-z0-9_-]+\/csv)\))/g;
  let index = 0;
  for (const match of text.matchAll(expression)) {
    parent.append(document.createTextNode(text.slice(index, match.index)));
    const value = match[0];
    if (value.startsWith('**')) parent.append(node('strong', '', value.slice(2, -2)));
    else if (value.startsWith('`')) parent.append(node('code', '', value.slice(1, -1)));
    else { const split = value.indexOf(']('); parent.append(link(value.slice(1, split), value.slice(split + 2, -1))); }
    index = match.index + value.length;
  }
  parent.append(document.createTextNode(text.slice(index)));
}
function renderRichText(parent, text) {
  replace(parent); const lines = String(text || '').split('\n'); let codeLines = null; let paragraph = [];
  const flush = () => { if (paragraph.length) { const p = node('p'); appendInline(p, paragraph.join('\n')); parent.append(p); paragraph = []; } };
  const tableCells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
    const line = lines[lineIndex];
    if (line.startsWith('```')) { flush(); if (codeLines) { parent.append(node('pre', '', codeLines.join('\n'))); codeLines = null; } else codeLines = []; continue; }
    if (codeLines) { codeLines.push(line); continue; }
    if (!line.trim()) { flush(); continue; }
    if (line.includes('|') && lines[lineIndex + 1]?.includes('|') && tableCells(lines[lineIndex + 1]).every(cell => /^:?-{3,}:?$/.test(cell))) {
      flush(); const table = node('table', 'message-table'); const head = node('thead'); const row = node('tr'); const columns = tableCells(line);
      for (const cell of columns) { const th = node('th'); appendInline(th, cell); row.append(th); } head.append(row); table.append(head);
      const body = node('tbody'); lineIndex += 2;
      while (lineIndex < lines.length && lines[lineIndex].includes('|') && lines[lineIndex].trim()) { const tr = node('tr'); const values = tableCells(lines[lineIndex]); for (let column = 0; column < columns.length; column++) { const td = node('td'); appendInline(td, values[column] || ''); tr.append(td); } body.append(tr); lineIndex++; }
      lineIndex--; table.append(body); const scroll = node('div', 'table-scroll'); scroll.append(table); parent.append(scroll); continue;
    }
    if (/^#{1,6}\s/.test(line)) { flush(); const heading = node('h4'); appendInline(heading, line.replace(/^#{1,6}\s+/, '')); parent.append(heading); }
    else if (/^\s*[-*]\s/.test(line)) { flush(); const p = node('p', 'list-line'); appendInline(p, '• ' + line.replace(/^\s*[-*]\s+/, '')); parent.append(p); }
    else paragraph.push(line);
  }
  flush(); if (codeLines) parent.append(node('pre', '', codeLines.join('\n')));
}
function messageNode(role, text, streaming = false) {
  const article = node('article', 'message ' + (role === 'user' ? 'user' : 'assistant') + (streaming ? ' streaming' : ''));
  const meta = node('div', 'message-meta'); meta.append(node('span', 'message-avatar', role === 'user' ? 'You' : 'L'), node('span', '', role === 'user' ? 'You' : role === 'assistant' ? 'LanM Research' : 'Workspace'));
  const body = node('div', 'message-body'); renderRichText(body, text); article.append(meta, body); return article;
}
function renderMessages(messages) {
  const target = $('#messages'); replace(target);
  if (!messages.length) {
    const welcome = node('div', 'conversation-empty'); welcome.append(node('div', 'agent-symbol', '⌁'), node('h2', '', state.mode === 'build' ? 'Turn a scientific method into a reusable tool.' : 'What would you like to investigate?'), node('p', '', state.mode === 'build' ? 'Describe the inputs, equations, and expected checks. Draft methods remain inspectable before registration.' : 'Work through the science, inspect a candidate, or question the assumptions behind a calculation. The conversation stays with this project.')); target.append(welcome); return;
  }
  for (const message of messages) target.append(messageNode(message.role, message.content || message.text || ''));
  target.scrollTop = target.scrollHeight;
}
async function loadMessages() { if (!state.project) return; const data = await api(`/api/projects/${encodeURIComponent(state.project.id)}/messages`); renderMessages(data.messages || []); }
async function submitChat(event) {
  event.preventDefault(); if (!state.project || state.job) return;
  const input = $('#chat-input'); const message = input.value.trim(); if (!message) return;
  await busy($('#send-message'), async () => {
    const payload = {message, mode: state.mode}; const model = $('#model-select').value; if (model) payload.model = model;
    const data = await api(`/api/projects/${encodeURIComponent(state.project.id)}/chat`, {method: 'POST', body: payload});
    if (!data.job_id) throw new Error('The agent did not return a task identifier.');
    $('.conversation-empty', $('#messages'))?.remove(); $('#messages').append(messageNode('user', message));
    const response = messageNode('assistant', '', true); $('#messages').append(response);
    state.job = {id: data.job_id, projectId: state.project.id, response, text: ''}; input.value = ''; input.disabled = true;
    $('#job-activity').hidden = false; $('#job-activity-text').textContent = 'Connecting to the research agent…'; $('#conversation-saved').textContent = 'Work in progress';
    startStream(data.job_id); $('#messages').scrollTop = $('#messages').scrollHeight;
  });
  if (state.job) $('#send-message').disabled = true;
}
function startStream(jobId) {
  state.stream?.close(); const stream = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`); state.stream = stream;
  stream.onopen = () => { if (state.job?.id === jobId) { state.job.text = ''; $('.message-body', state.job.response).textContent = ''; } };
  stream.onmessage = event => {
    let data; try { data = JSON.parse(event.data); } catch { return; }
    if (!state.job || state.job.id !== jobId) return;
    if (data.type === 'activity') $('#job-activity-text').textContent = data.text || data.message || 'Working…';
    if (data.type === 'text') {
      const target = $('#messages'); const stick = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
      state.job.text += data.text || data.delta || ''; $('.message-body', state.job.response).textContent = state.job.text;
      if (stick) target.scrollTop = target.scrollHeight;
    }
    if (data.type === 'done') finishJob(data).catch(error => toast(error.message, true));
    if (data.type === 'error') finishJob(data, data.text || data.error || 'The agent could not complete this request.').catch(error => toast(error.message, true));
  };
  stream.onerror = () => { if (state.job?.id === jobId) $('#job-activity-text').textContent = 'Reconnecting to the activity stream… You can still stop this task.'; };
}
async function finishJob(data, error = null) {
  const job = state.job; if (!job) return;
  state.stream?.close(); state.stream = null; state.job = null;
  $('#chat-input').disabled = false; $('#send-message').disabled = false; $('#cancel-job').disabled = false; $('#job-activity').hidden = true; $('#conversation-saved').textContent = 'Saved with this project';
  job.response.classList.remove('streaming'); renderRichText($('.message-body', job.response), job.text || data.answer || data.text || (error ? 'This request did not finish.' : 'Task completed.'));
  if (error) toast(error, true); else if (data.status === 'cancelled' || data.status === 'interrupted') toast('Task stopped. Completed changes remain saved.');
  const results = await Promise.allSettled([loadMessages(), refreshProject(), loadCandidates(), loadRuns(), loadSources(), loadMethods(), loadScalePredictions(), loadTestingBatches()]);
  results.forEach(result => { if (result.status === 'rejected') toast(result.reason.message, true); });
}

async function loadCandidates() {
  if (!state.project) return;
  const request = ++state.candidateRequest; const params = new URLSearchParams({project_id: state.project.id, q: $('#candidate-search').value.trim(), pool: state.pool});
  const data = await api('/api/candidates?' + params); if (request !== state.candidateRequest) return;
  state.candidates = data.candidates || []; const total = data.total ?? state.candidates.length;
  $('#candidate-count').textContent = state.candidates.length < total ? `Showing ${state.candidates.length} of ${number(total, 0)} candidates` : `${number(total, 0)} candidate${total === 1 ? '' : 's'}`;
  const body = $('#candidate-rows'); replace(body);
  for (const candidate of state.candidates) {
    const tr = node('tr'); tr.tabIndex = 0; tr.setAttribute('aria-label', `Inspect ${candidate.name || candidate.id}`);
    tr.addEventListener('click', () => inspectCandidate(candidate.id)); tr.addEventListener('keydown', event => { if (event.key === 'Enter') inspectCandidate(candidate.id); });
    const title = node('td'); title.append(node('span', 'candidate-name', candidate.name || candidate.id), node('span', 'candidate-sub', candidate.id));
    const organism = node('td'); organism.append(node('span', '', candidate.organism || 'Organism not listed'), node('span', 'candidate-sub mono', candidate.accession || ''));
    const evidence = node('td'); const count = candidate.accepted_experiment_count || 0; evidence.append(badge(count ? `${count} accepted result${count === 1 ? '' : 's'}` : 'Untested in project', count ? '' : 'neutral'));
    tr.append(title, organism, evidence, node('td', 'row-arrow', '↗')); body.append(tr);
  }
  $('#library-empty').hidden = state.candidates.length > 0;
  replace($('#candidate-options'), ...state.candidates.map(candidate => { const item = node('option', '', candidate.name || candidate.id); item.value = candidate.id; return item; }));
  const select = $('#calculation-candidate'); const prior = select.value; replace(select, Object.assign(node('option', '', 'Project scenario'), {value: ''}));
  for (const candidate of state.candidates) { const item = node('option', '', candidate.name || candidate.id); item.value = candidate.id; select.append(item); }
  if (state.candidates.some(candidate => candidate.id === prior)) select.value = prior;
}
async function inspectCandidate(id) {
  showDetail('CANDIDATE RECORD', node('div', 'loading-shimmer', 'Loading candidate evidence…'));
  try {
    const data = await api(`/api/candidates/${encodeURIComponent(id)}?project_id=${encodeURIComponent(state.project.id)}`);
    const candidate = data.candidate || data; const content = node('div');
    content.append(node('h2', 'detail-title', candidate.name || candidate.id), node('p', 'detail-subtitle', [candidate.id, candidate.organism, candidate.accession].filter(Boolean).join(' · ')));
    const actions = node('div', 'detail-actions');
    actions.append(button('Calculate this candidate', () => { $('#detail-dialog').close(); ensureCandidateOption(candidate); $('#calculation-candidate').value = candidate.id; goTab('model'); $('#calculate-form').scrollIntoView({behavior: 'smooth', block: 'center'}); }), button('Add experimental result', () => { $('#detail-dialog').close(); openExperiment(candidate.id); }, 'button primary'));
    content.append(actions);
    const screening = candidate.screening || {};
    const mean = screening.mean || screening.normalized_mean || screening.profile || {};
    if (Object.keys(mean).length) {
      const section = node('section', 'detail-section'); section.append(node('h3', '', 'Published screening profile'), node('p', '', 'Normalized screening observations describe relative signals under the published assay conditions. They are not process capacity or recovery.'));
      const values = Object.entries(mean).filter(([, value]) => numeric(value)); const maximum = Math.max(...values.map(([, value]) => Number(value)), 0);
      const bars = node('div', 'profile-bars');
      for (const [metal, value] of values) { const bar = node('div', 'profile-bar' + (metal === state.project.target ? ' target' : '')); const fill = node('i'); fill.style.height = `${maximum ? Number(value) / maximum * 90 : 0}px`; bar.title = `${metal}: ${number(value)}`; bar.append(fill, node('span', '', metal)); bars.append(bar); }
      section.append(bars, details('Inspect screening measurements', raw(screening))); content.append(section);
    } else if (Object.keys(screening).length) content.append(details('Published screening record', raw(screening), true));
    const experiments = candidate.experiments || data.experiments || [];
    const section = node('section', 'detail-section'); section.append(node('h3', '', 'Project experimental results'));
    if (!experiments.length) section.append(node('p', '', 'No experimental results have been added for this candidate in this project.'));
    for (const experiment of experiments) section.append(experimentCard(experiment, () => inspectCandidate(id)));
    content.append(section);
    if (candidate.sequence) content.append(details('Protein sequence', raw(candidate.sequence)));
    const sourceIds = candidate.source_ids || candidate.sources || screening.source_ids || candidate.source_id;
    if (sourceIds) content.append(details('Source references', raw(sourceIds)));
    const evidence = node('section', 'detail-section'); evidence.append(node('h3', '', 'Published evidence and assay contexts'), node('p', 'muted small', 'Loading retained source observations…')); content.append(evidence);
    content.append(details('Complete candidate record', raw(candidate)));
    showDetail('CANDIDATE RECORD', content);
    try {
      const retained = await api('/api/library-evidence?' + new URLSearchParams({candidate_id: id}));
      replace(evidence, node('h3', '', 'Published evidence and assay contexts'));
      for (const [key, label] of [['contexts', 'Experimental contexts'], ['assertions', 'Reported observations'], ['formulas', 'Source formulas']]) if (retained[key]?.length) evidence.append(details(`${label} (${retained[key].length})`, raw(retained[key]), key === 'contexts'));
      if (!Object.values(retained).some(value => Array.isArray(value) && value.length)) evidence.append(node('p', 'muted small', 'No additional source contexts are linked to this candidate. Its screening record remains available above.'));
    } catch (error) { replace(evidence, node('p', 'muted small', 'Additional source contexts could not be loaded: ' + error.message)); }
  } catch (error) { showDetail('CANDIDATE RECORD', node('div', 'notice error', error.message)); }
}
function ensureCandidateOption(candidate) {
  if (!$$('option', $('#calculation-candidate')).some(item => item.value === candidate.id)) { const item = node('option', '', candidate.name || candidate.id); item.value = candidate.id; $('#calculation-candidate').append(item); }
}
function experimentCard(experiment, afterAccept) {
  const card = node('div', 'experiment-record'); const accepted = experiment.status === 'accepted';
  card.append(badge(accepted ? 'Accepted record' : 'Draft • not used in comparison', accepted ? '' : 'amber'), node('h4', '', experiment.label || experiment.id), node('p', '', date(experiment.created_at)), objectDetails(experiment.conditions || {}), objectDetails(experiment.metrics || {}));
  if (experiment.notes) card.append(node('p', '', experiment.notes));
  if (experiment.applicability_issues?.length) { const notice = node('div', 'notice'); notice.append(node('strong', '', 'Applicability limits'), textList(experiment.applicability_issues)); card.append(notice); }
  if (!accepted) {
    const label = node('label', 'field', 'Reason for accepting this result'); const input = node('textarea'); input.rows = 2; input.placeholder = 'Confirm the evidence basis and applicable conditions…'; label.append(input); card.append(label);
    const accept = button('Accept reviewed result', () => busy(accept, async () => {
      const reason = input.value.trim(); if (!reason) throw new Error('Record a reason before accepting this experimental result.');
      await api(`/api/experiments/${encodeURIComponent(experiment.id)}/accept`, {method: 'POST', body: {reason}});
      await refreshProject(); await loadCandidates(); toast('Experimental result accepted. Previous evidence remains preserved.'); afterAccept();
    }), 'button primary'); card.append(accept);
  } else if (experiment.acceptance_reason) card.append(node('p', '', 'Acceptance basis: ' + experiment.acceptance_reason));
  return card;
}
function openExperiment(candidateId = '') {
  if (!state.project) return;
  const form = $('#experiment-form'); form.reset(); form.elements.candidate_id.value = candidateId;
  form.elements.support.value = state.project.configuration?.support || ''; form.elements.feed.value = state.project.configuration?.feed || '';
  $('#experiment-target').textContent = state.project.target; showDialog('#experiment-dialog');
}

function renderAssumptions() {
  const assumptions = state.project.assumptions || {}; const fields = $('#assumptions-fields'); replace(fields);
  const seen = new Set();
  const makeGroup = (title, keys, open) => {
    const present = keys.filter(key => Object.hasOwn(assumptions, key)); if (!present.length) return;
    const group = node('details', 'assumption-group'); group.open = open; group.append(node('summary', '', title)); const grid = node('div', 'assumption-grid');
    for (const key of present) {
      seen.add(key); const info = fieldInfo[key] || [humanize(key), state.project.assumption_details?.find(item => item.parameter === key)?.unit || ''];
      const label = node('label', 'field', info[0]); const input = node('input'); input.type = 'number'; input.name = key; input.step = 'any'; input.required = true; input.value = typeof assumptions[key] === 'object' ? assumptions[key].value : assumptions[key]; input.dataset.assumption = key;
      label.append(node('span', 'assumption-unit', info[1]), input); grid.append(label);
    }
    group.append(grid); fields.append(group);
  };
  assumptionGroups.forEach(([title, keys], i) => makeGroup(title, keys, i === 0)); makeGroup('Other method inputs', Object.keys(assumptions).filter(key => !seen.has(key)), false);
  if (!Object.keys(assumptions).length) fields.append(node('p', 'muted small', 'No scenario assumptions have been saved yet.'));
  $('#assumption-reason').value = '';
  const revisions = state.project.revisions || []; $('#revision-count').textContent = revisions.length ? `(${revisions.length})` : '';
  replace($('#revision-list'));
  for (const revision of [...revisions].reverse().slice(0, 20)) {
    const item = node('div', 'revision-entry'); item.append(node('strong', '', `${date(revision.created_at)}${revision.scope ? ' · ' + revision.scope : ''}`), node('p', '', revision.reason || 'Saved revision'));
    if (revision.values) item.append(node('code', '', Object.entries(revision.values).map(([key, value]) => `${labelFor(key)}: ${displayValue(value)}`).join(' · ')));
    $('#revision-list').append(item);
  }
  if (!revisions.length) $('#revision-list').append(node('p', 'muted small', 'No revisions recorded.'));
}
async function saveAssumptions(event) {
  event.preventDefault(); await busy($('#save-assumptions'), async () => {
    const values = {};
    $$('[data-assumption]').forEach(input => { const key = input.dataset.assumption; const value = Number(input.value); const old = state.project.assumptions[key]; if (!Number.isFinite(value)) throw new Error('Every assumption must contain a finite number.'); if (value !== Number(typeof old === 'object' ? old.value : old)) values[key] = value; });
    if (!Object.keys(values).length) { toast('No assumption values changed.'); return; }
    const reason = $('#assumption-reason').value.trim(); if (!reason) { $('#assumption-reason').focus(); throw new Error('Record the reason for this revision before saving.'); }
    await api(`/api/projects/${encodeURIComponent(state.project.id)}/assumptions`, {method: 'POST', body: {values, reason}}); await refreshProject(); toast('Assumption revision saved. Existing runs keep their original inputs.');
  });
}
async function loadMethods() {
  const data = await api('/api/methods'); state.methods = data.methods || [];
  const list = $('#method-list'); replace(list);
  const select = $('#calculation-method'); const previous = select.value; replace(select, Object.assign(node('option', '', 'Default registered method'), {value: ''}));
  for (const method of state.methods) {
    const registered = method.status === 'registered' || method.status === 'built-in' || method.registered === true;
    const row = button('', () => inspectMethod(method.id), 'method-row');
    row.append(node('strong', '', method.name || method.title || method.id), node('small', '', method.description || method.summary || 'Inspect the method, inputs, and check results.'));
    const meta = node('span', 'method-meta'); meta.append(badge(method.status === 'built-in' ? 'Built-in' : registered ? 'Registered' : humanize(method.status || 'draft'), registered ? '' : 'amber'), node('span', 'mono muted', method.version ? `v${method.version}` : '')); row.append(meta); list.append(row);
    if (registered) { const option = node('option', '', `${method.name || method.id}${method.version ? ' · v' + method.version : ''}`); option.value = method.id; select.append(option); }
  }
  if (!state.methods.length) list.append(node('p', 'muted small', 'No methods are available. Build methods can create a draft through the research agent.'));
  if ($$('option', select).some(item => item.value === previous)) select.value = previous;
  renderMethodInputs();
}
function isCustomMethod(method) { return method && method.status !== 'built-in' && method.kind !== 'builtin' && !['separation-unit-v1', 'separation_unit_tea'].includes(method.id); }
function renderMethodInputs() {
  const method = state.methods.find(item => item.id === $('#calculation-method').value); const custom = isCustomMethod(method);
  const container = $('#method-inputs'); replace(container); $('#calculation-scope-field').hidden = Boolean(custom); $('#calculation-candidate').disabled = Boolean(custom);
  $('#calculation-scope-note').textContent = custom ? 'These explicit arguments are passed to the selected method version. Review their units and evidence basis.' : 'Candidate-specific evidence is used only where applicable. Missing performance remains explicit.';
  if (!custom) return;
  for (const [key, sourceSpec] of Object.entries(method.inputs || method.input_schema?.properties || method.input_schema || {})) {
    const spec = typeof sourceSpec === 'object' && sourceSpec !== null ? sourceSpec : {description: String(sourceSpec)};
    const type = spec.type || (typeof spec.default === 'string' ? 'string' : 'number'); const label = node('label', 'field', spec.title || labelFor(key));
    if (spec.unit || spec.description) label.append(node('small', '', [spec.unit, spec.description].filter(Boolean).join(' · ')));
    let input;
    if (type === 'boolean') { input = node('select'); for (const value of ['true', 'false']) { const option = node('option', '', value); option.value = value; input.append(option); } }
    else if (type === 'object' || type === 'array') { input = node('textarea'); input.rows = 3; input.placeholder = type === 'array' ? '[]' : '{}'; }
    else { input = node('input'); input.type = type === 'number' || type === 'integer' ? 'number' : 'text'; if (input.type === 'number') { input.step = type === 'integer' ? '1' : 'any'; if (spec.minimum !== undefined) input.min = spec.minimum; if (spec.maximum !== undefined) input.max = spec.maximum; } }
    input.dataset.methodInput = key; input.dataset.valueType = type; input.required = true;
    const initial = spec.default ?? state.project?.assumptions?.[key];
    if (initial !== undefined && initial !== null) input.value = typeof initial === 'object' ? JSON.stringify(initial) : String(initial);
    label.append(input); container.append(label);
  }
}
async function inspectMethod(id) {
  showDetail('METHOD PACKAGE', node('div', 'loading-shimmer', 'Loading inspectable method…'));
  try {
    const data = await api('/api/methods/' + encodeURIComponent(id)); const method = data.method || data; const manifest = method.manifest || method; const content = node('div');
    content.append(node('h2', 'detail-title', manifest.name || method.name || method.id || id), node('p', 'detail-subtitle', manifest.description || method.description || 'Reusable scientific calculation package.'));
    const builtin = method.status === 'built-in' || manifest.kind === 'builtin';
    const registered = builtin || method.status === 'registered' || method.registered === true || manifest.status === 'registered';
    const meta = node('div', 'detail-actions'); meta.append(badge(builtin ? 'Built-in method' : registered ? 'Registered method' : humanize(method.status || 'draft'), registered ? '' : 'amber'), badge('Scientific validity requires evidence', 'neutral')); content.append(meta);
    content.append(node('div', 'notice', 'Code checks establish the behavior tested. Registration does not establish that a method predicts physical scale-up or is scientifically valid for every candidate.'));
    const actions = node('div', 'detail-actions');
    const check = button('Run reference checks', () => busy(check, async () => { const result = await api(`/api/methods/${encodeURIComponent(id)}/check`, {method: 'POST', body: {}}); toast(result.passed === false || result.success === false ? 'Checks completed with failures. Inspect the results.' : 'Reference checks completed. Inspect the recorded results.'); await loadMethods(); await inspectMethod(id); }));
    if (!registered) actions.append(check);
    if (!registered) { const register = button('Register checked version', () => busy(register, async () => { await api(`/api/methods/${encodeURIComponent(id)}/register`, {method: 'POST', body: {}}); toast('Method version registered. Scientific validity remains separately assessed.'); await loadMethods(); await inspectMethod(id); }), 'button primary'); actions.append(register); }
    content.append(actions);
    const validity = method.scientific_validity || manifest.scientific_validity || manifest.scientific_status || manifest.validation_status || manifest.validation;
    if (validity) content.append(details('Scientific validity and limitations', raw(validity), true));
    const checks = method.checks || method.check_result || method.latest_check || manifest.checks;
    if (checks) content.append(details('Recorded check results', raw(checks), true));
    const inputSchema = manifest.input_schema || manifest.inputs || method.input_schema;
    if (inputSchema) content.append(details('Input schema', raw(inputSchema)));
    const source = method.source || method.source_code || method.code || method.files?.['method.py'];
    if (source) content.append(details('Method source', raw(source)));
    if (method.tests || method.test_source || method.reference_cases || method.files?.['test_method.py']) content.append(details('Reference tests', raw(method.tests || method.test_source || method.reference_cases || method.files['test_method.py'])));
    content.append(details('Complete method manifest', raw(manifest)));
    showDetail('METHOD PACKAGE', content);
  } catch (error) { showDetail('METHOD PACKAGE', node('div', 'notice error', error.message)); }
}
async function calculate(event) {
  event.preventDefault(); await busy($('#run-calculation'), async () => {
    const payload = {}; const candidate = $('#calculation-candidate').value; const method = $('#calculation-method').value; if (candidate && !$('#calculation-candidate').disabled) payload.candidate_id = candidate; if (method) payload.method_id = method;
    const inputFields = $$('[data-method-input]');
    if (inputFields.length) { payload.inputs = {}; for (const input of inputFields) { const type = input.dataset.valueType; let value = input.value; if (type === 'number' || type === 'integer') { value = Number(value); if (!Number.isFinite(value)) throw new Error('Method arguments must be finite numbers.'); } else if (type === 'boolean') value = value === 'true'; else if (type === 'object' || type === 'array') { try { value = JSON.parse(value); } catch { throw new Error(`${input.dataset.methodInput} must contain valid JSON.`); } } payload.inputs[input.dataset.methodInput] = value; } }
    const result = await api(`/api/projects/${encodeURIComponent(state.project.id)}/calculate`, {method: 'POST', body: payload});
    renderCalculation(result.run || result); await refreshProject(); await loadRuns(); toast('Calculation saved with its input and method versions.');
    $('#calculation-result').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
}
function metric(label, value, unit) { const box = node('div', 'metric-box'); box.append(node('span', 'eyebrow', label), node('div', 'metric-value', value), node('span', 'metric-unit', unit)); return box; }
const predictionRequired = ['collected_target_kg_per_l_cycle', 'cycle_time_hours', 'usable_lifetime_cycles', 'target_production_kg_per_day', 'equipment_cost_usd', 'labor_hours_per_day', 'labor_rate_usd_per_hour'];
const predictionOptional = ['product_purity_fraction', 'target_recovery_fraction', 'feed_target_kg_per_l', 'feed_volume_l_per_l_cycle'];
const predictionLabels = {product_purity_fraction: ['Predicted product purity', 'fraction, 0–1'], target_recovery_fraction: ['Predicted target recovery', 'fraction, 0–1'], feed_target_kg_per_l: ['Target concentration in feed', 'kg target / L feed'], feed_volume_l_per_l_cycle: ['Feed processed per cycle', 'L feed / L bed / cycle']};
async function loadScalePredictions() {
  const projectId = state.project?.id; if (!projectId) return;
  const response = await api(`/api/projects/${encodeURIComponent(projectId)}/scale-predictions`);
  if (state.project?.id !== projectId) return;
  const list = $('#scale-prediction-list'); replace(list);
  for (const prediction of response.predictions || []) {
    const card = button('', () => inspectScalePrediction(prediction.id), 'run-card');
    card.append(badge('Prediction · not measured', 'amber'), node('strong', '', prediction.label), node('small', '', `${prediction.candidate_id || 'Project scenario'} · ${number(prediction.intended_bed_volume_l)} L intended total bed`), node('small', '', date(prediction.created_at))); list.append(card);
  }
  if (!list.childNodes.length) list.append(node('p', 'muted small', 'No scale-up predictions saved. Enter your own performance estimates and revised equipment and labor costs for the intended scale.'));
}
function openScalePrediction() {
  const project = state.project; if (!project) return;
  const content = node('div', 'prediction-panel'); content.append(node('h2', 'detail-title', 'Add scale-up prediction'), node('p', 'literature-scope', 'Enter a researcher-supplied scenario for the larger column. The platform calculates economics from these inputs; it does not simulate protein behavior or column transport. Required performance and scale costs start blank.'));
  const form = node('form', 'prediction-form'); const inputs = {};
  function textField(name, label, required = true, multiline = false) {
    const field = node('label', 'field', label), input = node(multiline ? 'textarea' : 'input'); input.name = name; input.required = required; input.maxLength = multiline ? 5000 : 2000;
    if (multiline) input.rows = 3; else input.type = name === 'source_url' ? 'url' : 'text';
    if (name === 'candidate_id') input.setAttribute('list', 'candidate-options'); field.append(input); form.append(field); inputs[name] = input; return input;
  }
  textField('label', 'Scenario label, e.g. larger-column conservative estimate').maxLength = 200;
  textField('candidate_id', 'Candidate ID (optional)', false);
  const volume = textField('intended_bed_volume_l', 'Intended total operating bed volume (L)'); volume.type = 'number'; volume.step = 'any'; volume.min = '0';
  textField('scale_description', 'Operating context: column scale, support, feed and flow assumptions', true, true);
  textField('basis', 'Basis for the performance predictions and revised scale costs', true, true);
  textField('source_url', 'Supporting source URL (optional)', false);
  const numericInputs = {};
  function numericFields(container, keys, required, prefill = false) {
    const grid = node('div', 'metrics-grid');
    for (const key of keys) {
      const [labelText, unit] = predictionLabels[key] || fieldInfo[key] || [humanize(key), ''];
      const field = node('label', 'field', labelText), input = node('input'); input.type = 'number'; input.name = key; input.step = 'any'; input.min = '0'; input.required = required;
      if (key.includes('fraction') || key === 'discount_rate') input.max = '1';
      if (prefill) input.value = project.assumptions[key]; else input.placeholder = required ? 'Enter your scale-specific estimate' : 'Unknown unless supplied';
      field.append(node('small', '', unit), input); grid.append(field); numericInputs[key] = input;
    }
    container.append(grid);
  }
  form.append(node('h3', '', 'Predicted performance and production')); numericFields(form, predictionRequired.slice(0, 4), true);
  form.append(node('h3', '', 'Equipment and labor at this scale'), node('p', 'muted small', 'Supply revised estimates, or explicitly re-enter the same values with a justification in the basis. Costs are not scaled automatically.')); numericFields(form, predictionRequired.slice(4), true);
  const optional = node('div'); numericFields(optional, predictionOptional, false); form.append(details('Optional purity, recovery and feed predictions', optional));
  const inherited = node('div'); inherited.append(node('p', 'muted small', 'These shared project assumptions are retained in the saved snapshot. Revise any that differ at the intended scale. Candidate overrides and accepted small-column measurements are not imported.'));
  const extraKeys = Object.keys(project.assumptions).filter(key => !predictionRequired.includes(key) && !predictionOptional.includes(key)); numericFields(inherited, extraKeys, true, true); form.append(details('Other economic assumptions retained from this project', inherited));
  const error = node('div', 'form-error'); error.hidden = true; error.setAttribute('role', 'alert'); form.append(error);
  const submit = node('button', 'button primary', 'Save prediction'); submit.type = 'submit'; form.append(submit); content.append(form); showDetail('SCALE-UP PREDICTION', content);
  form.addEventListener('submit', event => {
    event.preventDefault(); formError(form);
    busy(submit, async () => {
      const payload = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()])); payload.intended_bed_volume_l = Number(payload.intended_bed_volume_l); if (!payload.candidate_id) delete payload.candidate_id;
      payload.values = {};
      for (const [key, input] of Object.entries(numericInputs)) if (input.value !== '' && (!extraKeys.includes(key) || Number(input.value) !== Number(project.assumptions[key]))) payload.values[key] = Number(input.value);
      const saved = await api(`/api/projects/${encodeURIComponent(project.id)}/scale-predictions`, {method: 'POST', body: payload});
      if (state.project?.id === project.id) { await loadScalePredictions(); await inspectScalePrediction(saved.id); } toast('Prediction saved separately from experiments and current assumptions.');
    }, message => formError(form, message));
  });
}
async function inspectScalePrediction(id) {
  const projectId = state.project?.id; if (!projectId) return;
  const content = node('div', 'prediction-panel'); content.append(node('p', 'muted', 'Loading saved prediction…')); showDetail('SCALE-UP PREDICTION', content);
  try {
    const prediction = await api(`/api/projects/${encodeURIComponent(projectId)}/scale-predictions/${encodeURIComponent(id)}`); if (!content.isConnected || state.project?.id !== projectId) return;
    replace(content, node('h2', 'detail-title', prediction.label), badge('User-supplied prediction · not measured', 'amber'), node('p', 'literature-scope', prediction.qualification));
    content.append(objectDetails({candidate: prediction.candidate_id || 'Project scenario', intended_total_bed_volume_l: prediction.intended_bed_volume_l, target: prediction.target, operating_context: prediction.scale_description, basis: prediction.basis}));
    if (safeUrl(prediction.source_url)) content.append(link('Supporting source', prediction.source_url));
    content.append(details('Explicit prediction inputs', objectDetails(prediction.supplied_values), true), details('All saved inputs and their basis', raw(prediction.input_details)), node('p', 'muted small', `Saved from project revision ${prediction.project_revision}. Create another prediction to change this snapshot; project edits do not alter it.`));
    const run = button('Calculate prediction', () => busy(run, async () => {
      const result = await api(`/api/projects/${encodeURIComponent(projectId)}/scale-predictions/${encodeURIComponent(id)}/calculate`, {method: 'POST', body: {}});
      if (state.project?.id === projectId) { $('#detail-dialog').close(); goTab('model'); renderCalculation(result); await loadRuns(); $('#calculation-result').scrollIntoView({behavior: 'smooth', block: 'start'}); }
    }), 'button primary'); content.append(run);
  } catch (error) { if (content.isConnected) replace(content, node('p', 'notice error', error.message)); }
}
function renderCalculation(run) {
  const target = $('#calculation-result'); const result = run.result || run; const summary = result.summary || {}; const card = node('div', 'card result-card');
  if (result.kind === 'custom_calculation' || (result.outputs && !result.summary)) {
    const heading = node('div', 'card-heading'); const title = node('div'); title.append(node('span', 'eyebrow', 'SAVED METHOD RUN'), node('h3', '', state.methods.find(item => item.id === result.method_id)?.name || 'Registered method result')); heading.append(title, badge('Conditional on method assumptions', 'amber')); card.append(heading);
    card.append(objectDetails(result.outputs || {}));
    if (result.boundary) card.append(details('Method boundary', raw(result.boundary), true));
    if (result.qualification) card.append(node('p', 'source-note', result.qualification));
    if (run.stale || result.stale) card.append(node('div', 'notice', 'The project has changed since this run. Its saved inputs and outputs are retained as a historical result.'));
    card.append(details('Exact method arguments', raw(result.inputs || {})), details('Assumptions and complete saved record', raw(result)));
    replace(target, card); target.hidden = false; return;
  }
  const heading = node('div', 'card-heading'); const title = node('div'); title.append(node('span', 'eyebrow', 'SAVED CALCULATION'), node('h3', '', result.prediction ? 'Prediction: ' + result.prediction.label : result.candidate_id ? `${result.candidate_id} · economic scenario` : 'Project economic scenario')); heading.append(title, badge(result.prediction ? 'User-supplied prediction' : 'Conditional estimate', 'amber')); card.append(heading);
  if (result.prediction) {
    const check = result.scale_check; card.append(node('p', 'literature-scope', result.prediction.scale_description), node('div', check.status === 'mismatch' ? 'notice error' : 'notice', `Intended total bed: ${number(check.intended_bed_volume_l)} L. Required aggregate bed from predicted output and production: ${number(check.calculated_required_bed_volume_l)} L. ${check.status === 'mismatch' ? 'These differ by more than 5%; reconcile the design and its costs before using this estimate.' : 'Volumes agree within 5%; this checks arithmetic only.'}`), details('Prediction basis and scale check', raw({prediction: result.prediction, scale_check: check})));
  }
  const metrics = node('div', 'result-metrics'); metrics.append(metric('SEPARATION UNIT COST', money(summary.cost_usd_per_kg), `USD / kg ${state.project?.target || 'target'}`), metric('ANNUAL TARGET OUTPUT', number(summary.annual_target_kg), 'kg / year'), metric('REQUIRED BED VOLUME', number(summary.required_bed_volume_l), 'L of prepared material')); card.append(metrics);
  if (run.stale || result.stale) card.append(node('div', 'notice', 'The project has changed since this run. This result keeps its original assumptions; it is not a calculation of the current scenario.'));
  const grid = node('div', 'result-grid'); const costs = node('div'); costs.append(node('h4', '', 'Cost components'));
  const breakdown = result.cost_breakdown || [];
  for (const cost of Array.isArray(breakdown) ? breakdown : Object.entries(breakdown).map(([name, value]) => ({name, ...(typeof value === 'object' ? value : {cost_usd_per_kg: value})}))) { const row = node('div', 'cost-row'); row.append(node('span', '', humanize(cost.name || cost.component)), node('strong', '', numeric(cost.cost_usd_per_kg) ? money(cost.cost_usd_per_kg) + ' / kg' : money(cost.annual_cost_usd) + ' / year')); costs.append(row); }
  if (!asList(breakdown).length) costs.append(node('p', 'muted small', 'No component breakdown was returned by this method.'));
  if (numeric(summary.annual_cost_usd)) costs.append(node('p', 'source-note', `Annual modeled cost: ${money(summary.annual_cost_usd)}.`));
  const limits = node('div'); limits.append(node('h4', '', 'Boundary & uncertainty'));
  if (typeof result.boundary === 'object' && result.boundary) { if (result.boundary.name) limits.append(node('p', 'boundary-text', result.boundary.name)); for (const [key, value] of Object.entries(result.boundary)) { if (key === 'name') continue; limits.append(node('p', 'source-note', humanize(key)), Array.isArray(value) ? textList(value) : node('p', 'boundary-text', displayValue(value))); } }
  else limits.append(node('p', 'boundary-text', displayValue(result.boundary)));
  if (result.uncertainties) limits.append(textList(result.uncertainties)); grid.append(costs, limits); card.append(grid);
  const footer = node('div', 'result-footer'); footer.append(node('span', 'mono', result.id || run.id || ''), node('span', '', `Method ${result.method_id || 'default'}${result.method_version ? ' · v' + result.method_version : ''}`), node('span', '', date(result.created_at))); card.append(footer);
  card.append(details('Inspect exact inputs and evidence basis', raw(result.input_details || result.assumptions || {})), details('Complete saved result', raw(result)));
  replace(target, card); target.hidden = false;
}
async function rank(pool, control) {
  await busy(control, async () => {
    const data = await api(`/api/projects/${encodeURIComponent(state.project.id)}/rank`, {method: 'POST', body: {pool, limit: 10}}); renderRanking(data.run || data); await loadRuns(); $('#ranking-result').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
}
function renderRanking(result) {
  const target = $('#ranking-result'); const card = node('div', 'card result-card'); const heading = node('div', 'card-heading'); const title = node('div');
  title.append(node('span', 'eyebrow', 'SAVED COMPARISON'), node('h3', '', result.pool === 'updated' ? 'Candidates with accepted results' : 'Untested candidate comparison')); heading.append(title, badge(`${result.pool_count ?? result.total_evaluated ?? result.rows?.length ?? 0} in pool`, 'neutral')); card.append(heading);
  if (result.is_hypothetical) {
    heading.append(badge('Hypothetical scenario', 'amber'));
    const scenario = result.scenario || {}; const basis = node('div');
    basis.append(node('p', '', 'This comparison uses the scenario below. Committed project assumptions and conditions are unchanged.'));
    if (scenario.reason) basis.append(node('p', '', scenario.reason));
    if (Object.keys(scenario.assumption_overrides || {}).length) basis.append(node('h4', '', 'Scenario assumptions'), objectDetails(scenario.assumption_overrides));
    if (Object.keys(scenario.configuration_overrides || {}).length) basis.append(node('h4', '', 'Scenario conditions'), objectDetails(scenario.configuration_overrides));
    if (scenario.exclude_candidate_ids?.length) basis.append(node('p', '', 'Excluded from this comparison: ' + scenario.exclude_candidate_ids.join(', ')));
    card.append(details('Hypothetical comparison basis', basis, true));
  }
  if (result.stale) card.append(node('div', 'notice', 'Project inputs have changed since this comparison. This is its retained historical ranking.'));
  card.append(node('p', 'ranking-intro', typeof result.rationale === 'string' ? result.rationale : displayValue(result.rationale)));
  const rows = result.rows || [];
  if (rows.length) {
    const table = node('table', 'ranking-table'); const head = node('thead'); const hr = node('tr'); ['#', 'Candidate', 'Profile contrast', 'Modeled cost', 'Qualification'].forEach(label => hr.append(node('th', '', label))); head.append(hr); const body = node('tbody');
    rows.forEach((candidate, index) => { const row = node('tr'); row.append(node('td', 'rank-number', index + 1)); const name = node('td'); name.append(button(candidate.name || candidate.candidate_id, () => inspectCandidate(candidate.candidate_id), 'text-button')); row.append(name, node('td', '', number(candidate.profile_contrast)), node('td', '', numeric(candidate.cost_usd_per_kg) ? money(candidate.cost_usd_per_kg) + ' / kg' : 'Not estimated'), node('td', 'ranking-qualification', typeof candidate.qualification === 'string' ? candidate.qualification : asList(candidate.reasons).join('; ') || (candidate.eligible === false ? 'Outside criteria' : 'See comparison basis'))); body.append(row); });
    table.append(head, body); const scroll = node('div', 'table-scroll'); scroll.append(table); card.append(scroll);
  } else card.append(node('div', 'empty-state', 'No candidates qualify under these inputs and evidence requirements.'));
  if (result.uncertainties) card.append(textList(result.uncertainties));
  card.append(details(`Exclusions (${result.excluded_count ?? result.exclusions?.length ?? 0})`, raw(result.exclusions || [])), details('Comparison assumptions and complete record', raw(result)));
  replace(target, card); target.hidden = false;
}
async function loadRuns() {
  if (!state.project) return; const data = await api(`/api/projects/${encodeURIComponent(state.project.id)}/runs`); state.runs = data.runs || [];
  const latestCalculation = state.runs.find(run => (run.result || run).kind !== 'rank'); renderLatest(latestCalculation ? latestCalculation.result || latestCalculation : null);
  const list = $('#run-list'); replace(list);
  for (const run of state.runs.slice(0, 15)) {
    const result = run.result || run; const item = button('', () => { if (result.kind === 'rank') { goTab('library'); renderRanking(result); $('#ranking-result').scrollIntoView({behavior: 'smooth'}); } else { renderCalculation(result); $('#calculation-result').scrollIntoView({behavior: 'smooth'}); } }, 'run-card');
    if (result.is_hypothetical) item.append(badge('Hypothetical scenario', 'amber'));
    item.append(node('span', 'eyebrow', result.kind === 'rank' ? 'CANDIDATE COMPARISON' : result.kind === 'custom_calculation' ? 'REGISTERED METHOD RUN' : result.prediction ? 'SCALE-UP PREDICTION' : 'ECONOMIC CALCULATION'), node('strong', '', numeric(result.summary?.cost_usd_per_kg) ? money(result.summary.cost_usd_per_kg) + ' / kg' : result.kind === 'rank' ? humanize(result.pool || 'Candidate pool') : result.candidate_id || result.method_id || 'Project scenario'), node('small', '', date(run.created_at || result.created_at)), node('small', 'mono', run.id || result.id || '')); if (result.prediction) item.append(node('small', '', result.prediction.label), badge('Prediction · not measured', 'amber')); if (run.stale || result.stale) item.append(badge('Project changed since run', 'amber')); list.append(item);
  }
  if (!state.runs.length) list.append(node('p', 'muted small', 'Calculations and comparisons will appear here when saved.'));
}
async function loadTestingBatches() {
  const projectId = state.project?.id; if (!projectId) return;
  const data = await api(`/api/projects/${encodeURIComponent(projectId)}/testing-batches`);
  if (state.project?.id !== projectId) return;
  state.testingBatches = data.batches || []; const list = $('#testing-batch-list'); replace(list);
  for (const batch of state.testingBatches) {
    const item = node('article', 'card testing-batch-card');
    item.append(node('span', 'eyebrow', 'SERIAL DILUTION'), node('h3', '', `${batch.count} candidate${batch.count === 1 ? '' : 's'} · A1${batch.count > 1 ? '–' + String.fromCharCode(64 + batch.count) + '1' : ''}`), node('p', 'small muted', date(batch.created_at)), badge(batch.schema_version === 'lanm_testing_batch_1' ? 'Legacy · simulated concentrations' : 'Simulated stock volumes', 'amber'));
    if (batch.is_hypothetical) item.append(badge('Hypothetical selection', 'neutral'));
    if (batch.stale || batch.revision !== state.project.revision) item.append(node('p', 'small muted', 'Project has changed; this saved batch retains its original selection.'));
    const actions = node('div', 'detail-actions'); actions.append(button('Preview', () => inspectTestingBatch(batch)));
    const download = link('Download CSV', batch.download_url); download.className = 'button'; actions.append(download); item.append(actions); list.append(item);
  }
  if (!state.testingBatches.length) list.append(node('p', 'muted small', 'Ask the agent to export your selected candidates, or create a testing CSV here.'));
}
function inspectTestingBatch(batch) {
  const content = node('div', 'testing-batch-detail');
  const legacy = batch.schema_version === 'lanm_testing_batch_1';
  content.append(node('h2', 'detail-title', 'Testing batch'), node('p', 'detail-subtitle', `${batch.count} candidates · ${date(batch.created_at)}`), node('p', 'literature-scope', legacy ? 'Legacy concentration batch: these simulated starting-well concentrations retain their original values and units. Each download contains the same saved values.' : 'These simulated values specify the volume of stock solution dispensed into each starting well before serial dilution. Each download contains the same saved values.'));
  if (!legacy) content.append(node('p', 'literature-scope', 'Add one fixed volume of water to every starting well. The receiving automation sets that water amount and checks stock plus water against the chosen plate’s working-volume limit.'));
  const download = link('Download CSV', batch.download_url); download.className = 'button primary'; content.append(download);
  const table = node('table', 'message-table'); const head = node('thead'); const heading = node('tr');
  for (const title of ['Well', 'Candidate', legacy ? 'Starting concentration (legacy)' : 'Stock-solution volume']) heading.append(node('th', '', title)); head.append(heading); table.append(head);
  const body = node('tbody');
  for (const row of batch.rows || []) {
    const tr = node('tr'); const candidate = node('td'); candidate.append(node('span', 'candidate-name', row.candidate_name || row.candidate_id), node('span', 'candidate-sub mono', row.candidate_id));
    const value = legacy ? `${row.starting_concentration} ${row.concentration_unit}` : `${row.stock_volume} ${row.volume_unit === 'uL' ? 'µL' : row.volume_unit}`;
    tr.append(node('td', 'mono', row.well), candidate, node('td', '', value)); body.append(tr);
  }
  table.append(body); const scroll = node('div', 'table-scroll'); scroll.append(table); content.append(scroll);
  const basis = node('div');
  basis.append(node('p', '', batch.selection_reason || batch.selection_snapshot?.reason || 'Top candidates from the saved ranking, in ranking order.'));
  if (batch.is_hypothetical) basis.append(node('p', '', 'Selection uses a hypothetical scenario. Committed project assumptions were not changed.'));
  const scenario = batch.scenario || {};
  if (scenario.reason) basis.append(node('p', '', scenario.reason));
  if (Object.keys(scenario.assumption_overrides || {}).length) basis.append(node('h4', '', 'Scenario assumptions'), objectDetails(scenario.assumption_overrides));
  if (Object.keys(scenario.configuration_overrides || {}).length) basis.append(node('h4', '', 'Scenario conditions'), objectDetails(scenario.configuration_overrides));
  if (scenario.exclude_candidate_ids?.length) basis.append(node('p', '', 'Excluded from this comparison: ' + scenario.exclude_candidate_ids.join(', ')));
  if (batch.generation) basis.append(node('p', '', `Simulated range: ${batch.generation.minimum}–${batch.generation.maximum} ${batch.generation.unit}.`));
  if (batch.revision !== state.project.revision) basis.append(node('p', '', 'The project has changed since this selection. This batch preserves the decision at the time it was saved.'));
  basis.append(objectDetails({project_revision: batch.revision, ranking: batch.ranking_run_id, batch: batch.id}));
  content.append(details('Saved selection and assumptions', basis, true)); showDetail('TESTING HANDOFF', content);
}
async function openTestingBatchForm() {
  const projectId = state.project?.id; if (!projectId) return;
  const content = node('div'); content.append(node('h2', 'detail-title', 'Create testing CSV'), node('p', 'literature-scope', 'Choose 1–8 candidates for wells A1–H1. Stock-solution volumes are simulated from 35–250 µL for the MVP. You can narrow this range. Add the same fixed water volume to every starting well; the receiving automation sets that amount and checks the total against the chosen plate’s working-volume limit.'));
  const form = node('form'); const sourceLabel = node('label', 'field', 'Candidate selection'); const source = node('select'); source.required = true; source.disabled = true;
  const placeholder = node('option', '', 'Loading saved selections…'); placeholder.value = ''; source.append(placeholder); sourceLabel.append(source); form.append(sourceLabel);
  const sourceNote = node('p', 'small muted'); form.append(sourceNote);
  const makeNumber = (labelText, whole = false) => { const label = node('label', 'field', labelText); const input = node('input'); input.type = 'number'; input.required = true; input.step = whole ? '1' : 'any'; input.min = whole ? '1' : '0'; if (whole) input.max = '8'; label.append(input); return {label, input}; };
  const count = makeNumber('Number of candidates (1–8)', true); form.append(count.label);
  const pair = node('div', 'field-pair'); const minimum = makeNumber('Minimum stock volume (µL)'); const maximum = makeNumber('Maximum stock volume (µL)'); minimum.input.value = '35'; maximum.input.value = '250';
  for (const input of [minimum.input, maximum.input]) { input.min = '35'; input.max = '250'; } pair.append(minimum.label, maximum.label); form.append(pair);
  const error = node('div', 'form-error'); error.hidden = true; error.setAttribute('role', 'alert'); form.append(error);
  const actions = node('div', 'detail-actions'); const submit = node('button', 'button primary', 'Create saved CSV'); submit.type = 'submit'; actions.append(submit); form.append(actions); content.append(form); showDetail('TESTING HANDOFF', content);
  const snapshots = new Map();
  source.addEventListener('change', () => {
    const saved = snapshots.get(source.value);
    sourceNote.textContent = saved ? (saved.reason || saved.scenario?.reason || 'Saved comparison') + (saved.candidate_ids ? ' · ' + saved.candidate_ids.join(', ') : '') : source.value === 'current:updated' ? 'Uses the current economic comparison of candidates with sufficient applicable accepted results.' : source.value ? 'Uses the current published screening comparison for untested candidates.' : '';
  });
  form.addEventListener('submit', event => {
    event.preventDefault(); formError(form);
    busy(submit, async () => {
      const payload = {count: Number(count.input.value), stock_volume_min_ul: Number(minimum.input.value), stock_volume_max_ul: Number(maximum.input.value)};
      if (!Number.isInteger(payload.count) || payload.count < 1 || payload.count > 8) throw new Error('Choose a whole number of candidates from 1 to 8.');
      if (!Number.isFinite(payload.stock_volume_min_ul) || !Number.isFinite(payload.stock_volume_max_ul) || payload.stock_volume_min_ul < 35 || payload.stock_volume_max_ul > 250 || payload.stock_volume_max_ul < payload.stock_volume_min_ul) throw new Error('Enter stock volumes from 35 to 250 µL, with maximum at least minimum.');
      const [kind, id] = source.value.split(':');
      if (kind === 'current') payload.pool = id; else if (kind === 'run') payload.ranking_run_id = id; else if (kind === 'selection') payload.selection_id = id; else throw new Error('Choose a candidate selection.');
      const batch = await api(`/api/projects/${encodeURIComponent(projectId)}/testing-batches`, {method: 'POST', body: payload});
      if (state.project?.id !== projectId) return;
      inspectTestingBatch(batch); await loadTestingBatches(); toast('Testing batch saved. Its CSV is ready to download.');
    }, message => formError(form, message));
  });
  try {
    const [rankings, selections] = await Promise.all([api(`/api/projects/${encodeURIComponent(projectId)}/runs`), api(`/api/projects/${encodeURIComponent(projectId)}/testing-selections`)]);
    if (!content.isConnected || state.project?.id !== projectId) return;
    replace(source); const blank = node('option', '', 'Choose a candidate selection'); blank.value = ''; source.append(blank);
    for (const [value, title] of [['current:untested', 'Current untested ranking'], ['current:updated', 'Current accepted-results ranking']]) { const option = node('option', '', title); option.value = value; source.append(option); }
    for (const saved of selections.selections || []) {
      const value = 'selection:' + saved.id; snapshots.set(value, saved); const option = node('option', '', `Saved selection · ${date(saved.created_at)} · ${(saved.candidate_ids || []).length} candidates${saved.is_hypothetical ? ' · hypothetical' : ''}`); option.value = value;
      if (saved.stale || saved.revision !== state.project.revision) { option.disabled = true; option.textContent += ' · project changed'; } source.append(option);
    }
    for (const saved of (rankings.runs || []).filter(run => run.kind === 'rank')) {
      const value = 'run:' + saved.id; snapshots.set(value, saved); const option = node('option', '', `Saved ${humanize(saved.pool).toLowerCase()} comparison · ${date(saved.created_at)}${saved.is_hypothetical ? ' · hypothetical' : ''}`); option.value = value;
      if (saved.stale || saved.revision !== state.project.revision) { option.disabled = true; option.textContent += ' · project changed'; } source.append(option);
    }
    source.disabled = false;
  } catch (error) { if (content.isConnected) formError(form, error.message); }
}
function sourceLiteratureProvenance(source) {
  return source.origin === 'reviewed_shared_evidence' ? source.provenance?.record_snapshot?.provenance || {} : source.provenance || {};
}
function sourceLabel(source) {
  if (source.origin === 'reviewed_shared_evidence') return 'Shared evidence';
  if (source.evidence_kind === 'retrieved_literature_abstract') return 'PubMed citation / abstract';
  return source.origin === 'user_upload' || source.text ? 'Project evidence' : 'Published source';
}
async function loadSources() {
  const projectId = state.project?.id; if (!projectId) return; const data = await api(`/api/projects/${encodeURIComponent(projectId)}/sources`);
  if (state.project?.id !== projectId) return; state.sources = data.sources || [];
  const list = $('#sources-list'); replace(list);
  for (const source of state.sources) {
    const literature = source.evidence_kind === 'retrieved_literature_abstract';
    const provenance = sourceLiteratureProvenance(source);
    const shared = source.origin === 'reviewed_shared_evidence';
    const item = button('', () => inspectSource(source), 'source-card'); const type = node('div', 'source-type'); type.append(badge(sourceLabel(source), 'neutral'), node('span', 'muted', '↗')); item.append(type, node('h3', '', source.title || source.id), node('p', '', (source.text || source.excerpt || source.description || 'Open the source record to inspect its reference and provenance.').slice(0, 230)));
    if (literature) {
      item.append(node('p', 'source-scope', provenance.content_scope || 'Citation and abstract only. Full article not retrieved.'));
      if (provenance.is_retracted) item.append(badge('Retraction indexed', 'red'));
      else if (provenance.notices?.length) item.append(badge('Related indexing notices', 'amber'));
    }
    if (shared) {
      item.append(node('p', 'source-scope', source.review_reason ? `Sharing reason: ${source.review_reason}` : 'Available to all projects in this workspace.'));
      if (source.evidence_kind === 'accepted_experiment_snapshot') item.append(node('p', 'source-scope', 'Experimental snapshot accepted in its originating project. Sharing does not accept it in this project.'));
      if (source.supersedes_source_id) item.append(badge('Updated shared evidence', 'neutral'));
      if (source.superseded_by_source_ids?.length) item.append(badge('Newer shared evidence available', 'amber'));
    }
    const footer = node('div', 'source-footer'); footer.append(node('span', '', date(source.shared_at || source.created_at || source.uploaded_at)), node('span', 'mono', (source.sha256 || source.content_hash || '').slice(0, 12))); item.append(footer); list.append(item);
  }
  if (!state.sources.length) { const empty = node('div', 'card empty-state'); empty.append(node('h3', '', 'Start with the evidence.'), node('p', '', 'Archive a paper excerpt, laboratory note, or dataset description for this project.')); list.append(empty); }
}
function inspectSource(source) {
  previewEvidence({source_id: source.id});
}
function pubmedScope() {
  const note = node('p', 'literature-scope', 'Searches retrieve and save citations and available abstracts to this project. Full articles are not retrieved. PubMed does not cover all REE engineering literature. ');
  note.append(link('NLM disclaimer', 'https://pubmed.ncbi.nlm.nih.gov/disclaimer/', false)); return note;
}
function renderLiteratureResults(target, result) {
  const articles = result.articles || result.records || [];
  replace(target, node('h3', '', result.query || 'Saved literature search'), node('p', 'muted small', `${number(result.total, 0)} PubMed matches · ${articles.length} saved records${result.created_at ? ' · ' + date(result.created_at) : ''}`));
  if (result.warnings?.length) target.append(textList(result.warnings));
  if (result.missing_pmids?.length) target.append(node('p', 'notice', 'PubMed did not return these requested records: ' + result.missing_pmids.join(', ')));
  if (!articles.length) target.append(node('p', 'muted', 'No records were saved for this search. Try a broader query.'));
  for (const article of articles) {
    const row = node('article', 'literature-result');
    row.append(node('h4', '', article.title || `PMID ${article.pmid}`), node('p', 'muted small', [article.journal, article.year, article.pmid ? 'PMID ' + article.pmid : ''].filter(Boolean).join(' · ')));
    const actions = node('div', 'detail-actions'); actions.append(badge(article.has_abstract === false ? 'Citation only · no abstract supplied' : 'Citation / abstract only', 'neutral'));
    if (article.source_id) actions.append(button('Preview saved record', () => previewEvidence({source_id: article.source_id}), 'button small-button'));
    if (safeUrl(article.url)) actions.append(link('PubMed ↗', article.url, false)); row.append(actions);
    if (article.is_retracted) row.append(node('p', 'notice error', 'PubMed indexes a retraction for this record. Inspect the related notices before using its findings.'));
    if (article.notices?.length) row.append(textList(article.notices.map(item => `${humanize(item.type)}${item.pmid ? ' · PMID ' + item.pmid : ''}${item.note ? ': ' + item.note : ''}`)));
    target.append(row);
  }
}
function openPubmedSearch() {
  const projectId = state.project?.id; if (!projectId) return;
  const content = node('div', 'literature-panel'); content.append(node('h2', 'detail-title', 'Search PubMed'), pubmedScope());
  const form = node('form', 'literature-search-form');
  const queryLabel = node('label', 'field', 'Search query'); const query = node('input'); query.type = 'search'; query.required = true; query.maxLength = 2000; query.value = 'lanmodulin'; query.placeholder = 'e.g. lanmodulin immobilization'; queryLabel.append(query); form.append(queryLabel);
  const options = node('div', 'field-pair'); const limitLabel = node('label', 'field', 'Records to retrieve'); const limit = node('select');
  for (const value of [5, 10, 20]) { const option = node('option', '', String(value)); option.value = String(value); limit.append(option); } limitLabel.append(limit);
  const sortLabel = node('label', 'field', 'Order'); const sort = node('select');
  for (const [value, label] of [['relevance', 'Relevance'], ['date', 'Publication date']]) { const option = node('option', '', label); option.value = value; sort.append(option); } sortLabel.append(sort); options.append(limitLabel, sortLabel); form.append(options);
  const submit = node('button', 'button primary', 'Search and save abstracts'); submit.type = 'submit'; form.append(submit);
  const error = node('div', 'form-error'); error.hidden = true; error.setAttribute('role', 'alert'); form.append(error); content.append(form);
  const results = node('section', 'detail-section literature-results'); results.hidden = true; results.setAttribute('aria-live', 'polite'); content.append(results);
  const historyList = node('div', 'literature-history'); const history = details('Saved PubMed searches', historyList, true); content.append(history);
  async function loadHistory() {
    replace(historyList, node('p', 'muted small', 'Loading saved searches…'));
    try {
      const response = await api(`/api/projects/${encodeURIComponent(projectId)}/literature-searches`);
      if (!content.isConnected || state.project?.id !== projectId) return;
      const searches = Array.isArray(response) ? response : response.searches || []; replace(historyList);
      for (const search of searches) {
        const row = button('', () => { query.value = search.query || ''; renderLiteratureResults(results, search); results.hidden = false; results.scrollIntoView({behavior: 'smooth', block: 'start'}); }, 'method-row');
        row.append(node('strong', '', search.query), node('small', '', `${date(search.created_at)} · ${(search.records || []).length} saved records`)); historyList.append(row);
      }
      if (!searches.length) historyList.append(node('p', 'muted small', 'No PubMed searches saved in this project yet.'));
    } catch (error) { if (content.isConnected) replace(historyList, node('p', 'muted small', 'Search history could not be loaded: ' + error.message)); }
  }
  form.addEventListener('submit', event => {
    event.preventDefault(); formError(form);
    busy(submit, async () => {
      results.hidden = false; replace(results, node('p', 'muted', 'Searching PubMed and saving available abstracts…'));
      const result = await api(`/api/projects/${encodeURIComponent(projectId)}/pubmed/search`, {method: 'POST', body: {query: query.value.trim(), limit: Number(limit.value), sort: sort.value}});
      if (content.isConnected && state.project?.id === projectId) { renderLiteratureResults(results, result); await loadHistory(); }
      if (state.project?.id === projectId) await loadSources().catch(error => toast('Records saved. Evidence list could not refresh: ' + error.message, true));
    }, message => { formError(form, message); replace(results); results.hidden = true; });
  });
  showDetail('LITERATURE SEARCH', content); loadHistory(); query.focus();
}
async function openHandbook(sectionId = null) {
  const content = node('div', 'handbook-panel'); content.append(node('p', 'muted', 'Loading LanM handbook…')); showDetail('LANM HANDBOOK', content);
  try {
    const result = await api(sectionId ? `/api/guidance/${encodeURIComponent(sectionId)}` : '/api/guidance');
    if (!content.isConnected) return;
    if (!sectionId) {
      replace(content, node('h2', 'detail-title', 'LanM handbook'), node('p', 'literature-scope', 'Guidance on candidate evidence, experiments, and conditional economics. Authored synthesis; not independently scientifically validated.'));
      for (const section of result.sections || []) {
        const item = button('', () => openHandbook(section.id), 'method-row'); item.append(node('strong', '', section.title), node('small', '', section.summary)); content.append(item);
      }
    } else {
      replace(content, button('← All handbook sections', () => openHandbook(), 'text-button'), node('h2', 'detail-title', result.title), node('p', 'literature-scope', `${result.review_status} Version ${result.version}.`));
      const body = node('div', 'message-body handbook-body'); renderRichText(body, result.text); content.append(body);
      const sources = node('div', 'handbook-sources');
      for (const url of result.sources || []) sources.append(link(url, url));
      if (sources.childNodes.length) content.append(details('Primary sources', sources));
    }
  } catch (error) { if (content.isConnected) replace(content, node('h2', 'detail-title', 'Handbook unavailable'), node('p', 'notice error', error.message), button('Try again', () => openHandbook(sectionId))); }
}
async function previewEvidence(reference) {
  const projectId = state.project?.id; if (!projectId) return;
  const content = node('div', 'evidence-preview'); content.append(node('p', 'muted', 'Loading source preview…'));
  showDetail('SOURCE EVIDENCE', content);
  try {
    const result = await api(`/api/projects/${encodeURIComponent(projectId)}/evidence-preview?${new URLSearchParams(reference)}`);
    if (!content.isConnected) return;
    replace(content, node('h2', 'detail-title', result.title || 'Source evidence'));
    if (result.source_id) content.append(node('p', 'detail-subtitle', result.source_id));
    const source = result.source && {...result.source, id: result.source_id || result.source.id};
    const shared = source?.origin === 'reviewed_shared_evidence';
    const actions = node('div', 'detail-actions preview-actions');
    let fileUrl = null;
    if (result.file_url && result.source_id) {
      const candidate = new URL(result.file_url, location.href);
      const expectedPath = `/api/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(result.source_id)}/file`;
      if (candidate.origin === location.origin && candidate.pathname === expectedPath && !candidate.search && !candidate.hash) fileUrl = candidate.href;
    }
    const canEmbed = fileUrl && ['pdf', 'image'].includes(result.preview_kind);
    if (canEmbed || safeUrl(result.url)) {
      const original = link(canEmbed ? 'Open original ↗' : 'Open source website ↗', canEmbed ? fileUrl : result.url, false);
      original.className = 'button'; actions.append(original);
    }
    if (fileUrl && result.original_available) {
      const download = link(shared ? 'Download snapshot' : 'Download file', fileUrl + '?download=1', false); download.className = 'button'; download.removeAttribute('target'); download.download = result.file_name || ''; actions.append(download);
    }
    if (result.hash_verified) actions.append(badge(shared ? 'Shared snapshot · hash verified' : result.original_available ? 'Original file · hash verified' : 'Archived text · hash verified'));
    if (actions.childNodes.length) content.append(actions);
    if (shared) {
      const provenance = source.provenance || {};
      content.append(node('p', 'notice', source.verification || 'Shared evidence is available across projects in this workspace. Sharing does not independently validate its claims or accept an experiment in this project.'));
      const context = {scope: 'Shared across projects in this workspace', source_project: provenance.source_project_id, source_record: `${humanize(provenance.source_record_type)} · ${provenance.source_record_id || 'Not specified'}`, sharing_reason: source.review_reason, shared: date(source.shared_at)};
      if (source.candidate_id) context.candidate = source.candidate_id;
      content.append(details('Sharing record', objectDetails(context), true));
      if (source.supersedes_source_id) content.append(button('Previous shared version', () => previewEvidence({source_id: source.supersedes_source_id}), 'button small-button'));
      if (source.superseded_by_source_ids?.length) {
        content.append(node('p', 'notice', 'Newer shared evidence is available. This view preserves the historical snapshot.'));
        const successors = node('div', 'detail-actions');
        source.superseded_by_source_ids.forEach((id, index) => successors.append(button(source.superseded_by_source_ids.length === 1 ? 'Open newer shared evidence' : `Open newer shared evidence ${index + 1}`, () => previewEvidence({source_id: id}), 'button small-button')));
        content.append(successors);
      }
      if (source.evidence_kind === 'accepted_experiment_snapshot') content.append(node('p', 'source-note', 'This snapshot was accepted in its originating project. Its conditions and measurements remain evidence to review here; this project’s accepted experiments and rankings are unchanged.'));
    }
    if (source?.evidence_kind === 'retrieved_literature_abstract') {
      const provenance = sourceLiteratureProvenance(source);
      content.append(node('p', 'notice', provenance.content_scope || 'PubMed citation and abstract. The full article has not been retrieved.'));
      if (provenance.is_retracted) content.append(node('p', 'notice error', 'A retraction is indexed for this record. Inspect its notices before using the findings.'));
      content.append(link('NLM disclaimer', 'https://pubmed.ncbi.nlm.nih.gov/disclaimer/', false));
    }
    if (canEmbed) {
      const controls = node('div', 'preview-tabs'); controls.setAttribute('aria-label', 'Source view');
      const originalView = node('div', 'preview-original');
      const frame = node(result.preview_kind === 'pdf' ? 'iframe' : 'img', 'source-document');
      if (result.preview_kind === 'pdf') { frame.title = `${result.title || 'Source'} — original PDF`; frame.src = fileUrl + '#view=FitH'; }
      else { frame.alt = result.title || result.file_name || 'Archived source image'; frame.src = fileUrl; }
      originalView.append(frame);
      const originalButton = button('Original', () => selectView(false), 'button active'); originalButton.setAttribute('aria-pressed', 'true'); controls.append(originalButton);
      let textView = null; let textButton = null;
      if (source && result.text_available) {
        textButton = button('Source text', () => selectView(true)); textButton.setAttribute('aria-pressed', 'false'); controls.append(textButton);
        if (result.preview_kind === 'pdf') originalView.append(node('p', 'source-note', 'If your browser cannot display the PDF, select Source text to read the archived extraction.'));
      }
      function selectView(useText) {
        if (useText && !textView) { textView = sourceReader(source, projectId, true); content.insertBefore(textView, originalView.nextSibling); }
        originalView.hidden = useText; if (textView) textView.hidden = !useText;
        originalButton.classList.toggle('active', !useText); originalButton.setAttribute('aria-pressed', String(!useText));
        if (textButton) { textButton.classList.toggle('active', useText); textButton.setAttribute('aria-pressed', String(useText)); }
      }
      if (textButton) content.append(controls);
      content.append(originalView);
    } else if (result.preview_kind === 'text' && source) {
      content.append(sourceReader(source, projectId, true));
    } else {
      content.append(node('div', 'notice preview-unavailable', result.reason || 'A preview is not available for this source. Use the source website to view the original.'));
    }
    if (source) content.append(details('Source provenance', raw(source)));
  } catch (error) {
    if (!content.isConnected) return;
    replace(content, node('h2', 'detail-title', 'Source preview unavailable'), node('div', 'notice error', error.message));
    const actions = node('div', 'detail-actions'); actions.append(button('Try again', () => previewEvidence(reference)));
    if (safeUrl(reference.url)) { const original = link('Open source website ↗', reference.url, false); original.className = 'button'; actions.append(original); }
    content.append(actions);
  }
}
function sourceReader(source, projectId = state.project.id, autoRead = false) {
  let nextOffset = null; let reading = false;
  const literature = source.evidence_kind === 'retrieved_literature_abstract';
  const experiment = source.evidence_kind === 'accepted_experiment_snapshot';
  const section = node('section', 'detail-section source-reader'); section.append(node('h3', '', literature ? 'Archived citation and abstract' : experiment ? 'Shared experimental snapshot' : 'Archived source text'), node('p', '', literature ? 'Read the citation and available abstract returned by PubMed. Full text has not been retrieved. Saved literature does not automatically become an accepted experimental result.' : 'Read the retained text or search for a phrase. File verification checks its integrity against the saved hash; it does not validate the scientific claims.'));
  const form = node('form'); const label = node('label', 'field', 'Find a phrase in the source (optional)'); const query = node('input'); query.type = 'search'; query.maxLength = 2000; query.placeholder = 'e.g. immobilization or regeneration'; label.append(query); form.append(label);
  const controls = node('div', 'detail-actions'); const read = node('button', 'button', 'Read archived text'); read.type = 'submit';
  const more = button('More', () => readText(nextOffset, true)); more.hidden = true; controls.append(read, more); form.append(controls);
  const status = node('div', 'source-read-status'); status.setAttribute('role', 'status'); const excerpt = node('pre', 'raw-data source-excerpt'); excerpt.hidden = true;
  form.addEventListener('submit', event => { event.preventDefault(); readText(0, false); }); section.append(form, status, excerpt);
  async function readText(offset, continuing) {
    if (reading || offset === null) return; reading = true; read.disabled = true; more.disabled = true;
    replace(status, node('p', 'muted small', 'Reading archived text…'));
    try {
      const params = new URLSearchParams({offset: String(offset), limit: '12000'}); if (!continuing && query.value.trim()) params.set('query', query.value.trim());
      const result = await api(`/api/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(source.id)}/text?${params}`);
      nextOffset = result.next_offset ?? null; more.hidden = nextOffset === null;
      if (result.status !== 'available') { excerpt.hidden = true; replace(status, node('div', 'notice', result.reason || 'Archived text is unavailable for this source. Inspect its provenance or linked original.')); return; }
      replace(status, badge(result.hash_verified ? 'Archived text · hash verified' : 'Text returned · hash not verified', result.hash_verified ? '' : 'amber'));
      if (result.query_found === false) status.append(node('p', 'small muted', 'The phrase was not found. Showing the text from the requested position.'));
      else if (result.query_found === true) status.append(node('p', 'small muted', 'Phrase found. The excerpt includes surrounding text.'));
      const length = (result.excerpt || '').length; status.append(node('p', 'small muted', length ? `Characters ${number(result.offset + 1, 0)}–${number(result.offset + length, 0)} of ${number(result.total_chars, 0)}.` : 'No further text at this position.'));
      excerpt.textContent = result.excerpt || ''; excerpt.hidden = false; excerpt.scrollTop = 0;
    } catch (error) { nextOffset = null; more.hidden = true; excerpt.hidden = true; replace(status, node('div', 'notice error', error.message)); }
    finally { reading = false; read.disabled = false; more.disabled = false; }
  }
  if (autoRead) readText(0, false);
  return section;
}

function bindEvents() {
  $$('[data-close-dialog]').forEach(item => item.addEventListener('click', () => item.closest('dialog').close()));
  $$('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
  $$('[data-tab]').forEach(item => item.addEventListener('click', () => goTab(item.dataset.tab)));
  $$('[data-go-tab]').forEach(item => item.addEventListener('click', () => goTab(item.dataset.goTab)));
  $$('[data-mode]').forEach(item => item.addEventListener('click', () => setMode(item.dataset.mode)));
  $$('[data-prompt]').forEach(item => item.addEventListener('click', () => { $('#chat-input').value = item.dataset.prompt; $('#chat-input').focus(); }));
  $('#new-project').addEventListener('click', () => { if (state.job) return toast('Finish or stop the active conversation before creating another project.'); $('#project-form').reset(); $('#new-target').value = 'Nd'; $('#new-competitor').value = 'La'; showDialog('#project-dialog'); });
  $('#welcome-create').addEventListener('click', () => $('#new-project').click());
  $('#project-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; formError(form);
    busy($('[type=submit]', form), async () => { const data = Object.fromEntries(new FormData(form)); if (data.target === data.competitor) throw new Error('Target and comparison elements must differ.'); const result = await api('/api/projects', {method: 'POST', body: data}); const project = result.project || result; $('#project-dialog').close(); await loadProjects(); await selectProject(project.id); toast('Project created. Its evidence and methods will be saved together.'); }, message => formError(form, message));
  });
  $('#project-settings').addEventListener('click', () => { const form = $('#settings-form'); form.elements.support.value = state.project.configuration?.support || ''; form.elements.feed.value = state.project.configuration?.feed || ''; form.elements.description.value = state.project.description || ''; form.elements.reason.value = ''; showDialog('#settings-dialog'); });
  $('#settings-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; formError(form); busy($('[type=submit]', form), async () => { const values = Object.fromEntries(new FormData(form)); const {reason, support, feed, description} = values; await api(`/api/projects/${encodeURIComponent(state.project.id)}`, {method: 'PATCH', body: {changes: {configuration: {support, feed}, description}, reason}}); await refreshProject(); await loadCandidates(); $('#settings-dialog').close(); toast('Project configuration updated.'); }, message => formError(form, message)); });
  $('#chat-form').addEventListener('submit', submitChat);
  $('#chat-input').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
  $('#cancel-job').addEventListener('click', () => busy($('#cancel-job'), async () => { if (!state.job) return; $('#job-activity-text').textContent = 'Stopping the active task…'; await api(`/api/jobs/${encodeURIComponent(state.job.id)}/cancel`, {method: 'POST', body: {}}); toast('Stop requested. Completed changes are retained.'); }));
  let searchTimer; $('#candidate-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadCandidates().catch(error => toast(error.message, true)), 250); });
  $$('[data-pool]').forEach(item => item.addEventListener('click', () => { state.pool = item.dataset.pool; $$('[data-pool]').forEach(pill => { const active = pill === item; pill.classList.toggle('active', active); pill.setAttribute('aria-pressed', String(active)); }); loadCandidates().catch(error => toast(error.message, true)); }));
  $('#add-experiment').addEventListener('click', () => openExperiment());
  $('#experiment-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; formError(form);
    busy($('[type=submit]', form), async () => {
      const data = Object.fromEntries(new FormData(form)); const metrics = {};
      $$('[data-metric]', form).forEach(input => { if (input.value !== '') { const value = Number(input.value); if (!Number.isFinite(value)) throw new Error('Measurements must be finite numbers.'); metrics[input.dataset.metric] = value; } });
      if (!Object.keys(metrics).length) throw new Error('Enter at least one measured result.');
      const payload = {candidate_id: data.candidate_id.trim(), label: data.label.trim(), conditions: {target: state.project.target, support: data.support.trim(), feed: data.feed.trim()}, metrics, notes: data.notes || ''};
      await api(`/api/projects/${encodeURIComponent(state.project.id)}/experiments`, {method: 'POST', body: payload}); $('#experiment-dialog').close(); await refreshProject(); await loadCandidates(); toast('Draft result saved. Review and explicitly accept it to use applicable metrics.'); await inspectCandidate(payload.candidate_id);
    }, message => formError(form, message));
  });
  $('#rank-untested').addEventListener('click', event => rank('untested', event.currentTarget));
  $('#rank-updated').addEventListener('click', event => rank('updated', event.currentTarget));
  $('#create-testing-batch').addEventListener('click', openTestingBatchForm);
  $('#open-testing-batches').addEventListener('click', () => { goTab('library'); $('#testing-batches-section').scrollIntoView({behavior: 'smooth'}); });
  $('#assumptions-form').addEventListener('submit', saveAssumptions);
  $('#calculate-form').addEventListener('submit', calculate);
  $('#add-scale-prediction').addEventListener('click', openScalePrediction);
  $('#calculation-method').addEventListener('change', renderMethodInputs);
  $('#build-method').addEventListener('click', () => { setMode('build'); goTab('research'); $('#chat-input').focus(); });
  $('#refresh-methods').addEventListener('click', event => busy(event.currentTarget, loadMethods));
  $('#add-source').addEventListener('click', () => { $('#source-form').reset(); showDialog('#source-dialog'); });
  $('#search-pubmed').addEventListener('click', openPubmedSearch);
  $('#open-handbook').addEventListener('click', () => openHandbook());
  $('#source-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; formError(form); busy($('[type=submit]', form), async () => { const data = Object.fromEntries(new FormData(form)); await api(`/api/projects/${encodeURIComponent(state.project.id)}/sources`, {method: 'POST', body: data}); $('#source-dialog').close(); await loadSources(); toast('Source evidence archived.'); }, message => formError(form, message)); });
}

async function initialize() {
  for (const element of metals) { for (const select of [$('#new-target'), $('#new-competitor')]) { const option = node('option', '', element); option.value = element; select.append(option); } }
  const metrics = ['collected_target_kg_per_l_cycle', 'purity_fraction', 'recovery_fraction', 'cycles_observed', 'cycle_time_hours', 'working_capacity_kg_per_l'];
  for (const key of metrics) { const [labelText, unit] = fieldInfo[key]; const label = node('label', 'field', labelText); const input = node('input'); input.type = 'number'; input.step = 'any'; input.min = '0'; if (key.endsWith('_fraction')) input.max = '1'; input.name = key; input.dataset.metric = key; input.placeholder = 'Not measured'; label.append(node('small', '', unit), input); $('#experiment-metrics').append(label); }
  bindEvents();
  const results = await Promise.allSettled([loadStatus(), loadProjects(), loadMethods()]);
  if (results[1].status === 'rejected') { showGlobalError(results[1].reason.message); $('#welcome').hidden = false; }
  else if (state.projects.length) { let saved; try { saved = localStorage.getItem('lanm-project'); } catch {} await selectProject(state.projects.find(item => item.id === saved)?.id || state.projects[0].id); }
  else $('#welcome').hidden = false;
  if (results[0].status === 'rejected') { $('#runtime-label').textContent = 'Connection unavailable'; $('#runtime-description').textContent = 'Local service could not be reached'; }
  if (results[2].status === 'rejected') replace($('#method-list'), node('p', 'muted small', 'Method registry unavailable: ' + results[2].reason.message));
}

initialize().catch(error => showGlobalError(error.message));
