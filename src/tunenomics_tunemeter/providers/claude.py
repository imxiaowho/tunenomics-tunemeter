"""Claude Code assistant usage; no Desktop/Cowork inference."""
from .. import engine
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation
from .storage import rows

USAGE = dict.fromkeys(("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"), True)
SCHEMA = {"type": True, "uuid": True, "sessionId": True, "timestamp": True,
          "message": {"id": True, "role": True, "model": True, "usage": USAGE}}
SPEC = ProviderSpec("claude", "assistant-jsonl", "per_event", "per_event", (
    FieldRule("input_tokens", ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"), "sum_known"),
    FieldRule("cached_input_tokens", ("cache_read_input_tokens",)),
    FieldRule("cache_write_input_tokens", ("cache_creation_input_tokens",)),
    FieldRule("output_tokens", ("output_tokens",)),
    FieldRule("total_tokens", ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"), "sum_known")))


def read(path, issues):
    for index, row in enumerate(rows(path, SCHEMA, issues)):
        if row.get("sessionId"):
            yield SessionObservation(engine.alias(row["sessionId"]))
        msg = row.get("message") or {}
        if row.get("type") == "assistant" and isinstance(msg.get("usage"), dict):
            identity = msg.get("id") or row.get("uuid")
            yield NativeEvent(engine.alias(row.get("sessionId") or str(path)), str(identity or f"row-{index}"),
                              row.get("timestamp"), msg.get("model"), msg["usage"], "assistant", "record_id" if identity else "row_fallback")
