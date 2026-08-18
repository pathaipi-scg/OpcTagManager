import asyncio
from unittest.mock import AsyncMock

import pytest
from asyncua.ua import NodeClass

from services.runtime_supervisor import HistorianSupervisor
from services.tag_fast_sync import (
    ExactOpcTagResolver,
    FastSyncError,
    OpcTagNotVisibleError,
    TagFastSyncService,
)
from services.tag_registry import FastTagApplyResult, TagSnapshot


class NodeId:
    def __init__(self, value):
        self.value = value

    def to_string(self):
        return self.value


class Node:
    def __init__(self, name, children=None, node_id=None, data_type="Boolean", visible_after=0):
        self.name = name
        self.children = children or []
        self.nodeid = NodeId(node_id or f"ns=2;s={name}")
        self.data_type = data_type
        self.visible_after = visible_after
        self.calls = 0

    async def get_children(self):
        self.calls += 1
        return self.children if self.calls > self.visible_after else []

    async def read_display_name(self):
        return type("DisplayName", (), {"Text": self.name})()

    async def read_node_class(self):
        return NodeClass.Variable

    async def read_data_type_as_variant_type(self):
        return type("VariantType", (), {"name": self.data_type})()


class Client:
    def __init__(self, root):
        self.nodes = type("Nodes", (), {"objects": root})()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def tree(visible_after=0):
    tag = Node("Tag", node_id="ns=2;s=Line.Device.Group.Tag", data_type="Float")
    group = Node("Group", [tag], visible_after=visible_after)
    device = Node("Device", [group])
    channel = Node("Line", [device])
    return Node("Objects", [channel]), tag, group


def test_exact_path_resolution_reads_node_id_and_type_without_full_browse():
    root, tag, _group = tree()
    resolver = ExactOpcTagResolver("configured", 2, 0, lambda **_kwargs: Client(root))
    snapshot, attempts = asyncio.run(resolver.resolve("Line/Device/Group/Tag"))
    assert snapshot == TagSnapshot("Line/Device/Group/Tag", tag.nodeid.to_string(), "Float")
    assert attempts == 1


def test_eventual_visibility_retries_bounded_exact_path_then_succeeds():
    root, _tag, group = tree(visible_after=2)
    sleep = AsyncMock()
    resolver = ExactOpcTagResolver("configured", 4, 0.25, lambda **_kwargs: Client(root), sleep=sleep)
    snapshot, attempts = asyncio.run(resolver.resolve("Line/Device/Group/Tag"))
    assert snapshot.path == "Line/Device/Group/Tag"
    assert attempts == 3
    assert sleep.await_count == 2
    assert group.calls == 3


def test_visibility_timeout_is_bounded_and_requires_no_destructive_compensation():
    root, _tag, group = tree(visible_after=20)
    sleep = AsyncMock()
    resolver = ExactOpcTagResolver("configured", 3, 0.1, lambda **_kwargs: Client(root), sleep=sleep)
    with pytest.raises(OpcTagNotVisibleError, match="3 attempts"):
        asyncio.run(resolver.resolve("Line/Device/Group/Tag"))
    assert group.calls == 3
    assert sleep.await_count == 2


class Registry:
    def __init__(self):
        self.snapshots = []

    def sync_tag(self, snapshot):
        self.snapshots.append(snapshot)
        return FastTagApplyResult(tag_id=9, state="added", run_id=4)


class Resolver:
    async def resolve(self, path):
        return TagSnapshot(path, "node", "Boolean"), 2


def test_success_notifies_disabled_supervisor_as_pending_without_starting_worker():
    supervisor = HistorianSupervisor(False)
    registry = Registry()
    service = TagFastSyncService(Resolver(), registry, supervisor.notify_registry_changed)
    result = asyncio.run(service.sync("Line/Device/Tag"))
    status = supervisor.status()
    assert result.historian_rebuild_requested is False
    assert status["registry_generation"] == 1
    assert status["rebuild_pending"] is True
    assert status["worker_state"] == "disabled"
    assert registry.snapshots[0].path == "Line/Device/Tag"


def test_resolution_failure_does_not_touch_registry_or_notify_generation():
    class FailedResolver:
        async def resolve(self, _path):
            raise FastSyncError("not visible")

    registry = Registry()
    notifications = []
    service = TagFastSyncService(FailedResolver(), registry, notifications.append)
    with pytest.raises(FastSyncError):
        asyncio.run(service.sync("Line/Device/Tag"))
    assert registry.snapshots == []
    assert notifications == []
