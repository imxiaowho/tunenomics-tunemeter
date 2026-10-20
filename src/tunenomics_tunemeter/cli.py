"""TuneMeter's offline CLI; stdout is one result envelope."""
import argparse
from datetime import datetime, time, date, timedelta, timezone
from pathlib import Path
import json
import math
import os
import re
import sys
import uuid
from . import __version__, engine, codex, billing, submission, reports, registry
from .contracts import read_json, LOCAL_SCHEMA
from .providers.base import import_accounting, select_native, normalize


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes the offending argument; keep errors inert.
        raise ValueError("Invalid command arguments")


class SnapshotConsistencyError(ValueError):
    """Selected aggregate declarations conflict with retained event evidence."""

    def __init__(self, code, *, fields=(), event_index=None, source=None):
        sections = {"native_normalized_conflict": "usage_events",
                    "summary_aggregate_conflict": "summary",
                    "source_event_count_conflict": "source_inventory"}
        if code not in sections:
            raise ValueError("Unknown snapshot consistency category")
        super().__init__("Snapshot evidence conflicts with its declarations")
        self.details = {"code": code, "section": sections[code],
                        "fields": [key for key in fields if key in (*engine.FIELDS, "usage_events")]}
        if engine.number(event_index) is not None:
            self.details["event_index"] = event_index
        if source in registry.NAMES:
            self.details["source"] = source


def count(value):
    if value is not None and engine.number(value) is None:
        raise ValueError("Invalid usage counter")
    return value


def load_batch(path):
    path = Path(path).expanduser()
    raw = read_json(path / "summary.json" if path.is_dir() else path)
    if not isinstance(raw, dict) or not str(raw.get("schema_version", "")).startswith(("uco-codex-usage/", "tunemeter-usage/")):
        raise ValueError("Select a generated local usage batch")
    result = {"schema_version": raw["schema_version"]}
    for key in ("snapshot_at", "selected_start", "selected_end_exclusive"):
        result[key] = billing.instant(raw[key]).isoformat() if raw.get(key) else None
    if not result["snapshot_at"]:
        raise ValueError("Snapshot timestamp required")
    snapshot = billing.instant(result["snapshot_at"])
    result["timezone"] = str(snapshot.tzinfo)
    version = raw.get("source_collector_version", raw.get("collector_version"))
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Collector provenance required")
    result.update(collector_version=version, source_collector_version=version)
    def usage_row(row):
        if not isinstance(row, dict):
            raise ValueError("Invalid usage row")
        out = {key: count(row.get(key)) for key in engine.FIELDS}
        out["usage_events"] = count(row["usage_events"])
        if out["usage_events"] is None:
            raise ValueError("Event count required")
        out["missing_field_events"] = {k: count(row["missing_field_events"][k]) for k in engine.FIELDS}
        for key in ("turn_seconds", "covered_seconds"):
            if key in row:
                v = row[key]
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
                    raise ValueError("Invalid duration")
                out[key] = v
        return out
    result["summary"] = usage_row(raw["summary"])
    for key in ("files_read", "sessions_observed", "sessions_with_usage", "completed_turns", "unfinished_turns"):
        result["summary"][key] = count(raw["summary"][key])
    for section in ("models", "daily", "hourly"):
        result[section] = []
        for row in raw[section]:
            out = usage_row(row)
            if section == "models":
                out["model"] = engine.safe_label(row.get("model"))
            elif section == "daily":
                out["date"] = date.fromisoformat(row["date"]).isoformat()
            else:
                out["hour_start"] = billing.instant(row["hour_start"]).isoformat()
            result[section].append(out)
    if "usage_events" in raw and not isinstance(raw["usage_events"], list):
        raise ValueError("Snapshot event evidence must be an array or omitted")
    if isinstance(raw.get("usage_events"), list):
        events = []
        for event_index, row in enumerate(raw["usage_events"]):
            stamp = billing.instant(row["timestamp"])
            events.append({"timestamp": stamp.isoformat(), "date": stamp.date().isoformat(),
                           "model": engine.safe_label(row.get("model")),
                           "harness": row.get("harness", "codex") if row.get("harness", "codex") in registry.NAMES else "unknown",
                           "configured_service_tier": engine.safe_label(row["configured_service_tier"]) if row.get("configured_service_tier") else None,
                           **{k: count(row.get(k)) for k in engine.FIELDS}})
            declared = row.get("accounting")
            if declared is not None:
                spec = registry.providers.get(events[-1]["harness"]).SPEC
                events[-1]["accounting"] = import_accounting(spec, declared)
                if isinstance(row.get("native_usage"), dict) and spec.native_semantics == "per_event":
                    events[-1]["native_usage"] = select_native(spec, row["native_usage"])
                    normalized, _ = normalize(spec, events[-1]["native_usage"], {})
                    conflicts = [k for k in engine.FIELDS if events[-1][k] != normalized[k]]
                    if conflicts:
                        raise SnapshotConsistencyError("native_normalized_conflict", fields=conflicts,
                                                       event_index=event_index, source=events[-1]["harness"])
        result["usage_events"] = events
        observed = engine.sum_usage(events)
        conflicts = [key for key in ("usage_events", *engine.FIELDS) if result["summary"].get(key) != observed[key]]
        if conflicts:
            raise SnapshotConsistencyError("summary_aggregate_conflict", fields=conflicts)
    result["issues"] = {k: v for k, v in raw.get("issues", {}).items()
                        if re.fullmatch(r"[a-z_]{1,80}", k) and engine.number(v) is not None}
    result["billing"] = {"actual_amount": None, "currency": None, "estimate": None}
    result.update(engine.analysis_metadata(result))
    if version.startswith("3.") and isinstance(result.get("usage_events"), list):
        from collections import Counter
        tiers = Counter(e.get("configured_service_tier") for e in result["usage_events"])
        result["service_tier"] = {"status": "partially_observed" if tiers.get(None) and len(tiers) > 1 else "observed" if tiers and None not in tiers else "unavailable",
                                  "source_availability": "checked_selected_records", "billing_tier_confirmed": False,
                                  "billed_service_tier": None, "configured_tiers": [{"value": k, "usage_events": v} for k, v in sorted(tiers.items(), key=lambda x: x[0] or "")]}
    result["financials"] = raw.get("financials", {})
    if "source_inventory" in raw:
        statuses = []
        for item in raw["source_inventory"]:
            if item.get("source") not in registry.NAMES or item.get("status") not in registry.STATUSES:
                raise ValueError("Invalid source provenance")
            statuses.append({"source": item["source"], "status": item["status"],
                             "time_status": item.get("time_status") if item.get("time_status") in {"not_collected", "observed_intervals_only", "unavailable", "unknown"} else "unknown"})
            if item.get("aggregation_validity") in {"unverified_lineage", "declared_lineage_resolved", "adapter_accounting_only"}:
                statuses[-1]["aggregation_validity"] = item["aggregation_validity"]
            for key in ("files_read", "sessions_observed", "sessions_with_usage", "usage_events"):
                if key in item:
                    statuses[-1][key] = count(item[key])
        if not statuses or len(statuses) > len(registry.NAMES) or len({s["source"] for s in statuses}) != len(statuses):
            raise ValueError("Invalid source inventory")
        if any(e["harness"] not in {s["source"] for s in statuses} for e in result.get("usage_events", [])):
            raise ValueError("Event source conflicts with inventory")
        if "usage_events" in result:
            for source in statuses:
                observed_count = sum(e["harness"] == source["source"] for e in result["usage_events"])
                if source.get("usage_events") is not None and source["usage_events"] != observed_count:
                    raise SnapshotConsistencyError("source_event_count_conflict", fields=("usage_events",),
                                                   source=source["source"])
        raw_validity = raw.get("aggregation_validity")
        if raw_validity in {"source_rules_applied", "limited", "requires_recollection"}:
            result["aggregation_validity"] = raw_validity
        pi_events = [e for e in result.get("usage_events", []) if e["harness"] == "pi"]
        pi_present = bool(pi_events) or any(s["source"] == "pi" and (
            (s.get("usage_events") or 0) > 0 or "usage_events" not in result
            and s.get("usage_events") is None and result["summary"]["usage_events"] > 0) for s in statuses)
        if pi_present and (tuple(map(int, version.split("."))) < (3, 3, 1) or not pi_events or any(e.get("accounting", {}).get("contract_id") != registry.providers.get("pi").SPEC.contract_id for e in pi_events)):
            result["aggregation_validity"] = "requires_recollection"
            result["issues"]["legacy_pi_identity_scope_unverified"] = 1
        elif pi_present and (any(result["issues"].get(key) for key in registry.providers.get("pi").LINEAGE_FAILURES)
                             or any(s.get("aggregation_validity") == "unverified_lineage" for s in statuses)):
            result["aggregation_validity"] = "limited"
        context = raw.get("collection_context")
        mode = context.get("source_selection_mode") if isinstance(context, dict) else None
        registry.enrich(result, statuses, contract_basis="imported_snapshot",
                        selection_mode=mode if mode in {"all", "explicit"} else "unknown")
    return result


def evidence_records(path, batch):
    if path:
        value = read_json(path, maximum=1024 * 1024)
        if not isinstance(value, dict) or value.get("schema") != "tunemeter-evidence/1.0.0":
            raise ValueError("Select structured TuneMeter evidence")
        return value["records"]
    return batch.get("financials", {}).get("records", [])


def financials(batch, records):
    snapshot = billing.instant(batch["snapshot_at"])
    start = billing.instant(batch["selected_start"]) if batch.get("selected_start") else datetime.combine(
        date.fromisoformat(min((d["date"] for d in batch["daily"]), default=snapshot.date().isoformat())), time(), snapshot.tzinfo)
    end = min(snapshot, billing.instant(batch["selected_end_exclusive"])) if batch.get("selected_end_exclusive") else snapshot
    if end <= start:
        end = start
    result = billing.summarize(records, start, end)
    result["reference_estimate"].update(status="out_of_scope", responsible_party="Tunenomics")
    return result


def output_parent(path):
    path = Path(path).expanduser().absolute()
    # Verify existing ancestors before creating an output directory.
    if any(p.exists() and not engine.safe_path(p) for p in (path, *path.parents)):
        raise ValueError("Linked output paths are not allowed")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_local(batch, parent):
    parent = output_parent(parent)
    folder = parent / ("tunemeter-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    folder.mkdir()
    data = submission.project(batch, batch["financials"])
    (folder / "summary.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "usage-report.html").write_text(reports.render(batch, batch["financials"]), encoding="utf-8")
    (folder / "usage-report.md").write_text(submission.handoff(data), encoding="utf-8")
    (folder / "ts-ai-cost-intake.md").write_text(submission.handoff(data), encoding="utf-8")
    for name, fields in [("usage-events", ["timestamp", "date", "harness", "model", "configured_service_tier", *engine.FIELDS]),
                         ("daily", ["date", "usage_events", *engine.FIELDS, "turn_seconds", "covered_seconds"]),
                         ("hourly", ["hour_start", "usage_events", *engine.FIELDS]),
                         ("daily_by_model", ["date", "model", "usage_events", *engine.FIELDS]),
                         ("hourly_by_model", ["hour_start", "model", "usage_events", *engine.FIELDS]),
                         ("turns", ["session", "source", "line", "start", "end", "duration_seconds", "status"])]:
        engine.write_csv(folder / (name + ".csv"), batch.get("usage_events" if name == "usage-events" else name, []), fields)
    package = submission.write(data, folder) if submission.delivery(data)["status"] != "blocked" else None
    return folder, package


def main(argv=None):
    parser = Parser(description="TuneMeter — offline multi-harness usage collection; no price conversion")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "doctor", "collect", "report", "export"):
        p = sub.add_parser(name)
        p.add_argument("--format", choices=["json", "html"] if name == "report" else ["json"], default="json")
        if name in {"discover", "doctor", "collect"}:
            p.add_argument("--source", default="all", help="all or comma-separated registered harness identifiers")
            p.add_argument("--codex-home", type=Path)
            p.add_argument("--source-root", action="append", default=[], metavar="HARNESS=PATH", help="Override that harness's documented data root")
        if name == "collect":
            p.add_argument("--start", type=date.fromisoformat, help="First calendar date, inclusive, in --timezone")
            p.add_argument("--end", type=date.fromisoformat, help="Last calendar date, inclusive, in --timezone; collection stops at the snapshot")
            p.add_argument("--timezone", type=engine.offset, default=engine.offset("+08:00"))
        if name in {"report", "export"}:
            p.add_argument("--input", type=Path, required=True)
        if name in {"collect", "report", "export"}:
            p.add_argument("--output-dir", type=Path)
            p.add_argument("--billing-json", type=Path)
        if name == "export":
            p.add_argument("--profile", choices=["ts"], default="ts")
    result = {"schema": "tunemeter-result/1.0.0", "version": __version__, "status": "unknown", "pipeline_status": "not_started"}
    try:
        args = parser.parse_args(argv)
    except ValueError:
        result.update(status="error", issues=["Invalid command arguments"], error_kind="ArgumentError")
        print(json.dumps(result))
        return 2
    code = 0
    try:
        selected = getattr(args, "source", "all")
        unknown = selected != "all" and any(s not in registry.NAMES for s in selected.split(","))
        if unknown:
            result.update(status="not_implemented", source="unsupported", issues=["Requested harness adapter is not implemented"], supported_sources=list(registry.NAMES))
            code = 3
        elif args.command in {"discover", "doctor"}:
            locations = registry.roots(args.source_root, args.codex_home)
            result.update((registry.discover if args.command == "discover" else registry.doctor)(registry.selection(selected), locations))
            result["pipeline_status"] = "completed"
            code = 0 if result["status"] == "ready" else 4 if result["status"] == "partial" else 2 if result["status"] == "permission_denied" else 3
        else:
            if args.command == "collect":
                if args.start and args.end and args.end < args.start:
                    raise ValueError("End date precedes start")
                start = datetime.combine(args.start, time(), args.timezone).astimezone(timezone.utc) if args.start else None
                end = datetime.combine(args.end + timedelta(days=1), time(), args.timezone).astimezone(timezone.utc) if args.end else None
                if start and start > datetime.now(timezone.utc):
                    raise ValueError("Collection start is after snapshot")
                locations = registry.roots(args.source_root, args.codex_home)
                names = registry.selection(selected)
                source = registry.discover(names, locations)
                batch = registry.collect(names, locations, args.timezone, start, end,
                                         selection_mode="all" if selected == "all" else "explicit")
            else:
                batch = load_batch(args.input)
                source = {"status": "selected_generated_snapshot"}
            delivery = submission.delivery(batch)
            if args.command == "export" and delivery["status"] == "blocked":
                result.update(status="requires_recollection" if batch.get("aggregation_validity") == "requires_recollection" else "delivery_blocked", pipeline_status="not_exported",
                              issues=batch["issues"], artifacts={}, delivery=delivery,
                              aggregation_validity=batch.get("aggregation_validity", "unknown"),
                              summary=batch["summary"], by_source=batch.get("by_source", []),
                              provider_contracts=batch.get("provider_contracts", {}),
                              coverage_gaps=batch.get("coverage_gaps", []), warnings=batch.get("warnings", {}),
                              completion=batch.get("completion", {}), completion_note=submission.completion_note(batch))
                print(json.dumps(result, ensure_ascii=False))
                return 2
            batch["financials"] = financials(batch, evidence_records(args.billing_json, batch))
            parent = args.output_dir or (Path.home()/"TuneMeter"/"reports" if args.command == "collect" else args.input if args.input.is_dir() else args.input.parent)
            if args.command == "collect":
                folder, package = write_local(batch, parent)
                artifacts = {"output_directory": str(folder), "html_report": str(folder/"usage-report.html")}
                if package is not None:
                    artifacts["submission_package"] = str(package)
            elif args.command == "export":
                parent = output_parent(parent)
                package = submission.write(submission.project(batch, batch["financials"]), parent)
                artifacts = {"submission_package": str(package)}
            elif args.format == "json":
                result["report"] = submission.project(batch, batch["financials"])
                artifacts = {}
            else:
                parent = output_parent(parent)
                page = parent / ("TuneMeter-report-" + uuid.uuid4().hex[:8] + ".html")
                with page.open("x", encoding="utf-8") as stream:
                    stream.write(reports.render(batch, batch["financials"]))
                artifacts = {"html_report": str(page)}
            has_data = batch["summary"]["usage_events"] > 0 or (batch["summary"]["completed_turns"] or 0) > 0
            partial = source["status"] in {"partial", "permission_denied"} or registry.has_coverage_issues(batch["issues"]) or any(s["status"] in {"partial", "permission_denied", "error", "unsupported_format"} for s in batch.get("source_inventory", [])) or batch.get("completion", {}).get("collection_status", "unknown") != "observed_requested_metrics" or delivery["status"] == "blocked"
            code = 3 if not has_data else 4 if partial else 0
            snapshot = billing.instant(batch["snapshot_at"])
            effective_end = min(snapshot, billing.instant(batch["selected_end_exclusive"])) if batch["selected_end_exclusive"] else snapshot
            result.update(status="no_countable_data" if not has_data else "partial" if partial else "complete",
                          source=batch.get("identity_context", {}).get("harness", "codex"), sources=batch.get("source_inventory", []), period={"start": batch["selected_start"], "end_exclusive": batch["selected_end_exclusive"], "timezone": batch["timezone"],
                                                 "date_selection": "inclusive_calendar_dates", "effective_end_exclusive": effective_end.isoformat()},
                          snapshot_at=batch["snapshot_at"], coverage=batch["coverage"], issues=batch["issues"],
                          source_status=source["status"], artifacts=artifacts,
                          summary=batch["summary"], by_source=batch.get("by_source", []),
                          provider_contracts=batch.get("provider_contracts", {}),
                          warnings=batch.get("warnings", {}), coverage_gaps=batch.get("coverage_gaps", []), delivery=delivery,
                          completion_note=submission.completion_note(batch),
                          pipeline_status="completed", completion=batch.get("completion", {"collection_status": "unknown", "historical_completeness": "unknown"}),
                          aggregation_validity=batch.get("aggregation_validity", "unknown"), payment_status=batch["financials"]["payment_status"])
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
        # Never echo untrusted input, content, paths or native exception messages.
        result.update(status="error", pipeline_status="failed", issues=["Input/schema/date/permission validation failed"], error_kind=type(exc).__name__)
        if isinstance(exc, SnapshotConsistencyError):
            result["issues"] = ["快照记录与其声明不一致；请按 error_details 定位，选用完整原始批次或重新授权采集"]
            result["error_details"] = exc.details
        code = 1 if isinstance(exc, OSError) else 2
    print(json.dumps(result, ensure_ascii=False))
    return code
