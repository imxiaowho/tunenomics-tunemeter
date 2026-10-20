"""Compatibility facade; provider semantics live in individual modules."""
from .providers import get
from .providers.base import normalize as normalize_usage
from .providers.base import NativeEvent
from .providers.storage import projection, rows, stamp, sqlite_rows


def parse(source, path, issues):
    for event in get(source).read(path, issues):
        if isinstance(event, NativeEvent):
            yield event.session, event.identity, event.timestamp, event.model, event.counters


def normalize(source, usage, issues):
    return normalize_usage(get(source).SPEC, usage, issues)
