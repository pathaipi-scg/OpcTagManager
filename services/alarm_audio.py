from __future__ import annotations

from pathlib import Path


class AlarmAudioError(RuntimeError):
    pass


class AlarmAudioRepository:
    def __init__(self, root: str) -> None:
        self.root = Path(root) if root else None

    @staticmethod
    def validate_filename(filename: str) -> str:
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise AlarmAudioError("MP3 filename must be a plain basename.")
        if not filename.lower().endswith(".mp3"):
            raise AlarmAudioError("Alarm audio file must use the .mp3 extension.")
        return filename

    def list_files(self) -> list[dict]:
        if self.root is None or not self.root.is_dir():
            return []
        return [
            {"filename": path.name, "size": path.stat().st_size}
            for path in sorted(self.root.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.suffix.lower() == ".mp3"
        ]

    def resolve(self, filename: str) -> Path:
        name = self.validate_filename(filename)
        if self.root is None:
            raise AlarmAudioError("Alarm MP3 browse repository is not configured.")
        root = self.root.resolve()
        candidate = (root / name).resolve()
        if candidate.parent != root:
            raise AlarmAudioError("MP3 path escapes the configured repository.")
        if not candidate.is_file():
            raise AlarmAudioError("Alarm MP3 file was not found.")
        return candidate
