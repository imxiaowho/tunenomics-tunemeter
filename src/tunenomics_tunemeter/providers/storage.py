"""Bounded metadata storage primitives; no provider normalization rules."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
from .. import engine
from ..contracts import selected_file

MAX_FILE = 128 * 1024 * 1024
MAX_ROWS = 1_000_000


def projection(raw, schema):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    value, end = engine.project(raw, schema)
    if raw[end:].strip():
        raise ValueError("Trailing data")
    return value



def stamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # The documented OpenCode time.created field is epoch milliseconds.
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    return engine.instant(value) if isinstance(value, str) else None



def rows(path, schema, issues):
    path = selected_file(path)
    if path.stat().st_size > MAX_FILE:
        issues["oversized_files"] += 1
        return
    with path.open("rb") as stream:
        if path.suffix.lower() == ".json":
            raw = stream.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                issues["oversized_files"] += 1
                return
            yield projection(raw, schema)
        else:
            for index in range(MAX_ROWS + 1):
                raw = stream.readline(engine.MAX_LINE + 1)
                if not raw:
                    break
                if index == MAX_ROWS or len(raw) > engine.MAX_LINE:
                    issues["read_limit_reached"] += 1
                    break
                if not raw.strip():
                    continue
                try:
                    yield projection(raw, schema)
                except (ValueError, UnicodeError, RecursionError):
                    issues["malformed_records"] += 1



def sqlite_rows(path, issues, include_kind=False):
    """Fixed OpenCode tables only; never SELECT message bodies or tool parts.

    JSON scalar extraction occurs inside SQLite. No data payload reaches Python.
    Unknown layouts fail visibly; part-only usage is explicitly not supported.
    """
    path = selected_file(path)
    if path.stat().st_size > 1024 * 1024 * 1024:
        issues["oversized_databases"] += 1
        return
    for sidecar in (Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        if sidecar.exists():
            selected_file(sidecar)
            # Avoid modifying live sidecars or ignoring uncheckpointed usage.
            issues["live_database_sidecars_not_read"] += 1
            return
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        operations = [0]
        def bounded():
            operations[0] += 1
            return int(operations[0] > 20000)
        db.set_progress_handler(bounded, 1000)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('message','session_message')")}
        if not tables:
            issues["unsupported_database_schema"] += 1
            return
        for table in sorted(tables):
            v2 = table == "session_message"
            role = "type" if v2 else "json_extract(data,'$.role')"
            model = "json_extract(data,'$.model.id')" if v2 else "json_extract(data,'$.modelID')"
            # Constants only; table/role/model are never interpolated user input.
            fields = ["input", "output", "reasoning", "total", "cache.read", "cache.write"]
            extracts = ",".join(f"json_extract(data,'$.tokens.{field}')" for field in fields)
            query = f"SELECT session_id,id,time_created,{model},{extracts},{role} FROM {table} WHERE {role} IN ('assistant','model','compaction') LIMIT {MAX_ROWS + 1}"
            for index, row in enumerate(db.execute(query)):
                if index == MAX_ROWS:
                    issues["read_limit_reached"] += 1
                    break
                usage = dict(zip(fields[:4], row[4:8]))
                usage["cache"] = {"read": row[8], "write": row[9]}
                if all(v is None for v in row[4:10]):
                    issues["database_rows_without_usage"] += 1
                    continue
                record = (engine.alias(str(row[0])), str(row[1]), row[2], row[3], usage)
                yield (*record, str(row[10])) if include_kind else record



