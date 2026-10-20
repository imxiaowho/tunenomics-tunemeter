"""Known-root harness registry, isolated readers and shared aggregate contract."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from . import __version__, codex, engine, providers
from .providers.base import accounting, field_evidence, normalize, SessionObservation
from .providers.storage import stamp

NAMES = providers.NAMES
PENDING = ("cursor", "copilot", "cline", "roo", "kilo", "kimi", "windsurf", "zed")
MAX_FILES = 100000
STATUSES = {"not_found", "empty", "ready", "partial", "permission_denied", "unsupported_format", "error", "not_implemented", "selected_generated_snapshot"}
INFORMATIONAL_ISSUES = frozenset({"after_snapshot_records", "duplicate_usage_records",
                                  "resolved_lineage_parents_by_filename"})


def has_coverage_issues(issues):
    return any(value for key, value in issues.items() if key not in INFORMATIONAL_ISSUES)


def selection(value):
    names = list(NAMES) if value == "all" else list(dict.fromkeys(value.split(",")))
    if not names or any(name not in NAMES for name in names):
        raise ValueError("Unsupported source selection")
    return names


def roots(overrides=(), codex_home=None):
    home = Path.home()
    defaults = {
        "codex": Path(os.environ.get("CODEX_HOME") or home/".codex"),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR") or home/".claude"),
        "pi": home/".pi"/"agent", "omp": home/".omp"/"agent",
        "gemini": home/".gemini", "openclaw": home/".openclaw", "qwen": home/".qwen",
        "workbuddy": Path(os.environ.get("WORKBUDDY_HOME") or home/".workbuddy"),
        "opencode": Path(os.environ.get("OPENCODE_DATA_DIR") or Path(os.environ.get("XDG_DATA_HOME") or home/".local"/"share")/"opencode"),
    }
    if codex_home is not None:
        defaults["codex"] = codex_home
    for override in overrides:
        name, sep, value = override.partition("=")
        if name not in NAMES or not sep or not value:
            raise ValueError("Invalid source root")
        defaults[name] = Path(value)
    return {name: Path(path).expanduser().absolute() for name, path in defaults.items()}


def safe_root(path):
    return all(not p.exists() and not p.is_symlink() or engine.safe_path(p) for p in (path, *path.parents))


def candidates(name, root, issues):
    if not safe_root(root):
        raise PermissionError("Linked source root")
    if name == "codex":
        return [path for _, path in engine.discover(root)]
    subtrees = {"claude": [root/"projects"], "pi": [root/"sessions"], "omp": [root/"sessions"],
                "gemini": [root/"tmp"], "qwen": [root/"projects"], "workbuddy": [root/"projects"],
                "opencode": [root/"storage"/"message"], "openclaw": []}
    found = []
    if name == "openclaw" and (root/"agents").exists():
        agents = root/"agents"
        if not safe_root(agents):
            raise PermissionError("Linked agents root")
        for agent in sorted(agents.iterdir()):
            if not engine.safe_path(agent):
                issues["linked_paths_skipped"] += 1
                continue
            if agent.is_dir():
                subtrees[name].append(agent/"sessions")
                database = agent/"agent"/"openclaw-agent.sqlite"
                if database.exists():
                    # SQLite/compressed OpenClaw era is not silently empty.
                    issues["unsupported_openclaw_sqlite_store"] += 1
    def walk_error(exc):
        issues["permission_denied" if isinstance(exc, PermissionError) else "directory_read_error"] += 1
    for subtree in subtrees[name]:
        if not subtree.exists():
            continue
        if not safe_root(subtree):
            issues["linked_paths_skipped"] += 1
            continue
        for current, dirs, files in os.walk(subtree, followlinks=False, onerror=walk_error):
            safe = [d for d in dirs if engine.safe_path(Path(current)/d)]
            if len(safe) != len(dirs):
                issues["linked_paths_skipped"] += len(dirs) - len(safe)
            dirs[:] = sorted(safe)
            if name == "workbuddy":
                depth = len(Path(current).relative_to(subtree).parts)
                if depth == 1:
                    dirs[:] = [d for d in dirs if d not in {"tool-results", "audit-log"}]
                elif depth == 2:
                    dirs[:] = [d for d in dirs if d == "subagents"]
                elif depth >= 3:
                    dirs[:] = []
            for file in sorted(files):
                path = Path(current)/file
                wanted = path.suffix.lower() == (".json" if name == "opencode" else ".jsonl")
                if name == "gemini":
                    wanted = path.parent.name == "chats" and file.startswith("session-") and path.suffix.lower() in {".json", ".jsonl"}
                elif name == "qwen":
                    wanted = path.parent.name == "chats" and path.suffix.lower() == ".jsonl"
                elif name == "workbuddy":
                    wanted = wanted and (depth == 1 or depth == 3 and path.parent.name == "subagents" and file.startswith("agent-"))
                if wanted:
                    if engine.safe_path(path):
                        found.append(path)
                    else:
                        issues["linked_paths_skipped"] += 1
                if len(found) >= MAX_FILES:
                    issues["file_limit_reached"] += 1
                    return found
    if name == "opencode" and root.is_dir():
        for path in sorted(root.glob("opencode*.db")):
            if engine.safe_path(path):
                found.append(path)
            else:
                issues["linked_paths_skipped"] += 1
    return found


def probe_one(name, root):
    if name == "codex":
        return codex.probe(root)
    issues = Counter()
    result = {"source": name, "status": "not_found", "candidate_files": 0}
    try:
        files = candidates(name, root, issues)
        result.update(candidate_files=len(files), status="ready" if files else "empty" if root.is_dir() else "not_found")
    except PermissionError:
        issues["permission_denied"] += 1
        result["status"] = "permission_denied"
    except OSError:
        issues["source_discovery_failed"] += 1
        result["status"] = "error"
    result["issues"] = {k: v for k, v in issues.items() if v}
    if result["issues"] and result["status"] not in {"permission_denied", "error"}:
        result["status"] = "partial" if result["candidate_files"] else "unsupported_format"
    return result


def discover(names, locations):
    sources = [probe_one(name, locations[name]) for name in names]
    bad = any(s["status"] in {"partial", "permission_denied", "error", "unsupported_format"} for s in sources)
    ready = any(s["candidate_files"] for s in sources)
    return {"status": "partial" if bad else "ready" if ready else "not_found", "sources": sources,
            "capabilities": {"implemented_format_previews": list(NAMES), "pending_not_probed": list(PENDING),
                             "provider_contracts": {name: providers.get(name).SPEC.describe() for name in names}},
            "installation_inventory": False, "historical_completeness": "unknown"}


def doctor(names, locations):
    result = discover(names, locations)
    for source in result["sources"]:
        name = source["source"]
        if source["status"] not in {"ready", "partial"}:
            continue
        if name == "codex":
            source.update(codex.doctor(locations[name]))
            continue
        issues = Counter()
        recognized = sampled = metadata_samples = 0
        try:
            for path in candidates(name, locations[name], issues)[:8]:
                sampled += 1
                try:
                    # Bounded metadata check, not just directory existence.
                    reader = providers.get(name).read(path, issues)
                    try:
                        saw_metadata = False
                        for item in reader:
                            if isinstance(item, SessionObservation):
                                saw_metadata = True
                            else:
                                recognized += 1
                                break
                        metadata_samples += int(saw_metadata)
                    finally:
                        reader.close()
                except (OSError, ValueError, UnicodeError, RecursionError, sqlite3.Error):
                    issues["sample_read_error"] += 1
            source.update(sampled_files=sampled, readable_usage_samples=recognized,
                          metadata_samples=metadata_samples, bounded_sample=True,
                          status="partial" if any(issues.values()) else "ready" if recognized else "empty" if metadata_samples else "unsupported_format")
            source["issues"].update({k: v for k, v in issues.items() if v})
        except (OSError, ValueError):
            source.update(status="error")
    if any(s["status"] in {"partial", "permission_denied", "error", "unsupported_format"} for s in result["sources"]):
        result["status"] = "partial"
    return result


def native_collect(name, root, tz, start, end, snapshot):
    provider = providers.get(name)
    issues = Counter()
    paths = candidates(name, root, issues)
    identity_context = provider.identity_context(paths, issues) if provider.SPEC.identity_scope == "lineage" else {}
    events, conflicts, sessions = {}, set(), set()
    read = recognized = 0
    for path in paths:
        try:
            for item in provider.read(path, issues):
                sessions.add(item.session)
                if isinstance(item, SessionObservation):
                    continue
                recognized += 1
                moment = stamp(item.timestamp)
                if moment is None:
                    issues["missing_or_invalid_timestamps"] += 1
                    continue
                if moment > snapshot or start and moment < start or end and moment >= end:
                    continue
                if item.counter_semantics != provider.SPEC.native_semantics:
                    issues["unsupported_counter_semantics"] += 1
                    continue
                counts, numeric_native = normalize(provider.SPEC, item.counters, issues)
                if all(v is None for v in counts.values()):
                    issues["events_without_numeric_usage"] += 1
                    continue
                if item.identity_basis == "row_fallback":
                    key = (engine.alias(str(path)), item.identity)
                elif provider.SPEC.identity_scope == "lineage" and identity_context.get(provider.file_key(path)):
                    # Short Pi entry ids are not globally unique. Fork copies
                    # retain both the entry id and original timestamp.
                    key = (identity_context[provider.file_key(path)], item.identity, moment.isoformat())
                else:
                    key = (item.session, item.identity)
                event = {"timestamp": moment.astimezone(tz).isoformat(), "date": moment.astimezone(tz).date().isoformat(),
                         "model": engine.safe_label(item.model), "harness": name, "configured_service_tier": None,
                         "session": item.session, "native_usage": numeric_native,
                         "accounting": accounting(provider.SPEC, item.native_kind, item.identity_basis), **counts}
                if item.identity_basis == "row_fallback":
                    issues["identity_row_fallback"] += 1
                if key in events:
                    # Repeated exports collapse; differing stream snapshots need
                    # format-specific reconciliation, so exclude rather than sum.
                    if events[key]["native_usage"] != numeric_native or events[key]["model"] != event["model"]:
                        conflicts.add(key)
                    else:
                        issues["duplicate_usage_records"] += 1
                    continue
                events[key] = event
            read += 1
        except (OSError, ValueError, UnicodeError, OverflowError, RecursionError, sqlite3.Error):
            issues["unreadable_or_unsupported_files"] += 1
    for key in conflicts:
        events.pop(key, None)
    if conflicts:
        issues["conflicting_usage_records_excluded"] += len(conflicts)
    status = "partial" if has_coverage_issues(issues) else "ready" if recognized else "empty" if sessions else "unsupported_format" if paths else "empty" if root.is_dir() else "not_found"
    unresolved = provider.SPEC.identity_scope == "lineage" and any(issues.get(key) for key in provider.LINEAGE_FAILURES)
    return list(events.values()), {"source": name, "status": status, "candidate_files": len(paths),
        "files_read": read, "sessions_observed": len(sessions),
        "sessions_with_usage": len({e["session"] for e in events.values()}), "usage_events": len(events),
        "aggregation_validity": "unverified_lineage" if unresolved else "declared_lineage_resolved" if provider.SPEC.identity_scope == "lineage" else "adapter_accounting_only",
        "time_status": "not_collected", "issues": {k: v for k, v in issues.items() if v}}


def source_rows(events, statuses):
    if not isinstance(events, list):
        return [{"harness": item["source"], "status": item["status"], "time_status": item.get("time_status", "unknown"),
                 "usage_events": item.get("usage_events"), **dict.fromkeys(engine.FIELDS),
                 "missing_field_events": dict.fromkeys(engine.FIELDS)} for item in statuses]
    return [{"harness": item["source"], "status": item["status"], "time_status": item.get("time_status", "unknown"),
             **engine.sum_usage([e for e in events if e.get("harness") == item["source"]])} for item in statuses]


def field_partitions(report):
    events = report.get("usage_events")
    if not isinstance(events, list):
        report["data_semantics"]["field_eligibility"] = "unavailable_in_snapshot"
        return
    specs = {s["source"]: providers.get(s["source"]).SPEC for s in report["source_inventory"]}
    declarations = {name: {r.field for r in spec.rules if r.paths} for name, spec in specs.items()}
    def annotate(row, items):
        missing = dict.fromkeys(engine.FIELDS, 0)
        not_collected = dict.fromkeys(engine.FIELDS, 0)
        unknown = dict.fromkeys(engine.FIELDS, 0)
        for event in items:
            name = event.get("harness")
            spec = specs.get(name)
            known_contract = spec and event.get("accounting", {}).get("contract_id") in {spec.contract_id, *spec.legacy_contract_ids}
            for field in engine.FIELDS:
                if not known_contract:
                    unknown[field] += 1
                elif field not in declarations[name]:
                    not_collected[field] += 1
                elif event.get(field) is None:
                    missing[field] += 1
        row["missing_field_events"] = missing
        row["not_collected_field_events"] = not_collected
        row["eligibility_unknown_field_events"] = unknown
        row["unobserved_field_events"] = {field: sum(e.get(field) is None for e in items) for field in engine.FIELDS}
    annotate(report["summary"], events)
    for section, keys in (("models", ("model",)), ("daily", ("date",)), ("hourly", ("hour_start",)),
                          ("daily_by_model", ("date", "model")), ("hourly_by_model", ("hour_start", "model")),
                          ("by_source", ("harness",))):
        groups = defaultdict(list)
        for event in events:
            hour = datetime.fromisoformat(event["timestamp"]).replace(minute=0, second=0, microsecond=0).isoformat()
            values = {**event, "hour_start": hour}
            groups[tuple(values[key] for key in keys)].append(event)
        for row in report.get(section, []):
            annotate(row, groups[tuple(row[key] for key in keys)])
    for field, observation in report["field_observations"].items():
        known = sum(e.get(field) is not None for e in events)
        excluded = report["summary"]["not_collected_field_events"][field]
        unknown = report["summary"]["eligibility_unknown_field_events"][field]
        eligible = len(events) - excluded - unknown
        observation.update(eligible_events=eligible, known_events=known,
                           missing_events=report["summary"]["missing_field_events"][field],
                           not_collected_events=excluded, eligibility_unknown_events=unknown,
                           status="no_samples" if not events else "eligibility_unknown" if unknown else "not_collected" if not eligible else "unavailable" if not known else "partially_observed" if known < eligible else "observed")
    report["data_semantics"]["missing_field_events"] = "null among contract-supported field observations only; not_collected and unknown eligibility are separate; unobserved counts every null"


def completion(report):
    gaps = []
    for key, value in report.get("issues", {}).items():
        if value and key not in INFORMATIONAL_ISSUES:
            gaps.append({"kind": "source_diagnostic", "code": key, "count": value})
    events = report.get("usage_events")
    missing_roots = []
    selection_mode = report.get("collection_context", {}).get("source_selection_mode", "unknown")
    for source in report.get("source_inventory", []):
        name = source["source"]
        if (selection_mode == "all" and source["status"] == "not_found"
                and not any(source.get("issues", {}).values())
                and not source.get("candidate_files") and not source.get("files_read")
                and not source.get("usage_events")):
            missing_roots.append(name)
            continue
        if source["status"] != "ready":
            gaps.append({"source": name, "kind": "source_not_ready", "status": source["status"]})
        # No event fields/time are expected from a known zero-event source.
        # Unknown event counts remain unknown, not silently treated as zero.
        if source.get("usage_events") == 0 or source["status"] == "not_found":
            continue
        if source.get("time_status") != "observed_intervals_only":
            gaps.append({"source": name, "kind": "turn_time_not_observed"})
        evidence = report["provider_contracts"][name]["field_evidence"]["normalized_fields"]
        missing = [{"field": key, "missing_events": value["missing_events"], "eligible_events": value["eligible_events"]}
                   for key, value in evidence.items() if value["missing_events"]]
        not_collected = [key for key, value in evidence.items() if value["collection"] == "not_collected"]
        unknown = [{"field": key, "eligibility_unknown_events": value["eligibility_unknown_events"]}
                   for key, value in evidence.items()
                   if value["collection"] == "not_verified_for_snapshot" or value["eligibility_unknown_events"]]
        for kind, fields in (("field_missing", missing), ("field_not_collected", not_collected),
                             ("field_eligibility_unknown", unknown)):
            if fields:
                gaps.append({"source": name, "kind": kind, "fields": fields})
    if missing_roots:
        gaps.append({"kind": "source_roots_not_found", "sources": missing_roots})
    if not isinstance(events, list):
        gaps.append({"kind": "source_events_unavailable_in_snapshot"})
    if report.get("aggregation_validity") == "requires_recollection":
        gaps.append({"source": "pi", "kind": "legacy_identity_scope_requires_recollection"})
    if report.get("aggregation_validity") == "limited":
        gaps.append({"kind": "identity_coverage_limited"})
    return {"pipeline_status": "completed", "collection_status": "partial" if gaps else "observed_requested_metrics",
            "historical_completeness": "unknown", "gaps": gaps}


def enrich(report, statuses, contract_basis="current_collection", selection_mode="unknown"):
    report["source_inventory"] = statuses
    report["by_source"] = source_rows(report.get("usage_events"), statuses)
    report["identity_context"] = {"source_kind": "local_harness_usage", "harness": "multiple" if len(statuses) > 1 else statuses[0]["source"],
        "model_provider": None, "billing_channel": None, "account_alias": None, "billed_model": None, "request_count": None}
    report["collection_context"] = {
        "harnesses": [s["source"] for s in statuses], "pricing": "out_of_scope",
        "source_selection_mode": selection_mode,
        "time_status": "observed_for_codex_only" if any(s["source"] == "codex" and s.get("time_status") == "observed_intervals_only" for s in statuses) else "not_collected",
        "time_coverage": {"observed_harnesses": [s["source"] for s in statuses if s.get("time_status") == "observed_intervals_only"],
                          "unavailable_harnesses": [s["source"] for s in statuses if s.get("time_status") != "observed_intervals_only"]},
        "cross_harness_deduplication": "not_established",
        "native_counters": "source-specific numeric fields in local usage_events; no prices or content",
        "normalization": "input includes cache only when all components known; output includes reasoning where source requires; reported totals preferred; null remains unknown",
        "contract_evidence_basis": contract_basis}
    report["collection_context"]["source_aggregate_basis"] = (
        "retained_event_evidence" if isinstance(report.get("usage_events"), list)
        else "event_evidence_unavailable; declared source counts only; source token totals unknown")
    report["provider_contracts"] = {}
    for status in statuses:
        name = status["source"]
        spec = providers.get(name).SPEC
        selected = [e for e in report.get("usage_events", []) if e.get("harness") == name]
        contract_known = contract_basis == "current_collection" or bool(selected) and all(e.get("accounting", {}).get("contract_id") in {spec.contract_id, *spec.legacy_contract_ids} for e in selected)
        evidence = field_evidence(spec, selected, contract_known=contract_known)
        description = spec.describe()
        description.update(evidence_basis=contract_basis,
                           source_contract_observation="declared_current_collection" if contract_basis == "current_collection" else "imported_event_declarations" if contract_known else "unavailable_in_snapshot",
                           field_evidence=evidence)
        report["provider_contracts"][name] = description
    for observation in report["field_observations"].values():
        observation.update(source="per-harness allowlisted counters; see provider_contracts", sample_unit="source_usage_observation",
                           collection="see_per_provider_contract", applicability="unknown")
    report["input_size_distribution"]["sample_unit"] = "source_usage_observation"
    report["data_semantics"]["time_coverage"] = "observed Codex intervals only; non-Codex time null/unknown; mixed totals are partial"
    report["data_semantics"]["session_counts"] = "observed includes distinct recognized session identifiers before time/usage filters; multiple selected files may share a session, so files_read is not sessions_observed; with_usage counts sessions represented after accounting; neither is a request or human-task count"
    report["data_semantics"]["missing_field_events"] = "missing normalized values among retained source usage observations; native values remain local"
    report["data_semantics"]["distribution"] = "mixed source usage observations, not verified request input sizes"
    field_partitions(report)
    report["completion"] = completion(report)
    report["warnings"] = {key: value for key, value in report.get("issues", {}).items()
                          if value and key in INFORMATIONAL_ISSUES}
    report["coverage_gaps"] = report["completion"]["gaps"]
    return report


def collect(names, locations, tz, start=None, end=None, selection_mode="explicit"):
    snapshot = datetime.now(timezone.utc)
    events, statuses, turns = [], [], []
    issues = Counter()
    files_read = sessions_observed = sessions_with_usage = 0
    codex_timing = None
    for name in names:
        try:
            if name == "codex":
                provider = providers.get(name)
                local = provider.collect(locations[name], tz, start, end, snapshot=snapshot)
                codex_timing = local if local["summary"]["files_read"] else None
                batch_events = [{**event, "harness": "codex",
                                 "accounting": accounting(provider.SPEC, "token_count", "engine_reconciled")} for event in local["usage_events"]]
                # A shared snapshot caps every adapter in this batch.
                batch_events = [e for e in batch_events if engine.instant(e["timestamp"]) <= snapshot]
                source = {"source": name, "status": "partial" if has_coverage_issues(local["issues"]) else "ready" if batch_events else "empty" if locations[name].is_dir() else "not_found",
                    "files_read": local["summary"]["files_read"], "sessions_observed": local["summary"]["sessions_observed"],
                    "sessions_with_usage": local["summary"]["sessions_with_usage"],
                    "usage_events": len(batch_events), "time_status": "observed_intervals_only" if codex_timing else "unavailable", "issues": local["issues"]}
                for turn in local["turns"]:
                    turns.append({**turn, "harness": "codex"})
            else:
                batch_events, source = native_collect(name, locations[name], tz, start, end, snapshot)
            events.extend(batch_events)
            statuses.append(source)
            files_read += source.get("files_read", 0)
            sessions_observed += source.get("sessions_observed", 0)
            sessions_with_usage += source.get("sessions_with_usage", 0)
            issues.update(source["issues"])
        except (OSError, ValueError, OverflowError, RecursionError, sqlite3.Error):
            statuses.append({"source": name, "status": "error", "time_status": "unavailable", "issues": {"adapter_failed": 1}})
            issues["adapter_failed"] += 1
    events.sort(key=lambda e: (e["timestamp"], e["harness"], e["model"]))
    models, days, hours = defaultdict(list), defaultdict(list), defaultdict(list)
    for event in events:
        models[event["model"]].append(event)
        days[event["date"]].append(event)
        hour = datetime.fromisoformat(event["timestamp"]).replace(minute=0, second=0, microsecond=0).isoformat()
        hours[hour].append(event)
    intervals = [(engine.instant(t["start"]), engine.instant(t["end"])) for t in turns]
    intervals = [(max(a, start) if start else a, min(b, end, snapshot) if end else min(b, snapshot)) for a, b in intervals if a and b]
    intervals = [(a, b) for a, b in intervals if b > a]
    report = {"schema_version": "tunemeter-usage/2.2.0", "collector_version": __version__, "source_collector_version": __version__,
        "snapshot_at": snapshot.astimezone(tz).isoformat(), "timezone": str(tz),
        "selected_start": start.astimezone(tz).isoformat() if start else None,
        "selected_end_exclusive": end.astimezone(tz).isoformat() if end else None,
        "billing": {"actual_amount": None, "currency": None, "estimate": None},
        "summary": {"files_read": files_read, "sessions_observed": sessions_observed, "sessions_with_usage": sessions_with_usage,
                    "completed_turns": len(turns) if codex_timing else None, "unfinished_turns": issues.get("unfinished_turns", 0) if codex_timing else None,
                    "turn_seconds": round(sum((b-a).total_seconds() for a, b in intervals), 3) if codex_timing else None,
                    "covered_seconds": engine.union_seconds(intervals) if codex_timing else None, **engine.sum_usage(events)},
        "models": [{"model": key, **engine.sum_usage(value), "turn_seconds": None, "covered_seconds": None} for key, value in sorted(models.items())],
        "daily": [{"date": key, **engine.sum_usage(value), "turn_seconds": None, "covered_seconds": None} for key, value in sorted(days.items())],
        "hourly": [{"hour_start": key, **engine.sum_usage(value)} for key, value in sorted(hours.items())],
        "usage_events": events, "turns": turns, "issues": dict(issues)}
    report["aggregation_validity"] = "limited" if any(s.get("aggregation_validity") == "unverified_lineage" for s in statuses) else "source_rules_applied"
    if codex_timing:
        # Keep measured Codex timing, including time-only rows. Other harnesses
        # contribute no invented duration; mixed coverage is declared explicitly.
        for section, key in (("models", "model"), ("daily", "date")):
            existing = {r[key]: r for r in report[section]}
            for row in codex_timing[section]:
                if row[key] not in existing:
                    existing[row[key]] = {key: row[key], **engine.sum_usage([])}
                existing[row[key]].update({k: row[k] for k in ("turn_seconds", "covered_seconds")})
            report[section] = [existing[k] for k in sorted(existing)]
    report.update(engine.analysis_metadata(report))
    tiers = Counter(e.get("configured_service_tier") for e in events)
    report["service_tier"] = {"status": "partially_observed" if any(k for k in tiers) else "unavailable",
        "source_availability": "source_specific", "billing_tier_confirmed": False, "billed_service_tier": None,
        "configured_tiers": [{"value": k, "usage_events": v} for k, v in sorted(tiers.items(), key=lambda x: x[0] or "")]}
    return enrich(report, statuses, selection_mode=selection_mode)
