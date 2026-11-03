# Harness format previews — 3.3.6

The registry is an explicit code adapter list, not a Windows registry scan or an installed-app inventory. Default `all` selects these nine implemented format previews. Current bounded synthetic checks and environment are recorded in the bundled verification-receipt.json; they do not certify actual client releases. A user-selected external report dated 2026-10-20 records successful 3.3.1 Codex/Pi/WorkBuddy and broken/legacy delivery-gate checks on Windows 11/Python 3.13.12; these were not independently reproduced here. The report does not establish the other six adapters, exact client-version ranges or cross-platform installation compatibility.

Version 3.3 adds the WorkBuddy project JSONL preview described below. Version 3.2 separates each provider module and adds explicit counter/field contracts; that earlier change did not add harnesses or resolve the format limits below. See [provider-contracts.md](provider-contracts.md).

Audit correction: Pi batches through 3.3.0 require recollection before submission export. 3.2.1 introduced selected-header lineage grouping; 3.3.1 adds unique selected-basename recovery with filename/header session-id agreement. Missing/ambiguous/cyclic ancestry blocks submission ZIP creation while diagnostic reports remain available. No global entry-id fallback or unselected parent-path reads. External 3.3.1 runtime feedback supports the stated single-machine scenario; selected synthetic ambiguity/cycle cases are now checked; broader real runtime and privacy coverage remain unverified. Shell callers must handle partial exit code 4 and inspect delivery; blocked explicit export returns 2.

| Identifier | Default data root | Read scope / limitation |
| --- | --- | --- |
| codex | `$CODEX_HOME` or `~/.codex` | sessions and archived_sessions JSONL; retained accounting engine; observed completed-turn timing only |
| claude | `$CLAUDE_CONFIG_DIR` or `~/.claude` | projects/**/*.jsonl assistant usage; no Desktop/Cowork, WSL or automatic multi-profile expansion |
| pi | `~/.pi/agent` | sessions/**/*.jsonl assistant message usage |
| omp | `~/.omp/agent` | sessions/**/*.jsonl assistant usage and model_usage side calls |
| gemini | `~/.gemini` | tmp/*/chats/session-*.json or .jsonl; message tokens; no file-mtime timestamp fallback |
| openclaw | `~/.openclaw` | agents/*/sessions/*.jsonl; SQLite/compressed era flagged unsupported, not silently empty |
| opencode | `$OPENCODE_DATA_DIR` or `$XDG_DATA_HOME/opencode` or `~/.local/share/opencode` | storage/message/**/*.json and opencode*.db message/session_message token fields; no part-only/raw-usage variants; active WAL/SHM stores skipped with an issue |
| workbuddy | `$WORKBUDDY_HOME` (TuneMeter override) or `~/.workbuddy` | projects/*/*.jsonl plus projects/*/*/subagents/agent-*.jsonl only; function_call and top-level assistant message usage; no audit-log, rollback or tool-results |
| qwen | `~/.qwen` | projects/*/chats/*.jsonl assistant usageMetadata |

Root overrides replace the data root above, **not** the final sessions directory:

```text
python scripts/tunemeter.pyz discover --source pi,claude
python scripts/tunemeter.pyz collect --source pi --source-root pi=<selected-agent-root>
```

Only documented usage subtrees are traversed. No credentials/config content, OS inventory, other user homes, cloud accounts, hooks or background services. Models and timestamps come from observed metadata; missing models stay unknown, missing/invalid timestamps exclude the event visibly.

Cursor, Copilot, Cline/Roo/Kilo, Kimi, Windsurf and Zed remain unimplemented. Do not guess their paths or call their APIs. The pending list is illustrative, not an exhaustive app inventory.

For Pi/OMP/OpenClaw/Claude, fresh input and cache read/write remain native numeric fields locally; normalized prompt total requires every constituent. Gemini/Qwen use their reported prompt and total, and add reasoning to visible output only when both are present. OpenCode output already includes reasoning. Missing values stay null. Metadata conflicts are excluded rather than summing uncertain snapshots. No cross-harness mirror reconciliation or complete fork-history reconstruction is claimed.

The shared event unit is a source usage observation: Codex counter delta and another harness's assistant usage record are not interchangeable request counts. Only Codex contributes measured turn intervals. Default submission adds sources.csv and per-harness coverage; native event fields stay local. A complete CLI pipeline status does not establish complete history or verified platform support.

WorkBuddy mapping is based on a user-selected external technical note for WorkBuddy 2.137.1, dated 2026-10-19, not independent runtime verification. Input already includes cache; reasoning is a subset of output. Cache write prefers message.usage, then selected rawUsage; credit is excluded. Invalid cache/reasoning subsets become null with a diagnostic while declared native values remain local. Session IDs are hashed; identities are scoped by session and event kind. Duplicate calls across different kinds or sessions and fork/replay semantics remain unverified. WORKBUDDY_HOME is a TuneMeter root override, not a verified upstream setting. Only source usage observations are counted; WorkBuddy timing remains unknown.

CLI collect/report/export results include provider_contracts, by_source, coverage_gaps, warnings and delivery. issues remains the full diagnostic counter map. Only after_snapshot_records, identical duplicate_usage_records and resolved_lineage_parents_by_filename are informational; missing/invalid counters and inconsistent subsets remain gaps. Unavailable metrics still produce partial; ready_for_customer_review is not complete history or independent validation. sessions_observed counts distinct recognized identifiers before filtering: several files may share one session, so files_read need not match it. A mismatch alone does not prove resume.

3.3.2 diagnostic presentation: all-mode clean not_found roots are grouped under source_roots_not_found; explicit or unknown selection modes retain source-specific failures. A missing root does not establish an uninstalled app. Known zero-event sources keep errors/status but omit irrelevant per-event field/time gaps; unknown counts are not zero. field_missing names fields and missing/eligible counts; field_not_collected names unsupported collection fields; field_eligibility_unknown records unknown original contracts. None means not_applicable. Read completion_note for the Chinese summary; issues and detailed provider_contracts remain authoritative evidence. Selection mode is preserved as collection_context.source_selection_mode; old imports default to unknown.

3.3.3 import integrity: present event arrays must agree with the overall event/token aggregates and each declared source event count. Conflicts return a safe SnapshotConsistencyError; no conflicting snapshot is packaged. Omitted arrays are distinct from empty arrays: source tokens and missing-field counts remain null without event evidence; only declared source counts are retained. Missing counts stay unknown. Original snapshot/source version is preserved. Possible Pi usage without identity evidence requires recollection. Validation is internal consistency, not source authentication. External 3.3.2 feedback also reports three-source stability, named-field diagnostics and broken/legacy gating in the same stated Windows/Python environment; other-adapter, visual and ambiguity coverage remains unverified.

3.3.4 error details: validated native/normalized, summary/event and source-count conflicts use SnapshotConsistencyError with safe error_details.code/section/fields and optional zero-based event_index or registered source. No counter values, record IDs, paths or native exception messages are emitted. Invalid types/counts, dates and unknown contracts remain input/schema errors. Both report and export share this import path; new diagnostics are statically inspected only. External 3.3.3 feedback reports prior collection stability and rejection scenarios in its Windows/Python scope, not independent validation of 3.3.4.
