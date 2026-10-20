"""Selected OpenCode JSON/SQLite layouts with explicit fresh-input rules."""
from .. import engine
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation
from .storage import rows, sqlite_rows

USAGE = {"input": True, "output": True, "reasoning": True, "total": True,
         "cache": {"read": True, "write": True}}
SCHEMA = {"id": True, "sessionID": True, "role": True, "modelID": True, "providerID": True,
          "model": {"id": True, "providerID": True}, "tokens": USAGE,
          "time": {"created": True, "completed": True}}
SPEC = ProviderSpec("opencode", "message-json-sqlite", "per_event", "per_event", (
    FieldRule("input_tokens", ("input", "cache.read", "cache.write"), "sum_known"),
    FieldRule("cached_input_tokens", ("cache.read",)), FieldRule("cache_write_input_tokens", ("cache.write",)),
    FieldRule("output_tokens", ("output",)), FieldRule("reasoning_output_tokens", ("reasoning",)),
    FieldRule("total_tokens", ("total",), "reported_else_sum_known", ("input", "cache.read", "cache.write", "output"))),
    event_kinds=("assistant", "model", "compaction"))


def read(path, issues):
    if path.suffix.lower() == ".db":
        for session, identity, timestamp, model, counters, kind in sqlite_rows(path, issues, include_kind=True):
            yield NativeEvent(session, identity, timestamp, model, counters, kind, "record_id")
        return
    for row in rows(path, SCHEMA, issues):
        if row.get("sessionID"):
            yield SessionObservation(engine.alias(row["sessionID"]))
        if row.get("role") in {"assistant", "model"} and isinstance(row.get("tokens"), dict):
            identity = row.get("id")
            yield NativeEvent(engine.alias(row.get("sessionID") or path.parent.name), str(identity or path.stem),
                              (row.get("time") or {}).get("created"), row.get("modelID"), row["tokens"],
                              row["role"], "record_id" if identity else "row_fallback")
