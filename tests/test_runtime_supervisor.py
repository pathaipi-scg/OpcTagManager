import io
import json
import queue
import subprocess
import threading
import time

from services.runtime_supervisor import HistorianSupervisor
from workers.historian_worker import STATUS_PREFIX


class BlockingOutput:
    def __init__(self):
        self.items = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        item = self.items.get(timeout=2)
        if item is None:
            raise StopIteration
        return item


class FakeStdin:
    def __init__(self, process):
        self.process = process
        self.commands = []
        self.payloads = []

    def write(self, value):
        payload = json.loads(value)
        self.payloads.append(payload)
        command = payload["command"]
        self.commands.append(command)
        if command == "stop":
            self.process.finish(0)

    def flush(self):
        pass


class FakeProcess:
    next_pid = 100

    def __init__(self):
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.stdout = BlockingOutput()
        self.stdin = FakeStdin(self)
        self.return_code = None
        self.done = threading.Event()
        self.terminated = False

    def poll(self):
        return self.return_code

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.return_code

    def finish(self, code):
        if self.return_code is None:
            self.return_code = code
            self.stdout.items.put(None)
            self.done.set()

    def terminate(self):
        self.terminated = True
        self.finish(-1)

    def event(self, event, **values):
        self.stdout.items.put(STATUS_PREFIX + json.dumps({"event": event, **values}) + "\n")


class ProcessFactory:
    def __init__(self):
        self.processes = []
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        process = FakeProcess()
        self.processes.append(process)
        return process


def wait_until(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_disabled_default_never_spawns_and_tracks_pending_generation():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(False, factory)
    assert not supervisor.start()
    assert not supervisor.notify_registry_changed(4)
    status = supervisor.status()
    assert factory.processes == []
    assert status["worker_state"] == "disabled"
    assert status["registry_generation"] == 1
    assert status["rebuild_pending"] is True
    assert status["historian_ownership"] == "legacy_opc_service"


def test_start_duplicate_prevention_status_rebuild_and_graceful_stop():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(True, factory, restart_delay=0.01)
    try:
        assert supervisor.start()
        assert not supervisor.start()
        process = factory.processes[0]
        assert factory.calls[0][0][-2:] == ["-m", "workers.historian_worker"]
        process.event("worker_started")
        process.event("tag_snapshot", active_tag_count=3)
        process.event("opc_state", state="connected")
        process.event("subscriptions_ready", requested_subscription_count=3, subscribed_tag_count=2,
                      failed_subscription_count=1, complete=False)
        wait_until(lambda: supervisor.status()["subscribed_tag_count"] == 2)
        assert supervisor.notify_registry_changed(7)
        assert "rebuild" in process.stdin.commands
        assert supervisor.status()["rebuild_pending"] is True
        supervisor.stop(timeout=1)
        assert "stop" in process.stdin.commands
        wait_until(lambda: supervisor.status()["worker_state"] == "stopped")
        assert process.poll() == 0
    finally:
        supervisor.shutdown()


def test_worker_exit_is_detected_and_restarted_without_crashing_supervisor():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(True, factory, restart_delay=0.01)
    try:
        supervisor.start()
        factory.processes[0].finish(5)
        wait_until(lambda: len(factory.processes) == 2)
        status = supervisor.status()
        assert status["restart_count"] == 1
        assert status["worker_pid"] == factory.processes[1].pid
    finally:
        supervisor.shutdown()
    assert all(process.poll() is not None for process in factory.processes)


def test_rebuild_pending_clears_only_for_current_generation_ack():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(True, factory, restart_delay=0.01)
    try:
        supervisor.start()
        process = factory.processes[0]
        assert supervisor.notify_registry_changed(10)
        process.event("subscriptions_ready", requested_subscription_count=4, subscribed_tag_count=4,
                      failed_subscription_count=0, complete=True)
        wait_until(lambda: supervisor.status()["subscribed_tag_count"] == 4)
        assert supervisor.status()["rebuild_pending"] is True
        process.event("rebuild_ack", generation=0, complete=True)
        time.sleep(0.03)
        assert supervisor.status()["rebuild_pending"] is True
        process.event("rebuild_ack", generation=1, complete=True)
        wait_until(lambda: supervisor.status()["rebuild_pending"] is False)
        assert supervisor.status()["acknowledged_generation"] == 1
    finally:
        supervisor.shutdown()


def test_partial_rebuild_ack_does_not_clear_pending_generation():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(True, factory, restart_delay=0.01)
    try:
        supervisor.start()
        process = factory.processes[0]
        assert supervisor.notify_registry_changed(12)
        process.event("rebuild_ack", generation=1, complete=False,
                      requested_subscription_count=10, subscribed_tag_count=9,
                      failed_subscription_count=1)
        time.sleep(0.03)
        status = supervisor.status()
        assert status["rebuild_pending"] is True
        assert status["acknowledged_generation"] == 0
    finally:
        supervisor.shutdown()


def test_pending_generation_survives_crash_and_is_resent_after_restart():
    factory = ProcessFactory()
    supervisor = HistorianSupervisor(True, factory, restart_delay=0.01)
    try:
        supervisor.start()
        assert supervisor.notify_registry_changed(11)
        first = factory.processes[0]
        first.finish(7)
        wait_until(lambda: len(factory.processes) == 2)
        second = factory.processes[1]
        wait_until(lambda: any(item.get("command") == "rebuild" for item in second.stdin.payloads))
        rebuild = next(item for item in second.stdin.payloads if item.get("command") == "rebuild")
        assert rebuild["generation"] == 1
        assert supervisor.status()["rebuild_pending"] is True
    finally:
        supervisor.shutdown()
