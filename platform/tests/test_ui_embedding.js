'use strict';

// Run with: node platform/tests/test_ui_embedding.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const integration = require('../ui/integration.js');

function element() {
  return {value: '', hidden: false, disabled: false, open: false, dataset: {}, children: [], attributes: {},
    classList: {add() {}, remove() {}, toggle() {}},
    setAttribute(key, value) { this.attributes[key] = value; }, append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; }};
}

function browser(url) {
  const location = new URL(url); const elements = new Map(); const messages = []; const requests = []; const events = {}; const dialogs = [];
  const views = Object.keys(integration.views).map(view => Object.assign(element(), {dataset: {researchView: view}}));
  const panels = ['research', 'library', 'evidence', 'model'].map(tab => Object.assign(element(), {id: 'panel-' + tab}));
  const parent = {postMessage: (data, origin) => messages.push({data, origin})};
  const document = {body: element(), createElement: () => element(), createTextNode: text => ({textContent: text}),
    querySelector(selector) { if (!elements.has(selector)) elements.set(selector, element()); return elements.get(selector); },
    querySelectorAll(selector) { return selector === '[data-research-view]' ? views : selector === '.tab-panel' ? panels : selector === 'dialog' ? dialogs : []; }};
  const window = {location, parent, addEventListener: (name, handler) => { events[name] = handler; }};
  const context = vm.createContext({window, location, document, LanMIntegration: integration, URL, URLSearchParams, Intl,
    console, setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: callback => callback(), localStorage: {getItem: () => null, setItem() {}},
    fetch: async (resource, init) => { requests.push({resource, init}); return {ok: true, json: async () => ({project: {id: resource.split('/').pop(), name: 'Research project'}, projects: []})}; },
    EventSource: function (resource) { requests.push({resource, stream: true}); this.close = () => {}; }});
  const source = fs.readFileSync(path.join(__dirname, '../ui/app.js'), 'utf8');
  const startup = 'initialize().catch(error => showGlobalError(error.message));';
  assert(source.includes(startup), 'Isolate application startup for the controller test.');
  vm.runInContext(source.replace(startup, ''), context);
  const evaluate = source => vm.runInContext(source, context);
  evaluate(`renderProject = () => {}; loadMessages = async () => {}; loadCandidates = async () => {}; loadSources = async () => {}; loadRuns = async () => {}; loadScalePredictions = async () => {}; loadTestingBatches = async () => {}; loadSharedRecords = async () => {}; loadMethods = async () => {};`);
  return {context, evaluate, dialogs, elements, events, parent, messages, requests};
}

async function run() {
  const origin = 'http://127.0.0.1:8780';
  assert.deepEqual(integration.context(new URL(origin + '/research/?embed=argus'), true), {prefix: '/research', embedded: true});
  assert.equal(integration.context(new URL(origin + '/?embed=argus'), true).embedded, false);
  assert.equal(integration.context(new URL(origin + '/research/?embed=argus'), false).embedded, false);
  assert.equal(integration.apiPath('/api/projects?a=1', '/research'), '/research/api/projects?a=1');
  assert.equal(integration.apiPath('/research/api/projects', '/research'), '/research/api/projects');
  assert.equal(integration.apiPath('/api/projects', ''), '/api/projects');
  const download = '/api/projects/project_1/testing-batches/batch_1/csv';
  for (const value of [download, origin + download, '/research' + download]) {
    assert.deepEqual(integration.localApiUrl(value, origin, '/research'), {path: download, href: origin + '/research' + download});
  }
  for (const value of ['https://example.com' + download, 'http://user@127.0.0.1:8780' + download, download + '?download=1', download + '#fragment', '/research/../private', 'javascript:alert(1)']) {
    assert.equal(integration.localApiUrl(value, origin, '/research'), null, value);
  }
  const parent = {}; const command = {type: 'argus:research-select', projectId: 'project_1', view: 'build'};
  assert.deepEqual(integration.selectionMessage({origin, source: parent, data: command}, parent, origin), {projectId: 'project_1', view: 'build'});
  for (const event of [
    {origin: 'https://example.com', source: parent, data: command}, {origin, source: {}, data: command},
    {origin, source: parent, data: {...command, view: '__proto__'}}, {origin, source: parent, data: {...command, projectId: '../other'}},
    {origin, source: parent, data: {...command, projectId: 12}}, {origin, source: parent, data: {type: 'other'}}
  ]) assert.equal(integration.selectionMessage(event, parent, origin), null);

  const embedded = browser(origin + '/research/?embed=argus');
  embedded.evaluate('initializeEmbedding(); state.initialized = true;');
  await embedded.evaluate(`applyResearchSelection({projectId: 'project_1', view: 'build'})`);
  assert.equal(embedded.evaluate('state.project.id'), 'project_1');
  assert.equal(embedded.evaluate('state.mode'), 'build');
  assert.equal(embedded.evaluate('state.tab'), 'research');
  assert(embedded.requests.some(request => request.resource === '/research/api/projects/project_1'));
  assert.equal(embedded.messages.at(-1).data.view, 'build');
  assert.equal(embedded.messages.at(-1).origin, origin);
  assert.equal(embedded.messages.at(-1).data.projectId, 'project_1');
  assert.equal(embedded.evaluate(`testingDownloadUrl('${download}')`), origin + '/research' + download);
  assert.equal(embedded.evaluate(`testingDownloadUrl('/api/projects/other/testing-batches/batch_1/csv')`), null);
  embedded.evaluate(`startStream('job_1')`);
  assert.equal(embedded.requests.at(-1).resource, '/research/api/jobs/job_1/events');
  for (const busyState of [`state.job = {id: 'job_1'}`, 'state.job = null; state.chatSubmitting = true']) {
    embedded.evaluate(busyState); const count = embedded.requests.length;
    await embedded.evaluate(`applyResearchSelection({projectId: 'project_2', view: 'candidates'})`);
    assert.equal(embedded.requests.length, count, 'Active and submitting turns must block project fetches.');
    assert.equal(embedded.evaluate('state.project.id'), 'project_1');
    assert.equal(embedded.messages.at(-1).data.projectId, 'project_1');
    assert.equal(embedded.messages.at(-1).data.busy, true);
    assert.equal(embedded.messages.at(-1).data.busyReason, 'turn');
  }
  embedded.evaluate('state.job = null; state.chatSubmitting = false;');
  const dialog = element(); dialog.open = true; embedded.dialogs.push(dialog);
  await embedded.evaluate(`applyResearchSelection({projectId: 'project_2', view: 'candidates'})`);
  assert.equal(embedded.evaluate('state.project.id'), 'project_1', 'An open project dialog must not be moved to another project.');
  assert.equal(embedded.messages.at(-1).data.busyReason, 'dialog');
  dialog.open = false; embedded.evaluate('syncEmbedded()');
  assert.equal(embedded.messages.at(-1).data.busy, false);
  for (const [view, panel] of Object.entries(integration.views)) {
    await embedded.evaluate(`applyResearchSelection({view: '${view}'})`);
    assert.equal(embedded.evaluate('state.tab'), panel); assert.equal(embedded.messages.at(-1).data.view, view);
  }
  embedded.evaluate('state.initialized = false;');
  embedded.events.message({origin, source: embedded.parent, data: command});
  assert.equal(embedded.evaluate('state.pendingSelection.projectId'), 'project_1');
  embedded.events.message({origin: 'https://example.com', source: embedded.parent, data: {...command, projectId: 'other'}});
  assert.equal(embedded.evaluate('state.pendingSelection.projectId'), 'project_1');

  const race = browser(origin + '/research/?embed=argus'); const resolves = {};
  race.context.fetch = resource => new Promise(resolve => { resolves[resource] = project => resolve({ok: true, json: async () => ({project})}); });
  const older = race.evaluate(`selectProject('older')`); const newer = race.evaluate(`selectProject('newer')`);
  resolves['/research/api/projects/newer']({id: 'newer', name: 'Newer'}); await newer;
  resolves['/research/api/projects/older']({id: 'older', name: 'Older'}); await older;
  assert.equal(race.evaluate('state.project.id'), 'newer', 'An older response must not replace the latest selection.');

  const standalone = browser('http://127.0.0.1:8781/');
  standalone.evaluate('initializeEmbedding(); state.initialized = true;');
  await standalone.evaluate(`selectProject('project_1')`);
  assert.equal(standalone.requests[0].resource, '/api/projects/project_1'); assert.equal(standalone.messages.length, 0);
  assert.equal(standalone.events.message, undefined, 'Standalone UI must not accept parent commands.');
  console.log('PASS: URL routing, safe downloads, message validation, navigation, turn/modal locks, project races, standalone isolation.');
}

module.exports = run;
if (require.main === module) run().catch(error => { console.error(error); process.exitCode = 1; });
