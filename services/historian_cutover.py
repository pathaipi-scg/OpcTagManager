from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable

from services.historian_validation import run_contract_self_check


class HistorianCutoverPreflight:
    """Read-only preparation checks; it never controls either historian process."""

    def __init__(
        self,
        connection_factory: Callable[[], object],
        supervisor_status: Callable[[], dict],
        contract_config: dict,
        legacy_poller_launcher: str,
    ) -> None:
        self.connection_factory = connection_factory
        self.supervisor_status = supervisor_status
        self.contract_config = contract_config
        self.legacy_poller_launcher = legacy_poller_launcher

    @staticmethod
    def _check(ok: bool, message: str, severity: str = "required") -> dict:
        return {"ok": bool(ok), "severity": severity, "message": message}

    def run(self) -> dict:
        runtime = self.supervisor_status()
        checks = {}
        checks["canonical_supervisor_disabled"] = self._check(
            not runtime["supervisor_enabled"],
            "Canonical supervisor is disabled." if not runtime["supervisor_enabled"]
            else "Canonical supervisor is enabled; preparation requires it to remain disabled.",
        )

        required = ("opc_url", "sql_server", "sql_db", "influx_host", "influx_db")
        missing = [name for name in required if not self.contract_config.get(name)]
        port = self.contract_config.get("influx_port")
        configuration_valid = not missing and isinstance(port, int) and 1 <= port <= 65535
        checks["historian_configuration"] = self._check(
            configuration_valid,
            "Historian endpoint configuration is present and structurally valid."
            if configuration_valid else "Missing or invalid historian configuration: " + ", ".join(missing or ["influx_port"]),
        )

        active_count = None
        sql_error = "NoResult"
        try:
            connection = self.connection_factory()
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT COUNT(*) FROM TagMaster WHERE IsActive = 1")
                row = cursor.fetchone()
                active_count = int(row[0]) if row else None
            finally:
                connection.close()
            sql_ok = active_count is not None
        except Exception as exc:
            sql_ok = False
            sql_error = type(exc).__name__
        checks["sql_tagmaster_read"] = self._check(
            sql_ok,
            "TagMaster active count read succeeded." if sql_ok else f"TagMaster read failed: {sql_error}.",
        )

        module_ok = importlib.util.find_spec("workers.historian_worker") is not None
        checks["canonical_worker_importable"] = self._check(module_ok, "Canonical worker module is importable." if module_ok else "Canonical worker module is unavailable.")

        configured_launcher = bool(self.legacy_poller_launcher)
        launcher_exists = configured_launcher and Path(self.legacy_poller_launcher).is_file()
        checks["legacy_rollback_launcher"] = self._check(
            launcher_exists,
            "Configured legacy rollback launcher exists."
            if launcher_exists else "LEGACY_POLLER_LAUNCHER is missing or does not resolve to a file.",
        )

        parity = run_contract_self_check(self.contract_config.get("influx_db", ""))
        checks["no_write_contract_validation"] = self._check(
            parity["valid"],
            "Canonical historian contract passed NO-WRITE validation."
            if parity["valid"] else "Canonical historian contract NO-WRITE validation failed.",
        )

        pending_consistent = not (
            runtime["rebuild_pending"]
            and runtime["acknowledged_generation"] >= runtime["registry_generation"]
        )
        checks["rebuild_generation_consistent"] = self._check(
            pending_consistent,
            "Registry generation and rebuild acknowledgement are consistent."
            if pending_consistent else "Rebuild is pending despite acknowledgement of the current generation.",
        )

        manual = [
            "Verify the legacy poller by its configured launcher/command line, not by python.exe name.",
            "Record the current Influx last-write time and confirm Grafana data is flowing.",
            "Confirm no canonical historian worker process is running before cutover.",
        ]
        all_required_ok = all(item["ok"] for item in checks.values())
        return {
            "mode": "READ-ONLY",
            "production_historian_ownership": "legacy_opc_service",
            "legacy_process_state": "unknown",
            "requires_manual_verification": True,
            "ready_for_live_cutover": False,
            "ready_for_cutover_authorization": all_required_ok,
            "tagmaster_active_count": active_count,
            "runtime": runtime,
            "checks": checks,
            "contract_validation": parity,
            "manual_verification": manual,
        }
