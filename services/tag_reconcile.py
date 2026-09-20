from __future__ import annotations

from services.startup_trace import trace_step, logger as trace_logger
import asyncio
import logging
from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter
from typing import Awaitable, Callable, Iterable

from asyncua import Client, ua
from asyncua.ua import NodeClass

from services.tag_registry import TagRegistry, TagSnapshot
from services.line_scope import LineScope


SKIP_ROOTS = frozenset({"LP_UA", "_Statistics", "_System", "_Scheduler", "_LocalHistorian"})


class OpcDiscoveryError(RuntimeError):
    """The OPC tree could not be proven complete."""


class SnapshotValidationError(RuntimeError):
    """The discovered snapshot is not safe to apply."""


class ReconcileInProgressError(RuntimeError):
    """A full reconcile is already running in this process."""


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    total_discovered: int
    added: int
    changed: int
    unchanged: int
    deactivated: int
    run_id: int
    duration: float
    reactivated: int = 0
    success: bool = True
    subscriber_synchronized: bool = False
    subscriber_rebuild_requested: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def is_allowed_name(name: str) -> bool:
    return bool(name) and not name.startswith("_") and name not in SKIP_ROOTS


def is_allowed_path(path: str) -> bool:
    if not path or path.startswith("_") or "/_" in path:
        return False
    return not path.split("/")[-1].startswith("_")


def validate_snapshot(tags: Iterable[TagSnapshot]) -> tuple[TagSnapshot, ...]:
    ordered = tuple(sorted(tags, key=lambda item: item.path))
    if not ordered:
        raise SnapshotValidationError("OPC discovery returned no usable tags; the registry was not changed.")
    paths: set[str] = set()
    for tag in ordered:
        if not is_allowed_path(tag.path):
            raise SnapshotValidationError(f"Filtered path reached snapshot validation: {tag.path!r}.")
        if not tag.node_id:
            raise SnapshotValidationError(f"OPC Tag {tag.path!r} has no NodeId.")
        if tag.path in paths:
            raise SnapshotValidationError(f"Duplicate OPC path: {tag.path!r}.")
        paths.add(tag.path)
    return ordered


class OpcTagDiscoverer:
    """Strict OPC traversal that returns a complete in-memory snapshot or fails."""

    def __init__(self, opc_url: str, client_factory: Callable[..., Client] = Client,
                 excluded_paths: Iterable[str] = (), request_timeout: float = 30.0,
                 scope: LineScope = LineScope()) -> None:
        self._opc_url = opc_url
        self._client_factory = client_factory
        self._excluded_paths = frozenset(excluded_paths)
        self._request_timeout = request_timeout
        self.scope = scope
        self.matched_channels = set()

    async def _browse_node_legacy(self, node, path: str, tags: list[TagSnapshot]) -> None:
        node_class = await node.read_node_class()
        if (node_class == NodeClass.Variable and is_allowed_path(path)
                and path not in self._excluded_paths):
            data_type = (await node.read_data_type_as_variant_type()).name
            tags.append(TagSnapshot(path=path, node_id=node.nodeid.to_string(), data_type=data_type))

        children = await node.get_children()
        for child in children:
            display_name = await child.read_display_name()
            child_name = display_name.Text
            if not is_allowed_name(child_name):
                continue
            child_path = f"{path}/{child_name}" if path else child_name
            if not self.scope.allows_path(child_path):
                continue
            if not path:
                self.matched_channels.add(child_name)
            await self._browse_node_legacy(child, child_path, tags)

    async def _browse_node(self, client, node, path: str, variables: list[tuple[object, str]]) -> None:
        """Browse using ReferenceDescription metadata instead of three reads per OPC node."""
        descriptions = await node.get_children_descriptions()
        for description in descriptions:
            child_name = description.DisplayName.Text
            if not is_allowed_name(child_name):
                continue
            child_path = f"{path}/{child_name}" if path else child_name
            if not self.scope.allows_path(child_path):
                continue
            if not path:
                self.matched_channels.add(child_name)
            child = client.get_node(description.NodeId)
            if (description.NodeClass == NodeClass.Variable and is_allowed_path(child_path)
                    and child_path not in self._excluded_paths):
                variables.append((child, child_path))
            # Kepware Tag variables are leaves. Browsing every variable creates thousands
            # of unnecessary service calls and can exhaust the OPC session timeout.
            if description.NodeClass != NodeClass.Variable:
                await self._browse_node(client, child, child_path, variables)

    @staticmethod
    def _data_type_name(data_value) -> str:
        data_value.StatusCode.check()
        node_id = data_value.Value.Value
        if node_id.NamespaceIndex == 0:
            try:
                return ua.VariantType(node_id.Identifier).name
            except ValueError:
                pass
        return node_id.to_string()

    async def _snapshots(self, client, variables: list[tuple[object, str]]) -> list[TagSnapshot]:
        tags: list[TagSnapshot] = []
        batch_size = 500
        for offset in range(0, len(variables), batch_size):
            batch = variables[offset:offset + batch_size]
            values = await client.read_attributes(
                [node for node, _path in batch], ua.AttributeIds.DataType
            )
            tags.extend(
                TagSnapshot(path=path, node_id=node.nodeid.to_string(),
                            data_type=self._data_type_name(value))
                for (node, path), value in zip(batch, values, strict=True)
            )
        return tags

    async def discover(self) -> tuple[TagSnapshot, ...]:
        self.matched_channels.clear()
        tags: list[TagSnapshot] = []
        try:
            # A full Kepware hierarchy is much larger than an individual runtime read.
            # asyncua's short default request timeout can expire midway through a valid
            # browse even while the endpoint and existing subscriptions remain healthy.
            connect_started = perf_counter()
            trace_logger.info("OPC CONNECT START")
            async with self._client_factory(url=self._opc_url, timeout=self._request_timeout) as client:
                trace_logger.info("OPC CONNECT END elapsed=%.3fs", perf_counter() - connect_started)
                if hasattr(client.nodes.objects, "get_children_descriptions") and hasattr(client, "read_attributes"):
                    variables: list[tuple[object, str]] = []
                    with trace_step("OPC BROWSE"):
                        await self._browse_node(client, client.nodes.objects, "", variables)
                    with trace_step("OPC METADATA"):
                        tags = await self._snapshots(client, variables)
                else:  # Small test doubles and older compatible clients.
                    with trace_step("OPC LEGACY BROWSE"):
                        await self._browse_node_legacy(client.nodes.objects, "", tags)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise OpcDiscoveryError("OPC discovery failed; the registry was not changed.") from exc
        snapshot = validate_snapshot(tags)
        logging.getLogger('opctagmanager').info('LINE_NAME=%s MATCHED_CHANNELS=%s REGISTRY_DISCOVERED=%s',
            self.scope.line_name or '(legacy)', ','.join(sorted(self.matched_channels)), len(snapshot))
        return snapshot


class TagReconcileService:
    def __init__(self, discoverer: OpcTagDiscoverer, registry: TagRegistry, on_registry_changed=None) -> None:
        self._discoverer = discoverer
        self._registry = registry
        self._on_registry_changed = on_registry_changed
        self._lock = Lock()

    async def reconcile(self, notify_subscriber: bool = True) -> ReconcileResult:
        if not self._lock.acquire(blocking=False):
            raise ReconcileInProgressError("A Full Reconcile is already running.")
        try:
            started = perf_counter()
            with trace_step("RECONCILIATION RUN CREATE"):
                run_id = self._registry.start_run()
            with trace_step("OPC DISCOVERY"):
                snapshot = await self._discoverer.discover()
            with trace_step("REGISTRY APPLY"):
                applied = self._registry.apply_snapshot(run_id, snapshot)
            rebuild_requested = False
            registry_changed = bool(
                applied.added or applied.changed or applied.reactivated or applied.deactivated
            )
            if notify_subscriber and registry_changed and self._on_registry_changed is not None:
                try:
                    rebuild_requested = bool(self._on_registry_changed(run_id))
                except Exception:
                    rebuild_requested = False
            return ReconcileResult(
                total_discovered=len(snapshot),
                added=applied.added,
                changed=applied.changed,
                unchanged=applied.unchanged,
                deactivated=applied.deactivated,
                reactivated=applied.reactivated,
                run_id=run_id,
                duration=round(perf_counter() - started, 3),
                subscriber_rebuild_requested=rebuild_requested,
            )
        finally:
            self._lock.release()
