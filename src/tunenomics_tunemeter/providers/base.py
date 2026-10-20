"""Explicit native/effective accounting contracts; no monetary semantics."""
from dataclasses import dataclass
from typing import Literal
from .. import engine

CounterSemantics = Literal["cumulative_total", "per_event", "session_total"]


@dataclass(frozen=True)
class FieldRule:
    field: str
    paths: tuple[str, ...] = ()
    operation: Literal["direct", "sum_known", "reported_else_sum_known"] = "direct"
    fallback: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    format_id: str
    native_semantics: CounterSemantics
    effective_semantics: Literal["increment", "per_event", "session_total"]
    rules: tuple[FieldRule, ...]
    time_status: str = "not_collected"
    service_tier_status: str = "not_collected"
    extra_native_paths: tuple[str, ...] = ()
    event_kinds: tuple[str, ...] = ("assistant",)
    identity_scope: Literal["session", "lineage"] = "session"
    contract_version: str = "1.0.0"
    legacy_contract_ids: tuple[str, ...] = ()
    validate_subsets: bool = False

    @property
    def contract_id(self):
        return f"tunemeter-provider/{self.name}/{self.format_id}/{self.contract_version}"

    @property
    def native_paths(self):
        paths = {path for rule in self.rules for path in (*rule.paths, *rule.fallback)}
        paths.update(self.extra_native_paths)
        return tuple(sorted(paths))

    def describe(self):
        rules = {r.field: r for r in self.rules}
        return {"contract_id": self.contract_id, "format_id": self.format_id,
                "native_counter_semantics": self.native_semantics,
                "effective_counter_semantics": self.effective_semantics,
                "native_event_kinds": list(self.event_kinds),
                "declaration_scope": "current_implementation",
                "identity_scope": self.identity_scope,
                "subset_validation": "inconsistent_normalized_subset_is_null; native_preserved" if self.validate_subsets else "not_declared",
                "legacy_import_contract_ids": list(self.legacy_contract_ids),
                "fields": {key: {"collection": "supported" if rules.get(key) and rules[key].paths else "not_collected",
                                 "applicability": "unknown",
                                 "native_paths": list(rules[key].paths) if key in rules else [],
                                 "operation": rules[key].operation if key in rules else None,
                                 "fallback_paths": list(rules[key].fallback) if key in rules else []} for key in engine.FIELDS},
                "time_status": self.time_status, "service_tier_status": self.service_tier_status,
                "verification": "implementation_preview"}


@dataclass(frozen=True)
class NativeEvent:
    session: str
    identity: str
    timestamp: object
    model: object
    counters: dict
    native_kind: str
    identity_basis: Literal["record_id", "response_id", "row_fallback", "engine_reconciled"]
    counter_semantics: CounterSemantics = "per_event"


@dataclass(frozen=True)
class SessionObservation:
    session: str


def get_path(value, path):
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def select_native(spec, value, issues=None):
    """Only declared numeric paths survive; missing is retained as null."""
    result = {}
    for path in spec.native_paths:
        raw = get_path(value, path)
        count = engine.number(raw)
        if raw is not None and count is None and issues is not None:
            issues["invalid_native_counters"] = issues.get("invalid_native_counters", 0) + 1
        target = result
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = count
    return result


def normalize(spec, native, issues):
    if spec.native_semantics != "per_event" or spec.effective_semantics != "per_event":
        raise ValueError("This contract requires a dedicated accounting engine")
    cleaned = select_native(spec, native, issues)
    counts = dict.fromkeys(engine.FIELDS)
    for rule in spec.rules:
        values = [get_path(cleaned, path) for path in rule.paths]
        if rule.operation == "direct":
            counts[rule.field] = values[0] if values else None
        elif rule.operation == "sum_known":
            counts[rule.field] = sum(values) if values and all(v is not None for v in values) else None
        elif rule.operation == "reported_else_sum_known":
            fallback = [get_path(cleaned, path) for path in rule.fallback]
            value = values[0] if values else None
            if value is None and fallback and all(v is not None for v in fallback):
                value = sum(fallback)
            counts[rule.field] = value
    if spec.validate_subsets:
        for subset, parent, issue in (
            ("cached_input_tokens", "input_tokens", "cached_exceeds_input"),
            ("cache_write_input_tokens", "input_tokens", "cache_write_exceeds_input"),
            ("reasoning_output_tokens", "output_tokens", "reasoning_exceeds_output"),
        ):
            if counts[subset] is not None and counts[parent] is not None and counts[subset] > counts[parent]:
                counts[subset] = None
                issues[issue] = issues.get(issue, 0) + 1
    return counts, cleaned


def accounting(spec, kind, identity_basis):
    if kind not in spec.event_kinds or identity_basis not in {"record_id", "response_id", "row_fallback", "engine_reconciled"}:
        raise ValueError("Unsupported accounting identity or event kind")
    if (identity_basis == "engine_reconciled") != (spec.effective_semantics == "increment"):
        raise ValueError("Identity basis conflicts with accounting stage")
    return {"contract_id": spec.contract_id, "native_counter_semantics": spec.native_semantics,
            "effective_counter_semantics": spec.effective_semantics,
            "native_kind": kind, "identity_basis": identity_basis,
            "cumulative_differencing": "already_applied_by_codex_engine" if spec.effective_semantics == "increment" else "not_applied"}


def import_accounting(spec, declared):
    if not isinstance(declared, dict) or declared.get("contract_id") not in {spec.contract_id, *spec.legacy_contract_ids}:
        raise ValueError("Unknown event accounting contract")
    expected = accounting(spec, declared.get("native_kind"), declared.get("identity_basis"))
    expected["contract_id"] = declared["contract_id"]
    if any(declared.get(key) != value for key, value in expected.items()):
        raise ValueError("Event accounting declaration conflicts with implementation")
    return expected


def field_evidence(spec, events, contract_known=True):
    """Capability, observation and applicability are independent dimensions."""
    result = {}
    declarations = spec.describe()["fields"]
    for key in engine.FIELDS:
        known = sum(engine.number(e.get(key)) is not None for e in events)
        supported = declarations[key]["collection"] == "supported"
        result[key] = {"collection": declarations[key]["collection"] if contract_known else "not_verified_for_snapshot", "applicability": "unknown",
                       "observation": "not_collected" if contract_known and not supported else "no_samples" if not events else "missing" if not known else "partially_observed" if known < len(events) else "observed",
                       "eligible_events": len(events) if contract_known and supported else 0,
                       "known_events": known, "missing_events": len(events)-known if contract_known and supported else 0,
                       "not_collected_events": len(events) if contract_known and not supported else 0,
                       "eligibility_unknown_events": len(events) if not contract_known else 0,
                       "zero_value_events": sum(e.get(key) == 0 for e in events),
                       "observed_total": sum(e[key] for e in events if engine.number(e.get(key)) is not None) if known else None,
                       "value_basis": "normalized_source_counters; may require known-component arithmetic" if contract_known else "selected_snapshot_values; original normalization contract not retained"}
    native_events = [e for e in events if isinstance(e.get("native_usage"), dict)]
    native = {}
    for path in spec.native_paths:
        values = [get_path(e["native_usage"], path) for e in native_events]
        known = [v for v in values if engine.number(v) is not None]
        native[path] = {"eligible_events": len(native_events), "known_events": len(known),
                        "missing_events": len(values)-len(known), "zero_value_events": sum(v == 0 for v in known),
                        "observation": "unavailable_in_snapshot" if not native_events else "missing" if not known else "partially_observed" if len(known) < len(values) else "observed"}
    return {"normalized_fields": result, "native_fields": native,
            "native_evidence_events": len(native_events), "events_without_native_evidence": len(events)-len(native_events),
            "native_evidence_limit": "Codex engine retains deltas, not original cumulative snapshots; older imports may lack native evidence"}
