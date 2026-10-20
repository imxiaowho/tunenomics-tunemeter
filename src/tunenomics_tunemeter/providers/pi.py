"""Pi-family message projection; shared only for documented envelope shapes."""
import os
from pathlib import Path, PureWindowsPath
from .. import engine
from ..contracts import selected_file
from .base import FieldRule, NativeEvent, ProviderSpec, SessionObservation
from .storage import projection, rows

USAGE = dict.fromkeys(("input", "output", "cacheRead", "cacheWrite", "totalTokens"), True)
SCHEMA = {"type": True, "id": True, "timestamp": True, "model": True, "modelId": True,
          "provider": True, "customType": True, "data": {"modelId": True}, "usage": USAGE,
          "message": {"role": True, "model": True, "provider": True, "responseId": True, "usage": USAGE}}
RULES = (FieldRule("input_tokens", ("input", "cacheRead", "cacheWrite"), "sum_known"),
         FieldRule("cached_input_tokens", ("cacheRead",)), FieldRule("cache_write_input_tokens", ("cacheWrite",)),
         FieldRule("output_tokens", ("output",)),
         FieldRule("total_tokens", ("totalTokens",), "reported_else_sum_known", ("input", "cacheRead", "cacheWrite", "output")))
SPEC = ProviderSpec("pi", "message-jsonl", "per_event", "per_event", RULES, event_kinds=("message",),
                    identity_scope="lineage", contract_version="1.2.0",
                    legacy_contract_ids=("tunemeter-provider/pi/message-jsonl/1.0.0",
                                         "tunemeter-provider/pi/message-jsonl/1.1.0"))
LINEAGE_FAILURES = frozenset({"malformed_lineage_header_records", "unreadable_lineage_headers",
    "missing_lineage_headers", "unresolved_lineage_parents", "invalid_lineage_parents",
    "ambiguous_lineage_parents", "lineage_parent_header_mismatch", "cyclic_lineage_headers"})


def file_key(path):
    # Lexical normalization only: never resolve/open a header-supplied path.
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def identity_context(paths, issues):
    """Resolve only parent links whose files are already selected candidates."""
    headers, filenames = {}, {}
    for path in paths:
        key = file_key(path)
        filenames.setdefault(os.path.normcase(path.name), []).append(key)
        try:
            with selected_file(path).open("rb") as stream:
                remaining = 256 * 1024
                for _ in range(20):
                    raw = stream.readline(min(remaining, 64 * 1024) + 1)
                    remaining -= len(raw)
                    if not raw or remaining < 0 or len(raw) > 64 * 1024:
                        break
                    if not raw.strip():
                        continue
                    try:
                        row = projection(raw, {"type": True, "id": True, "parentSession": True})
                    except (ValueError, UnicodeError, RecursionError):
                        issues["malformed_lineage_header_records"] += 1
                        continue
                    if row.get("type") == "session" and isinstance(row.get("id"), str) and row["id"]:
                        headers[key] = row
                        break
        except (OSError, ValueError, UnicodeError, RecursionError):
            issues["unreadable_lineage_headers"] += 1
        if key not in headers:
            issues["missing_lineage_headers"] += 1
    parents, scopes = {}, {}
    for key, row in headers.items():
        parent = row.get("parentSession")
        if parent is None:
            parents[key] = None
        elif isinstance(parent, str) and parent and not any(ord(c) < 32 for c in parent):
            value = Path(parent)
            parent_key = file_key(value if value.is_absolute() else Path(key).parent/value)
            if parent_key in headers:
                parents[key] = parent_key
            else:
                # Read no header-supplied path. Recover a relocation only from
                # the selected set, an unambiguous basename and session id.
                name = PureWindowsPath(parent).name
                matches = filenames.get(os.path.normcase(name), [])
                if len(matches) == 1 and matches[0] in headers:
                    candidate = matches[0]
                    session_id = headers[candidate]["id"]
                    if os.path.normcase(Path(name).stem).endswith(os.path.normcase("_" + session_id)):
                        parents[key] = candidate
                        issues["resolved_lineage_parents_by_filename"] += 1
                        continue
                    issues["lineage_parent_header_mismatch"] += 1
                elif len(matches) > 1:
                    issues["ambiguous_lineage_parents"] += 1
                scopes[key] = None
                issues["unresolved_lineage_parents"] += 1
        else:
            scopes[key] = None
            issues["invalid_lineage_parents"] += 1
    for key in headers:
        chain, seen, node = [], set(), key
        while node not in scopes:
            if node in seen:
                issues["cyclic_lineage_headers"] += 1
                scopes[node] = None
                break
            seen.add(node)
            chain.append(node)
            parent = parents.get(node)
            if parent is None:
                scopes[node] = engine.alias(node)
                break
            node = parent
        scope = scopes[node]
        for child in chain:
            scopes[child] = scope
    return scopes


def read_family(name, path, issues):
    session, model = engine.alias(str(path)), None
    for index, row in enumerate(rows(path, SCHEMA, issues)):
        kind = row.get("type")
        if kind == "session":
            session = engine.alias(row.get("id") or str(path))
            yield SessionObservation(session)
            continue
        if kind == "model_change":
            model = row.get("model") or row.get("modelId")
            continue
        if kind == "custom" and row.get("customType") == "model-snapshot":
            model = (row.get("data") or {}).get("modelId")
            continue
        msg = row.get("message") or {}
        if kind == "model_usage" and name == "omp":
            msg = {"role": "assistant", "usage": row.get("usage"), "model": row.get("model")}
        if msg.get("role") != "assistant" or not isinstance(msg.get("usage"), dict):
            continue
        if kind != "message" and not (name == "omp" and kind == "model_usage"):
            issues["unknown_usage_record_types"] += 1
            continue
        basis = "response_id" if msg.get("responseId") else "record_id" if row.get("id") else "row_fallback"
        identity = str(msg.get("responseId") or row.get("id") or f"row-{index}")
        # Native kind namespaces side calls separately from assistant messages.
        yield NativeEvent(session, f"{kind}:{identity}", row.get("timestamp"), msg.get("model") or model,
                          msg["usage"], kind or "message", basis)


def read(path, issues):
    yield from read_family("pi", path, issues)
