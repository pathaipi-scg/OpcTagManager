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
function setup(handler, timerApi = {setTimeout, clearTimeout}) {
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
        URLSearchParams, Date, ...timerApi,
        encodeURIComponent,
        FormData: class { constructor() { return ['MachineName', 'Description', 'Location', 'Remark', 'Vendor', 'DeviceType'].map(key => [key, get(`field-${key}`).value]); } },
        fetch: async (url, options) => { calls.push({url, options}); return handler(url, options); }});
    vm.runInContext(fs.readFileSync('static/network_inventory.js', 'utf8'), context);
    return {get, calls};
}
const row = {IPAddress: '172.28.231.1', MachineName: '<img src=x onerror=alert(1)>', Status: 'Offline - Known',
    KepwareDevice: 'MIX', Description: 'Mixer', Location: 'Packing', Vendor: 'Example Vendor', DeviceType: 'PLC',
    LastScan: '2026-09-08T01:00:00', LastSeen: '2026-09-07T01:00:00', Manual: {}, KepwareIdentity: []};
const current = {rows: [row], scan_start: row.IPAddress, scan_end: row.IPAddress,
    last_run: {FinishedAt: row.LastScan}};
const ok = data => ({ok: true, json: async () => data});

function fakeTimers() {
    let next = 0;
    const timers = new Map();
    return {
        timers,
        setTimeout(fn, delay) { const id = ++next; timers.set(id, {fn, delay}); return id; },
        clearTimeout(id) { timers.delete(id); },
        fire() { const [id, item] = timers.entries().next().value; timers.delete(id); return item.fn(); },
    };
}
const activeProgress = {status: 'running', scan_id: 'test-run', network_name: 'DEFAULT_OT',
    network_number: 1, total_networks: 3, scanned_ips: 87, total_ips: 762,
    current_ip: '172.28.231.87', online_count: 14, mac_count: 9, elapsed_seconds: 18, phase: 'ICMP'};

test('live progress polls once per second, advances networks and keeps completion summary', async () => {
    const clock = fakeTimers();
    let finish, progress = {...activeProgress};
    const ui = setup(url => url.endsWith('/scan') ? new Promise(resolve => {finish = resolve;}) :
        ok(url.endsWith('/progress') ? progress : current), clock);
    const pending = ui.get('inventory-scan').events.click();
    assert.match(ui.get('inventory-progress').textContent, /Starting scan/);
    assert.equal(clock.timers.size, 1);
    assert.equal([...clock.timers.values()][0].delay, 1000);
    await clock.fire();
    const text = ui.get('inventory-progress').textContent;
    for (const part of ['Scanning DEFAULT_OT', 'Network 1/3', 'Progress: 87 / 762', 'Current IP: 172.28.231.87',
                        'Online: 14', 'MAC Found: 9', 'Elapsed: 00:18']) assert(text.includes(part), part);
    assert(ui.get('inventory-scan').disabled);
    progress = {...progress, network_name: 'REJECT_OT', network_number: 2, scanned_ips: 300};
    await clock.fire();
    assert.match(ui.get('inventory-progress').textContent, /Network 2\/3/);
    progress = {...progress, network_number: 3, status: 'completed', scanned_ips: 762, elapsed_seconds: 42};
    finish(ok({progress}));
    await pending;
    assert.match(ui.get('inventory-progress').textContent, /Scan completed\n762 IPs scanned/);
    assert.match(ui.get('inventory-progress').textContent, /Duration: 00:42/);
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(clock.timers.size, 0);
});

test('late running poll cannot overwrite the completed POST summary', async () => {
    const clock = fakeTimers();
    let finish, pollFinish;
    const ui = setup(url => url.endsWith('/scan') ? new Promise(resolve => {finish = resolve;}) :
        url.endsWith('/progress') ? new Promise(resolve => {pollFinish = resolve;}) : ok(current), clock);
    const pending = ui.get('inventory-scan').events.click();
    const polling = clock.fire();
    assert.equal(clock.timers.size, 0); // No second timer while request is pending.
    finish(ok({progress: {...activeProgress, status: 'completed'}}));
    await pending;
    pollFinish(ok(activeProgress));
    await polling;
    assert.match(ui.get('inventory-progress').textContent, /Scan completed/);
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(clock.timers.size, 0);
});

test('scan error displays partial summary and stops polling', async () => {
    const clock = fakeTimers();
    const failed = {...activeProgress, status: 'error', error: 'Scan failed; completed network history is retained.'};
    const ui = setup(url => url.endsWith('/scan') ? {ok: false, json: async () => ({error: 'Inventory unavailable'})} :
        ok(url.endsWith('/progress') ? failed : current), clock);
    await ui.get('inventory-scan').events.click();
    assert.match(ui.get('inventory-progress').textContent, /Scan failed/);
    assert.match(ui.get('inventory-progress').textContent, /87 IPs scanned/);
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(clock.timers.size, 0);
});

test('disconnected POST keeps button disabled while server continues scanning', async () => {
    const clock = fakeTimers();
    let progress = activeProgress;
    const ui = setup(url => {
        if (url.endsWith('/scan')) throw new Error('Disconnected');
        return ok(url.endsWith('/progress') ? progress : current);
    }, clock);
    await ui.get('inventory-scan').events.click();
    assert(ui.get('inventory-scan').disabled);
    assert.equal(clock.timers.size, 1);
    progress = {...progress, status: 'completed'};
    await clock.fire();
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(clock.timers.size, 0);
});

test('refresh discovers an existing scan without posting another scan', async () => {
    const clock = fakeTimers();
    const ui = setup(() => ok({...current, progress: activeProgress}), clock);
    await ui.get('tab').events.click();
    assert(ui.get('inventory-scan').disabled);
    assert.match(ui.get('inventory-progress').textContent, /Network 1\/3/);
    assert.equal(clock.timers.size, 1);
    assert(ui.calls.every(c => c.options?.method !== 'POST'));
});

test('tab loads inventory without scanning; displays names as text and UTC timestamps in local time', async () => {
    const ui = setup(async () => ok(current));
    assert.equal(ui.calls.length, 0);
    await ui.get('tab').events.click();
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.get('inventory-message').textContent, '');
    assert(!ui.calls[0].url.includes('/scan'));
    const cells = ui.get('inventory-rows').children[0].children;
    assert.equal(cells[1].textContent, row.MachineName);
    assert.equal(cells[1].children.length, 0);
    assert.equal(cells.length, 8);
    assert.equal(cells[1].title, row.MachineName);
    assert.equal(cells[0].children[0].textContent, row.IPAddress);
    assert.deepEqual(cells.slice(1).map(cell => cell.textContent), [row.MachineName, row.Status,
        row.KepwareDevice, new Date(`${row.LastSeen}Z`).toLocaleString(), 'Mixer / Packing', row.Vendor, row.DeviceType]);
    assert.equal(cells[4].title, cells[4].textContent);
    assert.equal(ui.get('inventory-freshness').textContent, `Scanned: ${new Date(`${row.LastScan}Z`).toLocaleString()}`);
    assert.equal(ui.get('inventory-range').textContent, `IP range: ${current.scan_start}-${current.scan_end}`);
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
    assert.equal(ui.get('inventory-scan').textContent, 'Scanning...');
    assert.equal(ui.calls[0].options.method, 'POST');
    assert.equal(ui.calls[0].options.body, undefined);
    finish(ok({run: {}}));
    await pending;
    assert(!ui.get('inventory-scan').disabled);
    assert.equal(ui.get('inventory-scan').textContent, 'Scan Now');
    assert.equal(ui.calls.length, 2);
});

test('selected IP loads all three histories and manual save posts a new revision', async () => {
    const ui = setup(async url => ok(url.endsWith('/history') ? {network: [{ScanTime: row.LastScan}], kepware: [], manual: []} : current));
    assert.equal(ui.get('inventory-manual-save').disabled, true);
    assert.equal(ui.get('field-MachineName').disabled, true);
    assert.equal(ui.get('inventory-manual-selection').textContent, 'Select an IP to edit');
    await ui.get('tab').events.click();
    ui.get('inventory-rows').children[0].children[0].children[0].events.click();
    await new Promise(resolve => setImmediate(resolve));
    assert(ui.calls.some(call => call.url === `/api/network-inventory/${row.IPAddress}/history`));
    assert.equal(ui.get('inventory-histories').children.length, 3);
    assert.equal(ui.get('inventory-manual-save').disabled, false);
    assert.equal(ui.get('field-MachineName').disabled, false);
    assert.equal(ui.get('inventory-manual-selection').textContent, `Editing IP: ${row.IPAddress}`);
    const details = ui.get('inventory-current').children;
    const fields = new Map();
    for (let i = 0; i < details.length; i += 2) fields.set(details[i].textContent, details[i + 1].textContent);
    for (const label of ['IP Address', 'Effective Machine Name', 'Status', 'Vendor', 'Device Type', 'Device Model',
        'MAC Address', 'Host Name', 'Kepware Channel', 'Kepware Device', 'Last Scan', 'Last Seen',
        'Source', 'Description', 'Location', 'Detection Source']) assert(fields.has(label), label);
    assert.equal(fields.get('Last Scan'), new Date(`${row.LastScan}Z`).toLocaleString());
    assert.equal(fields.get('Effective Machine Name'), row.MachineName);
    ui.get('field-MachineName').value = 'Packing Camera';
    await ui.get('inventory-manual').events.submit({preventDefault() {}, submitter: new Element()});
    const save = ui.calls.find(call => call.url.endsWith('/manual'));
    assert.equal(save.options.method, 'POST');
    assert.equal(JSON.parse(save.options.body).MachineName, 'Packing Camera');
    assert.equal(save.url, `/api/network-inventory/${row.IPAddress}/manual`);
    assert.match(ui.get('inventory-manual-message').textContent, /Previous revisions preserved/);
});

test('filtering out the selected IP clears and disables the editor; submitting cannot save', async () => {
    let visible = true;
    const ui = setup(async url => ok(url.endsWith('/history') ? {network: [], kepware: [], manual: []} : {...current, rows: visible ? [row] : []}));
    await ui.get('tab').events.click();
    await ui.get('inventory-rows').children[0].children[0].children[0].events.click();
    ui.get('field-MachineName').value = 'Draft';
    visible = false;
    await ui.get('inventory-refresh').events.click();
    assert.equal(ui.get('field-MachineName').value, '');
    assert.equal(ui.get('inventory-manual-save').disabled, true);
    await ui.get('inventory-manual').events.submit({preventDefault() {}});
    assert.equal(ui.calls.filter(call => call.url.endsWith('/manual')).length, 0);
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

test('removing the address count preserves Kepware scan errors', async () => {
    const ui = setup(async () => ok({...current, last_run: {KepwareError: 'Kepware capture unavailable'}}));
    await ui.get('tab').events.click();
    assert.equal(ui.get('inventory-message').textContent, 'Kepware capture unavailable');
});

const networks = [
    {network_id: 7, network_name: 'MC1', scan_start: row.IPAddress, scan_end: row.IPAddress},
    {network_id: 9, network_name: 'MC2', scan_start: row.IPAddress, scan_end: row.IPAddress},
];
const multiRows = networks.map(n => ({...row, ...n, NetworkId: n.network_id, NetworkName: n.network_name}));
const multi = {...current, networks, rows: multiRows, scan_start: null, scan_end: null,
    network_summaries: networks.map(n => ({...n, last_run: current.last_run}))};

test('All Networks shows separate same-IP rows and network column; scan has no target override', async () => {
    const ui = setup(async () => ok(multi));
    await ui.get('tab').events.click();
    assert.equal(ui.get('inventory-network').children.length, 3);
    assert.equal(ui.get('inventory-network-heading').hidden, false);
    assert.equal(ui.get('inventory-network-col').hidden, false);
    assert.equal(ui.get('inventory-range').textContent, 'All Networks: 2 configured');
    assert.equal(ui.get('inventory-freshness').textContent, 'Scanned: 2/2 networks');
    assert.equal(ui.get('inventory-rows').children.length, 2);
    assert.deepEqual(ui.get('inventory-rows').children.map(tr => tr.children[8].textContent), ['MC1', 'MC2']);
    await ui.get('inventory-scan').events.click();
    assert(ui.calls.some(c => c.url === '/api/network-inventory/scan' && c.options.method === 'POST'));
});

test('selector scopes refresh, scan, candidate filter and clears stale manual target', async () => {
    const ui = setup(async url => ok(url.includes('/history') ? {network: [], kepware: [], manual: []} :
        {...multi, rows: url.includes('network_id=9') ? [multiRows[1]] : multiRows}));
    await ui.get('tab').events.click();
    await ui.get('inventory-rows').children[0].children[0].children[0].events.click();
    ui.get('inventory-network').value = '9';
    await ui.get('inventory-network').events.change();
    assert.equal(ui.get('inventory-manual-save').disabled, true);
    assert.equal(ui.get('inventory-network-heading').hidden, true);
    assert.equal(ui.get('inventory-rows').children.length, 1);
    await ui.get('inventory-scan').events.click();
    assert(ui.calls.some(c => c.url === '/api/network-inventory/scan?network_id=9'));
    ui.get('inventory-free').events.click();
    const free = new URL(ui.calls.at(-1).url, 'http://localhost');
    assert.equal(free.searchParams.get('network_id'), '9');
    assert.equal(free.searchParams.get('category'), 'Candidate Free');
});

test('same IP manual save and history use the selected row network in All Networks', async () => {
    const ui = setup(async url => ok(url.includes('/history') ? {network: [], kepware: [], manual: []} : multi));
    await ui.get('tab').events.click();
    await ui.get('inventory-rows').children[1].children[0].children[0].events.click();
    assert.equal(ui.get('inventory-manual-selection').textContent, `Editing IP: MC2 / ${row.IPAddress}`);
    assert(ui.calls.some(c => c.url === `/api/network-inventory/${row.IPAddress}/history?network_id=9`));
    ui.get('field-MachineName').value = 'MC2 Camera';
    await ui.get('inventory-manual').events.submit({preventDefault() {}});
    assert(ui.calls.some(c => c.url === `/api/network-inventory/${row.IPAddress}/manual?network_id=9`));
    assert.equal(ui.get('inventory-manual-selection').textContent, `Editing IP: MC2 / ${row.IPAddress}`);
});

test('legacy NULL rows are distinct, readable and cannot be edited', async () => {
    const legacy = {...row, network_id: null, NetworkId: null, network_name: 'Legacy / unassigned'};
    const ui = setup(async url => ok(url.includes('/history') ? {network: [], kepware: [], manual: [{NetworkId: null}]} :
        {...multi, legacy_count: 1, rows: [multiRows[0], legacy]}));
    await ui.get('tab').events.click();
    await ui.get('inventory-rows').children[1].children[0].children[0].events.click();
    assert(ui.calls.some(c => c.url.endsWith('/history?network_id=legacy')));
    assert.equal(ui.get('inventory-manual-save').disabled, true);
    await ui.get('inventory-manual').events.submit({preventDefault() {}});
    assert(!ui.calls.some(c => c.url.includes('/manual')));
});

test('late network response cannot replace selection or rows after a network switch', async () => {
    const pending = [];
    const ui = setup(() => new Promise(resolve => pending.push(resolve)));
    const all = ui.get('tab').events.click();
    ui.get('inventory-network').value = '9';
    const selected = ui.get('inventory-network').events.change();
    pending[1](ok({...multi, rows: [multiRows[1]]})); await selected;
    pending[0](ok(multi)); await all;
    assert.equal(ui.get('inventory-network').value, '9');
    assert.equal(ui.get('inventory-rows').children.length, 1);
});
