"""Qwen's own usageMetadata names; no Gemini record compatibility claim."""
from .. import engine
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation
from .storage import rows

USAGE = dict.fromkeys(("promptTokenCount", "candidatesTokenCount", "cachedContentTokenCount", "thoughtsTokenCount", "totalTokenCount"), True)
SCHEMA = {"type": True, "uuid": True, "sessionId": True, "timestamp": True, "model": True, "usageMetadata": USAGE}
SPEC = ProviderSpec("qwen", "chat-usage-jsonl", "per_event", "per_event", (
    FieldRule("input_tokens", ("promptTokenCount",)), FieldRule("cached_input_tokens", ("cachedContentTokenCount",)),
    FieldRule("output_tokens", ("candidatesTokenCount", "thoughtsTokenCount"), "sum_known"),
    FieldRule("reasoning_output_tokens", ("thoughtsTokenCount",)), FieldRule("total_tokens", ("totalTokenCount",))))


def read(path, issues):
    for index, row in enumerate(rows(path, SCHEMA, issues)):
        if row.get("sessionId"):
            yield SessionObservation(engine.alias(row["sessionId"]))
        if row.get("type") == "assistant" and isinstance(row.get("usageMetadata"), dict):
            identity = row.get("uuid")
            yield NativeEvent(engine.alias(row.get("sessionId") or str(path)), str(identity or f"row-{index}"),
                              row.get("timestamp"), row.get("model"), row["usageMetadata"], "assistant", "record_id" if identity else "row_fallback")
