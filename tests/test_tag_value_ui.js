const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('failed read displays actual OPC status and error safely', async () => {
    const ui = setup(async () => ({ok: true, json: async () => ({
        success: false, quality: 'BadNodeIdUnknown', status_code: '0x80340000',
        error: 'OPC UA BadNodeIdUnknown: <node>'
    })}));
    ui.run('selectedRuntimeTag = {nodeId: "ns=2;s=A"}; resetTagValuePreview()');
    await ui.run('refreshTagValue()');
    assert.equal(ui.elements.get('current-tag-value').textContent, 'OPC UA BadNodeIdUnknown: <node>');
    assert.equal(ui.elements.get('current-tag-quality').textContent, 'BadNodeIdUnknown 0x80340000');
});

function setup(fetch) {
    const elements = new Map();
    const context = vm.createContext({
        document: { getElementById(id) {
            if (!elements.has(id)) elements.set(id, { textContent: '', disabled: false, addEventListener() {} });
            return elements.get(id);
        } }, fetch, AbortController, setTimeout, clearTimeout,
    });
    const source = fs.readFileSync('static/app.js', 'utf8').split('let selectedAlarm = null;')[0];
    vm.runInContext(source, context);
    return { elements, run: code => vm.runInContext(code, context) };
}

test('selection does not read; refresh reads only selected node and displays result', async () => {
    const calls = [];
    const ui = setup(async (url, options) => {
        calls.push(JSON.parse(options.body));
        return { ok: true, json: async () => ({ success: true, value: '42', quality: 'Good', read_at: 'now' }) };
    });
    ui.run('resetTagValuePreview()');
    assert.equal(ui.elements.get('refresh-tag-value').disabled, true);
    ui.run('selectedRuntimeTag = {nodeId: "ns=2;s=A"}; resetTagValuePreview()');
    assert.equal(calls.length, 0);
    await ui.run('refreshTagValue()');
    assert.deepEqual(calls, [{node_id: 'ns=2;s=A'}]);
    assert.equal(ui.elements.get('current-tag-value').textContent, '42');
    assert.equal(ui.elements.get('current-tag-quality').textContent, 'Good');
});

test('late responses cannot replace a new selection or enable a cleared preview', async () => {
    let finish;
    const ui = setup(() => new Promise(resolve => { finish = resolve; }));
    ui.run('selectedRuntimeTag = {nodeId: "ns=2;s=A"}; resetTagValuePreview()');
    const pending = ui.run('refreshTagValue()');
    ui.run('resetTagValuePreview(null)');
    finish({ok: true, json: async () => ({success: true, value: 'old'})});
    await pending;
    assert.equal(ui.elements.get('current-tag-value').textContent, 'No tag selected');
    assert.equal(ui.elements.get('refresh-tag-value').disabled, true);
});
