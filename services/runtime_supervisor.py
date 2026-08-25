from __future__ import annotations

from copy import deepcopy
from collections import deque
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

    def __init__(
        self,
        enabled: bool,
        process_factory=subprocess.Popen,
        restart_delay: float = 10.0,
        production_historian_owner: str = "legacy_opc_service",
    ) -> None:
        self.enabled = enabled
        self._process_factory = process_factory
        self._restart_delay = restart_delay
        self._process = None
        self._monitor_thread = None
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._intentional_stop = False
        self._subscription_activity = deque(maxlen=200)
        self._influx_activity = deque(maxlen=200)
        self._alarm_activity = deque(maxlen=200)
        self._active_alarm_activity = {}
        self._status = {
            "supervisor_enabled": enabled,
            "historian_ownership": production_historian_owner,
            "development_historian_runtime": "canonical" if enabled else "disabled",
            "production_historian_owner": production_historian_owner,
            "worker_state": "stopped" if enabled else "disabled",
            "worker_pid": None,
            "restart_count": 0,
            "last_start_time": None,
            "last_stop_time": None,
            "last_error": None,
            "registry_generation": 0,
            "acknowledged_generation": 0,
            "rebuild_pending": False,
            "legacy_historian_ownership": (
                "expected" if production_historian_owner == "legacy_opc_service" else "not_expected"
            ),
            "legacy_historian_process_state": "unknown",
            "active_tag_count": None,
            "requested_subscription_count": None,
            "subscribed_tag_count": None,
            "failed_subscription_count": None,
            "subscription_complete": False,
            "opc_state": "unknown",
            "influx_state": "unknown",
            "last_write_time": None,
            "alarm_activity_state": "unknown",
            "configured_alarm_tags": 0,
            "active_alarms": 0,
            "alarm_events_session": 0,
            "last_alarm_event": None,
            "last_alarm_path": None,
        }

    def status(self) -> dict:
        with self._lock:
            return deepcopy(self._status)

    def activity(self) -> dict:
        with self._lock:
            return {
                "subscription": list(self._subscription_activity),
                "influx": list(self._influx_activity),
                "alarm": list(self._alarm_activity),
                "summary": {
                    "configured_alarm_tags": self._status["configured_alarm_tags"],
                    "active_alarms": self._status["active_alarms"],
                    "alarm_events_session": self._status["alarm_events_session"],
                    "last_alarm_event": self._status["last_alarm_event"],
                    "last_alarm_path": self._status["last_alarm_path"],
                    "alarm_activity_state": self._status["alarm_activity_state"],
                },
            }

    def active_alarm_activity(self) -> list[dict]:
        with self._lock:
            return deepcopy(list(self._active_alarm_activity.values()))

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
        self._active_alarm_activity.clear()
        self._process = process
        self._status.update(
            worker_state="starting",
            worker_pid=process.pid,
            last_start_time=utc_now(),
            last_stop_time=None,
            last_error=None,
            opc_state="unknown",
            influx_state="unknown",
            active_tag_count=None,
            requested_subscription_count=None,
            subscribed_tag_count=None,
            failed_subscription_count=None,
            subscription_complete=False,
            alarm_activity_state="unknown",
            active_alarms=0,
        )
        monitor = threading.Thread(target=self._monitor, args=(process,), daemon=True)
        self._monitor_thread = monitor
        monitor.start()
        if self._status["rebuild_pending"]:
            self._send("rebuild", generation=self._status["registry_generation"])
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
        if event in {
            "worker_started", "tag_snapshot", "opc_state", "subscriptions_build_started",
            "subscriptions_progress", "subscriptions_ready", "subscription_error",
            "subscriptions_connection_lost", "rebuild_started", "rebuild_ack",
        }:
            self._subscription_activity.append(deepcopy(message))
        if event == "worker_started":
            self._status["worker_state"] = "running"
        elif event == "tag_snapshot":
            self._status["active_tag_count"] = message.get("active_tag_count")
        elif event == "opc_state":
            self._status["opc_state"] = message.get("state", "unknown")
            if self._status["opc_state"] != "connected":
                self._status["requested_subscription_count"] = None
                self._status["subscribed_tag_count"] = None
                self._status["failed_subscription_count"] = None
                self._status["subscription_complete"] = False
            if message.get("error"):
                self._status["last_error"] = message["error"]
        elif event in {"subscriptions_progress", "subscriptions_ready"}:
            self._status["worker_state"] = "running"
            self._status["requested_subscription_count"] = message.get("requested_subscription_count")
            self._status["subscribed_tag_count"] = message.get("subscribed_tag_count")
            self._status["failed_subscription_count"] = message.get("failed_subscription_count")
            self._status["subscription_complete"] = bool(message.get("complete")) if event == "subscriptions_ready" else False
        elif event == "rebuild_ack":
            generation = message.get("generation")
            if isinstance(generation, int):
                if message.get("complete"):
                    self._status["acknowledged_generation"] = max(
                        self._status["acknowledged_generation"], generation
                    )
                if message.get("complete") and generation >= self._status["registry_generation"]:
                    self._status["rebuild_pending"] = False
                    self._status["worker_state"] = "running"
        elif event == "rebuild_started":
            self._status["worker_state"] = "rebuilding"
        elif event == "influx_write":
            self._influx_activity.append(deepcopy(message))
            if message.get("success"):
                self._status["influx_state"] = "last_write_ok"
                self._status["last_write_time"] = message.get("time")
            else:
                self._status["influx_state"] = "error"
                self._status["last_error"] = message.get("error")
        elif event == "subscription_error":
            self._status["last_error"] = message.get("error")
        elif event == "alarm_activity_state":
            self._status["alarm_activity_state"] = message.get("state", "unknown")
            self._active_alarm_activity.clear()
            self._status["active_alarms"] = 0
            if message.get("configured_alarm_tags") is not None:
                self._status["configured_alarm_tags"] = message["configured_alarm_tags"]
            if message.get("error"):
                self._status["last_error"] = message["error"]
        elif event == "alarm_activity":
            self._alarm_activity.append(deepcopy(message))
            self._status["alarm_activity_state"] = "ready"
            self._status["active_alarms"] = int(message.get("active_alarm_count", 0))
            alarm_id = message.get("alarm_id")
            if alarm_id is not None:
                alarm_id = int(alarm_id)
                state = message.get("state")
                if state == "ACTIVE":
                    previous = self._active_alarm_activity.get(alarm_id)
                    current = deepcopy(message)
                    if previous is None or message.get("transition"):
                        current["activated_at"] = message.get("time") if message.get("transition") else None
                        current["active_order_time"] = message.get("time")
                    else:
                        current["activated_at"] = previous.get("activated_at")
                        current["active_order_time"] = previous.get("active_order_time")
                    self._active_alarm_activity[alarm_id] = current
                elif state in {"CLEARED", "NORMAL"}:
                    self._active_alarm_activity.pop(alarm_id, None)
            if message.get("transition"):
                self._status["alarm_events_session"] += 1
            self._status["last_alarm_event"] = message.get("time")
            self._status["last_alarm_path"] = message.get("path")

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
            self._status.update(
                worker_pid=None,
                last_stop_time=utc_now(),
                opc_state="unknown",
                active_tag_count=None,
                requested_subscription_count=None,
                subscribed_tag_count=None,
                failed_subscription_count=None,
                subscription_complete=False,
                alarm_activity_state="unknown",
                active_alarms=0,
            )
            self._active_alarm_activity.clear()
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

    def _send(self, command: str, **values) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps({"command": command, **values}) + "\n")
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
            requested = self._send("rebuild", generation=self._status["registry_generation"])
            if requested:
                self._status["worker_state"] = "rebuilding"
            return requested

    def notify_alarm_mappings_changed(self) -> bool:
        with self._lock:
            if not self.enabled:
                return False
            return self._send("reload_alarm_mappings")

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._intentional_stop = True
            process = self._process
            if process is None or process.poll() is not None:
                self._status["worker_state"] = "stopped" if self.enabled else "disabled"
                self._status["worker_pid"] = None
                self._status["alarm_activity_state"] = "unknown"
                self._status["active_alarms"] = 0
                self._active_alarm_activity.clear()
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
