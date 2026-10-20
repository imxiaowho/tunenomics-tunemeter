# Provider evidence contracts — 3.3.5 implementation preview

## 3.3.4 safe consistency diagnostics

All three validated-evidence conflict categories now use SnapshotConsistencyError/exit 2: native_normalized_conflict, summary_aggregate_conflict and source_event_count_conflict. error_details contains only a closed code/section, declared field names, optional zero-based event_index or registered source. It never includes values, record identifiers, input paths or exception text. The index identifies a row in the selected array, not a universal record id.

Types/negative counters/invalid dates/unknown contracts remain input/schema failures; no blanket ValueError conversion. Aggregate mismatch cannot prove which row is wrong or who changed the evidence. These are consistency diagnostics, not authentication. report/export use the same loader. Provider accounting, absence semantics and delivery gates are unchanged; current bounded synthetic diagnostic checks are recorded in verification-receipt.json. External 3.3.3 feedback supports its prior collection/rejection scenarios within its stated Windows/Python environment.

## 3.3.3 selected snapshot integrity

Provider contracts and live collection counters are unchanged. Imports with event arrays must match summary usage_events and six normalized token totals, plus non-null source event counts. Mismatch yields SnapshotConsistencyError before report/export writes. A malformed non-array is rejected; an omitted event array is not rewritten as an empty one. Without events, source token totals and missing counts are null and source event counts only retain validated declarations. source_aggregate_basis documents this limit; original snapshot/version remains unchanged. Possible Pi contributions with unavailable identity evidence require recollection; the shared delivery gate remains in force. Internal consistency checks do not authenticate the original source or establish source totals absent from the snapshot.

Current checks remain syntax/static/build only. Dated external 3.3.2 Windows/Python feedback supports the reported three-source accounting/diagnostic/gating scenarios, not new import behavior or all-platform compatibility.

## 3.3.2 diagnostic explanation

Accounting contracts, native normalization and submission gating are unchanged. source_selection_mode is all/explicit/unknown; old imports do not infer all. Clean not_found roots in all mode yield one source_roots_not_found gap, without asserting installation state. Explicit failures and all diagnostics survive; zero-event sources omit irrelevant per-event field/time expansion, while unknown counts retain uncertainty.

field_coverage_limited is replaced by field_missing (field and missing/eligible event counts), field_not_collected (field names), and field_eligibility_unknown (field and unknown eligibility counts). No not_applicable inference is made. coverage_gaps and completion.gaps use this richer structure; consumers must tolerate new kind values. completion_note is shared across CLI, projected JSON, Markdown and HTML. Grouping does not itself change partial/exit-code policy. Local schema stays 2.2.0 with additive context/summary fields; older source provenance remains unchanged on import.

Verification evidence: a user-selected external report dated 2026-10-20 records successful 3.3.1 Windows 11/Python 3.13.12 Codex/Pi/WorkBuddy, all-source, broken-lineage and legacy-export scenarios. This is external testimony, not an independently reproduced result, public customer fixture or verified client-version range. 3.3.2 has static/build inspection only. Historical verification statements below refer to their original checkpoint.

## 3.3.1 Pi ancestry and delivery correction

Pi contract is now message-jsonl/1.2.0. If lexical matching fails, the selected candidate basename must be unique, the selected header readable and its session id must match the filename suffix. The full selected set participates in ambiguity detection, including unreadable candidates. Windows-style parent basenames are recognized without opening those paths. Cycles and uncertain ancestry stay unresolved; no global short-id merge is attempted. Recovery counters are informational, not lineage failures.

Pi event contracts 1.0.0/1.1.0 remain importable for diagnosis, but older Pi usage batches require recollection; repackaging cannot apply the new scope to already-aggregated values. limited/requires_recollection or unknown Pi accounting blocks submission entries at the shared boundary. collect keeps local diagnostic files without a ZIP; export returns 2; report remains available. All collection/report/export envelopes expose contracts, warnings, coverage_gaps and delivery where source evidence exists, including blocked export.

Only after_snapshot_records, identical duplicate_usage_records and resolved_lineage_parents_by_filename are informational. Every other nonzero diagnostic remains conservative coverage evidence. Missing metrics are still explicit gaps, including time or unsupported fields; partial therefore does not always mean token totals are unusable. No requested-metrics selector was added. This patch has static/build inspection only. The historical sections below describe their original version and are superseded where applicable.

## 3.3.0 WorkBuddy format preview

Ninth registered adapter: project-jsonl/1.0.0. Main project logs and known subagents only; function_call and top-level assistant message observations. Input includes cache; output includes reasoning. Selected cache-write fallback comes from rawUsage; no credit or money fields. WorkBuddy opts into subset validation in shared normalization: an inconsistent cache/reasoning subset becomes null with an issue, while native numeric evidence is preserved. Import uses the same rules. Existing adapters retain their normalization behavior. No global-ID uniqueness, cross-kind request equivalence, replay completeness or WorkBuddy timing is asserted. This is source/build inspection only, not verified installation or runtime compatibility. Local schema remains 2.2.0.

## 3.2.1 audit correction

The CLI remains primary. Current local schema is 2.2.0. Pi uses a 1.1.0 provider contract with lineage-scoped entry id + original timestamp. Headers are read only from enumerated allowed files; parentSession links are matched lexically to that set and never followed/opened. Missing/cyclic header relationships fall back conservatively with explicit gaps. Unrelated roots and fallback row identities remain separate. This is not global short-id deduplication or proof of all fork formats. OMP/OpenClaw retain their previous session policy pending independent evidence.

Observed-session counts include explicit metadata even without retained usage; Codex sessions_observed is preserved from its engine. Other adapter inventories remain limited to recognized selected metadata/usage, not every past session.

missing_field_events now counts only contract-supported null observations. not_collected_field_events and eligibility_unknown_field_events have separate counts; unobserved_field_events counts every null. Not-collected never automatically means not-applicable. These partitions are consistent across aggregate JSON tables and global field observations; source CSV token totals remain numeric observations only.

pipeline_status=completed describes execution, while completion.collection_status is partial if selected sources, timing or field evidence are unavailable. Historical completeness stays unknown. Stdout exposes by_source directly. Exit 4 is expected for usable partial results; shell automation must handle it explicitly (for example by invoking the command in a conditional when using set -e).

Earlier Pi 1.0.0 contracts can be imported for inspection under explicit compatibility rules; their totals are marked requires_recollection. Old batches cannot be corrected by repackaging without the original identity relationships. Export returns an actionable error without a ZIP; report remains available for diagnosis. Current unresolved lineage reports are also marked limited. No functional verification or real-store scan was performed for this correction preview.

The following describes the original 3.2 contract foundation; this correction supersedes the schema/missing-field/identity wording where applicable.

The eight harness identifiers and known-root scope are unchanged. New local schema is tunemeter-usage/2.1.0. Provider modules have a static SPEC and metadata-only read function; Codex wraps the retained accounting engine. Modules are selected from a closed registry, never arbitrary customer module names.

## Counter stages

- Codex native snapshots are cumulative_total; retained events are increment after the existing baseline/fork/reset accounting, with engine_reconciled identity basis rather than an asserted request/message ID. They must never be differenced a second time. Original cumulative snapshots are not reconstructed or claimed as retained native_usage.
- Current other formats produce per_event observations. Each NativeEvent declares its semantics and native kind; mismatches are excluded visibly. OMP message and model_usage identities occupy different kind namespaces.
- session_total is a reserved contract category, not an implemented adapter; do not invent hourly buckets or lifecycle timing from session aggregates.
- Field rules name native paths and direct / sum_known / reported_else_sum_known operations. Arithmetic requires known constituents; optional missing counters stay null. No character estimates, logged cost objects or rate conversion enter measured usage.

## Three independent dimensions

| Dimension | Meaning |
| --- | --- |
| collection: supported / not_collected | What this parser implements; not proof that a particular log contains the field |
| observation: observed / partially_observed / missing / no_samples / not_collected | What retained values show; known zero has its own count |
| applicability: unknown | No automatic billing applicability inference from absent data or parser support |

provider_contracts contains static current-implementation declarations plus evidence_basis and source_contract_observation. field_evidence separates normalized field totals from native-field coverage counts. A known normalized zero may result from known-component arithmetic. Native counters, row identities and accounting event records stay local; only per-source aggregate capability/coverage appears in the submission.

## Existing snapshots

- report/export reads selected generated data only. It does not rescan source stores.
- Known event contract declarations are allowlisted; supported per-event native counters are projected and checked against normalized values. This is consistency validation, not independent source authentication.
- An older snapshot without accounting metadata has unavailable_in_snapshot source-contract observation, with collection marked not_verified_for_snapshot. Native evidence is unavailable when it was not retained; current implementation capabilities do not prove old collector capabilities.
- Codex always keeps its original collector version/snapshot provenance on import. This version does not retroactively replay counters or recover missing native data.

Functional/privacy/accounting regression and platform workflows remain unverified in this implementation preview. A ready or complete pipeline status is not proof of supported installation, complete history or request-level accounting. Cross-harness mirrors, conflicting streaming snapshots, SQLite sidecars and other existing format gaps remain explicit limits.
