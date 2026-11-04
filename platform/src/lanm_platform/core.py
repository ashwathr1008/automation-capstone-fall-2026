"""Durable local projects, scientific evidence, decisions and calculations."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from . import economics
from .config import source_archive
from .migration import load_asset

METALS = ("Y", "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu")
METRIC_UNITS = {
    "collected_target_kg_per_l_cycle": "kg/L/cycle", "recovery_fraction": "fraction",
    "purity_fraction": "fraction", "cycles_observed": "cycle", "cycle_time_hours": "h/cycle",
    "working_capacity_kg_per_l": "kg/L", "capacity_retention_fraction": "fraction",
    "protein_loss_fraction": "fraction", "pressure_drop_kpa": "kPa",
}
MEASUREMENT_INPUTS = {"collected_target_kg_per_l_cycle": "collected_target_kg_per_l_cycle",
                      "cycle_time_hours": "cycle_time_hours", "purity_fraction": "product_purity_fraction",
                      "recovery_fraction": "target_recovery_fraction"}
REQUIRED_SCALE_METRICS = {"collected_target_kg_per_l_cycle", "cycle_time_hours", "purity_fraction", "recovery_fraction", "cycles_observed"}
REQUIRED_PREDICTION_INPUTS = {"collected_target_kg_per_l_cycle", "cycle_time_hours", "usable_lifetime_cycles",
                              "target_production_kg_per_day", "equipment_cost_usd", "labor_hours_per_day", "labor_rate_usd_per_hour"}
LEGACY_TESTING_CSV_FIELDS = ("schema_version", "batch_id", "rank", "candidate_id", "candidate_name", "plate_id", "well",
                      "starting_concentration", "concentration_unit", "concentration_basis", "concentration_location",
                      "recommendation_rank")
TESTING_CSV_FIELDS = ("schema_version", "batch_id", "rank", "candidate_id", "candidate_name", "plate_id", "well",
                      "stock_volume", "volume_unit", "volume_basis", "volume_location", "water_addition_mode",
                      "recommendation_rank")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _id(prefix):
    return prefix + "_" + uuid.uuid4().hex[:20]


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _text(value, field, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be nonempty text of at most {maximum} characters")
    return value.strip()


def _same(a, b):
    return str(a).strip().casefold() == str(b).strip().casefold()


def _specified(value):
    return isinstance(value, str) and value.strip().casefold() not in {"", "unspecified", "unknown", "not specified"}


class Store:
    """Short-lived SQLite connections; safe for one Store per HTTP request."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "research.sqlite3"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS library_records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,scope TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS revision_project ON revisions(project_id,scope,seq);
                CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,candidate_id TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS experiment_project ON experiments(project_id,candidate_id,status);
                CREATE TABLE IF NOT EXISTS runs(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,sha256 TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(project_id,sha256));
                CREATE TABLE IF NOT EXISTS literature_searches(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scale_predictions(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS testing_selections(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS testing_batches(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT,payload TEXT NOT NULL);
            """)
            imported = db.execute("SELECT value FROM metadata WHERE key='library_version'").fetchone()
            if not imported:
                package = load_asset()
                db.executemany("INSERT OR IGNORE INTO candidates VALUES(?,?)", [(row["id"], _json(row)) for row in package["candidates"]])
                for kind in ("sources", "contexts", "assertions", "formulas"):
                    db.executemany("INSERT OR IGNORE INTO library_records VALUES(?,?,?)",
                                   [(kind + ":" + row["id"], kind, _json(row)) for row in package.get(kind, [])])
                db.execute("INSERT OR IGNORE INTO metadata VALUES('library_version',?)", (package["origin_sha256"],))
                db.execute("INSERT OR IGNORE INTO metadata VALUES('library_notes',?)", (_json(package.get("dataset_notes", [])),))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, project_id, kind, **details):
        payload = {"id": _id("event"), "project_id": project_id, "kind": kind, "created_at": _now(), **details}
        db.execute("INSERT INTO events(id,project_id,payload) VALUES(?,?,?)", (payload["id"], project_id, _json(payload)))

    def _project(self, project_id):
        with self._connect() as db:
            row = db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise ValueError("Project not found: " + str(project_id))
        return json.loads(row[0])

    def _touch(self, db, project_id):
        row = db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise ValueError("Project not found")
        project = json.loads(row[0])
        project["revision"] += 1
        project["updated_at"] = _now()
        db.execute("UPDATE projects SET payload=? WHERE id=?", (_json(project), project_id))
        return project["revision"]

    def list_projects(self):
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM projects ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def create_project(self, name, target, competitor, description=""):
        name = _text(name, "Project name", 200)
        if target not in METALS or competitor not in METALS or target == competitor:
            raise ValueError("Choose two distinct supported rare-earth elements")
        if not isinstance(description, str) or len(description) > 20000:
            raise ValueError("Project description must be text of at most 20000 characters")
        project = {"id": _id("project"), "name": name, "target": target, "competitor": competitor,
                   "description": description, "configuration": {"target": target, "support": "unspecified", "feed": "unspecified"},
                   "revision": 1, "created_at": _now(), "updated_at": _now()}
        revision = {"id": _id("revision"), "project_id": project["id"], "scope": "shared", "candidate_id": None,
                    "values": dict(economics.DEFAULTS), "reason": "Explicit illustrative starting scenario; refine with evidence or project choices.",
                    "evidence_kind": "scenario_estimate", "created_at": _now(), "project_revision": 1}
        with self._connect() as db:
            db.execute("INSERT INTO projects VALUES(?,?)", (project["id"], _json(project)))
            db.execute("INSERT INTO revisions(id,project_id,scope,payload) VALUES(?,?,?,?)", (revision["id"], project["id"], "", _json(revision)))
            self._event(db, project["id"], "project_created", revision_id=revision["id"])
        return self.get_project(project["id"])

    def update_project(self, project_id, changes, reason):
        reason = _text(reason, "Reason")
        project = self._project(project_id)
        if not isinstance(changes, dict) or not changes or set(changes) - {"name", "description", "configuration"}:
            raise ValueError("Update name, description or configuration; a changed metal pair requires a new project")
        if "name" in changes:
            changes = {**changes, "name": _text(changes["name"], "Project name", 200)}
        if "description" in changes and not isinstance(changes["description"], str):
            raise ValueError("Description must be text")
        if "configuration" in changes:
            config = changes["configuration"]
            if not isinstance(config, dict) or set(config) - {"target", "support", "feed", "pH", "temperature_c", "scale", "notes"}:
                raise ValueError("Configuration supports target, support, feed, pH, temperature_c, scale and notes")
            if "target" in config and config["target"] != project["target"]:
                raise ValueError("Configuration target must match the project")
            for key in ("support", "feed", "scale", "notes"):
                if key in config:
                    _text(config[key], key, 5000)
            for key in ("pH", "temperature_c"):
                if key in config and (isinstance(config[key], bool) or not isinstance(config[key], (int, float)) or not math.isfinite(config[key])):
                    raise ValueError(f"{key} must be finite numeric data")
            changes = {**changes, "configuration": {**project["configuration"], **config}}
        with self._connect() as db:
            current = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()[0])
            before = deepcopy(current)
            current.update(changes)
            current.update(revision=current["revision"] + 1, updated_at=_now())
            db.execute("UPDATE projects SET payload=? WHERE id=?", (_json(current), project_id))
            self._event(db, project_id, "project_updated", reason=reason, before=before, changes=changes, revision=current["revision"])
        return self.get_project(project_id)

    def _revisions(self, project_id):
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM revisions WHERE project_id=? ORDER BY seq", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_project(self, project_id):
        project = self._project(project_id)
        revisions = self._revisions(project_id)
        values, details = self._inputs(project, revisions=revisions)
        experiments = self._experiments(project_id)
        runs = self.list_runs(project_id)
        return {**project, "assumptions": values, "assumption_details": list(details.values()),
                "revisions": revisions, "experiment_count": len(experiments),
                "accepted_experiment_count": sum(e["status"] == "accepted" for e in experiments),
                "latest_run": runs[0] if runs else None, "candidate_count": self.candidate_count()}

    def candidate_count(self):
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]

    def update_assumptions(self, project_id, values, reason, candidate_id=None):
        self._project(project_id)
        values = economics.validate_values(values)
        if not values:
            raise ValueError("Supply at least one changed assumption")
        reason = _text(reason, "Revision reason")
        if candidate_id:
            self.get_candidate(candidate_id)
        revision = {"id": _id("revision"), "project_id": project_id, "scope": "candidate" if candidate_id else "shared",
                    "candidate_id": candidate_id, "values": values, "reason": reason,
                    "evidence_kind": "scenario_estimate", "created_at": _now()}
        with self._connect() as db:
            revision["project_revision"] = self._touch(db, project_id)
            db.execute("INSERT INTO revisions(id,project_id,scope,payload) VALUES(?,?,?,?)", (revision["id"], project_id, candidate_id or "", _json(revision)))
            self._event(db, project_id, "assumptions_revised", revision_id=revision["id"], candidate_id=candidate_id, parameters=list(values))
        return self.get_project(project_id)

    def _experiments(self, project_id, candidate_id=None):
        with self._connect() as db:
            if candidate_id:
                rows = db.execute("SELECT payload FROM experiments WHERE project_id=? AND candidate_id=? ORDER BY rowid", (project_id, candidate_id)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM experiments WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _applicability(self, project, experiment):
        conditions, config = experiment["conditions"], project["configuration"]
        reasons = []
        if conditions.get("target") != project["target"]:
            reasons.append("Experimental target differs from the project")
        for key in ("support", "feed"):
            if not _specified(config.get(key)):
                reasons.append(f"Project {key} is unspecified")
            elif not _same(config[key], conditions.get(key)):
                reasons.append(f"Experimental {key} does not match project {key}")
        for key in ("pH", "temperature_c"):
            if key in config and conditions.get(key) != config[key]:
                reasons.append(f"Experimental {key} does not match the specified project condition")
        return reasons

    def _inputs(self, project, candidate_id=None, *, revisions=None, experiments=None):
        revisions = self._revisions(project["id"]) if revisions is None else revisions
        values, details = {}, {}
        for scope in (None, candidate_id) if candidate_id else (None,):
            for rev in revisions:
                if rev["candidate_id"] != scope:
                    continue
                for key, value in rev["values"].items():
                    values[key] = value
                    details[key] = {"parameter": key, "value": value, "unit": economics.UNITS[key],
                                    "evidence_kind": rev["evidence_kind"], "revision_id": rev["id"], "reason": rev["reason"]}
        if candidate_id:
            experiments = self._experiments(project["id"], candidate_id) if experiments is None else experiments
            experiments = self._matching_group(project, [e for e in experiments if e["candidate_id"] == candidate_id])
            for exp in sorted(experiments, key=lambda e: e.get("project_revision_at_acceptance", 0)):
                if exp["candidate_id"] != candidate_id or exp["status"] != "accepted" or self._applicability(project, exp):
                    continue
                for metric, parameter in MEASUREMENT_INPUTS.items():
                    if metric in exp["metrics"]:
                        values[parameter] = exp["metrics"][metric]
                        details[parameter] = {"parameter": parameter, "value": values[parameter], "unit": economics.UNITS[parameter],
                                              "evidence_kind": "accepted_experimental_measurement", "experiment_id": exp["id"],
                                              "revision_id": "measurement:" + exp["id"] + ":" + metric,
                                              "reason": exp["acceptance_reason"], "conditions": exp["conditions"]}
        return values, details

    def _matching_group(self, project, experiments):
        groups = {}
        for exp in experiments:
            if exp["status"] == "accepted" and not self._applicability(project, exp):
                groups.setdefault(_json(dict(sorted(exp["conditions"].items()))), []).append(exp)
        return max(groups.values(), key=lambda group: max(e.get("project_revision_at_acceptance", 0) for e in group)) if groups else []

    def _candidate_summary(self, candidate, experiments):
        accepted = [e for e in experiments if e["candidate_id"] == candidate["id"] and e["status"] == "accepted"]
        return {"id": candidate["id"], "name": candidate["name"], "accession": candidate.get("accession"),
                "organism": candidate.get("organism_as_reported"), "pool": "updated" if accepted else "untested",
                "accepted_experiment_count": len(accepted), "source_id": candidate.get("source_id"),
                "screening": {key: candidate.get("screening", {}).get(key) for key in ("mean", "sd", "total_metal_ppb", "replicate_design")}}

    def list_candidates(self, project_id, query="", pool="all", limit=100):
        self._project(project_id)
        if pool not in {"all", "untested", "updated"}:
            raise ValueError("Pool must be all, untested or updated")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
        if not isinstance(query, str):
            raise ValueError("Query must be text")
        experiments = self._experiments(project_id)
        with self._connect() as db:
            candidates = [json.loads(r[0]) for r in db.execute("SELECT payload FROM candidates ORDER BY id")]
        rows = []
        for candidate in candidates:
            if query.casefold() not in " ".join(str(candidate.get(k, "")) for k in ("id", "name", "accession", "organism_as_reported")).casefold():
                continue
            row = self._candidate_summary(candidate, experiments)
            if pool == "all" or row["pool"] == pool:
                rows.append(row)
        return {"candidates": rows[:limit], "total": len(rows), "returned": min(limit, len(rows)), "pool": pool}

    def get_candidate(self, candidate_id, project_id=None):
        with self._connect() as db:
            row = db.execute("SELECT payload FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError("Candidate not found: " + str(candidate_id))
        candidate = json.loads(row[0])
        candidate["organism"] = candidate.get("organism_as_reported")
        if project_id:
            project = self._project(project_id)
            experiments = self._experiments(project_id, candidate_id)
            candidate.update(self._candidate_summary(candidate, experiments))
            # Preserve complete screening details on the detail endpoint.
            candidate["screening"] = json.loads(row[0]).get("screening", {})
            candidate["experiments"] = [{**e, "applicability_issues": self._applicability(project, e)} for e in experiments]
            values, details = self._inputs(project, candidate_id, experiments=experiments)
            candidate.update(assumptions=values, assumption_details=list(details.values()))
        return candidate

    def add_experiment(self, project_id, candidate_id, label, conditions, metrics, notes=""):
        project = self._project(project_id)
        self.get_candidate(candidate_id)
        label = _text(label, "Experiment label", 300)
        if not isinstance(conditions, dict) or not isinstance(metrics, dict) or not metrics:
            raise ValueError("Supply conditions and at least one processed numeric measurement")
        if set(metrics) - set(METRIC_UNITS):
            raise ValueError("Unsupported metric(s): " + ", ".join(sorted(set(metrics) - set(METRIC_UNITS))))
        for key, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a nonnegative finite measurement")
            if key.endswith("_fraction") and value > 1:
                raise ValueError(f"{key} must be a fraction between 0 and 1")
            if key == "cycle_time_hours" and value <= 0:
                raise ValueError("cycle_time_hours must be positive")
            if key == "cycles_observed" and value != int(value):
                raise ValueError("cycles_observed must be an integer")
        if not isinstance(notes, str) or len(notes) > 20000:
            raise ValueError("Notes must be text of at most 20000 characters")
        # Drafts may contain mismatched conditions; acceptance checks are explicit.
        _json(conditions)
        if len(_json(conditions)) > 20000:
            raise ValueError("Conditions are too large")
        experiment = {"id": _id("experiment"), "project_id": project_id, "candidate_id": candidate_id,
                      "label": label, "conditions": deepcopy(conditions), "metrics": deepcopy(metrics),
                      "units": {k: METRIC_UNITS[k] for k in metrics}, "notes": notes, "status": "draft",
                      "evidence_kind": "unaccepted_processed_experiment", "created_at": _now(),
                      "project_revision_at_submission": project["revision"]}
        with self._connect() as db:
            db.execute("INSERT INTO experiments VALUES(?,?,?,?,?)", (experiment["id"], project_id, candidate_id, "draft", _json(experiment)))
            self._event(db, project_id, "experiment_drafted", experiment_id=experiment["id"], candidate_id=candidate_id)
        return experiment

    def accept_experiment(self, experiment_id, reason):
        reason = _text(reason, "Acceptance reason")
        with self._connect() as db:
            row = db.execute("SELECT payload FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            if not row:
                raise ValueError("Experiment not found")
            exp = json.loads(row[0])
            if exp["status"] == "accepted":
                return exp
            project = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (exp["project_id"],)).fetchone()[0])
            if exp["conditions"].get("target") != project["target"]:
                raise ValueError("Experiment target must explicitly match the project target")
            for key in ("support", "feed"):
                if not _specified(exp["conditions"].get(key)):
                    raise ValueError(f"Acceptance requires a stated experimental {key}")
            exp.update(status="accepted", accepted_at=_now(), acceptance_reason=reason,
                       evidence_kind="accepted_experimental_measurement")
            exp["project_revision_at_acceptance"] = self._touch(db, exp["project_id"])
            db.execute("UPDATE experiments SET status='accepted',payload=? WHERE id=?", (_json(exp), experiment_id))
            self._event(db, exp["project_id"], "experiment_accepted", experiment_id=experiment_id, reason=reason)
        return exp

    def save_run(self, project_id, result):
        """Also available to registered tools; save exact inputs/version in result."""
        self._project(project_id)
        record = {**deepcopy(result), "id": _id("run"), "project_id": project_id, "created_at": _now()}
        with self._connect() as db:
            db.execute("INSERT INTO runs(id,project_id,payload) VALUES(?,?,?)", (record["id"], project_id, _json(record)))
            self._event(db, project_id, "run_saved", run_id=record["id"], kind_of_run=record.get("kind"), method_id=record.get("method_id"))
        return record

    def get_run(self, project_id, run_id):
        project = self._project(project_id)
        with self._connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=? AND project_id=?", (run_id, project_id)).fetchone()
        if not row:
            raise ValueError("Run not found in this project")
        run = json.loads(row[0])
        run["project_changed_since_run"] = run.get("revision") != project["revision"]
        run["stale"] = run["project_changed_since_run"]
        return run

    def save_custom_run(self, project_id, result):
        if not isinstance(result, dict) or not result.get("method_id") or not result.get("method_version"):
            raise ValueError("A custom calculation requires its exact method identifier and version")
        project = self._project(project_id)
        return self.save_run(project_id, {**deepcopy(result), "kind": "custom_calculation",
                                         "revision": project["revision"], "configuration": project["configuration"]})

    def calculate(self, project_id, candidate_id=None, method_id=None):
        if method_id not in {None, economics.METHOD_ID, "separation_unit_tea@1.0.0"}:
            raise ValueError("Use the method registry executor for a custom method; this endpoint evaluates separation_unit_tea")
        project = self._project(project_id)
        if candidate_id:
            self.get_candidate(candidate_id)
        values, details = self._inputs(project, candidate_id)
        result = economics.evaluate(values)
        result.update(kind="calculate", candidate_id=candidate_id, revision=project["revision"],
                      configuration=project["configuration"], input_details=list(details.values()),
                      input_revision_ids=sorted({d["revision_id"] for d in details.values()}))
        if candidate_id:
            result["uncertainties"].append("Only accepted measurements with matching support/feed/conditions replace scenario inputs; observed cycles never replace assumed usable life.")
        return self.save_run(project_id, result)

    def add_scale_prediction(self, project_id, label, intended_bed_volume_l, scale_description, basis, values, candidate_id=None, source_url=""):
        """Save a researcher's scale scenario separately from measurements and current inputs."""
        project = self._project(project_id)
        label, basis = _text(label, "Prediction label", 200), _text(basis, "Prediction basis")
        scale_description = _text(scale_description, "Scale, feed, support and flow context", 5000)
        if isinstance(intended_bed_volume_l, bool) or not isinstance(intended_bed_volume_l, (int, float)) or not math.isfinite(intended_bed_volume_l) or intended_bed_volume_l <= 0:
            raise ValueError("Intended total bed volume must be a positive finite number of litres")
        if candidate_id is not None:
            self.get_candidate(candidate_id)
        if not isinstance(source_url, str) or len(source_url) > 2000 or (source_url and (urlparse(source_url).scheme not in {"http", "https"} or not urlparse(source_url).hostname)):
            raise ValueError("Prediction source URL must be HTTP(S) or empty")
        supplied = economics.validate_values(values)
        missing = REQUIRED_PREDICTION_INPUTS - set(supplied)
        if missing:
            raise ValueError("Explicit predicted performance, production and scale-specific equipment/labor inputs are required: " + ", ".join(sorted(missing)))
        # Shared scenario values only. Candidate overrides and accepted small-column
        # measurements are deliberately not transferred to a different scale.
        inherited, details = self._inputs(project)
        for key in economics.OPTIONAL_PARAMETERS:
            inherited.pop(key, None)
            details.pop(key, None)
        snapshot = {**inherited, **supplied}
        checked = economics.evaluate(snapshot)  # Check finite arithmetic and any declared feed balance before saving.
        if not math.isfinite(intended_bed_volume_l * checked["summary"]["productivity_kg_per_l_day"]):
            raise ValueError("Intended scale exceeds supported finite numeric range")
        for key, value in supplied.items():
            details[key] = {"parameter": key, "value": value, "unit": economics.UNITS[key],
                            "evidence_kind": "user_supplied_prediction", "reason": basis}
        record = {"id": _id("prediction"), "project_id": project_id, "candidate_id": candidate_id,
                  "label": label, "created_at": _now(), "evidence_kind": "user_supplied_prediction",
                  "status": "prediction_not_measurement", "project_revision": project["revision"],
                  "target": project["target"], "competitor": project["competitor"],
                  "intended_bed_volume_l": float(intended_bed_volume_l), "scale_description": scale_description,
                  "basis": basis, "source_url": source_url, "supplied_values": supplied, "inputs": snapshot,
                  "input_details": list(details.values()), "inherited_parameters": sorted(set(inherited) - set(supplied)),
                  "qualification": "Researcher-supplied predictions and retained shared scenario assumptions. No physical scale-up simulation, experimental acceptance, or automatic equipment/labor scaling."}
        with self._connect() as db:
            db.execute("INSERT INTO scale_predictions(id,project_id,payload) VALUES(?,?,?)", (record["id"], project_id, _json(record)))
            self._event(db, project_id, "scale_prediction_saved", prediction_id=record["id"], candidate_id=candidate_id)
        return record

    def list_scale_predictions(self, project_id):
        self._project(project_id)
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM scale_predictions WHERE project_id=? ORDER BY seq DESC LIMIT 100", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_scale_prediction(self, project_id, prediction_id):
        self._project(project_id)
        with self._connect() as db:
            row = db.execute("SELECT payload FROM scale_predictions WHERE project_id=? AND id=?", (project_id, prediction_id)).fetchone()
        if not row:
            raise ValueError("Scale prediction not found in this project")
        return json.loads(row[0])

    def calculate_scale_prediction(self, project_id, prediction_id):
        prediction = self.get_scale_prediction(project_id, prediction_id)
        result = economics.evaluate(prediction["inputs"])
        required, intended = result["summary"]["required_bed_volume_l"], prediction["intended_bed_volume_l"]
        mismatch = abs(required - intended) / intended > 0.05
        scale_check = {"status": "mismatch" if mismatch else "consistent",
                       "intended_bed_volume_l": intended, "calculated_required_bed_volume_l": required,
                       "implied_output_kg_per_day_at_intended_volume": intended * result["summary"]["productivity_kg_per_l_day"],
                       "qualification": "Arithmetic comparison of aggregate operating material volumes; 5% display tolerance. It does not establish feasible column geometry, pressure drop or transport."}
        if mismatch:
            result["uncertainties"].append("Predicted output/cycle time and requested production imply a required bed volume more than 5% different from the intended volume. Reconcile the design and scale-specific costs before using this estimate.")
        result["uncertainties"].append(prediction["qualification"])
        result.update(kind="scale_prediction_calculation", candidate_id=prediction["candidate_id"],
                      revision=prediction["project_revision"], input_details=prediction["input_details"],
                      evidence_kind="user_supplied_prediction", scale_check=scale_check,
                      prediction={key: deepcopy(prediction[key]) for key in ("id", "label", "target", "competitor", "basis", "source_url", "scale_description", "intended_bed_volume_l", "project_revision", "qualification")})
        return self.save_run(project_id, result)

    def sensitivity(self, project_id, candidate_id=None, keys=None, factors=None):
        """Persist a reproducible what-if sweep without changing any evidence."""
        project = self._project(project_id)
        if candidate_id:
            self.get_candidate(candidate_id)
        keys = ["prepared_material_cost_usd_per_l", "collected_target_kg_per_l_cycle", "usable_lifetime_cycles",
                "labor_hours_per_day", "equipment_cost_usd"] if keys is None else keys
        factors = [.5, 1.0, 2.0] if factors is None else factors
        if not isinstance(keys, list) or not 1 <= len(keys) <= 10 or any(key not in economics.UNITS for key in keys):
            raise ValueError("Supply between 1 and 10 supported sensitivity parameter keys")
        if len(set(keys)) != len(keys):
            raise ValueError("Sensitivity keys must be unique")
        if not isinstance(factors, list) or not 1 <= len(factors) <= 10 or any(isinstance(f, bool) or not isinstance(f, (int, float)) or not math.isfinite(f) or f <= 0 for f in factors):
            raise ValueError("Supply between 1 and 10 positive finite multiplicative factors")
        values, details = self._inputs(project, candidate_id)
        missing = set(keys) - set(values)
        if missing:
            raise ValueError("Sensitivity input is not defined in the scenario: " + ", ".join(sorted(missing)))
        base = economics.evaluate(values)
        sweeps = []
        for key in keys:
            rows = []
            for factor in factors:
                value = values[key] * factor
                if not math.isfinite(value):
                    rows.append({"value": None, "factor": factor, "status": "inapplicable", "reason": "Scaled input exceeds finite numeric range"})
                    continue
                try:
                    trial = economics.sensitivity(values, key, [value])["rows"][0]
                    rows.append({**trial, "factor": factor, "status": "calculated"})
                except ValueError as error:
                    rows.append({"value": value, "factor": factor, "status": "inapplicable", "reason": str(error)})
            sweeps.append({"parameter": key, "unit": economics.UNITS[key], "baseline_value": values[key], "rows": rows})
        return self.save_run(project_id, {"kind": "sensitivity", "method_id": economics.METHOD_ID,
            "method_version": economics.METHOD_VERSION, "analysis_type": "one_at_a_time_multiplicative_sensitivity",
            "candidate_id": candidate_id, "revision": project["revision"], "configuration": project["configuration"],
            "summary": base["summary"], "baseline_summary": base["summary"], "sensitivity": sweeps,
            "assumptions": values, "input_details": list(details.values()),
            "input_revision_ids": sorted({d["revision_id"] for d in details.values()}),
            "boundary": base["boundary"], "factors": factors,
            "uncertainties": base["uncertainties"] + ["One input changes at a time; even measured inputs vary only as hypothetical scenarios. Saved evidence is unchanged. Invalid combinations are reported, not interpreted as valid predictions."]})

    def rank(self, project_id, pool="untested", limit=10, assumption_overrides=None,
             configuration_overrides=None, exclude_candidate_ids=None, scenario_reason=""):
        if pool not in {"untested", "updated"}:
            raise ValueError("Rank pool must be untested or updated")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Ranking limit must be between 1 and 100")
        project = self._project(project_id)
        committed_configuration = deepcopy(project["configuration"])
        overrides = economics.validate_values({} if assumption_overrides is None else assumption_overrides)
        config = {} if configuration_overrides is None else configuration_overrides
        if not isinstance(config, dict) or set(config) - {"target", "support", "feed", "pH", "temperature_c", "scale", "notes"}:
            raise ValueError("Scenario configuration supports target, support, feed, pH, temperature_c, scale and notes")
        if "target" in config and config["target"] != project["target"]:
            raise ValueError("Scenario target must match the project; use a separate project for a different metal pair")
        for key in ("support", "feed", "scale", "notes"):
            if key in config:
                _text(config[key], key, 5000)
        for key in ("pH", "temperature_c"):
            if key in config and (isinstance(config[key], bool) or not isinstance(config[key], (int, float)) or not math.isfinite(config[key])):
                raise ValueError(f"{key} must be finite numeric data")
        excluded_ids = [] if exclude_candidate_ids is None else exclude_candidate_ids
        if not isinstance(excluded_ids, list) or len(excluded_ids) > self.candidate_count() or any(not isinstance(cid, str) for cid in excluded_ids):
            raise ValueError("Excluded candidate IDs must be a list of library IDs")
        if len(excluded_ids) != len(set(excluded_ids)):
            raise ValueError("Excluded candidate IDs must be unique")
        for candidate_id in excluded_ids:
            self.get_candidate(candidate_id)
        hypothetical = bool(overrides or config or excluded_ids)
        if hypothetical:
            scenario_reason = _text(scenario_reason, "Scenario reason")
        elif not isinstance(scenario_reason, str):
            raise ValueError("Scenario reason must be text")
        scenario = {"assumption_overrides": overrides, "configuration_overrides": deepcopy(config),
                    "exclude_candidate_ids": list(excluded_ids), "reason": scenario_reason}
        project["configuration"] = {**project["configuration"], **deepcopy(config)}
        experiments, revisions = self._experiments(project_id), self._revisions(project_id)
        with self._connect() as db:
            candidates = [json.loads(r[0]) for r in db.execute("SELECT payload FROM candidates ORDER BY id")]
        accepted_by = {}
        for exp in experiments:
            if exp["status"] == "accepted":
                accepted_by.setdefault(exp["candidate_id"], []).append(exp)
        rows, exclusions, count = [], [], 0
        for candidate in candidates:
            accepted = accepted_by.get(candidate["id"], [])
            if (pool == "updated") != bool(accepted):
                continue
            count += 1
            profile = candidate.get("screening", {}).get("mean", {})
            target, competitor = profile.get(project["target"]), profile.get(project["competitor"])
            contrast = target - competitor if isinstance(target, (int, float)) and isinstance(competitor, (int, float)) else None
            row = {"candidate_id": candidate["id"], "name": candidate["name"], "profile_contrast": contrast,
                   "organism": candidate.get("organism_as_reported"), "eligible": True, "reasons": [],
                   "source_id": candidate.get("source_id"), "source_locator": candidate.get("locator"),
                   "pool": pool, "experiment_ids": [e["id"] for e in accepted]}
            if candidate["id"] in excluded_ids:
                row["reasons"].append("Excluded from this recommendation scenario by user request")
            if pool == "untested":
                row["qualification"] = "Published screening contrast for follow-up testing; no candidate process-cost inference"
                row["reported_profile_sd"] = {m: candidate.get("screening", {}).get("sd", {}).get(m) for m in (project["target"], project["competitor"])}
                if contrast is None or not math.isfinite(contrast):
                    row["reasons"].append("No finite screening values for the selected pair")
            else:
                matched = [e for e in accepted if not self._applicability(project, e)]
                if not matched:
                    row["reasons"].extend(sorted({reason for exp in accepted for reason in self._applicability(project, exp)}))
                # Combine only experiments at exactly the same operating conditions;
                # never build a fictional complete experiment across different feeds/pH.
                selected, measured = self._matching_group(project, accepted), {}
                for exp in sorted(selected, key=lambda e: e.get("project_revision_at_acceptance", 0)):
                    measured.update(exp["metrics"])
                missing = sorted(REQUIRED_SCALE_METRICS - set(measured))
                if missing:
                    row["reasons"].append("Missing matched accepted measurements: " + ", ".join(missing))
                values, details = self._inputs(project, candidate["id"], revisions=revisions, experiments=selected)
                # Hypothetical values are applied only to this calculation. They never
                # replace accepted measurements or committed project assumptions.
                values.update(overrides)
                if overrides:
                    row["scenario_assumption_overrides"] = dict(overrides)
                if measured.get("purity_fraction", 1) < values["minimum_purity_fraction"]:
                    row["reasons"].append("Measured purity below the declared project requirement")
                if measured.get("recovery_fraction", 1) < values["minimum_recovery_fraction"]:
                    row["reasons"].append("Measured recovery below the declared project requirement")
                if measured.get("cycles_observed", 0) < 1 and not missing:
                    row["reasons"].append("At least one observed operating cycle is required")
                if measured.get("collected_target_kg_per_l_cycle", 1) <= 0:
                    row["reasons"].append("Measured collected target output is zero")
                row.update(measured_metrics=measured, applicable_experiment_ids=[e["id"] for e in selected],
                           qualification="Conditional priority for the next scale evaluation; useful lifetime, hydrodynamics and full plant economics remain unvalidated")
                if not row["reasons"]:
                    try:
                        result = economics.evaluate(values)
                        row.update(cost_usd_per_kg=result["summary"]["cost_usd_per_kg"],
                                   required_bed_volume_l=result["summary"]["required_bed_volume_l"],
                                   assumed_usable_lifetime_cycles=values["usable_lifetime_cycles"],
                                   input_revision_ids=sorted({d["revision_id"] for d in details.values()}))
                        if row["cost_usd_per_kg"] > values["cost_ceiling_usd_per_kg"]:
                            row["reasons"].append("Conditional separation-unit cost exceeds the declared allowance")
                    except ValueError as error:
                        row["reasons"].append(str(error))
            row["eligible"] = not row["reasons"]
            if row["eligible"]:
                rows.append(row)
            else:
                exclusions.append(row)
        rows.sort(key=(lambda row: (-row["profile_contrast"], row["candidate_id"])) if pool == "untested" else (lambda row: (row["cost_usd_per_kg"], row["candidate_id"])))
        for number, row in enumerate(rows, 1):
            row["rank"] = number
        assumptions, _ = self._inputs(project, revisions=revisions)
        assumptions.update(overrides)
        rationale = ("All candidates without an explicitly accepted project experiment are compared by target-minus-competitor published normalized profile. No assay-signal cutoff or invented candidate economics is used. Ties do not imply scientifically distinct performance."
                     if pool == "untested" else "All candidates with explicitly accepted project experiments are checked for matched conditions, required measured metrics and declared recovery/purity/cost constraints. Qualified rows are ordered by conditional separation-unit cost; observed cycles and assumed maximum lifetime remain distinct.")
        return self.save_run(project_id, {"kind": "rank", "pool": pool, "rows": rows[:limit],
                    "ranked_candidate_ids": [row["candidate_id"] for row in rows],
                    "total_evaluated": len(candidates), "pool_count": count, "eligible_count": len(rows),
                    "excluded_count": len(exclusions), "exclusions": exclusions, "rationale": rationale,
                    "assumptions": assumptions, "revision": project["revision"], "method_id": "screening_priority_v1" if pool == "untested" else economics.METHOD_ID,
                    "method_version": "1.0.0", "configuration": project["configuration"],
                    "committed_configuration": committed_configuration, "scenario": scenario, "is_hypothetical": hypothetical,
                    "uncertainties": ["Profile contrast is not a separation factor, capacity, recovery or process prediction.",
                                      "Technical screening SD does not establish independent reproducibility or rank confidence.",
                                      "An accepted experiment records explicit acceptance, not independent verification of the submitted measurement.",
                                      "Candidates lacking applicable measurements remain visible as insufficient evidence."]})

    def _testing_count(self, count):
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
            raise ValueError("Candidate count must be an integer from 1 to 8 for wells A1–H1")
        return count

    def _testing_rank(self, project_id, ranking_run_id, allow_stale):
        if not isinstance(allow_stale, bool):
            raise ValueError("allow_stale must be true or false")
        run = self.get_run(project_id, ranking_run_id)
        if run.get("kind") != "rank":
            raise ValueError("Testing selections require a saved candidate ranking")
        if run["stale"] and not allow_stale:
            raise ValueError("Project changed since this ranking; rerank or explicitly request its historical snapshot with allow_stale")
        return run

    def _testing_rows(self, run, candidate_ids):
        # New ranks retain every eligible ID even when only the first few rows were
        # displayed. Older ranks can only export their actually saved rows.
        ranked_ids = run.get("ranked_candidate_ids", [row["candidate_id"] for row in run["rows"]])
        positions = {candidate_id: rank for rank, candidate_id in enumerate(ranked_ids, 1)}
        visible = {row["candidate_id"]: row for row in run["rows"]}
        rows = []
        for order, candidate_id in enumerate(candidate_ids, 1):
            if candidate_id not in positions:
                raise ValueError(f"Candidate {candidate_id} is not eligible in the saved ranking; rerank with the intended criteria")
            candidate = self.get_candidate(candidate_id)
            row = deepcopy(visible.get(candidate_id, {}))
            row.update(candidate_id=candidate_id, candidate_name=candidate["name"], rank=positions[candidate_id],
                       selection_order=order, source_id=candidate.get("source_id"), source_locator=candidate.get("locator"))
            rows.append(row)
        return rows

    def _testing_snapshot(self, run):
        keys = ("id", "project_id", "revision", "pool", "created_at", "method_id", "method_version", "assumptions",
                "configuration", "committed_configuration", "scenario", "is_hypothetical", "rationale", "uncertainties")
        return {key: deepcopy(run[key]) for key in keys if key in run}

    def _save_testing_record(self, table, record, allow_stale):
        # Internal table names are fixed by the two callers. Compare the revision
        # again while holding the write transaction to catch concurrent changes.
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (record["project_id"],)).fetchone()[0])
            stale = current["revision"] != record["revision"]
            if stale and not allow_stale:
                raise ValueError("Project changed since this ranking; rerank or explicitly request its historical snapshot with allow_stale")
            record["historical_snapshot_requested"] = allow_stale
            record["project_changed_at_creation"] = stale
            db.execute(f"INSERT INTO {table}(id,project_id,payload) VALUES(?,?,?)", (record["id"], record["project_id"], _json(record)))
            self._event(db, record["project_id"], "testing_selection_saved" if table == "testing_selections" else "testing_batch_created",
                        record_id=record["id"], ranking_run_id=record["ranking_run_id"])
        return {**record, "stale": stale, "project_changed_since_run": stale}

    def save_testing_selection(self, project_id, ranking_run_id, candidate_ids, reason, allow_stale=False):
        """Save the exact eligible IDs/order agreed in conversation, before export."""
        if not isinstance(candidate_ids, list) or any(not isinstance(cid, str) for cid in candidate_ids):
            raise ValueError("Candidate IDs must be a list of library IDs")
        self._testing_count(len(candidate_ids))
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Selected candidate IDs must be unique")
        reason = _text(reason, "Selection reason")
        run = self._testing_rank(project_id, ranking_run_id, allow_stale)
        record = {"id": _id("selection"), "project_id": project_id, "created_at": _now(), "revision": run["revision"],
                  "ranking_run_id": run["id"], "candidate_ids": list(candidate_ids), "count": len(candidate_ids),
                  "reason": reason, "rows": self._testing_rows(run, candidate_ids),
                  "ranking_snapshot": self._testing_snapshot(run), "scenario": deepcopy(run.get("scenario", {})),
                  "is_hypothetical": run.get("is_hypothetical", False)}
        return self._save_testing_record("testing_selections", record, allow_stale)

    def _get_testing_record(self, table, project_id, record_id):
        project = self._project(project_id)
        with self._connect() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=? AND project_id=?", (record_id, project_id)).fetchone()
        if not row:
            raise ValueError("Testing record not found in this project")
        record = json.loads(row[0])
        record["stale"] = record["revision"] != project["revision"]
        record["project_changed_since_run"] = record["stale"]
        return record

    def _list_testing_records(self, table, project_id):
        project = self._project(project_id)
        with self._connect() as db:
            rows = db.execute(f"SELECT payload FROM {table} WHERE project_id=? ORDER BY seq DESC", (project_id,)).fetchall()
        records = [json.loads(row[0]) for row in rows]
        for record in records:
            record["stale"] = record["revision"] != project["revision"]
            record["project_changed_since_run"] = record["stale"]
        return records

    def list_testing_selections(self, project_id):
        return self._list_testing_records("testing_selections", project_id)

    def get_testing_selection(self, project_id, selection_id):
        return self._get_testing_record("testing_selections", project_id, selection_id)

    def list_testing_batches(self, project_id):
        return self._list_testing_records("testing_batches", project_id)

    def get_testing_batch(self, project_id, batch_id):
        return self._get_testing_record("testing_batches", project_id, batch_id)

    def create_testing_batch(self, project_id, count, stock_volume_min_ul=None, stock_volume_max_ul=None,
                             ranking_run_id=None, selection_id=None, pool="untested", seed=None, allow_stale=False):
        """Freeze a software-demo starting-well plan; no physical procedure is run."""
        self._testing_count(count)
        self._project(project_id)
        if not isinstance(allow_stale, bool):
            raise ValueError("allow_stale must be true or false")
        if pool not in {"untested", "updated"}:
            raise ValueError("Rank pool must be untested or updated")
        if ranking_run_id is not None and selection_id is not None:
            raise ValueError("Choose a ranking_run_id or a selection_id, not both")
        supplied = (stock_volume_min_ul, stock_volume_max_ul)
        uses_default = all(value is None for value in supplied)
        if uses_default:
            stock_volume_min_ul, stock_volume_max_ul = 35, 250
        elif any(value is None for value in supplied):
            raise ValueError("Supply stock_volume_min_ul and stock_volume_max_ul together")
        for key, value in (("stock_volume_min_ul", stock_volume_min_ul), ("stock_volume_max_ul", stock_volume_max_ul)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 35 <= value <= 250:
                raise ValueError(f"{key} must be a finite number from 35 to 250 uL")
        if stock_volume_min_ul > stock_volume_max_ul:
            raise ValueError("stock_volume_min_ul cannot exceed stock_volume_max_ul")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**53 - 1):
            raise ValueError("Random seed must be an integer from 0 to 9007199254740991")
        seed = random.SystemRandom().randrange(2**53) if seed is None else seed
        selection = None
        if selection_id is not None:
            selection = self.get_testing_selection(project_id, selection_id)
            run = self._testing_rank(project_id, selection["ranking_run_id"], allow_stale)
            available = selection["rows"]
        else:
            run = self._testing_rank(project_id, ranking_run_id, allow_stale) if ranking_run_id is not None else self.rank(project_id, pool, count)
            ranked_ids = run.get("ranked_candidate_ids", [row["candidate_id"] for row in run["rows"]])
            available = self._testing_rows(run, ranked_ids[:count])
        if len(available) < count:
            raise ValueError(f"Requested {count} candidates but only {len(available)} are available in this saved selection or ranking")
        batch_id = _id("batch")
        plate_id = batch_id + "_plate_1"
        rng = random.Random(seed)
        integer_demo = stock_volume_min_ul == 35 and stock_volume_max_ul == 250
        rows = []
        for index, selected in enumerate(available[:count]):
            value = rng.randint(35, 250) if integer_demo else rng.uniform(stock_volume_min_ul, stock_volume_max_ul)
            if not integer_demo:
                value = max(stock_volume_min_ul, min(stock_volume_max_ul, float(format(value, ".6g"))))
            # Store the generated values, not a recipe to regenerate on download.
            row = {"candidate_id": selected["candidate_id"], "candidate_name": selected["candidate_name"],
                   "rank": index + 1, "recommendation_rank": selected["rank"], "well": "ABCDEFGH"[index] + "1",
                   "plate_id": plate_id, "stock_volume": value, "volume_unit": "uL",
                   "volume_basis": "simulated", "volume_location": "starting_well",
                   "water_addition_mode": "constant_per_starting_well"}
            rows.append(row)
        record = {"id": batch_id, "project_id": project_id, "created_at": _now(), "revision": run["revision"],
                  "schema_version": "lanm_testing_batch_2", "assay_profile": "serial_dilution_mvp", "plate_format": "96_well",
                  "plate_id": plate_id, "count": count, "candidate_ids": [row["candidate_id"] for row in rows], "rows": rows,
                  "volume_location": "starting_well", "volume_basis": "simulated",
                  "water_addition": {"mode": "constant_per_starting_well", "volume_ul": None,
                                     "configured_by": "receiving_automation"},
                  "generation": {"quantity": "stock_volume", "minimum": stock_volume_min_ul, "maximum": stock_volume_max_ul,
                                 "unit": "uL", "seed": seed,
                                 "distribution": "discrete_uniform" if integer_demo else "uniform",
                                 "uses_demo_defaults": uses_default},
                  "volume_note": "Simulated stock-solution volumes dispensed into starting wells for the MVP. "
                                 "The receiving automation sets one fixed water volume for all starting wells and checks "
                                 "stock plus water against the selected plate's working-volume limit.",
                  "ranking_run_id": run["id"], "ranking_snapshot": self._testing_snapshot(run),
                  "selection_id": selection_id, "selection_reason": selection["reason"] if selection else "Top requested candidates from the saved ranking",
                  "selection_snapshot": {key: deepcopy(value) for key, value in selection.items() if key not in {"stale", "project_changed_since_run"}} if selection else None,
                  "scenario": deepcopy(run.get("scenario", {})), "is_hypothetical": run.get("is_hypothetical", False),
                  "download_url": f"/api/projects/{project_id}/testing-batches/{batch_id}/csv"}
        return self._save_testing_record("testing_batches", record, allow_stale)

    def testing_batch_csv(self, project_id, batch_id):
        batch = self.get_testing_batch(project_id, batch_id)
        # Preserve historical concentration exports without reinterpreting their units.
        schemas = {"lanm_testing_batch_1": LEGACY_TESTING_CSV_FIELDS, "lanm_testing_batch_2": TESTING_CSV_FIELDS}
        if batch["schema_version"] not in schemas:
            raise ValueError("Unsupported saved testing batch schema")
        fields = schemas[batch["schema_version"]]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        for row in batch["rows"]:
            record = {key: row.get(key, "") for key in fields}
            record.update(schema_version=batch["schema_version"], batch_id=batch["id"])
            name = record["candidate_name"]
            if name.lstrip().startswith(("=", "+", "-", "@")) or name.startswith(("\t", "\r", "\n")):
                record["candidate_name"] = "'" + name
            writer.writerow(record)
        return output.getvalue()

    def list_runs(self, project_id):
        project = self._project(project_id)
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE project_id=? ORDER BY seq DESC LIMIT 100", (project_id,)).fetchall()
        runs = [json.loads(row[0]) for row in rows]
        for run in runs:
            run["project_changed_since_run"] = run.get("revision") != project["revision"]
            run["stale"] = run["project_changed_since_run"]
        return runs

    def messages(self, project_id):
        self._project(project_id)
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM messages WHERE project_id=? ORDER BY seq", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def add_message(self, project_id, role, content):
        self._project(project_id)
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Message role must be user, assistant or system")
        content = _text(content, "Message", 200000)
        record = {"id": _id("message"), "project_id": project_id, "role": role, "content": content, "created_at": _now()}
        with self._connect() as db:
            db.execute("INSERT INTO messages(id,project_id,payload) VALUES(?,?,?)", (record["id"], project_id, _json(record)))
        return record

    def add_source(self, project_id, title, text, url="", *, provenance=None, evidence_kind="user_supplied_source"):
        self._project(project_id)
        title, text = _text(title, "Source title", 500), _text(text, "Source text", 2000000)
        if not isinstance(url, str) or (url and not url.startswith(("https://", "http://"))):
            raise ValueError("Source URL must be HTTP(S) or empty")
        if evidence_kind not in {"user_supplied_source", "retrieved_literature_abstract"}:
            raise ValueError("Source evidence must remain separate from experimental measurements")
        if provenance is not None and (not isinstance(provenance, dict) or len(_json(provenance)) > 100000):
            raise ValueError("Source provenance must be a bounded metadata object")
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._connect() as db:
            previous = db.execute("SELECT payload FROM sources WHERE project_id=? AND sha256=?", (project_id, digest)).fetchone()
            if previous:
                return json.loads(previous[0])
            record = {"id": _id("source"), "project_id": project_id, "title": title, "text": text, "url": url,
                      "sha256": digest, "created_at": _now(), "evidence_kind": evidence_kind,
                      "verification": "Archived source; claims are not automatically accepted measurements"}
            if provenance is not None:
                record["provenance"] = deepcopy(provenance)
            db.execute("INSERT INTO sources VALUES(?,?,?,?)", (record["id"], project_id, digest, _json(record)))
            self._event(db, project_id, "source_archived", source_id=record["id"], sha256=digest)
        return record

    def _archive_pubmed_article(self, project_id, article):
        scope = "PubMed citation and abstract. The full article has not been retrieved."
        authors = "; ".join(article.get("authors", []))
        lines = [scope, "", article["title"], "PMID: " + article["pmid"],
                 "Journal: " + str(article.get("journal") or "Not supplied"),
                 "Year: " + str(article.get("year") or "Not supplied"), "Authors: " + authors]
        for key in ("doi", "pmcid"):
            if article.get(key): lines.append(key.upper() + ": " + article[key])
        lines.extend(["", "Abstract", article.get("abstract") or "No abstract was supplied by PubMed."])
        if article.get("publication_types"):
            lines.extend(["", "Publication types: " + "; ".join(article["publication_types"])])
        if article.get("notices"):
            lines.extend(["", "Indexing notices and related records", json.dumps(article["notices"], ensure_ascii=False, indent=2)])
        lines.extend(["", "Source: " + article["url"]])
        metadata = {key: deepcopy(value) for key, value in article.items() if key not in {"abstract", "abstract_sections"}}
        metadata.update(provider="NCBI PubMed", content_scope=scope)
        display_title = (article["title"].strip() or "PubMed record " + article["pmid"])
        if len(display_title) > 500: display_title = display_title[:499] + "…"
        source = self.add_source(project_id, display_title, "\n".join(lines), article["url"],
                                 provenance=metadata, evidence_kind="retrieved_literature_abstract")
        return {**article, "source_id": source["id"], "source_sha256": source["sha256"]}

    def search_pubmed(self, project_id, query, limit=5, sort="relevance"):
        """Archive bounded retrieval results as literature, without accepting experiments."""
        from .pubmed import PubMedClient
        self._project(project_id)
        result = PubMedClient(rate_limit_path=self.db_path).search(query, limit=limit, sort=sort)
        articles = [self._archive_pubmed_article(project_id, article) for article in result["articles"]]
        record = {"id": _id("search"), "project_id": project_id, "created_at": _now(),
                  **{key: deepcopy(value) for key, value in result.items() if key != "articles"},
                  "records": [{key: deepcopy(a[key]) for key in ("pmid", "title", "source_id", "url", "journal", "year", "has_abstract", "is_retracted", "notices") if key in a} for a in articles]}
        with self._connect() as db:
            db.execute("INSERT INTO literature_searches(id,project_id,payload) VALUES(?,?,?)", (record["id"], project_id, _json(record)))
            self._event(db, project_id, "literature_search_saved", search_id=record["id"], source_ids=[a["source_id"] for a in articles])
        return {**result, "articles": articles, "search_id": record["id"],
                "qualification": "Saved bibliographic records and abstracts. PubMed is not a complete index of REE engineering literature. No experimental result or model input was changed."}

    def fetch_pubmed(self, project_id, pmids):
        from .pubmed import PubMedClient
        self._project(project_id)
        articles = PubMedClient(rate_limit_path=self.db_path).fetch(pmids)
        return {"articles": [self._archive_pubmed_article(project_id, article) for article in articles],
                "missing_pmids": [pmid for pmid in dict.fromkeys(pmids) if pmid not in {article["pmid"] for article in articles}],
                "qualification": "Retrieved citations and available abstracts only. No full text, experiment acceptance, or assumption change is implied.",
                "disclaimer_url": "https://pubmed.ncbi.nlm.nih.gov/disclaimer/"}

    def list_literature_searches(self, project_id):
        self._project(project_id)
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM literature_searches WHERE project_id=? ORDER BY seq DESC LIMIT 20", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_sources(self, project_id):
        self._project(project_id)
        with self._connect() as db:
            own = [json.loads(r[0]) for r in db.execute("SELECT payload FROM sources WHERE project_id=? ORDER BY rowid DESC", (project_id,))]
            library = [json.loads(r[0]) for r in db.execute("SELECT payload FROM library_records WHERE kind='sources'")]
        return own + [{**row, "origin": "published_library", "evidence_kind": "archived_source_metadata"} for row in library]

    def read_source(self, project_id, source_id, query="", offset=0, limit=12000):
        """Read a bounded, hash-verified source excerpt without extracting files."""
        self._project(project_id)
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError("Source query must be text of at most 2000 characters")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("Source offset must be a nonnegative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20000:
            raise ValueError("Source excerpt limit must be between 1 and 20000 characters")
        with self._connect() as db:
            own = db.execute("SELECT payload FROM sources WHERE id=? AND project_id=?", (source_id, project_id)).fetchone()
            row = own or db.execute("SELECT payload FROM library_records WHERE id=? AND kind='sources'", ("sources:" + str(source_id),)).fetchone()
        if not row:
            raise ValueError("Source not found in this project or the published library")
        source = json.loads(row[0])
        result = {"source_id": source_id, "title": source.get("title", source_id), "url": source.get("url", ""),
                  "status": "unavailable", "hash_verified": False, "excerpt": "", "offset": offset,
                  "next_offset": None, "total_chars": None, "query_found": None if not query else False}
        try:
            if own:
                raw = source["text"].encode("utf-8")
                expected = source.get("sha256")
            else:
                member = str(source.get("text_path", "")).replace("\\", "/")
                name = PurePosixPath(member)
                if not member or name.is_absolute() or ".." in name.parts or ":" in member:
                    result["reason"] = "No supported relative archived text path is recorded; consult the linked source."
                    return result
                expected = source.get("text_sha256")
                if not expected:
                    result["reason"] = "No text hash is recorded for this source; consult its linked original."
                    return result
                archive = source_archive(self.data_dir)
                if not archive.is_file():
                    result["reason"] = "The original source archive is unavailable; consult the linked source."
                    return result
                with zipfile.ZipFile(archive, "r") as package:
                    matches = [info for info in package.infolist() if info.filename == member]
                    if len(matches) != 1 or matches[0].is_dir():
                        result["reason"] = "The expected source text is missing or ambiguous in the archive; consult the linked source."
                        return result
                    if matches[0].file_size > 50_000_000:
                        result["reason"] = "The archived text exceeds the supported source-reading size."
                        return result
                    raw = package.read(matches[0])
            actual = hashlib.sha256(raw).hexdigest()
            if not expected or actual != expected:
                result["reason"] = "Archived source text failed its recorded SHA-256 integrity check; no excerpt is shown."
                return result
            text = raw.decode("utf-8-sig")
        except (OSError, KeyError, ValueError, UnicodeError, zipfile.BadZipFile, RuntimeError) as error:
            result["reason"] = "Source text is unavailable: " + str(error)
            return result
        start = min(offset, len(text))
        if query:
            found = text.lower().find(query.lower(), start)
            result["query_found"] = found >= 0
            if found >= 0:
                start = max(0, found - min(1000, max(0, limit // 3)))
        end = min(len(text), start + limit)
        return {**result, "status": "available", "hash_verified": True, "sha256": actual,
                "excerpt": text[start:end], "offset": start, "next_offset": end if end < len(text) else None,
                "total_chars": len(text)}

    def library_evidence(self, candidate_id=None):
        """Read-only access to retained source contexts/assertions/formulas."""
        with self._connect() as db:
            records = [(row["kind"], json.loads(row["payload"])) for row in db.execute("SELECT kind,payload FROM library_records")]
        contexts = [r for kind, r in records if kind == "contexts" and (candidate_id is None or r.get("candidate_id") == candidate_id)]
        context_ids = {r["id"] for r in contexts}
        return {"contexts": contexts, "assertions": [r for kind, r in records if kind == "assertions" and r.get("context_id") in context_ids],
                "formulas": [r for kind, r in records if kind == "formulas" and r.get("context_id") in context_ids]}
