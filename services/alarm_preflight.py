from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlarmPreflight:
    alarm_service: object
    audio_repository: object
    production_alarm_owner: str
    capability: str
    alarm_write_enabled: bool
    alarm_reload_enabled: bool
    reload_host: str
    reload_port: int
    reload_address: int

    def run(self) -> dict:
        try:
            integrity = self.alarm_service.integrity()
            sql_reachable = True
            error = None
        except Exception:
            integrity = {
                "total_mappings": None, "distinct_tag_ids": None, "duplicate_tag_ids": [],
                "missing_tagmaster": None, "inactive_tagmaster": None,
                "missing_node_ids": None, "unsupported_modes": None,
                "missing_mp3_files": [],
            }
            sql_reachable = False
            error = "alarm_sql_read_failed"

        root = self.audio_repository.root
        repository_configured = root is not None
        repository_reachable = bool(root is not None and root.is_dir())
        duplicate_count = len(integrity["duplicate_tag_ids"])
        missing_mp3_count = len(integrity["missing_mp3_files"])
        data_ready = bool(
            sql_reachable
            and repository_reachable
            and duplicate_count == 0
            and integrity["missing_tagmaster"] == 0
            and integrity["inactive_tagmaster"] == 0
            and integrity["missing_node_ids"] == 0
            and integrity["unsupported_modes"] == 0
            and missing_mp3_count == 0
        )
        return {
            "read_only": True,
            "ready": data_ready,
            "error": error,
            "production_alarm_owner": self.production_alarm_owner,
            "opctagmanager_alarm_capability": self.capability,
            "sql_reachable": sql_reachable,
            "mp3_repository_configured": repository_configured,
            "mp3_repository_reachable": repository_reachable,
            "reload_configuration_present": bool(self.reload_host and self.reload_port > 0 and self.reload_address >= 0),
            "alarm_write_enabled": self.alarm_write_enabled,
            "alarm_reload_enabled": self.alarm_reload_enabled,
            "mapping_counts": {
                "total": integrity["total_mappings"],
                "distinct_tag_ids": integrity["distinct_tag_ids"],
                "duplicates": duplicate_count,
                "missing_tags": integrity["missing_tagmaster"],
                "inactive_tags": integrity["inactive_tagmaster"],
                "missing_node_ids": integrity["missing_node_ids"],
                "unsupported_modes": integrity["unsupported_modes"],
                "missing_mp3_files": missing_mp3_count,
            },
        }
