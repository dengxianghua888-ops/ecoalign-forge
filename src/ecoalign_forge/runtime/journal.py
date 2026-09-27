"""One transaction journal per run. JSON files are reproducible projections."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from ecoalign_forge.schemas.kernel import KernelCounts, canonical, digest

SCHEMA_VERSION = 2


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


@contextlib.contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


class RunBusyError(RuntimeError):
    pass


class Journal:
    def __init__(self, path: Path, *, hook: Callable | None = None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.hook = hook or (lambda *_: None)
        self.db = connect(self.path / "run.sqlite3")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,
                batch INTEGER NOT NULL,plan TEXT NOT NULL,source TEXT,state TEXT NOT NULL DEFAULT 'unattempted',reason TEXT);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,stage TEXT NOT NULL,case_ids TEXT NOT NULL,
                payload TEXT NOT NULL,payload_hash TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',parsed TEXT);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,request_id TEXT NOT NULL REFERENCES requests(id),
                number INTEGER NOT NULL,state TEXT NOT NULL,reservation TEXT NOT NULL DEFAULT '0',
                cost TEXT,usage TEXT,result TEXT,error TEXT,resolution TEXT,started REAL NOT NULL,ended REAL,
                UNIQUE(request_id,number));
            CREATE TABLE IF NOT EXISTS stages(case_id TEXT NOT NULL REFERENCES cases(id),stage TEXT NOT NULL,
                value TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(case_id,stage));
            CREATE TABLE IF NOT EXISTS pairs(id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(id),value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,at REAL NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts(name TEXT PRIMARY KEY,sha256 TEXT NOT NULL,value TEXT NOT NULL);
        """)
        version = self.get("schema_version")
        if version is not None and version != SCHEMA_VERSION:
            self.close()
            raise ValueError("Unsupported checkpoint schema version")
        self.set("schema_version", SCHEMA_VERSION)

    def close(self):
        self.db.close()

    @contextlib.contextmanager
    def owner(self):
        # flock releases even after SIGKILL. No unreliable PID-file takeover.
        import fcntl

        with (self.path / "owner.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunBusyError("Run already has an active executor") from exc
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute(
            "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, canonical(value)),
        )

    def event(self, kind, value):
        self.db.execute(
            "INSERT INTO events(at,kind,value) VALUES(?,?,?)", (time.time(), kind, canonical(value))
        )

    def initialize(self, manifest, plans):
        if self.get("manifest") is not None:
            raise ValueError("Run already initialized")
        with transaction(self.db):
            self.set("manifest", manifest)
            self.set("status", "pending")
            for ordinal, plan in enumerate(plans):
                self.db.execute(
                    "INSERT INTO cases(id,ordinal,batch,plan) VALUES(?,?,?,?)",
                    (plan["request_item_id"], ordinal, plan["batch_index"], canonical(plan)),
                )
            self.event("initialized", {"manifest_hash": digest(manifest)})
        self.hook("initialized", manifest)

    def cases(self):
        rows = self.db.execute("SELECT * FROM cases ORDER BY ordinal").fetchall()
        return [
            dict(row)
            | {
                "plan": json.loads(row["plan"]),
                "source": json.loads(row["source"]) if row["source"] else None,
            }
            for row in rows
        ]

    def set_case(self, case_id, *, state=None, reason=None, source=None):
        if state is not None:
            if state not in {"unattempted", "in_progress", "failed", "accepted", "excluded"}:
                raise ValueError("Invalid case state")
            self.db.execute(
                "UPDATE cases SET state=?,reason=? WHERE id=?", (state, reason, case_id)
            )
        if source is not None:
            self.db.execute("UPDATE cases SET source=? WHERE id=?", (canonical(source), case_id))

    def stage(self, case_id, stage):
        row = self.db.execute(
            "SELECT value FROM stages WHERE case_id=? AND stage=?", (case_id, stage)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def commit_stage(self, case_id, stage, value):
        encoded = canonical(value)
        with transaction(self.db):
            old = self.db.execute(
                "SELECT value FROM stages WHERE case_id=? AND stage=?", (case_id, stage)
            ).fetchone()
            if old and old[0] != encoded:
                raise ValueError("Cannot overwrite a committed stage")
            self.db.execute(
                "INSERT OR IGNORE INTO stages VALUES(?,?,?,?)",
                (case_id, stage, encoded, digest(value)),
            )
            self.event(
                "stage_committed", {"case_id": case_id, "stage": stage, "hash": digest(value)}
            )
        self.hook("stage_committed", {"case_id": case_id, "stage": stage})

    def commit_case(self, case_id, state, reason, pairs=()):
        with transaction(self.db):
            self.set_case(case_id, state=state, reason=reason)
            for pair in pairs:
                value = canonical(pair)
                old = self.db.execute(
                    "SELECT value FROM pairs WHERE id=?", (pair.pair_id,)
                ).fetchone()
                if old and old[0] != value:
                    raise ValueError("Conflicting stable pair ID")
                self.db.execute(
                    "INSERT OR IGNORE INTO pairs VALUES(?,?,?)", (pair.pair_id, case_id, value)
                )
            self.event("case_committed", {"case_id": case_id, "state": state, "reason": reason})
        self.hook("case_committed", {"case_id": case_id, "state": state})

    def request(self, request_id, stage, case_ids, payload):
        encoded = canonical(payload)
        with transaction(self.db):
            old = self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if old and old["payload"] != encoded:
                raise ValueError("Request payload differs from checkpoint")
            if not old:
                self.db.execute(
                    "INSERT INTO requests(id,stage,case_ids,payload,payload_hash) VALUES(?,?,?,?,?)",
                    (request_id, stage, canonical(case_ids), encoded, digest(payload)),
                )
        return self.request_row(request_id)

    def request_row(self, request_id):
        row = self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def attempts(self, request_id=None):
        query = (
            "SELECT * FROM attempts"
            + (" WHERE request_id=?" if request_id else "")
            + " ORDER BY started,number"
        )
        return [dict(r) for r in self.db.execute(query, (request_id,) if request_id else ())]

    def start_attempt(self, request_id, reservation):
        with transaction(self.db):
            number = (
                self.db.execute(
                    "SELECT count(*) FROM attempts WHERE request_id=?", (request_id,)
                ).fetchone()[0]
                + 1
            )
            attempt_id = f"{request_id}:{number}"
            self.db.execute(
                "INSERT INTO attempts(id,request_id,number,state,reservation,started) VALUES(?,?,?,'in_flight',?,?)",
                (attempt_id, request_id, number, str(reservation), time.time()),
            )
            self.db.execute("UPDATE requests SET state='in_flight' WHERE id=?", (request_id,))
            self.event("request_intent", {"request_id": request_id, "attempt_id": attempt_id})
        self.hook("request_intent_committed", {"request_id": request_id, "attempt_id": attempt_id})
        return attempt_id

    def save_response(self, attempt_id, result):
        with transaction(self.db):
            self.db.execute(
                "UPDATE attempts SET state='response_saved',result=?,ended=? WHERE id=?",
                (canonical(result), time.time(), attempt_id),
            )
        self.hook("response_committed", {"attempt_id": attempt_id})

    def finish_attempt(self, attempt_id, state, *, error=None, cost=None, usage=None, parsed=None):
        with transaction(self.db):
            self.db.execute(
                "UPDATE attempts SET state=?,error=?,cost=?,usage=?,ended=? WHERE id=?",
                (
                    state,
                    error,
                    str(cost) if cost is not None else None,
                    canonical(usage) if usage is not None else None,
                    time.time(),
                    attempt_id,
                ),
            )
            req = self.db.execute(
                "SELECT request_id FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()[0]
            self.db.execute(
                "UPDATE requests SET state=?,parsed=? WHERE id=?",
                (state, canonical(parsed) if parsed is not None else None, req),
            )
        self.hook("attempt_finished", {"attempt_id": attempt_id, "state": state})

    def recover_inflight(self):
        with transaction(self.db):
            rows = self.db.execute(
                "SELECT id,request_id FROM attempts WHERE state='in_flight'"
            ).fetchall()
            for row in rows:
                self.db.execute(
                    "UPDATE attempts SET state='unknown',error='executor_interrupted' WHERE id=?",
                    (row["id"],),
                )
                self.db.execute(
                    "UPDATE requests SET state='unknown' WHERE id=?", (row["request_id"],)
                )
            if rows:
                self.event("interrupted_requests", {"attempt_ids": [r["id"] for r in rows]})

    def unknown(self):
        return [a for a in self.attempts() if a["state"] == "unknown" and a["resolution"] is None]

    def resolve_unknown(self, choices):
        pending = {a["id"]: a for a in self.unknown()}
        if not set(choices).issubset(pending) or any(
            v not in {"retry", "skip"} for v in choices.values()
        ):
            raise ValueError("Unknown attempt ID or invalid explicit resolution")
        with transaction(self.db):
            for aid, choice in choices.items():
                row = pending[aid]
                self.db.execute("UPDATE attempts SET resolution=? WHERE id=?", (choice, aid))
                self.db.execute(
                    "UPDATE requests SET state=? WHERE id=?",
                    ("pending" if choice == "retry" else "skipped", row["request_id"]),
                )
                self.event(
                    "unknown_resolved",
                    {"attempt_id": aid, "choice": choice, "cost_reservation_retained": True},
                )

    def pairs(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT value FROM pairs ORDER BY id")]

    def counts(self) -> KernelCounts:
        cases = self.cases()
        state_counts = {
            s: sum(c["state"] == s for c in cases)
            for s in ["unattempted", "in_progress", "accepted", "excluded", "failed"]
        }
        paired = {r[0] for r in self.db.execute("SELECT DISTINCT case_id FROM pairs")}
        stage_counts = {
            s: self.db.execute("SELECT count(*) FROM stages WHERE stage=?", (s,)).fetchone()[0]
            for s in ["moderator", "judge"]
        }
        return KernelCounts(
            requested=len(cases),
            generated=sum(c["source"] is not None for c in cases),
            moderated=stage_counts["moderator"],
            judged=stage_counts["judge"],
            completed=state_counts["accepted"] + state_counts["excluded"],
            accepted_cases=state_counts["accepted"],
            excluded_cases=state_counts["excluded"],
            failed=state_counts["failed"],
            unattempted=state_counts["unattempted"],
            in_progress=state_counts["in_progress"],
            no_signal=sum(c["state"] == "accepted" and c["id"] not in paired for c in cases),
            dpo_pairs=len(self.pairs()),
        )

    def export(self, output_root: Path):
        pairs = self.pairs()
        content = "".join(canonical(pair) + "\n" for pair in pairs)
        version = digest(pairs)
        manifest = self.get("manifest")
        destination = Path(output_root) / manifest["execution_mode"] / manifest["run_id"] / version
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "pairs.jsonl"
        if target.exists() and target.read_text() != content:
            raise ValueError("Immutable export has conflicting bytes")
        self.hook("before_export", {"version": version})
        if not target.exists():
            atomic_write(target, content)
        self.hook("export_content_committed", {"version": version})
        payload = dict(
            schema_version=2,
            run_id=manifest["run_id"],
            dataset_version=version,
            execution_mode=manifest["execution_mode"],
            policy_hash=manifest["policy_hash"],
            language=manifest["policy"]["language"],
            data_license=manifest["policy"].get("data_license"),
            pairs=len(pairs),
            pairs_sha256=hashlib.sha256(content.encode()).hexdigest(),
            verification="deterministic_policy_consistency_not_ground_truth",
        )
        artifact = destination / "manifest.json"
        if artifact.exists() and json.loads(artifact.read_text()) != payload:
            raise ValueError("Immutable export manifest conflict")
        if not artifact.exists():
            atomic_write(artifact, canonical(payload) + "\n")
        self.db.execute(
            "INSERT OR IGNORE INTO artifacts VALUES(?,?,?)",
            (str(target), payload["pairs_sha256"], canonical(payload)),
        )
        self.hook("export_committed", {"version": version})
        return target
