"""WorkBuddy project JSONL metadata format preview; no credit or content."""
from .. import engine
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation, get_path
from .storage import rows

USAGE = dict.fromkeys(("input_tokens", "output_tokens", "total_tokens",
                       "cache_read_input_tokens", "cache_creation_input_tokens"), True)
SCHEMA = {"type": True, "role": True, "id": True, "sessionId": True, "timestamp": True,
          "message": {"usage": USAGE},
          "providerData": {"model": True, "requestModelId": True,
                           "rawUsage": {"cache_creation_input_tokens": True,
                                        "completion_tokens_details": {"reasoning_tokens": True}}}}
SPEC = ProviderSpec("workbuddy", "project-jsonl", "per_event", "per_event", (
    FieldRule("input_tokens", ("message.usage.input_tokens",)),
    FieldRule("cached_input_tokens", ("message.usage.cache_read_input_tokens",)),
    FieldRule("cache_write_input_tokens", ("message.usage.cache_creation_input_tokens",),
              "reported_else_sum_known", ("providerData.rawUsage.cache_creation_input_tokens",)),
    FieldRule("output_tokens", ("message.usage.output_tokens",)),
    FieldRule("reasoning_output_tokens", ("providerData.rawUsage.completion_tokens_details.reasoning_tokens",)),
    FieldRule("total_tokens", ("message.usage.total_tokens",))),
    event_kinds=("function_call", "message"), validate_subsets=True)


def read(path, issues):
    for index, row in enumerate(rows(path, SCHEMA, issues)):
        session = engine.alias(row.get("sessionId") or path.stem)
        if row.get("sessionId"):
            yield SessionObservation(session)
        # Ignore content-only records; any unknown usage-bearing kind is visible.
        if not any(get_path(row, key) is not None for key in SPEC.native_paths):
            continue
        kind = row.get("type")
        if kind not in SPEC.event_kinds:
            issues["unknown_usage_record_types"] += 1
            continue
        if kind == "message" and row.get("role") != "assistant":
            issues["non_assistant_usage_records"] += 1
            continue
        data = row.get("providerData") or {}
        model = None
        for value in (data.get("model"), data.get("requestModelId")):
            if isinstance(value, str) and value.strip().lower() not in {"", "auto", "default", "unknown", "unresolved"}:
                model = value.strip()
                break
        identity = row.get("id")
        yield NativeEvent(session, f"{kind}:{identity}" if identity else f"{kind}:row-{index}",
                          row.get("timestamp"), model, row, kind,
                          "record_id" if identity else "row_fallback")
