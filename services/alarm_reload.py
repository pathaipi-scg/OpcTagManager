from __future__ import annotations

from dataclasses import asdict, dataclass

from pyModbusTCP.client import ModbusClient


@dataclass(frozen=True, slots=True)
class ReloadResult:
    notified: bool
    category: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class AlarmReloadNotifier:
    def __init__(self, enabled: bool, host: str, port: int, address: int, client_factory=ModbusClient) -> None:
        self.enabled = enabled
        self.host = host
        self.port = port
        self.address = address
        self.client_factory = client_factory

    def notify(self) -> ReloadResult:
        if not self.enabled:
            return ReloadResult(False, "disabled")
        try:
            client = self.client_factory(host=self.host, port=self.port, auto_open=True)
            registers = client.read_holding_registers(self.address, 1)
            if not registers:
                return ReloadResult(False, "read_failed")
            if not client.write_single_register(self.address, (int(registers[0]) + 1) % 65536):
                return ReloadResult(False, "write_failed")
            return ReloadResult(True)
        except Exception:
            return ReloadResult(False, "connection_error")
