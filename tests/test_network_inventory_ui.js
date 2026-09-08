const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor() {
        this.children = []; this.events = {}; this.textContent = ''; this.value = '';
        this.checked = false; this.disabled = false;
        this.classList = {remove() {}, add() {}};
    }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren() { this.children = []; }
    addEventListener(event, handler) { this.events[event] = handler; }
}
function setup(handler) {
    const elements = new Map();
    const get = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    get('inventory-filter').value = 'All'; get('inventory-sort').value = 'IPAddress';
    get('inventory-manual').elements = {namedItem: key => get(`field-${key}`)};
    const calls = [];
    const context = vm.createContext({document: {getElementById: get,
        querySelector: () => get('tab'), createElement: () => new Element()},
        URLSearchParams, Date, setTimeout, clearTimeout,
        FormData: class { constructor() { return ['MachineName', 'Description', 'Location', 'Remark'].map(key => [key, get(`field-${key}`).value]); } },
        fetch: async (url, options) => { calls.push({url, options}); return handler(url, options); }});
    vm.runInContext(fs.readFileSync('static/network_inventory.js', 'utf8'), context);
    return {get, calls};
}
const row = {IPAddress: '172.28.231.1', MachineName: '<img src=x onerror=alert(1)>', Status: 'Offline - Known',
    LastScan: '2026-09-08T01:00:00', LastSeen: '2026-09-07T01:00:00', Manual: {}, KepwareIdentity: []};
const current = {rows: [row], scan_start: row.IPAddress, scan_end: row.IPAddress,
    last_run: {FinishedAt: row.LastScan}};
const ok = data => ({ok: true, json: async () => data});

test('tab loads inventory without scanning; displays names as text and UTC timestamps in local time', async () => {
    const ui = setup(async () => ok(current));
    assert.equal(ui.calls.length, 0);
    await ui.get('tab').events.click();
    assert.equal(ui.calls.length, 1);
    assert(!ui.calls[0].url.includes('/scan'));
    const cells = ui.get('inventory-rows').children[0].children;
    assert.equal(cells[1].textContent, row.MachineName);
    assert.equal(cells[1].children.length, 0);
    assert.equal(cells[10].textContent, new Date(`${row.LastScan}Z`).toLocaleString());
    assert(ui.get('inventory-freshness').textContent.includes(new Date(`${row.LastScan}Z`).toLocaleString()));
});

test('candidate action clears search and submits exact filter', async () => {
    const ui = setup(async () => ok(current));
    ui.get('inventory-search').value = 'Packing';
    ui.get('inventory-free').events.click();
    const url = new URL(ui.calls[0].url, 'http://localhost');
    assert.equal(url.searchParams.get('category'), 'Candidate Free');
    assert.equal(url.searchParams.get('q'), '');
});

test('scan is explicit, POST-only and disables button until completed', async () => {
    let finish;
    const ui = setup(url => url.endsWith('/scan') ? new Promise(resolve => {finish = resolve;}) : ok(current));
    const pending = ui.get('inventory-scan').events.click();
    assert(ui.get('inventory-scan').disabled);
    assert.equal(ui.calls[0].options.method, 'POST');
    assert.equal(ui.calls[0].options.body, undefined);
    finish(ok({run: {}}));
    await pending;
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(ui.calls.length, 2);
});

test('selected IP loads all three histories and manual save posts a new revision', async () => {
    const ui = setup(async url => ok(url.endsWith('/history') ? {network: [{ScanTime: row.LastScan}], kepware: [], manual: []} : current));
    await ui.get('tab').events.click();
    ui.get('inventory-rows').children[0].children[0].children[0].events.click();
    await new Promise(resolve => setImmediate(resolve));
    assert(ui.calls.some(call => call.url === `/api/network-inventory/${row.IPAddress}/history`));
    assert.equal(ui.get('inventory-histories').children.length, 3);
    ui.get('field-MachineName').value = 'Packing Camera';
    await ui.get('inventory-manual').events.submit({preventDefault() {}, submitter: new Element()});
    const save = ui.calls.find(call => call.url.endsWith('/manual'));
    assert.equal(save.options.method, 'POST');
    assert.equal(JSON.parse(save.options.body).MachineName, 'Packing Camera');
});

test('out-of-order refresh responses cannot overwrite the latest search', async () => {
    const pending = [];
    const ui = setup(() => new Promise(resolve => pending.push(resolve)));
    const first = ui.get('tab').events.click();
    ui.get('inventory-search').value = 'new';
    const second = ui.get('inventory-refresh').events.click();
    pending[1](ok({...current, rows: []})); await second;
    pending[0](ok(current)); await first;
    assert.equal(ui.get('inventory-rows').children.length, 0);
});

test('configuration/database errors are visible', async () => {
    const ui = setup(async () => ({ok: false, json: async () => ({error: 'Configure OT_SCAN_START'})}));
    await ui.get('tab').events.click();
    assert.equal(ui.get('inventory-message').textContent, 'Configure OT_SCAN_START');
});
