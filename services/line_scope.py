"""Shared, fail-closed runtime ownership and channel matching rules."""
from dataclasses import dataclass
from fnmatch import fnmatchcase
import re


def normalized_line_name(environment) -> str:
    """LINE_ID is accepted only at the configuration boundary during transition."""
    return ((environment.get('LINE_NAME') or '').strip() or
            (environment.get('LINE_ID') or '').strip()).upper()


def influx_database(value: str | None, line_name: str) -> str:
    if line_name and not (value or '').strip():
        return 'opc_' + line_name
    if value is None:
        raise RuntimeError('Missing configuration entry: INFLUX_DB')
    return value


@dataclass(frozen=True)
class LineScope:
    line_name: str = ""
    channel_patterns: tuple[str, ...] = ()

    def __post_init__(self):
        if bool(self.line_name) != bool(self.channel_patterns):
            raise ValueError("LINE_NAME and KEPWARE_CHANNEL_PATTERNS must be configured together")
        if self.line_name and not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", self.line_name):
            raise ValueError("LINE_NAME must contain 1-50 letters, digits, underscores or hyphens")
        if any(not p or any(c in p for c in '/.\\[]?') for p in self.channel_patterns):
            raise ValueError("Channel patterns support exact channel names and * wildcards only")

    @property
    def enabled(self):
        return bool(self.line_name)

    def allows_channel(self, channel: str) -> bool:
        if not self.enabled:
            return True
        if channel.casefold() in {'server', 'system'} or channel.startswith('_'):
            return False
        return any(fnmatchcase(channel.casefold(), pattern.casefold()) for pattern in self.channel_patterns)

    def allows_path(self, path: str) -> bool:
        return self.allows_channel(path.split('/', 1)[0])

    def require_path(self, path: str):
        if not self.allows_path(path):
            raise ValueError("Tag path is outside the configured line scope")

    def allows_tag(self, path: str, node_id: str) -> bool:
        if not self.enabled:
            return True
        # Kepware string NodeIds use dotted channel/device/tag paths. Check both
        # identities, so a corrupt registry NodeId cannot subscribe another line.
        match = re.fullmatch(r'ns=\d+;s=(.+)', node_id or '')
        return bool(self.allows_path(path) and match and
                    match[1].split('.', 1)[0].casefold() == path.split('/', 1)[0].casefold())
