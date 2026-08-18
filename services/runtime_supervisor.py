from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from workers.historian_worker import STATUS_PREFIX


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HistorianSupervisor:
    """Supervises only the known OpcTagManager historian worker module."""

    def __init__(self, enabled: bool, process_factory=subprocess.Popen, restart_delay: float = 10.0) -> None:
        self.enabled = enabled
        self._process_factory = process_factory
        self._restart_delay = restart_delay
        self._process = None
        self._monitor_thread = None
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._intentional_stop = False
        self._status = {
            "supervisor_enabled": enabled,
            "historian_ownership": "legacy_opc_service",
            "worker_state": "stopped" if enabled else "disabled",
            "worker_pid": None,
            "restart_count": 0,
            "last_start_time": None,
            "last_stop_time": None,
            "last_error": None,
            "registry_generation": 0,
            "rebuild_pending": False,
            "active_tag_count": None,
            "subscribed_tag_count": None,
            "opc_state": "unknown",
            "influx_state": "unknown",
            "last_write_time": None,
        }

    def status(self) -> dict:
        with self._lock:
            return deepcopy(self._status)

    def _spawn(self) -> bool:
        project_root = Path(__file__).resolve().parent.parent
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = self._process_factory(
            [sys.executable, "-m", "workers.historian_worker"],
            cwd=str(project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self._process = process
        self._status.update(
            worker_state="starting",
            worker_pid=process.pid,
            last_start_time=utc_now(),
            last_stop_time=None,
            last_error=None,
            opc_state="unknown",
            influx_state="unknown",
        )
        monitor = threading.Thread(target=self._monitor, args=(process,), daemon=True)
        self._monitor_thread = monitor
        monitor.start()
        return True

    def start(self) -> bool:
        with self._lock:
            if not self.enabled or self._shutdown.is_set():
                self._status["worker_state"] = "disabled" if not self.enabled else "stopped"
                return False
            if self._process is not None and self._process.poll() is None:
                return False
            self._intentional_stop = False
            return self._spawn()

    def _apply_event(self, message: dict) -> None:
        event = message.get("event")
        if event == "worker_started":
            self._status["worker_state"] = "running"
        elif event == "tag_snapshot":
            self._status["active_tag_count"] = message.get("active_tag_count")
        elif event == "opc_state":
            self._status["opc_state"] = message.get("state", "unknown")
            if message.get("error"):
                self._status["last_error"] = message["error"]
        elif event == "subscriptions_ready":
            self._status["worker_state"] = "running"
            self._status["subscribed_tag_count"] = message.get("subscribed_tag_count")
            self._status["rebuild_pending"] = False
        elif event == "rebuild_started":
            self._status["worker_state"] = "rebuilding"
        elif event == "influx_write":
            if message.get("success"):
                self._status["influx_state"] = "last_write_ok"
                self._status["last_write_time"] = message.get("time")
            else:
                self._status["influx_state"] = "error"
                self._status["last_error"] = message.get("error")
        elif event == "subscription_error":
            self._status["last_error"] = message.get("error")

    def _monitor(self, process) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                if not line.startswith(STATUS_PREFIX):
                    continue
                try:
                    message = json.loads(line[len(STATUS_PREFIX):])
                except json.JSONDecodeError:
                    continue
                with self._lock:
                    self._apply_event(message)
        return_code = process.wait()
        with self._lock:
            if process is not self._process:
                return
            self._status.update(worker_pid=None, last_stop_time=utc_now(), opc_state="unknown")
            should_restart = self.enabled and not self._intentional_stop and not self._shutdown.is_set()
            if should_restart:
                self._status["worker_state"] = "exited"
                self._status["last_error"] = f"Historian worker exited with code {return_code}."
            else:
                self._status["worker_state"] = "stopped" if self.enabled else "disabled"
        if should_restart and not self._shutdown.wait(self._restart_delay):
            with self._lock:
                if process is self._process and not self._intentional_stop:
                    self._status["restart_count"] += 1
                    self._spawn()

    def _send(self, command: str) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps({"command": command}) + "\n")
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError) as exc:
            self._status["last_error"] = f"Worker command failed: {type(exc).__name__}"
            return False

    def notify_registry_changed(self, _run_id: int | None = None) -> bool:
        with self._lock:
            self._status["registry_generation"] += 1
            self._status["rebuild_pending"] = True
            if not self.enabled:
                return False
            requested = self._send("rebuild")
            if requested:
                self._status["worker_state"] = "rebuilding"
            return requested

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._intentional_stop = True
            process = self._process
            if process is None or process.poll() is not None:
                self._status["worker_state"] = "stopped" if self.enabled else "disabled"
                self._status["worker_pid"] = None
                return
            self._status["worker_state"] = "stopping"
            self._send("stop")
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=timeout)

    def shutdown(self) -> None:
        self._shutdown.set()
        self.stop()
