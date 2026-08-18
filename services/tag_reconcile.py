from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter
from typing import Awaitable, Callable, Iterable

from asyncua import Client
from asyncua.ua import NodeClass

from services.tag_registry import TagRegistry, TagSnapshot


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
    success: bool = True
    subscriber_synchronized: bool = False

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

    def __init__(self, opc_url: str, client_factory: Callable[..., Client] = Client) -> None:
        self._opc_url = opc_url
        self._client_factory = client_factory

    async def _browse_node(self, node, path: str, tags: list[TagSnapshot]) -> None:
        node_class = await node.read_node_class()
        if node_class == NodeClass.Variable and is_allowed_path(path):
            data_type = (await node.read_data_type_as_variant_type()).name
            tags.append(TagSnapshot(path=path, node_id=node.nodeid.to_string(), data_type=data_type))

        children = await node.get_children()
        for child in children:
            display_name = await child.read_display_name()
            child_name = display_name.Text
            if not is_allowed_name(child_name):
                continue
            child_path = f"{path}/{child_name}" if path else child_name
            await self._browse_node(child, child_path, tags)

    async def discover(self) -> tuple[TagSnapshot, ...]:
        tags: list[TagSnapshot] = []
        try:
            async with self._client_factory(url=self._opc_url) as client:
                await self._browse_node(client.nodes.objects, "", tags)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise OpcDiscoveryError("OPC discovery failed; the registry was not changed.") from exc
        return validate_snapshot(tags)


class TagReconcileService:
    def __init__(self, discoverer: OpcTagDiscoverer, registry: TagRegistry) -> None:
        self._discoverer = discoverer
        self._registry = registry
        self._lock = Lock()

    async def reconcile(self) -> ReconcileResult:
        if not self._lock.acquire(blocking=False):
            raise ReconcileInProgressError("A Full Reconcile is already running.")
        try:
            started = perf_counter()
            run_id = self._registry.start_run()
            snapshot = await self._discoverer.discover()
            applied = self._registry.apply_snapshot(run_id, snapshot)
            return ReconcileResult(
                total_discovered=len(snapshot),
                added=applied.added,
                changed=applied.changed,
                unchanged=applied.unchanged,
                deactivated=applied.deactivated,
                run_id=run_id,
                duration=round(perf_counter() - started, 3),
            )
        finally:
            self._lock.release()
