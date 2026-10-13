"""Prefix scope regressions: mocked OPC/HTTP and in-memory SQL only."""
import asyncio
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from asyncua.ua import NodeClass
from dotenv import dotenv_values
import pytest

from services.line_scope import LineScope, normalized_line_name
from services.tag_registry import TagRegistry, TagRegistryError
from services.tag_reconcile import OpcTagDiscoverer
from services.tag_fast_sync import TagFastSyncService, FastSyncError
from services.kepware_config_api import KepwareConfigApi, KepwareConfigSettings, KepwareConfigError
from workers.historian_worker import _load_active_tags_from_connection
from test_line_isolation import Database, tag
from test_tag_reconcile import FakeNode, FakeClient


@pytest.mark.parametrize('line,allowed,rejected', [
    ('NR', ['NR_AB', 'NR_UA', 'NR_MODBUS'], ['SB11', 'SB12', 'XNR']),
    ('SB11', ['SB11', 'SB11_1', 'SB11S7'], ['SB110', 'SB111', 'SB110_UA', 'SB12']),
    ('SB12', ['SB12', 'SB12_1', 'SB12S7'], ['SB120', 'SB120_UA', 'SB11']),
    ('CELL9', ['CELL9', 'CELL9_PLC', 'CELL9S7'], ['CELL90', 'CELL99', 'CELL8']),
])
def test_prefix_matching_normalization_and_boundaries(line, allowed, rejected):
    scope = LineScope(normalized_line_name({'LINE_NAME': f' {line.lower()} '}))
    for channel in allowed:
        assert scope.allows_channel(channel)
        assert scope.allows_channel(channel.lower())
        assert scope.allows_tag(tag(channel).path, tag(channel).node_id)
    for channel in rejected + ['SYSTEM', 'system', 'Server', '_Internal', '']:
        assert not scope.allows_channel(channel)
    assert not scope.allows_tag(tag(allowed[0]).path, tag(rejected[0]).node_id)


def test_explicit_patterns_override_prefix_and_keep_existing_wildcard_rules():
    scope = LineScope('SB11', ('Shared', 'SB11*'))
    assert scope.allows_channel('shared')
    assert scope.allows_channel('SB110')  # explicit wildcard compatibility
    assert not LineScope('NR', ('NR_UA',)).allows_channel('NR_MODBUS')
    assert not LineScope('SYSTEM').allows_channel('SYSTEM')
    assert not LineScope('SYS').allows_channel('system')
    assert not LineScope('NR', ('*',)).allows_channel('SYSTEM')
    with pytest.raises(ValueError, match='requires LINE_NAME'):
        LineScope('', ('NR*',))
    assert LineScope().allows_channel('Anything')


@pytest.mark.parametrize('patterns', [None, '', '  ', ', ,'])
def test_real_configuration_accepts_missing_or_blank_patterns(patterns):
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in dotenv_values(root / 'config/.env.example').items() if v is not None}
    env.pop('KEPWARE_CHANNEL_PATTERNS', None)
    env.update(LINE_NAME=' nr ')
    if patterns is not None:
        env['KEPWARE_CHANNEL_PATTERNS'] = patterns
    with patch.dict(os.environ, env, clear=True), patch('dotenv.load_dotenv'):
        config = runpy.run_path(str(root / 'config/config.py'))
    assert config['LINE_NAME'] == 'NR'
    assert config['LINE_SCOPE'].channel_patterns == ()
    assert config['LINE_SCOPE'].allows_channel('nr_ua')


@pytest.mark.parametrize('line,own,foreign', [('NR', 'NR_UA', 'SB12'), ('SB11', 'SB11S7', 'SB110'), ('SB12', 'SB12_1', 'SB120')])
def test_mocked_browse_prunes_foreign_channels_in_both_traversals(line, own, foreign):
    root = FakeNode('Objects', children=[
        FakeNode(own, children=[FakeNode('Device', children=[FakeNode('Tag', NodeClass.Variable, tag(own).node_id)])]),
        FakeNode(foreign, fail='children'), FakeNode('SYSTEM', fail='children'),
    ])
    discoverer = OpcTagDiscoverer('offline', client_factory=lambda **kw: FakeClient(root), scope=LineScope(line))
    assert [t.path for t in asyncio.run(discoverer.discover())] == [tag(own).path]
    # Metadata traversal must prune before requesting the foreign node.
    def description(name, kind, node):
        return SimpleNamespace(DisplayName=SimpleNamespace(Text=name), NodeClass=kind, NodeId=node)
    root = SimpleNamespace(get_children_descriptions=AsyncMock(return_value=[
        description(own, NodeClass.Object, 'own'), description(foreign, NodeClass.Object, 'foreign'),
        description('SYSTEM', NodeClass.Object, 'system')]))
    own_node = SimpleNamespace(get_children_descriptions=AsyncMock(return_value=[description('Tag', NodeClass.Variable, 'leaf')]))
    leaf = object()
    client = SimpleNamespace(get_node=Mock(side_effect=lambda key: {'own': own_node, 'leaf': leaf}[key]))
    variables = []
    asyncio.run(discoverer._browse_node(client, root, '', variables))
    assert variables == [(leaf, own + '/Tag')]


@pytest.mark.parametrize('line,own,foreign', [('NR', 'NR_UA', 'SB12'), ('SB11', 'SB11S7', 'SB110'), ('SB12', 'SB12_1', 'SB120')])
def test_fast_sync_registry_and_historian_share_prefix_scope(line, own, foreign):
    db = Database()
    registry = TagRegistry(db.connection, LineScope(line))
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=(tag(own), 1)))
    fast = TagFastSyncService(resolver, registry)
    with pytest.raises(FastSyncError, match='outside'):
        asyncio.run(fast.sync(tag(foreign).path))
    resolver.resolve.assert_not_called()
    first = asyncio.run(fast.sync(tag(own).path))
    run = registry.start_run()
    assert registry.apply_snapshot(run, [tag(own)]).unchanged == 1
    assert db.db.execute('SELECT TagId,LineName FROM TagMaster').fetchall() == [(first.tag_id, line)]
    with pytest.raises(TagRegistryError, match='out-of-scope'):
        registry.apply_snapshot(registry.start_run(), [tag(foreign)])
    assert [t['TagId'] for t in _load_active_tags_from_connection(db, LineScope(line))] == [first.tag_id]
    db.db.execute('UPDATE TagMaster SET NodeId=? WHERE TagId=?', (tag(foreign).node_id, first.tag_id))
    assert _load_active_tags_from_connection(db, LineScope(line)) == []


def test_kepware_config_access_uses_prefix_scope_without_network_calls():
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = [{'common.ALLTYPES_NAME': name} for name in ['SB11', 'SB11S7', 'SB110', 'SB12', 'SYSTEM']]
    api = KepwareConfigApi(KepwareConfigSettings('http', 'offline', 1, '', '', False, 1, 1, True), session, LineScope('SB11'))
    assert [r['name'] for r in api.get_channels()] == ['SB11', 'SB11S7']
    assert [r['name'] for r in api.get_channels_uncached()] == ['SB11', 'SB11S7']
    for operation in [lambda: api.get_devices('SB110'), lambda: api.create_channel('SB12', 'Memory Based')]:
        with pytest.raises(KepwareConfigError):
            operation()
    assert session.get.call_count == 2
    session.post.assert_not_called()
