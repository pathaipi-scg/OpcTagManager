from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Callable

from asyncua import Client
from asyncua.ua import NodeClass

from services.tag_reconcile import validate_snapshot
from services.tag_registry import TagRegistry, TagSnapshot


class FastSyncError(RuntimeError):
    """An exact created Tag could not be synchronized safely."""


class OpcTagNotVisibleError(FastSyncError):
    """The exact Tag path is not visible through OPC within the bounded window."""


@dataclass(frozen=True, slots=True)
class FastSyncResult:
    path: str
    node_id: str
    data_type: str | None
    tag_id: int
    registry_state: str
    run_id: int
    attempts: int
    duration: float
    historian_rebuild_requested: bool

    def to_dict(self) -> dict:
        return asdict(self)


class ExactOpcTagResolver:
    def __init__(
        self,
        opc_url: str,
        attempts: int,
        retry_delay: float,
        client_factory: Callable[..., Client] = Client,
        sleep=asyncio.sleep,
    ) -> None:
        self._opc_url = opc_url
        self._attempts = attempts
        self._retry_delay = retry_delay
        self._client_factory = client_factory
        self._sleep = sleep

    @staticmethod
    async def _exact_child(parent, component: str):
        matches = []
        for child in await parent.get_children():
            display_name = await child.read_display_name()
            if display_name.Text == component:
                matches.append(child)
        if len(matches) > 1:
            raise FastSyncError(f"OPC path component {component!r} is ambiguous.")
        return matches[0] if matches else None

    async def resolve(self, path: str) -> tuple[TagSnapshot, int]:
        components = path.split("/")
        if any(not component for component in components):
            raise FastSyncError("Fast Sync received an invalid Kepware Path.")
        last_error = None
        try:
            async with self._client_factory(url=self._opc_url) as client:
                for attempt in range(1, self._attempts + 1):
                    try:
                        node = client.nodes.objects
                        for component in components:
                            node = await self._exact_child(node, component)
                            if node is None:
                                raise OpcTagNotVisibleError(
                                    f"Created Kepware Tag {path!r} is not visible through OPC yet."
                                )
                        if await node.read_node_class() != NodeClass.Variable:
                            raise FastSyncError(f"Resolved OPC path {path!r} is not a Variable.")
                        data_type = (await node.read_data_type_as_variant_type()).name
                        snapshot = validate_snapshot([
                            TagSnapshot(path=path, node_id=node.nodeid.to_string(), data_type=data_type)
                        ])[0]
                        return snapshot, attempt
                    except OpcTagNotVisibleError as exc:
                        last_error = exc
                        if attempt < self._attempts:
                            await self._sleep(self._retry_delay)
        except FastSyncError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise FastSyncError("OPC exact-Tag resolution failed.") from exc
        raise OpcTagNotVisibleError(
            f"Created Kepware Tag {path!r} did not become visible through OPC after "
            f"{self._attempts} attempts. Full Reconcile remains available."
        ) from last_error


class TagFastSyncService:
    def __init__(self, resolver: ExactOpcTagResolver, registry: TagRegistry, on_registry_changed=None) -> None:
        self._resolver = resolver
        self._registry = registry
        self._on_registry_changed = on_registry_changed

    async def sync(self, path: str) -> FastSyncResult:
        started = perf_counter()
        snapshot, attempts = await self._resolver.resolve(path)
        applied = self._registry.sync_tag(snapshot)
        rebuild_requested = False
        if self._on_registry_changed is not None:
            try:
                rebuild_requested = bool(self._on_registry_changed(applied.run_id))
            except Exception:
                rebuild_requested = False
        return FastSyncResult(
            path=snapshot.path,
            node_id=snapshot.node_id,
            data_type=snapshot.data_type,
            tag_id=applied.tag_id,
            registry_state=applied.state,
            run_id=applied.run_id,
            attempts=attempts,
            duration=round(perf_counter() - started, 3),
            historian_rebuild_requested=rebuild_requested,
        )
