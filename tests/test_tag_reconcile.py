import copy
import asyncio
from pathlib import Path

import pytest
from asyncua.ua import NodeClass

from services.tag_reconcile import (
    OpcDiscoveryError,
    OpcTagDiscoverer,
    SKIP_ROOTS,
    TagReconcileService,
    validate_snapshot,
)
from services.tag_registry import TagRegistry, TagRegistryError, TagSnapshot


class FakeNode:
    def __init__(self, name, node_class=NodeClass.Object, node_id=None, data_type="Int16", children=None, fail=None):
        self.name = name
        self.node_class = node_class
        self.nodeid = FakeNodeId(node_id or f"ns=2;s={name}")
        self.data_type = data_type
        self.children = children or []
        self.fail = fail

    async def read_node_class(self):
        if self.fail == "class":
            raise RuntimeError("class failed")
        return self.node_class

    async def read_data_type_as_variant_type(self):
        if self.fail == "datatype":
            raise RuntimeError("datatype failed")
        return type("VariantType", (), {"name": self.data_type})()

    async def get_children(self):
        if self.fail == "children":
            raise RuntimeError("children failed")
        return self.children

    async def read_display_name(self):
        if self.fail == "name":
            raise RuntimeError("name failed")
        return type("DisplayName", (), {"Text": self.name})()


class FakeNodeId:
    def __init__(self, value):
        self.value = value

    def to_string(self):
        return self.value


class FakeClient:
    def __init__(self, root=None, enter_error=None):
        self.nodes = type("Nodes", (), {"objects": root})()
        self.enter_error = enter_error

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    async def __aexit__(self, *_args):
        return None


class MemoryDatabase:
    def __init__(self, tags=None):
        self.tags = copy.deepcopy(tags or {})
        self.levels = []
        self.runs = {}
        self.next_tag_id = max((row["TagId"] for row in self.tags.values()), default=0) + 1
        self.next_run_id = 1

    def connection(self, fail_on=None):
        return MemoryConnection(self, fail_on)


class MemoryConnection:
    def __init__(self, database, fail_on):
        self.database = database
        self.local = copy.deepcopy({
            "tags": database.tags,
            "levels": database.levels,
            "runs": database.runs,
            "next_tag_id": database.next_tag_id,
            "next_run_id": database.next_run_id,
        })
        self.fail_on = fail_on
        self.rolled_back = False

    def cursor(self):
        return MemoryCursor(self)

    def commit(self):
        self.database.tags = self.local["tags"]
        self.database.levels = self.local["levels"]
        self.database.runs = self.local["runs"]
        self.database.next_tag_id = self.local["next_tag_id"]
        self.database.next_run_id = self.local["next_run_id"]

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class MemoryCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []
        self.rowcount = 0

    def execute(self, query, *params):
        normalized = " ".join(query.split()).upper()
        if self.connection.fail_on and self.connection.fail_on in normalized:
            raise RuntimeError("injected SQL failure")
        state = self.connection.local
        tags = state["tags"]

        if normalized.startswith("INSERT INTO BROWSERRUN"):
            run_id = state["next_run_id"]
            state["next_run_id"] += 1
            state["runs"][run_id] = {"StartTime": True, "EndTime": None, "TotalTags": None}
            self.result = [(run_id,)]
        elif normalized.startswith("SELECT TAGID, PATH, NODEID"):
            self.result = [
                (row["TagId"], path, row["NodeId"], row["DataType"], row["IsActive"])
                for path, row in tags.items()
            ]
        elif normalized.startswith("SELECT TAGID, NODEID"):
            row = tags.get(params[0])
            self.result = [] if row is None else [(row["TagId"], row["NodeId"], row["DataType"], row["IsActive"])]
        elif normalized.startswith("INSERT INTO TAGMASTER"):
            node_id, path, data_type, run_id = params
            tag_id = state["next_tag_id"]
            state["next_tag_id"] += 1
            tags[path] = {"TagId": tag_id, "NodeId": node_id, "DataType": data_type,
                          "IsActive": True, "LastBrowseRunId": run_id}
            self.result = [(tag_id,)]
        elif normalized.startswith("UPDATE TAGMASTER SET NODEID"):
            node_id, data_type, run_id, tag_id = params
            row = next(row for row in tags.values() if row["TagId"] == tag_id)
            row.update(NodeId=node_id, DataType=data_type, IsActive=True, LastBrowseRunId=run_id)
        elif normalized.startswith("DELETE FROM TAGLEVEL"):
            state["levels"] = [level for level in state["levels"] if level[0] != params[0]]
        elif normalized.startswith("INSERT INTO TAGLEVEL"):
            state["levels"].append(tuple(params))
        elif normalized.startswith("UPDATE TAGMASTER SET ISACTIVE = 0"):
            run_id = params[0]
            for row in tags.values():
                if row["IsActive"] and row.get("LastBrowseRunId") != run_id:
                    row["IsActive"] = False
        elif normalized.startswith("UPDATE BROWSERRUN"):
            if len(params) == 1:
                total, run_id = 1, params[0]
            else:
                total, run_id = params
            state["runs"][run_id].update(EndTime=True, TotalTags=total)
        else:
            raise AssertionError(f"Unexpected SQL: {normalized}")
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


def test_successful_complete_browse_and_filter_parity():
    root = FakeNode("Objects", children=[
        FakeNode("LINE_1", children=[
            FakeNode("Device", children=[FakeNode("Tag", NodeClass.Variable, "ns=2;s=LINE_1.Device.Tag")]),
            FakeNode("_Private", children=[FakeNode("Hidden", NodeClass.Variable)]),
        ]),
        FakeNode("_Statistics", children=[FakeNode("Skipped", NodeClass.Variable)]),
        FakeNode("Server", children=[FakeNode("SYSTEM", children=[FakeNode("Live", NodeClass.Variable)])]),
    ])
    discoverer = OpcTagDiscoverer("configured-endpoint", lambda **_kwargs: FakeClient(root))
    snapshot = asyncio.run(discoverer.discover())
    assert [tag.path for tag in snapshot] == ["LINE_1/Device/Tag", "Server/SYSTEM/Live"]
    assert SKIP_ROOTS == {"LP_UA", "_Statistics", "_System", "_Scheduler", "_LocalHistorian"}


@pytest.mark.parametrize("client", [
    FakeClient(enter_error=RuntimeError("connect failed")),
    FakeClient(FakeNode("Objects", children=[FakeNode("Line", fail="children")])),
])
def test_connection_or_mid_tree_failure_rejects_partial_snapshot(client):
    discoverer = OpcTagDiscoverer("configured-endpoint", lambda **_kwargs: client)
    with pytest.raises(OpcDiscoveryError):
        asyncio.run(discoverer.discover())


def test_registry_preserves_identity_updates_metadata_levels_run_and_counts():
    database = MemoryDatabase({
        "Line/Device/Same": {"TagId": 7, "NodeId": "old", "DataType": "Int16", "IsActive": True, "LastBrowseRunId": 0},
        "Line/Device/Missing": {"TagId": 8, "NodeId": "missing", "DataType": "Bool", "IsActive": True, "LastBrowseRunId": 0},
    })
    registry = TagRegistry(database.connection)
    run_id = registry.start_run()
    result = registry.apply_snapshot(run_id, [
        TagSnapshot("Line/Device/Same", "new", "Float"),
        TagSnapshot("Line/Device/New", "new-id", "Bool"),
    ])
    assert (result.added, result.changed, result.unchanged, result.deactivated) == (1, 1, 0, 1)
    assert database.tags["Line/Device/Same"]["TagId"] == 7
    assert database.tags["Line/Device/Same"]["NodeId"] == "new"
    assert database.tags["Line/Device/Same"]["DataType"] == "Float"
    assert database.tags["Line/Device/Same"]["LastBrowseRunId"] == run_id
    assert database.tags["Line/Device/New"]["TagId"] == 9
    assert database.tags["Line/Device/Missing"]["IsActive"] is False
    same_levels = [level[1:] for level in database.levels if level[0] == 7]
    assert same_levels == [(0, "Line"), (1, "Device"), (2, "Same")]
    assert database.runs[run_id]["TotalTags"] == 2
    assert database.runs[run_id]["EndTime"] is True


def test_unchanged_and_reactivated_counts_are_deterministic():
    database = MemoryDatabase({
        "Line/A": {"TagId": 1, "NodeId": "a", "DataType": "Bool", "IsActive": True, "LastBrowseRunId": 0},
        "Line/B": {"TagId": 2, "NodeId": "b", "DataType": "Bool", "IsActive": False, "LastBrowseRunId": 0},
    })
    registry = TagRegistry(database.connection)
    run_id = registry.start_run()
    result = registry.apply_snapshot(run_id, [TagSnapshot("Line/B", "b", "Bool"), TagSnapshot("Line/A", "a", "Bool")])
    assert (result.added, result.changed, result.unchanged, result.deactivated) == (0, 1, 1, 0)


def test_sql_failure_rolls_back_all_registry_changes_and_leaves_run_incomplete():
    database = MemoryDatabase({
        "Line/Existing": {"TagId": 4, "NodeId": "old", "DataType": "Int16", "IsActive": True, "LastBrowseRunId": 0},
    })
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        return database.connection("INSERT INTO TAGLEVEL" if calls == 2 else None)

    registry = TagRegistry(factory)
    run_id = registry.start_run()
    before_tags = copy.deepcopy(database.tags)
    with pytest.raises(TagRegistryError):
        registry.apply_snapshot(run_id, [TagSnapshot("Line/Existing", "new", "Float")])
    assert database.tags == before_tags
    assert database.levels == []
    assert database.runs[run_id]["EndTime"] is None


def test_failed_browse_does_not_deactivate_or_mutate_registry():
    database = MemoryDatabase({
        "Line/Keep": {"TagId": 3, "NodeId": "keep", "DataType": "Bool", "IsActive": True, "LastBrowseRunId": 0},
    })
    before = copy.deepcopy(database.tags)
    discoverer = OpcTagDiscoverer("configured-endpoint", lambda **_kwargs: FakeClient(enter_error=RuntimeError("offline")))
    notifications = []
    service = TagReconcileService(discoverer, TagRegistry(database.connection), notifications.append)
    with pytest.raises(OpcDiscoveryError):
        asyncio.run(service.reconcile())
    assert database.tags == before
    assert database.levels == []
    assert database.runs[1]["EndTime"] is None
    assert notifications == []


def test_successful_committed_reconcile_notifies_rebuild_once():
    database = MemoryDatabase()
    root = FakeNode("Objects", children=[
        FakeNode("Line", children=[FakeNode("Tag", NodeClass.Variable, "node")])
    ])
    notifications = []
    service = TagReconcileService(
        OpcTagDiscoverer("configured-endpoint", lambda **_kwargs: FakeClient(root)),
        TagRegistry(database.connection),
        lambda run_id: notifications.append(run_id) or True,
    )
    result = asyncio.run(service.reconcile())
    assert notifications == [result.run_id]
    assert result.subscriber_rebuild_requested is True
    assert result.subscriber_synchronized is False


def test_snapshot_validation_and_source_have_no_export_or_deployment_endpoint():
    with pytest.raises(Exception, match="Duplicate OPC path"):
        validate_snapshot([TagSnapshot("Line/A", "a", "Bool"), TagSnapshot("Line/A", "b", "Bool")])
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("services/tag_reconcile.py", "services/tag_registry.py")
    )
    assert "tagmaster.json" not in sources.lower()
    assert "opc.tcp://" not in sources
    assert "10.28." not in sources and "172.28." not in sources


def test_fast_sync_insert_retry_identity_reactivation_metadata_and_level_ordering():
    database = MemoryDatabase({
        "Line/Device/Existing": {
            "TagId": 7, "NodeId": "old", "DataType": "Int16",
            "IsActive": False, "LastBrowseRunId": 0,
        },
    })
    registry = TagRegistry(database.connection)

    inserted = registry.sync_tag(TagSnapshot("Line/Device/New", "new-node", "Boolean"))
    changed = registry.sync_tag(TagSnapshot("Line/Device/Existing", "new-existing", "Float"))
    retried = registry.sync_tag(TagSnapshot("Line/Device/New", "new-node", "Boolean"))

    assert inserted.state == "added"
    assert changed.state == "changed"
    assert retried.state == "unchanged"
    assert retried.tag_id == inserted.tag_id
    assert database.tags["Line/Device/Existing"]["TagId"] == 7
    assert database.tags["Line/Device/Existing"]["NodeId"] == "new-existing"
    assert database.tags["Line/Device/Existing"]["DataType"] == "Float"
    assert database.tags["Line/Device/Existing"]["IsActive"] is True
    levels = [level[1:] for level in database.levels if level[0] == inserted.tag_id]
    assert levels == [(0, "Line"), (1, "Device"), (2, "New")]
    assert all(row["IsActive"] for row in database.tags.values())


def test_fast_sync_sql_failure_rolls_back_run_tag_and_levels_together():
    database = MemoryDatabase({
        "Line/Existing": {
            "TagId": 4, "NodeId": "old", "DataType": "Int16",
            "IsActive": True, "LastBrowseRunId": 0,
        },
    })
    connection = database.connection("INSERT INTO TAGLEVEL")
    registry = TagRegistry(lambda: connection)
    before = copy.deepcopy((database.tags, database.levels, database.runs))

    with pytest.raises(TagRegistryError):
        registry.sync_tag(TagSnapshot("Line/Existing", "new", "Float"))

    assert (database.tags, database.levels, database.runs) == before
    assert connection.rolled_back
