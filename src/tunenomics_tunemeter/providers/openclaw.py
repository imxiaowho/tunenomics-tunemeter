"""OpenClaw JSONL only; registry reports the unsupported SQLite era."""
from .base import ProviderSpec
from .pi import RULES, read_family

SPEC = ProviderSpec("openclaw", "transcript-jsonl", "per_event", "per_event", RULES, event_kinds=("message",))


def read(path, issues):
    yield from read_family("openclaw", path, issues)
