#!/usr/bin/env python3
"""Collect allowlisted local Codex rollout metadata without exporting transcript text."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import zipfile
from importlib.resources import files as resource_files
from collections import Counter, defaultdict

VERSION = "3.3.5"
FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
          "output_tokens", "reasoning_output_tokens", "total_tokens")
CORE = ("input_tokens", "output_tokens", "total_tokens")
EVENTS = {"token_count", "task_started", "task_complete", "turn_started",
          "turn_complete", "turn_aborted", "thread_settings_applied"}
TOKEN_SCHEMA = dict.fromkeys(FIELDS, True)
SCHEMA = {"type": True, "timestamp": True, "ordinal": True, "payload": {
    "type": True, "id": True, "turn_id": True, "model": True,
    "cli_version": True, "forked_from_id": True,
    "subagent_history_start_ordinal": True,
    "started_at": True, "completed_at": True, "duration_ms": True,
    "thread_settings": {"service_tier": True},
    "info": {"total_token_usage": TOKEN_SCHEMA, "last_token_usage": TOKEN_SCHEMA}}}
STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)
CANDIDATE = re.compile(rb'"type"\s*:\s*"(?:session_meta|turn_context|token_count|task_started|task_complete|turn_started|turn_complete|turn_aborted|thread_settings_applied)"')
MAX_LINE = 32 * 1024 * 1024


def skip_value(text, pos):
    """Skip unselected JSON values without decoding their strings or containers."""
    pos = whitespace(text, pos)
    if pos >= len(text):
        raise ValueError("truncated")
    if text[pos] == '"':
        match = STRING.match(text, pos)
        if not match:
            raise ValueError("string")
        return match.end()
    if text[pos] in "[{":
        stack = ["]" if text[pos] == "[" else "}"]
        pos += 1
        while stack and pos < len(text):
            char = text[pos]
            if char == '"':
                pos = skip_value(text, pos)
                continue
            if char in "[{":
                stack.append("]" if char == "[" else "}")
            elif char in "]}":
                if char != stack.pop():
                    raise ValueError("container")
            pos += 1
        if stack:
            raise ValueError("truncated container")
        return pos
    while pos < len(text) and text[pos] not in ",}] \r\n\t":
        pos += 1
    return pos


def whitespace(text, pos):
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def project(text, schema, pos=0):
    """Decode only schema-selected JSON object fields, never transcript values."""
    pos = whitespace(text, pos)
    if text[pos:pos + 1] != "{":
        raise ValueError("object")
    result = {}
    pos += 1
    while True:
        pos = whitespace(text, pos)
        if text[pos:pos + 1] == "}":
            return result, pos + 1
        match = STRING.match(text, pos)
        if not match:
            raise ValueError("key")
        key = json.loads(match.group())
        pos = whitespace(text, match.end())
        if text[pos:pos + 1] != ":":
            raise ValueError("colon")
        pos = whitespace(text, pos + 1)
        selected = schema.get(key)
        if isinstance(selected, dict) and text[pos:pos + 1] == "{":
            value, pos = project(text, selected, pos)
            result[key] = value
        elif isinstance(selected, list) and text[pos:pos + 1] == "[":
            # Only explicitly selected metadata objects in arrays are decoded.
            values = []
            pos = whitespace(text, pos + 1)
            while text[pos:pos + 1] != "]":
                value, pos = project(text, selected[0], pos)
                values.append(value)
                pos = whitespace(text, pos)
                if text[pos:pos + 1] == "]":
                    break
                if text[pos:pos + 1] != ",":
                    raise ValueError("array separator")
                pos = whitespace(text, pos + 1)
            result[key] = values
            pos += 1
        elif selected is True:
            end = skip_value(text, pos)
            if text[pos:pos + 1] in "[{":
                result[key] = None  # Selected fields must be scalar.
            else:
                result[key] = json.loads(text[pos:end])
            pos = end
        else:
            pos = skip_value(text, pos)
        pos = whitespace(text, pos)
        char = text[pos:pos + 1]
        if char == "}":
            return result, pos + 1
        if char != ",":
            raise ValueError("separator")
        pos += 1


def instant(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def counters(value):
    if not isinstance(value, dict):
        return None
    result = {key: number(value.get(key)) for key in FIELDS}
    if any(result[k] is None for k in CORE):
        return None
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        return None
    for part, whole in (("cached_input_tokens", "input_tokens"),
                        ("reasoning_output_tokens", "output_tokens")):
        if result[part] is not None and result[part] > result[whole]:
            result[part] = None
    return result


def safe_label(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,79})?", value) else "unknown"


def alias(value):
    return "S-" + hashlib.sha256(str(value).encode()).hexdigest()[:12]


def safe_path(path):
    if path.is_symlink():
        return False
    try:
        return not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def discover(home):
    files = []
    for category in ("sessions", "archived_sessions"):
        root = home / category
        if not root.is_dir() or not safe_path(root):
            continue
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if safe_path(Path(current) / d))
            for name in sorted(names):
                path = Path(current) / name
                if path.suffix.lower() == ".jsonl" and safe_path(path):
                    files.append((category, path))
    return files


def read_rollout(path, file_alias, issues):
    records = []
    try:
        limit = path.stat().st_size
        with path.open("rb") as stream:
            remaining = limit
            line_number = 0
            while remaining > 0:
                raw = stream.readline(min(MAX_LINE + 1, remaining))
                if not raw:
                    break
                remaining -= len(raw)
                line_number += 1
                if len(raw) > MAX_LINE:
                    while not raw.endswith(b"\n") and remaining > 0:
                        raw = stream.readline(min(MAX_LINE + 1, remaining))
                        remaining -= len(raw)
                    issues["oversized_lines"] += 1
                    continue
                if not raw.endswith(b"\n"):
                    issues["incomplete_tail_lines"] += 1
                    continue
                if not CANDIDATE.search(raw):
                    continue
                try:
                    text = raw.decode("utf-8")
                    record, end = project(text, SCHEMA)
                    if text[end:].strip():
                        raise ValueError("trailing data")
                except (ValueError, UnicodeError, RecursionError, IndexError):
                    issues["malformed_selected_lines"] += 1
                    continue
                payload = record.get("payload")
                kind = record.get("type")
                if not isinstance(payload, dict):
                    continue
                if kind == "event_msg":
                    kind = payload.get("type")
                if kind not in EVENTS | {"session_meta", "turn_context"}:
                    continue
                stamp = instant(record.get("timestamp"))
                if stamp is None:
                    issues["missing_timestamps"] += 1
                    continue
                payload["_ordinal"] = number(record.get("ordinal"))
                records.append((stamp, kind, payload, file_alias, line_number))
        return records, limit
    except OSError:
        issues["unreadable_files"] += 1
        return [], None


def union_seconds(intervals):
    end = None
    total = 0.0
    for start, finish in sorted(intervals):
        if finish <= start:
            continue
        if end is None or start > end:
            total += (finish - start).total_seconds()
        elif finish > end:
            total += (finish - end).total_seconds()
        end = finish if end is None else max(end, finish)
    return round(total, 3)


def split_days(start, end, tz):
    while start < end:
        local = start.astimezone(tz)
        boundary = datetime.combine(local.date() + timedelta(days=1), time(), tz).astimezone(timezone.utc)
        finish = min(end, boundary)
        yield local.date().isoformat(), start, finish
        start = finish


def sum_usage(items):
    result = {}
    missing = {}
    for key in FIELDS:
        known = [item[key] for item in items if item[key] is not None]
        result[key] = sum(known) if known else None
        missing[key] = len(items) - len(known)
    return {"usage_events": len(items), **result, "missing_field_events": missing}


def collect(home, tz, start=None, end=None, snapshot=None):
    snapshot = snapshot or datetime.now(timezone.utc)
    cutoff_end = min(end, snapshot) if end else snapshot
    cutoff_start = start or datetime.min.replace(tzinfo=timezone.utc)
    issues = Counter()
    groups = {}
    inventory = []
    for index, (category, path) in enumerate(discover(home), 1):
        file_alias = f"F{index:04}"
        records, size = read_rollout(path, file_alias, issues)
        meta = next((r for r in records if r[1] == "session_meta"), None)
        identifier = meta[2].get("id") if meta else None
        # A missing identity must not merge unrelated files.
        key = identifier if isinstance(identifier, str) and identifier else file_alias
        group = groups.setdefault(key, {"records": [], "created": None, "forked": False, "files": [], "boundaries": {}})
        group["records"].extend(records)
        group["files"].append(file_alias)
        if meta:
            group["created"] = min(group["created"], meta[0]) if group["created"] else meta[0]
            group["forked"] |= bool(meta[2].get("forked_from_id"))
            group["boundaries"][file_alias] = number(meta[2].get("subagent_history_start_ordinal"))
        else:
            issues["files_without_session_metadata"] += 1
        inventory.append({"source": file_alias, "store": category, "snapshot_bytes": size,
                          "selected_metadata_records": len(records), "session": alias(key)})
    usage = []
    turns = []
    session_rows = []
    all_segments = []
    for identifier, group in groups.items():
        session = alias(identifier)
        model = "unknown"
        configured_tier = None
        active_turn = None
        contexts = []
        starts = {}
        completed = set()
        previous = None
        seen = set()
        session_usage = []
        session_intervals = []
        first = last = None
        for stamp, kind, payload, file_alias, line in sorted(group["records"], key=lambda r: (r[0], r[3], r[4])):
            if stamp > snapshot:
                issues["after_snapshot_records"] += 1
                continue
            fingerprint = (stamp, kind, json.dumps({k:v for k,v in payload.items() if k != "_ordinal"}, sort_keys=True, separators=(",", ":")))
            if fingerprint in seen:
                issues["copied_metadata_records"] += 1
                continue
            seen.add(fingerprint)
            inherited = bool(group["forked"] and group["created"] and stamp < group["created"])
            boundary = group["boundaries"].get(file_alias)
            ordinal = payload.get("_ordinal")
            if boundary is not None and ordinal is not None and ordinal < boundary:
                inherited = True
            reported_start = instant(payload.get("started_at"))
            if group["forked"] and reported_start and group["created"] and reported_start < group["created"] - timedelta(seconds=3):
                inherited = True
            if kind == "thread_settings_applied":
                settings = payload.get("thread_settings")
                tier = settings.get("service_tier") if isinstance(settings, dict) else None
                configured_tier = tier if isinstance(tier, str) and safe_label(tier) != "unknown" else None
                continue
            if inherited and kind != "token_count":
                issues["inherited_metadata_records"] += 1
                continue
            if kind == "turn_context":
                model = safe_label(payload.get("model"))
                contexts.append((stamp, model))
                if isinstance(payload.get("turn_id"), str):
                    active_turn = payload["turn_id"]
            elif kind in ("task_started", "turn_started"):
                if inherited:
                    continue
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str):
                    issues["starts_without_turn_id"] += 1
                    continue
                active_turn = turn_id
                starts.setdefault(turn_id, stamp)
            elif kind == "token_count":
                info = payload.get("info")
                current = counters(info.get("total_token_usage")) if isinstance(info, dict) else None
                last_usage = counters(info.get("last_token_usage")) if isinstance(info, dict) else None
                if current is None:
                    issues["invalid_or_missing_counters"] += 1
                    continue
                prior = previous
                previous = current
                if inherited:
                    issues["inherited_usage_snapshots"] += 1
                    continue
                if prior is None:
                    delta = current.copy()
                    if last_usage is None or any(delta[k] != last_usage[k] for k in CORE):
                        issues["initial_baseline_excluded"] += 1
                        continue
                else:
                    delta = {k: current[k] - prior[k] if current[k] is not None and prior[k] is not None else None for k in FIELDS}
                    if any(value is not None and value < 0 for value in delta.values()):
                        issues["counter_reset_baselines_excluded"] += 1
                        continue
                    if not any(delta[k] for k in CORE):
                        issues["repeated_cumulative_snapshots"] += 1
                        continue
                    if delta["total_tokens"] != delta["input_tokens"] + delta["output_tokens"]:
                        issues["inconsistent_deltas_excluded"] += 1
                        continue
                    if last_usage is not None and any(delta[k] != last_usage[k] for k in CORE):
                        # Keep the measured cumulative increment, flag batched/ambiguous provenance.
                        issues["delta_differs_from_last_usage"] += 1
                if not cutoff_start <= stamp <= cutoff_end:
                    continue
                entry = {"timestamp": stamp.astimezone(tz).isoformat(timespec="milliseconds"),
                         "date": stamp.astimezone(tz).date().isoformat(), "session": session,
                         "model": model, "configured_service_tier": configured_tier, "source": file_alias, "line": line, **delta}
                usage.append(entry)
                session_usage.append(entry)
                first = stamp if first is None else min(first, stamp)
                last = stamp if last is None else max(last, stamp)
            elif kind in ("task_complete", "turn_complete", "turn_aborted"):
                if inherited:
                    continue
                turn_id = payload.get("turn_id") or active_turn
                if not isinstance(turn_id, str):
                    issues["terminals_without_turn_id"] += 1
                    continue
                if turn_id in completed:
                    issues["repeated_turn_terminals"] += 1
                    continue
                completed.add(turn_id)
                begin = starts.get(turn_id) or instant(payload.get("started_at"))
                finish = instant(payload.get("completed_at")) or stamp
                duration = number(payload.get("duration_ms"))
                if begin is None:
                    issues["turns_without_start_time"] += 1
                    continue
                if duration is not None:
                    try:
                        finish = begin + timedelta(milliseconds=duration)
                    except OverflowError:
                        issues["invalid_turn_intervals"] += 1
                        continue
                    if abs((finish - stamp).total_seconds()) > 3:
                        issues["duration_timestamp_disagreements_excluded"] += 1
                        continue
                if finish < begin:
                    issues["invalid_turn_intervals"] += 1
                    continue
                begin = max(begin, cutoff_start, group["created"] or begin)
                finish = min(finish, cutoff_end)
                if finish <= begin:
                    continue
                interval = (begin, finish)
                session_intervals.append(interval)
                turns.append({"session": session, "source": file_alias, "line": line,
                              "start": begin.astimezone(tz).isoformat(timespec="milliseconds"),
                              "end": finish.astimezone(tz).isoformat(timespec="milliseconds"),
                              "duration_seconds": round((finish - begin).total_seconds(), 3),
                              "status": "aborted" if kind == "turn_aborted" else "completed"})
                first = begin if first is None else min(first, begin)
                last = finish if last is None else max(last, finish)
        for begin, finish in session_intervals:
            boundaries = [(begin, "unknown")]
            for context_stamp, context_model in contexts:
                if context_stamp <= begin:
                    boundaries[0] = (begin, context_model)
                elif context_stamp < finish:
                    boundaries.append((context_stamp, context_model))
            for index, (segment_start, segment_model) in enumerate(boundaries):
                segment_end = boundaries[index + 1][0] if index + 1 < len(boundaries) else finish
                for day, a, b in split_days(segment_start, segment_end, tz):
                    all_segments.append((day, segment_model, a, b))
        incomplete = sum(cutoff_start <= value <= cutoff_end for key, value in starts.items() if key not in completed)
        issues["unfinished_turns"] += incomplete
        session_rows.append({"session": session, "source_files": group["files"],
                             "forked": group["forked"], "models": sorted({x["model"] for x in session_usage}),
                             "first_observed": first.astimezone(tz).isoformat() if first else None,
                             "last_observed": last.astimezone(tz).isoformat() if last else None,
                             "completed_turns": len(session_intervals), "unfinished_turns": incomplete,
                             "turn_seconds": round(sum((b-a).total_seconds() for a,b in session_intervals),3),
                             **sum_usage(session_usage)})
    model_groups = defaultdict(list)
    daily_groups = defaultdict(list)
    hourly_groups = defaultdict(list)
    for entry in usage:
        model_groups[entry["model"]].append(entry)
        daily_groups[entry["date"]].append(entry)
        hour = datetime.fromisoformat(entry["timestamp"]).replace(minute=0, second=0, microsecond=0).isoformat()
        hourly_groups[hour].append(entry)
    for day, model, _, _ in all_segments:
        model_groups.setdefault(model, [])
        daily_groups.setdefault(day, [])
    models = []
    for model, items in sorted(model_groups.items()):
        intervals = [(a,b) for _,m,a,b in all_segments if m==model]
        models.append({"model":model, **sum_usage(items),
                       "turn_seconds":round(sum((b-a).total_seconds() for a,b in intervals),3),
                       "covered_seconds":union_seconds(intervals)})
    days = []
    for day, items in sorted(daily_groups.items()):
        intervals = [(a,b) for d,_,a,b in all_segments if d==day]
        days.append({"date":day, **sum_usage(items),
                     "turn_seconds":round(sum((b-a).total_seconds() for a,b in intervals),3),
                     "covered_seconds":union_seconds(intervals)})
    intervals = [(a,b) for _,_,a,b in all_segments]
    hours = [{"hour_start":hour, **sum_usage(items)} for hour, items in sorted(hourly_groups.items())]
    report = {"schema_version":"uco-codex-usage/2.3.0", "collector_version":VERSION,
            "snapshot_at":snapshot.astimezone(tz).isoformat(timespec="microseconds"),
            "timezone":str(tz), "selected_start":start.astimezone(tz).isoformat() if start else None,
            "selected_end_exclusive":end.astimezone(tz).isoformat() if end else None,
            "billing":{"actual_amount":None,"currency":None,"estimate":None},
            "summary":{"files_read":len(inventory), "sessions_observed":len(groups),
                       "sessions_with_usage":sum(bool(s["usage_events"]) for s in session_rows),
                       "completed_turns":len(turns), "unfinished_turns":issues["unfinished_turns"],
                       "turn_seconds":round(sum((b-a).total_seconds() for a,b in intervals),3),
                       "covered_seconds":union_seconds(intervals), **sum_usage(usage)},
            "models":models, "daily":days, "hourly":hours, "sessions":session_rows, "sources":inventory,
            "issues":dict(sorted(issues.items())), "usage_events":usage, "turns":turns}
    report.update(analysis_metadata(report))
    return report


def analysis_metadata(report):
    """Derive only aggregate metadata; never equate event deltas with requests."""
    events = report.get("usage_events")
    available = isinstance(events, list)
    observations = {}
    for key in FIELDS:
        missing = report["summary"]["missing_field_events"].get(key)
        samples = report["summary"]["usage_events"]
        known = samples - missing if missing is not None else None
        value = report["summary"].get(key)
        observations[key] = {
            "source": f"event_msg.info.total_token_usage.{key} cumulative differences",
            "status": "no_samples" if not samples else "unavailable" if known == 0 else
                      "partially_observed" if missing else "observed",
            "sample_unit": "usage_event_delta", "eligible_events": samples,
            "known_events": known, "missing_events": missing,
            "observed_total": value,
            "zero_value_events": sum(e.get(key) == 0 for e in events) if available else None,
            "billing_semantics": "unconfirmed",
        }
    daily = defaultdict(list)
    hourly = defaultdict(list)
    inputs = []
    if available:
        for event in events:
            model = safe_label(event.get("model"))
            stamp = datetime.fromisoformat(event["timestamp"])
            daily[(stamp.date().isoformat(), model)].append(event)
            hourly[(stamp.replace(minute=0, second=0, microsecond=0).isoformat(), model)].append(event)
            value = number(event.get("input_tokens"))
            if value is not None:
                inputs.append(value)
    inputs.sort()
    distribution = {
        "status": "observed" if inputs else "no_samples" if available else "unavailable_in_snapshot",
        "sample_unit": "usage_event_delta", "field": "input_tokens",
        "sample_count": len(inputs) if available else None,
        "missing_events": len(events) - len(inputs) if available else None,
        "method": "nearest_rank", "request_level": False,
        **{f"p{p}": inputs[math.ceil(len(inputs) * p / 100) - 1] if inputs else None
           for p in (50, 90, 95, 99)},
        "max": inputs[-1] if inputs else None,
    }
    snapshot = datetime.fromisoformat(report["snapshot_at"])
    start = datetime.fromisoformat(report["selected_start"]) if report.get("selected_start") else None
    requested_end = datetime.fromisoformat(report["selected_end_exclusive"]) if report.get("selected_end_exclusive") else None
    end = min(snapshot, requested_end) if requested_end else snapshot
    first_day = min((d["date"] for d in report["daily"]), default=None)
    window_start = start or (datetime.fromisoformat(first_day).replace(tzinfo=snapshot.tzinfo) if first_day else None)
    bucket_count = None
    if window_start and end > window_start:
        floor = window_start.replace(minute=0, second=0, microsecond=0)
        bucket_count = math.ceil((end - floor).total_seconds() / 3600)
    daily_windows = []
    for row in report["daily"]:
        begin = datetime.fromisoformat(row["date"]).replace(tzinfo=snapshot.tzinfo)
        finish = begin + timedelta(days=1)
        daily_windows.append({"date": row["date"],
                              "window_start_truncated": bool(start and begin < start < finish),
                              "window_end_truncated": begin < end < finish,
                              "historical_completeness": "unknown"})
    return {
        "field_observations": observations,
        "service_tier": {"status": "not_collected", "value": None,
                         "source_availability": "not_verified", "billing_tier_confirmed": False},
        "data_semantics": {
            "missing_field_events": "missing optional counters among counted usage events, not all scanned records",
            "null_tokens_with_zero_events": "no counted usage samples; not proven zero consumption",
            "unknown_model": "missing or invalid configuration label at event or time segment; not free or tool-only usage",
            "time_only_model_rows": "ended intervals may exist without counted token events; token and time evidence differ",
            "cache_write": "observed zero is not confirmation of no platform cache-write charge",
            "model_time_union": "per-model covered_seconds can overlap; do not sum as global covered_seconds",
            "csv": {"encoding": "utf-8-sig", "bom": True, "null": "empty cell means unknown/no samples, never zero"},
            "distribution": "event-delta sizes do not establish request input sizes or long-context repricing",
        },
        "input_size_distribution": distribution,
        "model_time_series": {"status": "derived" if available else "unavailable_in_snapshot",
                              "source": "allowlisted local usage events", "time_basis": "record_timestamp",
                              "first_observed_is_release_date": False},
        "daily_by_model": [{"date": day, "model": model, **sum_usage(items)}
                           for (day, model), items in sorted(daily.items())],
        "hourly_by_model": [{"hour_start": hour, "model": model, **sum_usage(items)}
                            for (hour, model), items in sorted(hourly.items())],
        "coverage": {"historical_completeness": "unknown",
                     "window_start": window_start.isoformat() if window_start else None,
                     "window_start_basis": "selected_filter" if start else "first_observed_day_not_history_start",
                     "window_end": end.isoformat(), "window_end_basis": "snapshot_or_selected_end",
                     "daily_windows": daily_windows,
                     "hourly_observation": {"observed_buckets": len(report["hourly"]),
                                            "window_buckets": bucket_count,
                                            "missing_bucket_semantics": "no counted events observed; not proven zero or missing history",
                                            "is_completeness_ratio": False}},
    }


def format_number(value):
    return "未知" if value is None else f"{value:,}"


def intake(report, submission=False):
    """Fill the shared handoff template using only projected aggregate metadata."""
    s = report["summary"]
    seconds_text = lambda key: "未知" if s[key] is None else f"{s[key]:.3f}"
    available = "可提供（范围受限）" if s["usage_events"] else "未提供"
    period = (f"筛选起点：{report['selected_start'] or '全部可用历史'}；"
              f"筛选截止（不含）：{report['selected_end_exclusive'] or '未指定'}；"
              f"快照：{report['snapshot_at']}；{report['timezone']}；非确认账期")
    readiness = [
        ("实际金额与账期", "未提供", "L1 /billing：金额、币种均未知", "指定账单页面、平台费用记录或付款凭证"),
        ("请求数与平均费用", "未提供", "事件数和轮次数不是请求分母", "平台请求统计及相同范围的费用"),
        ("模型与项目集中度", "部分提供" if s["usage_events"] else "未提供", "L1 /models：配置标签；业务项目未知", "计费模型及客户确认的中性项目映射"),
        ("逐日／小时用量与金额", "部分提供" if s["usage_events"] else "未提供", "L1 /daily、/hourly：事件时点用量；金额未知", "对应时段费用及账单时区"),
        ("输入／缓存／输出计费拆分", "部分提供" if s["usage_events"] else "未提供", "L1 /summary：记录计数，非计费类别", "类别费用；请求估算时补适用历史费率"),
        ("处理档位", "未采集", "L1 /service_tier：原记录可得性未核验，实际档位未知", "客户选定的匹配平台费用／响应档位证据；不扫描请求头"),
        ("模型的时间分布", "可提供" if report.get("daily_by_model") else "未提供", "L1 /daily_by_model、/hourly_by_model：配置标签与记录时点", "本机首次观测不等于官方发布日期；不能证明计费模型"),
        ("输入量分布", "部分提供" if report.get("input_size_distribution", {}).get("sample_count") else "未提供", "L1 /input_size_distribution：用量事件差值分位，非请求级", "单请求输入量及适用规则；事件分位不能判定长上下文重定价"),
        ("缓存／材料复用原因", "未提供", "缓存计数不能证明材料重复或可缓存", "另行授权的缓存／复用证据，当前未自动采集"),
        ("优化前后节省与质量", "未提供", "没有干预和任务验收证据", "匹配任务的前后用量、费用、验收和重试记录"),
        ("用量来源与覆盖", available, "L1 /sources、/issues；事件 CSV 的 source/line", "无法补回已删除、其他机器及未落盘记录"),
    ]
    missing = "; ".join(f"{key}: {value}" for key, value in s["missing_field_events"].items())
    values = {
        "generated_at": f"{report['snapshot_at']}；{report['timezone']}",
        "status": "部分完成：仅本机观测用量；账单输入未提供" if s["usage_events"] else "部分完成：未取得可计入用量；不代表零使用",
        "processing_path": "标准库脚本本机处理，无网络／模型调用；在云端 Agent 打开本材料可能向该模型传递汇总内容",
        "provider_product": "Codex 本机记录；采购渠道未知", "evidence": "L1 /sources",
        "period": period, "billing_type": "未知；不从本机记录推断订阅或 API", "currency_unit": "币种未知；tokens、秒",
        "coverage": "仅授权 Codex home 的 sessions／archived_sessions；筛选后可确认记录",
        "source_alias": "L1", "format": "生成的 summary.json、usage-events.csv、turns.csv、daily.csv、hourly.csv、daily_by_model.csv、hourly_by_model.csv",
        "location": "summary.json /sources 的 F 别名；事件／轮次 CSV 的 source、line 对应原始记录定位",
        "source_status": f"{s['files_read']} 份来源，{s['sessions_observed']} 个会话；本机观测，非账单",
        "unprocessed": "正文、工具、身份、路径与凭据排除；其他账号／机器／云端历史未读取",
        "source_ref": "L1 /summary；原始事件定位见 usage-events.csv source/line",
        "source_field": "total_token_usage 的允许计数；turn_context.model；生命周期字段",
        "standard_field": "input_tokens、cached_input_tokens、output_tokens、total_tokens、配置模型与轮次时间",
        "semantics": "累计快照差值；缓存／推理属于输入／输出子集；结束轮次墙钟区间",
        "handling": "重复／继承／不明基线按既有规则排除；配置标签非确认的计费模型；可选字段可能仅有部分覆盖",
        "model": "配置模型分项见 L1 /models", "usage_field": "input / cached input / output / total",
        "value": " / ".join(format_number(s[k]) for k in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")),
        "unit": "tokens", "counting_semantics": "累计差值；可选字段仅为已知部分，不补零、不叠加子集",
        "usage_totals_and_limits": f"计数详见 L1 /summary；字段缺失事件：{missing}。用量事件 {s['usage_events']}，已结束轮次 {format_number(s['completed_turns'])}，均不当作请求数。轮次累计 {seconds_text('turn_seconds')} 秒，并发去重 {seconds_text('covered_seconds')} 秒；含工具和等待，不代表人类注意力。",
        "amount_type": "未知", "amount": "未提供", "currency": "未提供", "record_kind": "未提供正式账单、平台费用或付款凭证",
        "billed_total_basis": "未知；本机 token 不换算为实际金额", "plan_cycle": "未提供",
        "plan_fee": "未提供", "seats": "未提供", "quotas": "未提供", "expiry_limits": "未提供",
        "estimate_status": "未估算", "formula": "不适用；未取得可适用的计费模型与费率",
        "rates": "未提供", "estimate_limits": "订阅用量不按 API 单价认定实付或现金节省",
        "estimate_vs_bill": "本材料没有费用估算或账单金额",
        "issue": "缺失与排除项见 L1 /issues、/summary/missing_field_events", "action": "保留原因与数量；不明值不补零",
        "impact": "仅可确认用量；不承诺完整账单覆盖",
        "redacted_categories": "对话／工具正文、工作路径、原始身份标识、账号和凭据不进入输出",
        "retained_fields": "时间、配置模型、计数、区间、中性别名与来源行号",
        "aliases": "L1 为本次生成数据；F 为来源文件序号，跨批次不稳定；会话为哈希别名",
        "source_handling": "原始记录不改写、不复制、不上传；每次新建个人报告批次",
        "privacy_limits": "时间、模型与规模仍可能敏感；别名不保证匿名；分享前检查",
        "requested_items": "- 仅需用量统计时，无须补材料。\n- 需要费用或完整报告时，先复用已选账单页面／付款证据和已知采购方式，无须先手动导出。\n- 缺少来源时按第 13 节标记缺口并交付；不扫描账号、项目目录或其他存储。",
        "confidence": "来源为允许字段的确定性汇总；排除和缺失见数据文件；账单关联尚未建立",
        "evidence_limits": "本机记录与计算结果，不包含客户采购声明、金额或干预假设",
        "conclusion_limits": "真实请求数、计费模型、项目、实际费用、质量和节省未知；当前轮次后续消耗不在快照内",
        "report_readiness_rows": "\n".join("| " + " | ".join(row) + " |" for row in readiness),
    }
    values["usage_totals_and_limits"] += (
        " 字段观测状态见 /field_observations；处理档位为未采集、源可得性未核验。"
        " 模型×日期／小时见 daily_by_model.csv、hourly_by_model.csv。"
        " 输入分布为用量事件差值的 nearest-rank 分位，不是请求大小。")
    values["issue"] += (
        "；缓存写入观测为 0 不证明平台无写入费。missing_field_events 只统计已计入事件中的字段缺失；"
        "0 个事件时 token=null 与缺失事件数=0 可同时成立。unknown 表示缺少有效配置标签，"
        "有耗时不代表未计费、纯工具调用或已知零 token。")
    values["coverage"] += (
        "；/coverage 标明快照／筛选窗口截断，历史完整度未知；少活跃小时不能判定不完整，"
        "未出现的小时不代表已确认零使用。CSV 为 UTF-8 BOM，空单元表示未知／无样本。")
    if report.get("model_time_series", {}).get("status") == "unavailable_in_snapshot":
        values["usage_totals_and_limits"] += " 原快照不含事件，新分模型时间表及分布不可得；空表不代表零使用。"
    if submission:
        values.update({
            "generated_at": f"{report['packaged_at']}；用量快照 {report['snapshot_at']}",
            "format": "包内 summary.json、models.csv、daily.csv、hourly.csv、daily_by_model.csv、hourly_by_model.csv",
            "location": "summary.json /summary、/models、/daily、/hourly、/daily_by_model、/hourly_by_model、/field_observations、/coverage、/issues；原始行级定位在本机留存",
            "source_ref": "L1 summary.json /summary；本包提供汇总证据",
            "aliases": "L1 为包内汇总；逐事件、会话别名、来源文件别名和轮次明细不在本包内",
            "retained_fields": "快照、日期、小时、配置模型及其交叉汇总、事件输入量分位、计数／时长和缺失／排除数量；没有会话、单事件或轮次区间",
            "source_status": f"{s['files_read']} 份本机记录的派生汇总；原始记录未附入，不等于账单",
            "handling": "累计差值与排除规则由本地采集器执行；包内汇总支持复算汇总关系，不支持原始行级核验",
            "conclusion_limits": "本包仅提供本机汇总；原始行级来源不随包提供。真实请求数、计费模型、项目、实际费用、质量和节省未知；后续消耗不在快照内",
            "report_readiness_rows": "\n".join("| " + " | ".join(row) + " |" for row in [
                *readiness[:-1], ("用量来源与覆盖", available, "L1 /sources、/issues；包内只含派生汇总", "原始行级记录留在本机，包内无法独立核验")]),
        })
    if report.get("collection_context"):
        harnesses = ", ".join(report["collection_context"]["harnesses"])
        values.update(provider_product=f"本机 Harness 记录：{harnesses}；采购渠道未知",
                      coverage="仅所选已实现适配器的已知用量目录；各来源状态见 /source_inventory；历史完整度未知",
                      source_field="各底座白名单数值字段，口径见 /collection_context 和本机 native_usage",
                      semantics="按底座原始口径保留计数；规范化只在组成字段已知时执行；不做价格换算",
                      counting_semantics="Codex 累计差值与其他底座消息观测混合；缺失为未知，不补零",
                      handling="按底座去重；冲突记录排除；跨底座镜像关系未确认；原始逐行证据留在本机",
                      formula="范围之外：价格换算交由元舵", rates="本工具不采集费率")
        values["usage_totals_and_limits"] += " 时间只覆盖 Codex 已结束区间；其他底座尚未采集时间，绝非零时长。跨底座镜像记录可能重复，不把汇总当作无重叠全量。"
        values["retained_fields"] += "；Harness 标识和各底座聚合／状态"
        if report.get("provider_contracts"):
            values["usage_totals_and_limits"] += " /provider_contracts 分列原生／有效计数口径、字段采集能力与观测状态；未采集和缺失均不自动表示计费不适用。旧快照的原契约可能不可得。"
        if "not_collected_field_events" in s:
            values["usage_totals_and_limits"] += " missing_field_events 仅统计契约支持而值缺失的观测；not_collected_field_events、eligibility_unknown_field_events 分列未采集和资格未知；unobserved_field_events 统计所有空值。"
    template = (resource_files(__package__) / "assets" / "intake-template.md").read_text(encoding="utf-8")
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda match: values[match[1]].replace("|", "／") if match[1] != "report_readiness_rows" else values[match[1]], template)


def markdown(report):
    s = report["summary"]
    lines = ["# Tunenomics UCO · Codex 本机用量报告", "", f"快照时间：{report['snapshot_at']}；版本：{VERSION}", "",
             f"扫描 {s['files_read']} 份记录，识别 {s['sessions_observed']} 个会话，其中 {s['sessions_with_usage']} 个有可计入用量。",
             f"记录 token 合计：**{format_number(s['total_tokens'])}**（输入 {format_number(s['input_tokens'])}；输出 {format_number(s['output_tokens'])}）。",
             f"已结束轮次：{s['completed_turns']}；轮次耗时累计：**{s['turn_seconds']/3600:.2f} 小时**；并发去重后的覆盖时间：**{s['covered_seconds']/3600:.2f} 小时**。", "",
             "缓存输入属于输入子集，推理输出属于输出子集，不再加进 token 合计。模型按最近 turn_context 的配置标签归属，不保证等于服务端计费模型。",
             "时间包含模型执行、工具和等待；不是人类在线时间或纯模型计算时间。未结束轮次单列，不推算耗时。实付金额、币种和费率估算均未知。", "",
             "## 按模型", "", "| 配置模型 | 输入 | 缓存输入 | 输出 | 推理输出 | 合计 | 轮次耗时（小时） |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for m in report["models"]:
        lines.append("| " + " | ".join([m["model"],*[format_number(m[k]) for k in ("input_tokens","cached_input_tokens","output_tokens","reasoning_output_tokens","total_tokens")],f"{m['turn_seconds']/3600:.2f}"]) + " |")
    lines += ["", "## 按日", "", "| 日期 | token 合计 | 轮次耗时（小时） | 并发去重覆盖（小时） |", "| --- | ---: | ---: | ---: |"]
    for d in report["daily"]:
        lines.append(f"| {d['date']} | {format_number(d['total_tokens'])} | {d['turn_seconds']/3600:.2f} | {d['covered_seconds']/3600:.2f} |")
    lines += ["", "逐小时用量见 hourly.csv；按 token 记录时点分桶，事件数不是请求数，也没有小时费用。",
              "提交元舵时，检查并上传 [元舵提交包.zip](元舵提交包.zip)，无需自行选择和压缩明细文件。",
              "模型×时间见 daily_by_model.csv、hourly_by_model.csv；输入事件分布、字段观测状态及窗口见 summary.json。",
              "处理档位未采集；缓存写入零值不证明无写入费；事件输入分位不是请求大小。",
              "历史完整度未知；空小时不证明零用量；CSV 为 UTF-8 BOM，空值表示未知／无样本。",
              "unknown 有时间无事件时，token=null 与缺失事件数=0 不矛盾；不能认定未计费或纯工具调用。",
              "报告输入与待补来源见 [标准交付材料](ts-ai-cost-intake.md)。", ""]
    lines += ["", "## 覆盖与限制", "", "- 只扫描本次 Codex home 的 sessions 和 archived_sessions；删除的历史、其他电脑、云端任务及未落盘事件不在覆盖内。",
              "- 日归属取 token 事件的记录时间；长请求可能跨日。轮次时间按区间分日，不按整段会话跨度或最后修改时间计算。",
              "- 来源采用中性文件/会话别名，事件 CSV 保留行号；不导出原始 ID、工作路径、对话正文、工具内容或凭据。",
              "- 首次不明累计基线、计数重置和无效数据会被排除并告警；有排除时结果仅为可确认部分，不承诺全量。",
              "- 缺失可选计数字段不填零，JSON 中记录每字段缺失事件数；CSV 空值表示未知。",
              f"- 未结束轮次：{s['unfinished_turns']}。当前采集轮次后续发生的消耗不会进入此快照。", ""]
    if not s["files_read"]:
        lines += ["未找到可读取的本机 JSONL 使用记录，请核对 Codex home 或历史保存状态。", ""]
    lines += ["| 检查项 | 数量 |", "| --- | ---: |"]
    for key,value in report["issues"].items():
        if value:
            lines.append(f"| {key} | {value} |")
    lines += ["", "本地脚本不连接网络、不调用模型；原始记录留在本机。若在 Agent 中打开报告，报告汇总可能进入该 Agent 的模型服务。分享前请复核日期、模型标签和覆盖限制。", ""]
    return "\n".join(lines)


def dashboard(report):
    summary = report["summary"]
    peak = max((m["total_tokens"] or 0 for m in report["models"]), default=1) or 1
    bars = "".join(f'<div class="bar"><span>{html.escape(m["model"])}</span><b>{format_number(m["total_tokens"])}</b><i style="width:{100*(m["total_tokens"] or 0)/peak:.2f}%"></i></div>' for m in report["models"])
    rows = "".join(f"<tr><td>{d['date']}</td><td>{format_number(d['total_tokens'])}</td><td>{d['turn_seconds']/3600:.2f}</td><td>{d['covered_seconds']/3600:.2f}</td></tr>" for d in report["daily"])
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tunenomics UCO · Codex 本机用量</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f4f6fa;color:#172437}}main{{max-width:980px;margin:40px auto;padding:24px}}.cards{{display:flex;gap:16px;flex-wrap:wrap}}.card{{background:white;padding:20px;border-radius:12px;flex:1;min-width:180px}}strong{{display:block;font-size:28px;margin-top:12px}}.bar{{position:relative;padding:16px 0 22px;margin:12px 0}}.bar b{{float:right}}i{{display:block;height:8px;background:#3273dc;position:absolute;bottom:0;border-radius:4px}}table{{width:100%;border-collapse:collapse;background:white;margin:20px 0}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #ddd}}small,p{{line-height:1.7}}@media(max-width:600px){{main{{margin:0;padding:16px}}table{{font-size:12px}}td,th{{padding:8px}}}}</style>
<main><h1>Tunenomics UCO</h1><p>Codex 本机用量 · {html.escape(report['snapshot_at'])}</p><div class="cards"><div class="card">记录 token 合计<strong>{format_number(summary['total_tokens'])}</strong></div><div class="card">有用量会话<strong>{summary['sessions_with_usage']}</strong></div><div class="card">并发去重覆盖<strong>{summary['covered_seconds']/3600:.2f} 小时</strong></div></div><h2>配置模型分布</h2>{bars}<h2>按日记录</h2><table><tr><th>日期</th><th>Token</th><th>轮次耗时 / 小时</th><th>去重覆盖 / 小时</th></tr>{rows}</table><p>轮次耗时包含工具和等待，并发覆盖是已结束轮次区间的并集。不是人类在线时长。配置模型标签与服务端计费模型未核验；缓存和推理子集不重复相加；实付金额未知。</p><p>覆盖、排除及缺失项请阅读同目录 usage-report.md；详细数据在 JSON/CSV 中。本页无网络请求或外部资源。</p></main></html>'''


def write_csv_rows(stream, rows, fields):
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        safe = {}
        for key in fields:
            value = row.get(key)
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)


def write_csv(path, rows, fields):
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        write_csv_rows(stream, rows, fields)


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    write_csv_rows(stream, rows, fields)
    return stream.getvalue().encode("utf-8-sig")


def submission_summary(report):
    """Allowlist aggregates; never copy the full local JSON into a submission."""
    def pick(row, keys):
        return {key: row.get(key) for key in keys}

    counts = ["usage_events", *FIELDS]
    timings = ["turn_seconds", "covered_seconds"]
    totals = pick(report["summary"], ["files_read", "sessions_observed", "sessions_with_usage",
                  "completed_turns", "unfinished_turns", *counts, *timings])
    totals["missing_field_events"] = pick(report["summary"]["missing_field_events"], FIELDS)
    result = pick(report, ["snapshot_at", "timezone", "selected_start", "selected_end_exclusive"])
    result.update({"schema_version": "uco-submission/1.2.0", "packager_version": VERSION,
                   "packaged_at": datetime.now(datetime.fromisoformat(report["snapshot_at"]).tzinfo).isoformat(timespec="seconds"),
                   "source_collector_version": report["collector_version"],
                   "billing": pick(report["billing"], ["actual_amount", "currency", "estimate"]),
                   "summary": totals,
                   "sources": {"record_files": totals["files_read"], "scope": ["sessions", "archived_sessions"],
                               "kind": "local_derived_aggregates", "raw_records_included": False},
                   "issues": {key: value for key, value in report["issues"].items()
                              if re.fullmatch(r"[a-z_]{1,80}", key) and number(value) is not None},
                   "limits": ["configured model is not billed model", "events and turns are not requests",
                              "hourly tokens follow record timestamps", "raw line-level evidence stays local"]})
    result.update(analysis_metadata(report))
    result["limits"] += ["service tier not collected; source availability unverified",
                         "cache-write observed zero does not establish absence of billed writes",
                         "event-delta distribution is not request size or repricing evidence",
                         "missing hour buckets are not proven zero; historical completeness unknown"]
    result["redaction"] = {
        "policy_version": "uco-redaction/1.0.0", "method": "allowlisted_aggregate_projection",
        "excluded": ["account_identity", "original_paths_and_filenames", "session_and_source_aliases",
                     "event_and_turn_records", "conversation_and_tool_content", "credentials"],
        "retained": ["dates_and_hours", "configured_model", "usage_totals", "duration_totals", "coverage_and_missing_counts"],
        "review_required": True, "absolute_anonymity_claimed": False,
    }
    for section, keys in [("models", ["model", *counts, *timings]),
                          ("daily", ["date", *counts, *timings]), ("hourly", ["hour_start", *counts])]:
        result[section] = [{**pick(row, keys), "missing_field_events": pick(row["missing_field_events"], FIELDS)}
                           for row in report[section]]
    return result


def write_bundle(entries, parent):
    parent.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        name = "元舵提交包.zip" if index == 1 else f"元舵提交包-{index}.zip"
        target = parent / name
        try:
            archive = zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED)
            break
        except FileExistsError:
            index += 1
    try:
        with archive:
            for name, data in entries.items():
                archive.writestr(name, data)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def redaction_note(manual=False):
    if manual:
        method = "本包为选定材料；已由整理方声明完成字段脱敏复核。打包脚本不解析附件内容，也不能独立证明复核完整。"
        fields = "| 姓名、邮箱、手机号、地址、账号／订单／请求标识、私有路径及非必要正文 | 整理方逐项移除或使用中性别名；请核对遗漏 |\n"
        retained = "保留项由 ts-ai-cost-intake.md 第 10 节列明；仅保留报告需要的用量、金额、币种、账期、模型和来源位置。"
    else:
        method = "本包通过固定字段白名单生成精简汇总；没有把完整本机 JSON、原始日志或整目录压缩后分享。"
        fields = ("| 账号身份、邮箱／手机号／地址、凭据 | 不进入采集／提交字段；不读取登录凭据文件 |\n"
                  "| 私有路径、原始文件名、会话／来源别名 | 从默认提交包排除 |\n"
                  "| 对话正文、工具输入输出 | 不提取到材料，不附原始日志 |\n"
                  "| 单事件、会话和轮次区间明细 | 留在本机，不进入默认提交包 |\n")
        retained = "保留真实日期／小时、配置模型标签、汇总用量／耗时、日期／小时×模型聚合、事件输入量分位和覆盖／缺失数量；交叉聚合可能增加识别性，分享前请检查。"
    return ("# 脱敏说明\n\n" + method + "\n\n| 字段类别 | 处理与复核 |\n| --- | --- |\n" + fields +
            "\n" + retained + "\n\n原件不被修改。附件改名不等于内容脱敏；不能安全处理的原件应留在本机，改交摘要并说明缺口。\n\n"
            "本说明不承诺绝对匿名或识别全部敏感信息。分享前请检查摘要、模型标签、时间、附件内容与文件元数据。\n\n"
            "本地脚本无网络／模型调用。若原材料或汇总在云端 Agent 中被打开，其内容可能已经进入该模型；输出脱敏不能撤回先前暴露。\n")


def write_submission(report, parent):
    data = submission_summary(report)
    readme = ("元舵提交包 · 本机 Codex 用量材料\n\n"
              "你通常只需检查并上传这个 ZIP，无须另行打包本机其他文件。\n"
              "先阅读 ts-ai-cost-intake.md：它说明已有数据、口径及费用等缺口。\n"
              "再阅读 脱敏说明.md，确认排除项和仍保留的数据；复核后再分享。\n"
              "包内还有精简 summary.json、模型 models.csv、逐日 daily.csv、逐小时 hourly.csv，\n"
              "以及 daily_by_model.csv、hourly_by_model.csv。输入分布与字段／窗口状态见 summary.json。\n"
              "处理档位未采集；缓存写入零值不证明无写入费；事件分位不是请求大小。\n"
              "历史完整度未知，未出现小时不证明零用量。CSV 为 UTF-8 BOM，空格单元表示未知／无样本。\n"
              "这些文件来自同一批用量，不能把它们重复相加。\n"
              "本包没有正式账单或实际扣款金额；本地 token 不折算实付金额。\n"
              "包内保留真实时间、模型、用量、耗时及缺失数量，请分享前检查。\n"
              "逐事件、会话、来源别名和轮次明细留在本机，没有放入本包；本包不能独立核验原始行记录。\n"
              "客户自行选择上传渠道；脚本没有上传或发送。上传后由接收服务按其流程处理。\n")
    return write_bundle({"README.txt": readme.encode("utf-8"),
                         "脱敏说明.md": redaction_note().encode("utf-8"),
                         "ts-ai-cost-intake.md": intake(data, submission=True).encode("utf-8"),
                         "summary.json": json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                         "models.csv": csv_bytes(data["models"], ["model", "usage_events", *FIELDS, "turn_seconds", "covered_seconds"]),
                         "daily.csv": csv_bytes(data["daily"], ["date", "usage_events", *FIELDS, "turn_seconds", "covered_seconds"]),
                         "hourly.csv": csv_bytes(data["hourly"], ["hour_start", "usage_events", *FIELDS]),
                         "daily_by_model.csv": csv_bytes(data["daily_by_model"], ["date", "model", "usage_events", *FIELDS]),
                         "hourly_by_model.csv": csv_bytes(data["hourly_by_model"], ["hour_start", "model", "usage_events", *FIELDS])}, parent)


def selected_file(path):
    path = path.expanduser().absolute()
    if not path.is_file() or not all(safe_path(p) for p in [path, *path.parents]):
        raise ValueError("Choose an existing ordinary file, not a linked path")
    return path


def write_evidence_submission(handoff, evidence, parent, redaction_reviewed=False):
    if not redaction_reviewed:
        raise ValueError("Redaction review of the handoff and selected copies is required before packaging")
    handoff = selected_file(handoff)
    if handoff.suffix.lower() != ".md":
        raise ValueError("The selected handoff must be Markdown")
    entries = {"ts-ai-cost-intake.md": handoff.read_bytes(), "脱敏说明.md": redaction_note(manual=True).encode("utf-8")}
    names = []
    for specification in evidence:
        label, separator, filename = specification.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", label):
            raise ValueError("Evidence must be ALIAS=selected-file-path")
        path = selected_file(Path(filename))
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".csv", ".tsv", ".json", ".txt", ".md", ".xlsx", ".png", ".jpg", ".jpeg"}:
            raise ValueError("Unsupported evidence file type")
        name = f"evidence/{label}{suffix}"
        if any(n.rsplit("/", 1)[-1].split(".", 1)[0].lower() == label.lower() for n in names):
            raise ValueError("Evidence aliases must be distinct")
        entries[name] = path.read_bytes()
        names.append(name)
    entries["README.txt"] = ("元舵提交包 · 选定材料\n\n先检查 ts-ai-cost-intake.md，再自行上传本 ZIP。\n"
                             "仅包含明确选定的文件，不自动收集同目录材料。\n"
                             "附入的是经过脱敏复核的选定副本；打包脚本不自行解析或修改其内容。\n"
                             "先阅读 脱敏说明.md，核对字段及附件元数据；改名不等于脱敏。\n"
                             "按材料里的来源别名核对以下文件；未附入的原始证据仍缺失。\n"
                             + ("\n".join(names) if names else "没有附加原始证据。") + "\n脚本没有上传或发送。\n").encode("utf-8")
    return write_bundle(entries, parent)


def write_reports(report, parent):
    parent.mkdir(parents=True, exist_ok=True)
    tag = "codex-usage-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = parent / tag
    output.mkdir(exist_ok=False)
    (output / "usage-report.md").write_text(markdown(report), encoding="utf-8")
    (output / "usage-report.html").write_text(dashboard(report), encoding="utf-8")
    (output / "ts-ai-cost-intake.md").write_text(intake(report), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(output / "usage-events.csv", report["usage_events"], ["timestamp","date","session","model","source","line",*FIELDS])
    write_csv(output / "daily.csv", report["daily"], ["date","usage_events",*FIELDS,"turn_seconds","covered_seconds"])
    write_csv(output / "hourly.csv", report["hourly"], ["hour_start","usage_events",*FIELDS])
    write_csv(output / "daily_by_model.csv", report["daily_by_model"], ["date","model","usage_events",*FIELDS])
    write_csv(output / "hourly_by_model.csv", report["hourly_by_model"], ["hour_start","model","usage_events",*FIELDS])
    write_csv(output / "turns.csv", report["turns"], ["session","source","line","start","end","duration_seconds","status"])
    write_submission(report, output)
    return output


def offset(value):
    if value == "UTC":
        return timezone.utc
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", value):
        raise argparse.ArgumentTypeError("Use UTC or a fixed offset such as +08:00")
    hours, minutes = map(int, value[1:].split(":"))
    if hours > 14 or minutes > 59 or hours == 14 and minutes:
        raise argparse.ArgumentTypeError("Invalid timezone offset")
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (1 if value[0] == "+" else -1)))

