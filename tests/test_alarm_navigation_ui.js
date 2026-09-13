const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('left views are exclusive and switching preserves selection and list contents', async () => {
    const elements = new Map();
    function element() {
        const classes = new Set();
        return { dataset: {}, attributes: {}, children: [],
            classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name) },
            setAttribute(name, value) { this.attributes[name] = value; }, addEventListener() {} };
    }
    const buttons = ['all', 'list', 'alarm'].map(view => Object.assign(element(), { dataset: { alarmFilter: view } }));
    const document = { querySelector: () => ({ classList: { contains: () => true } }), querySelectorAll: selector => selector === '.alarm-filter-button' ? buttons : [], getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
    } };
    const source = fs.readFileSync('static/app.js', 'utf8');
    const context = vm.createContext({ document, runtimeKepwareTreeHost: { appendChild() {} }, kepwareTree: {}, ensureKepwareRoot: async () => {}, findKepwareTagByPath: async () => null, selectedAlarm: null, selectedRuntimeTag: { path: 'Channel/Device/Tag' } });
    vm.runInContext(source.slice(source.indexOf('function revealNavigationItem('), source.indexOf('function renderAlarmTagTree(')), context);
    const row = {};
    document.getElementById('alarm-summary').children.push(row);
    for (const view of ['all', 'list', 'alarm', 'list', 'all']) {
        await context.setAlarmNavigationView(view);
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
    vm.runInContext(source.slice(source.indexOf('function revealNavigationItem('), source.indexOf('let alarmNavigationGeneration')), context);
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

test('live path lookup loads each ancestor, shares pending root load and stops stale navigation', async () => {
    const path = 'LP2_MODBUS/MIX/ALM/MOIST_CLN_PROBE';
    const container = () => ({ nodes: [], querySelectorAll() { return this.nodes; } });
    const branch = (object_type, name, context) => ({ kepwareNode: { object_type, name, context }, kepwareChildren: container() });
    const tree = container();
    const channel = branch('Channel', 'LP2_MODBUS');
    const device = branch('Device', 'MIX', { channel: 'LP2_MODBUS' });
    const group = branch('Tag Group', 'ALM', { channel: 'LP2_MODBUS', device: 'MIX', group_path: ['ALM'] });
    const target = { dataset: { canonicalPath: path } };
    const loaded = [];
    let current = true;
    let finishRoot;
    const rootPromise = new Promise(resolve => { finishRoot = () => { tree.nodes = [channel]; resolve(); }; });
    const context = vm.createContext({ kepwareLoaded: true, kepwareChannelsPromise: rootPromise,
        ensureKepwareRoot: () => rootPromise,
        document: { getElementById: () => tree },
        async ensureKepwareChildren(button) {
            loaded.push(button.kepwareNode.name);
            button.kepwareChildren.nodes = button === channel ? [device] : button === device ? [group] : [target];
        } });
    const source = fs.readFileSync('static/app.js', 'utf8');
    vm.runInContext(source.slice(source.indexOf('async function findKepwareTagByPath('), source.indexOf('async function openTagByKepwarePath(')), context);
    const pending = context.findKepwareTagByPath(path, () => current);
    assert.deepEqual(loaded, []);
    finishRoot();
    assert.equal(await pending, target);
    assert.deepEqual(loaded, ['LP2_MODBUS', 'MIX', 'ALM']);
    await assert.rejects(context.findKepwareTagByPath('LP2_MODBUS/MIX/ALM/Missing'));
    loaded.length = 0;
    current = false;
    assert.equal(await context.findKepwareTagByPath(path, () => current), null);
    assert.deepEqual(loaded, []);
});

test('late All Tags lookup cannot reveal an old path or overwrite right-side state', async () => {
    let finish;
    const revealed = [];
    const state = { path: 'Channel/Device/Tag' };
    const context = vm.createContext({ selectedRuntimeTag: state, selectedMp3: 'sound.mp3', activePreviewTag: state,
        runtimeKepwareTreeHost: { appendChild() {} }, kepwareTree: {}, ensureKepwareRoot: async () => {},
        document: { querySelectorAll: () => [], querySelector: () => ({ classList: { contains: () => true } }),
            getElementById: () => ({ classList: { toggle() {} } }) },
        syncAlarmNavigationSelection: view => revealed.push(view),
        findKepwareTagByPath: () => new Promise(resolve => { finish = resolve; }) });
    const source = fs.readFileSync('static/app.js', 'utf8');
    vm.runInContext(source.slice(source.indexOf('let alarmNavigationGeneration'), source.indexOf('function renderAlarmTagTree(')), context);
    const pending = context.setAlarmNavigationView('all');
    await new Promise(setImmediate);
    await context.setAlarmNavigationView('alarm');
    finish();
    await pending;
    assert.deepEqual(revealed, ['all', 'alarm']);
    const next = context.setAlarmNavigationView('all');
    await new Promise(setImmediate);
    state.path = 'Channel/Device/NewTag';
    finish();
    await next;
    assert.deepEqual(revealed, ['all', 'alarm', 'all']);
    assert.equal(context.selectedMp3, 'sound.mp3');
    assert.equal(context.activePreviewTag, state);
    context.findKepwareTagByPath = async () => { throw new Error('unavailable'); };
    await assert.doesNotReject(context.setAlarmNavigationView('all'));
    assert.equal(context.selectedRuntimeTag, state);
});

test('All Tags restores the full live root before best-effort navigation, even after a failed initial load', async () => {
    const source = fs.readFileSync('static/app.js', 'utf8');
    // Exercise startup order: the initial runtime click must see initialized loader state.
    assert.ok(source.indexOf('let kepwareChannelsPromise = null;') < source.indexOf("document.querySelector('.view-tab[data-view=\"runtime\"]').click();", source.indexOf('// Alarm authoring')));
    for (const from of ['list', 'alarm']) {
        const state = { path: 'LP2/MIX/FML/DryMix' };
        const tree = { nodes: [], querySelector() { return this.nodes[0]; } };
        const host = { appendChild(node) { this.tree = node; } };
        let completeRoot;
        let loads = 0;
        const navigation = [];
        const context = vm.createContext({ selectedRuntimeTag: state, selectedMp3: 'sound.mp3', activePreviewTag: state,
            kepwareLoaded: true, kepwareChannelsPromise: null, kepwareTree: tree, runtimeKepwareTreeHost: host,
            document: { querySelectorAll: () => [], querySelector: () => ({ classList: { contains: () => true } }),
                getElementById: () => ({ classList: { toggle() {} } }) },
            syncAlarmNavigationSelection() {},
            fetchKepwareChannels() {
                loads++;
                return new Promise(resolve => { completeRoot = () => { tree.nodes = ['LP2', 'OtherChannel']; resolve(); }; });
            },
            async findKepwareTagByPath(path) {
                assert.equal(host.tree, tree);
                assert.deepEqual(tree.nodes, ['LP2', 'OtherChannel']);
                navigation.push(path);
                if (path.endsWith('Missing')) throw new Error('missing');
            } });
        vm.runInContext(source.slice(source.indexOf('async function ensureKepwareRoot('), source.indexOf('async function fetchKepwareChannels(')), context);
        vm.runInContext(source.slice(source.indexOf('let alarmNavigationGeneration'), source.indexOf('function renderAlarmTagTree(')), context);
        await context.setAlarmNavigationView(from);
        const pending = context.setAlarmNavigationView('all');
        assert.equal(loads, 1);
        assert.deepEqual(navigation, []);
        completeRoot();
        await pending;
        assert.deepEqual(navigation, [state.path]);
        assert.deepEqual(tree.nodes, ['LP2', 'OtherChannel']);
        state.path = 'LP2/MIX/FML/Missing';
        await context.setAlarmNavigationView(from);
        await context.setAlarmNavigationView('all');
        assert.deepEqual(tree.nodes, ['LP2', 'OtherChannel']);
        assert.equal(loads, 1);
        assert.equal(context.selectedRuntimeTag, state);
        assert.equal(context.activePreviewTag, state);
        assert.equal(context.selectedMp3, 'sound.mp3');
        // No selected tag must still restore an empty root.
        context.selectedRuntimeTag = null;
        tree.nodes = [];
        const emptySelection = context.setAlarmNavigationView('all');
        completeRoot();
        await emptySelection;
        assert.deepEqual(tree.nodes, ['LP2', 'OtherChannel']);
        assert.equal(loads, 2);
    }
});
