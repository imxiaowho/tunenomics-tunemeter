"""Codex-only discovery; paths stay local and never appear in diagnostics."""
from pathlib import Path
from collections import Counter
import os
from . import engine
from .contracts import LOCAL_SCHEMA


def probe(home):
    home = Path(home).expanduser().absolute()
    result = {"source": "codex", "status": "not_found", "candidate_files": 0,
              "roots_found": 0, "issues": {}}
    if any(p.exists() and not engine.safe_path(p) for p in (home, *home.parents)):
        result.update(status="permission_denied", issues={"linked_or_inaccessible_parent": 1})
        return result
    errors = Counter()
    def onerror(exc):
        errors["permission_denied" if isinstance(exc, PermissionError) else "directory_read_error"] += 1
    for category in ("sessions", "archived_sessions"):
        root = home / category
        try:
            if not root.exists():
                continue
            if not all(engine.safe_path(p) for p in (home, root)) or not root.is_dir():
                errors["linked_or_invalid_root"] += 1
                continue
            result["roots_found"] += 1
            for current, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
                dirs[:] = [d for d in dirs if engine.safe_path(Path(current) / d)]
                result["candidate_files"] += sum(
                    Path(f).suffix.lower() == ".jsonl" and engine.safe_path(Path(current) / f) for f in files)
        except OSError as exc:
            onerror(exc)
    result["issues"] = dict(errors)
    result["status"] = ("partial" if result["candidate_files"] else "permission_denied") if errors else (
        "ready" if result["candidate_files"] else "empty" if result["roots_found"] else "not_found")
    return result


def doctor(home):
    result = probe(home)
    if result["status"] not in {"ready", "partial"}:
        return result
    issues = Counter()
    sampled = valid = 0
    for _, path in engine.discover(Path(home).expanduser().absolute())[:8]:
        sampled += 1
        records, _ = engine.read_rollout(path, "source", issues)
        valid += any(r[1] in {"session_meta", "turn_context", "token_count"} for r in records)
    result.update(sampled_files=sampled, readable_samples=valid, bounded_sample=True)
    result["issues"].update(dict(issues))
    if not valid:
        result["status"] = "permission_denied" if issues.get("unreadable_files") else "unsupported_format"
    elif valid < sampled or any(issues.values()):
        result["status"] = "partial"
    return result


def collect(home, tz, start=None, end_exclusive=None, snapshot=None):
    home = Path(home).expanduser().absolute()
    if any(p.exists() and not engine.safe_path(p) for p in (home, *home.parents)):
        raise PermissionError("Linked or inaccessible source")
    report = engine.collect(home, tz, start, end_exclusive, snapshot=snapshot)
    report.update(schema_version=LOCAL_SCHEMA, source_collector_version=engine.VERSION)
    report["identity_context"] = {"source_kind": "codex_rollout", "harness": "codex",
                                  "model_provider": None, "billing_channel": None, "account_alias": None,
                                  "billed_model": None, "request_count": None}
    tiers = Counter(e.get("configured_service_tier") for e in report["usage_events"])
    report["service_tier"] = {
        "status": "partially_observed" if tiers.get(None) and len(tiers) > 1 else
                  "observed" if tiers and None not in tiers else "unavailable",
        "source_availability": "checked_selected_records", "billing_tier_confirmed": False,
        "billed_service_tier": None,
        "configured_tiers": [{"value": k, "usage_events": v} for k, v in sorted(tiers.items(), key=lambda x: x[0] or "")],
    }
    return report
