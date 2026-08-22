from types import SimpleNamespace

import pytest

from services.kepware_config_api import KepwareConfigError
from services.kepware_system_control import KepwareSystemControl, SystemControlContract


class FakeApi:
    def __init__(self, *, write=False, channel=True, device=True, tag=True,
                 channel_driver="Memory Based", device_driver="Memory Based", drift=False):
        self.settings = SimpleNamespace(write_enabled=write)
        self.channel_present = channel
        self.device_present = device
        self.tag_present = tag
        self.channel_driver = channel_driver
        self.device_driver = device_driver
        self.drift = drift
        self.calls = []

    def get_project(self): return {"PROJECT_ID": 1}
    def get_channel(self, _name):
        return None if not self.channel_present else {"properties": {"servermain.MULTIPLE_TYPES_DEVICE_DRIVER": self.channel_driver}}
    def get_device(self, _channel, _device):
        if not self.device_present: return None
        return {"properties": {"servermain.MULTIPLE_TYPES_DEVICE_DRIVER": self.device_driver,
                               "servermain.DEVICE_MODEL": 0, "servermain.DEVICE_ID_FORMAT": 1,
                               "servermain.DEVICE_ID_STRING": "1"}}
    def get_tag_group(self, *_args): return {"properties": {}}
    def get_tag(self, *_args):
        if not self.tag_present: raise KepwareConfigError("HTTP 404")
        return {"properties": {"servermain.TAG_ADDRESS": "D4" if self.drift else "D0000",
                               "servermain.TAG_DATA_TYPE": 6, "servermain.TAG_READ_WRITE_ACCESS": 1,
                               "servermain.TAG_SCAN_RATE_MILLISECONDS": 1000}}
    def create_channel(self, *_args): self.calls.append("channel"); self.channel_present = True
    def create_device(self, *_args): self.calls.append("device"); self.device_present = True
    def create_tag_group(self, *_args): self.calls.append("group")
    def create_tag(self, *_args): self.calls.append("tag"); self.tag_present = True
    def _segment(self, value, _kind): return value
    def _tag_parent_path(self, *_args): return "/project/channels/SYSTEM/devices/OpcTagManager"
    def get_property_definitions(self, _path):
        return [{"symbolic_name": "servermain.TAG_ADDRESS", "read_only": False}]
    def get_property_states(self, _path): self.calls.append("states"); return {}
    def update_tag(self, *_args): self.calls.append("put"); self.drift = False


def opc_ready(_path, configured):
    return {"opc_endpoint_reachable": True, "resolved_node_id": "ns=4;s=control",
            "configured_node_id": configured or None, "node_id_consistent": not configured or configured == "ns=4;s=control",
            "reload_node_readable": True, "reload_datatype_supported": True}


@pytest.mark.parametrize("api,state", [
    (FakeApi(channel=False), "missing_channel"),
    (FakeApi(device=False), "missing_device"),
    (FakeApi(tag=False), "missing_tag"),
    (FakeApi(channel_driver="Simulator"), "ownership_conflict"),
    (FakeApi(device_driver="Simulator"), "ownership_conflict"),
    (FakeApi(drift=True), "drift_detected"),
    (FakeApi(), "ready"),
])
def test_inspection_states_are_read_only(api, state):
    subject = KepwareSystemControl(api, SystemControlContract(), opc_inspector=opc_ready)
    assert subject.inspect()["state"] == state
    assert api.calls == []


def test_driver_unavailable_and_configured_node_mismatch_are_explicit():
    api = FakeApi()
    api.has_driver = lambda _name: False
    assert KepwareSystemControl(api, SystemControlContract()).inspect()["state"] == "driver_unavailable"
    contract = SystemControlContract(configured_node_id="ns=9;s=stale")
    assert KepwareSystemControl(FakeApi(), contract, opc_inspector=opc_ready).inspect()["state"] == "verification_failed"


def test_bootstrap_gates_and_exact_order_without_delete_or_replace():
    disabled = KepwareSystemControl(FakeApi(write=True, channel=False), SystemControlContract())
    assert disabled.bootstrap()["state"] == "creation_not_configured"
    api = FakeApi(write=True, channel=False, device=False, tag=False)
    subject = KepwareSystemControl(api, SystemControlContract(), bootstrap_enabled=True, opc_inspector=opc_ready)
    assert subject.bootstrap()["state"] == "ready"
    assert api.calls == ["channel", "device", "tag"]


def test_bootstrap_stops_on_channel_and_device_conflicts():
    for api in (FakeApi(write=True, channel_driver="Simulator"), FakeApi(write=True, device_driver="Simulator")):
        state = KepwareSystemControl(api, SystemControlContract(), bootstrap_enabled=True).bootstrap()
        assert state["state"] == "ownership_conflict"
        assert api.calls == []


def test_repair_requires_gate_proves_mutability_and_updates_only_safe_drift():
    api = FakeApi(write=True, drift=True)
    assert KepwareSystemControl(api, SystemControlContract()).repair()["state"] == "repair_not_allowed"
    subject = KepwareSystemControl(api, SystemControlContract(), repair_enabled=True, opc_inspector=opc_ready)
    assert subject.repair()["state"] == "ready"
    assert api.calls == ["states", "put"]


def test_self_heal_gate_and_missing_tag_bootstrap_once():
    api = FakeApi(write=True, tag=False)
    disabled = KepwareSystemControl(api, SystemControlContract(), bootstrap_enabled=True)
    assert disabled.ensure_for_reload_failure()["state"] == "creation_not_configured"
    subject = KepwareSystemControl(api, SystemControlContract(), bootstrap_enabled=True,
                                   self_heal_enabled=True, opc_inspector=opc_ready)
    assert subject.ensure_for_reload_failure()["state"] == "ready"
    assert api.calls == ["tag"]
