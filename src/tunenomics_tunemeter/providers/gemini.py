"""Gemini chat JSON/JSONL with reported totals and explicit reasoning."""
from .. import engine
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation
from .storage import rows

USAGE = dict.fromkeys(("input", "output", "cached", "thoughts", "total", "tool"), True)
MESSAGE = {"id": True, "type": True, "timestamp": True, "model": True, "tokens": USAGE}
SCHEMA = {"sessionId": True, "startTime": True, **MESSAGE, "messages": [MESSAGE]}
SPEC = ProviderSpec("gemini", "chat-json-jsonl", "per_event", "per_event", (
    FieldRule("input_tokens", ("input",)), FieldRule("cached_input_tokens", ("cached",)),
    FieldRule("output_tokens", ("output", "thoughts"), "sum_known"),
    FieldRule("reasoning_output_tokens", ("thoughts",)), FieldRule("total_tokens", ("total",))), extra_native_paths=("tool",), event_kinds=("gemini",))


def read(path, issues):
    session = engine.alias(str(path))
    for index, row in enumerate(rows(path, SCHEMA, issues)):
        if row.get("sessionId"):
            session = engine.alias(row["sessionId"])
            yield SessionObservation(session)
        for message_index, msg in enumerate(row.get("messages", [row])):
            if msg.get("type") == "gemini" and isinstance(msg.get("tokens"), dict):
                identity = msg.get("id")
                yield NativeEvent(session, str(identity or f"row-{index}-{message_index}"), msg.get("timestamp"),
                                  msg.get("model"), msg["tokens"], "gemini", "record_id" if identity else "row_fallback")
