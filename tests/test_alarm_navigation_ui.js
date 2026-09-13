const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('left views are exclusive and switching preserves selection and list contents', () => {
    const elements = new Map();
    function element() {
        const classes = new Set();
        return { dataset: {}, attributes: {}, children: [],
            classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name) },
            setAttribute(name, value) { this.attributes[name] = value; }, addEventListener() {} };
    }
    const buttons = ['all', 'list', 'alarm'].map(view => Object.assign(element(), { dataset: { alarmFilter: view } }));
    const document = { querySelectorAll: selector => selector === '.alarm-filter-button' ? buttons : [], getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
    } };
    const source = fs.readFileSync('static/app.js', 'utf8');
    const context = vm.createContext({ document, selectedAlarm: null, selectedRuntimeTag: { path: 'Channel/Device/Tag' } });
    vm.runInContext(source.slice(source.indexOf('function revealNavigationItem('), source.indexOf('function renderAlarmTagTree(')), context);
    const row = {};
    document.getElementById('alarm-summary').children.push(row);
    for (const view of ['all', 'list', 'alarm', 'list', 'all']) {
        context.setAlarmNavigationView(view);
        for (const [id, expected] of [['runtime-kepware-tree-host', 'all'], ['alarm-summary', 'list'], ['alarm-tag-tree', 'alarm']]) {
            assert.equal(elements.get(id).classList.contains('hidden'), view !== expected);
        }
        assert.equal(buttons.filter(button => button.attributes['aria-pressed'] === 'true').length, 1);
        assert.equal(context.selectedRuntimeTag.path, 'Channel/Device/Tag');
        assert.equal(elements.get('alarm-summary').children[0], row);
    }
});

test('navigation reveals the same path in both directions without reloading authoring state', () => {
    const path = 'LP2_MODBUS/MIX/ALM/MOIST_CLN_PROBE';
    function item(path, parentElement = null) {
        const classes = new Set();
        return { dataset: { canonicalPath: path, alarmId: '217' }, parentElement,
            classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name) },
            scrollIntoView() { this.scrolled = (this.scrolled || 0) + 1; } };
    }
    const channel = { tagName: 'DETAILS', open: false };
    const device = { tagName: 'DETAILS', open: false, parentElement: channel };
    const group = { tagName: 'DETAILS', open: false, parentElement: device };
    const treeTag = item(path, group);
    const row = item(path);
    const liveTag = item(path);
    const otherRow = item('Other/Tag');
    const sources = { '.kepware-object': [liveTag], '#alarm-summary-body tr': [row, otherRow], '#alarm-tag-tree button': [treeTag] };
    const selectedRuntimeTag = { path };
    const selectedAlarm = { alarm_id: 217 };
    const context = vm.createContext({ selectedRuntimeTag, selectedAlarm, selectedMp3: 'sound.mp3',
        document: { querySelectorAll: selector => sources[selector] },
        showAlarmForm() { assert.fail('must not reload Alarm Configuration'); },
        loadOperationalTagContext() { assert.fail('must not reload Tag Knowledge'); } });
    const source = fs.readFileSync('static/app.js', 'utf8');
    vm.runInContext(source.slice(source.indexOf('function revealNavigationItem('), source.indexOf('function setAlarmNavigationView(')), context);
    context.syncAlarmNavigationSelection('alarm');
    assert.ok(channel.open && device.open && group.open);
    assert.equal(treeTag.scrolled, 1);
    assert.ok(treeTag.classList.contains('selected-object'));
    context.syncAlarmNavigationSelection('list');
    assert.equal(row.scrolled, 1);
    assert.ok(row.classList.contains('selected-mapping'));
    assert.equal(otherRow.classList.contains('selected-mapping'), false);
    context.syncAlarmNavigationSelection('all');
    assert.equal(liveTag.scrolled, 1);
    assert.equal(context.selectedRuntimeTag, selectedRuntimeTag);
    assert.equal(context.selectedAlarm, selectedAlarm);
    assert.equal(context.selectedMp3, 'sound.mp3');

    // An All Tags selection without an alarm must clear stale target highlights.
    selectedRuntimeTag.path = 'Unmapped/Tag';
    context.syncAlarmNavigationSelection('alarm');
    context.syncAlarmNavigationSelection('list');
    assert.equal(treeTag.classList.contains('selected-object'), false);
    assert.equal(row.classList.contains('selected-mapping'), false);
    assert.equal(treeTag.scrolled, 1);
    assert.equal(row.scrolled, 1);
    assert.equal(context.selectedMp3, 'sound.mp3');
    assert.equal(context.selectedRuntimeTag.path, 'Unmapped/Tag');
    context.selectedRuntimeTag = null;
    assert.doesNotThrow(() => context.syncAlarmNavigationSelection('alarm'));
});
