import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

from .models import ExperimentCreate, ExperimentRecord, ExperimentUpdate, RunRecord


class MetadataStore:
    def __init__(self, metadata_path: str):
        self.metadata_path = Path(metadata_path)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _default_payload(self):
        return {
            "experiments": {},
            "runs": {},
            "events": {},
        }

    def _read(self):
        if not self.metadata_path.exists():
            return self._default_payload()
        with self.metadata_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, payload):
        tmp_path = self.metadata_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp_path, self.metadata_path)

    def create_experiment(self, owner_user_id: str, data: ExperimentCreate,
                          config_path: str = "", experiment_id: Optional[str] = None):
        now = time.time()
        experiment = ExperimentRecord(
            experiment_id=experiment_id or f"exp-{uuid.uuid4().hex[:12]}",
            owner_user_id=owner_user_id,
            name=data.name,
            configuration=data.configuration,
            config_path=config_path,
            gs_lat_long=data.gs_lat_long,
            bird_conf_content=data.bird_conf_content,
            bird_conf_path=None,
            extra_nodes_links=data.extra_nodes_links,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            payload = self._read()
            payload["experiments"][experiment.experiment_id] = experiment.model_dump(mode="json")
            self._write(payload)
        return experiment

    def list_experiments(self, owner_user_id: str):
        with self._lock:
            payload = self._read()
        experiments = [
            ExperimentRecord.model_validate(item)
            for item in payload["experiments"].values()
            if item["owner_user_id"] == owner_user_id
        ]
        experiments.sort(key=lambda item: item.created_at)
        return experiments

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentRecord]:
        with self._lock:
            payload = self._read()
        item = payload["experiments"].get(experiment_id)
        if item is None:
            return None
        return ExperimentRecord.model_validate(item)

    def update_experiment(self, experiment_id: str, patch: ExperimentUpdate):
        with self._lock:
            payload = self._read()
            item = payload["experiments"].get(experiment_id)
            if item is None:
                return None
            current = ExperimentRecord.model_validate(item)
            updates = patch.model_dump(exclude_unset=True)
            updated = ExperimentRecord.model_validate({
                **current.model_dump(mode="json"),
                **updates,
                "updated_at": time.time(),
            })
            payload["experiments"][experiment_id] = updated.model_dump(mode="json")
            self._write(payload)
        return updated

    def update_experiment_fields(self, experiment_id: str, **updates):
        with self._lock:
            payload = self._read()
            item = payload["experiments"].get(experiment_id)
            if item is None:
                return None
            current = ExperimentRecord.model_validate(item)
            updated = ExperimentRecord.model_validate({
                **current.model_dump(mode="json"),
                **updates,
                "updated_at": time.time(),
            })
            payload["experiments"][experiment_id] = updated.model_dump(mode="json")
            self._write(payload)
        return updated

    def delete_experiment(self, experiment_id: str):
        with self._lock:
            payload = self._read()
            if experiment_id not in payload["experiments"]:
                return False

            run_ids = [
                run_id
                for run_id, run in payload["runs"].items()
                if run["experiment_id"] == experiment_id
            ]
            del payload["experiments"][experiment_id]
            for run_id in run_ids:
                payload["runs"].pop(run_id, None)
                payload["events"].pop(run_id, None)
            self._write(payload)
        return True

    def create_run(self, experiment: ExperimentRecord, artifact_dir: str):
        now = time.time()
        run = RunRecord(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            experiment_id=experiment.experiment_id,
            owner_user_id=experiment.owner_user_id,
            artifact_dir=artifact_dir,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            payload = self._read()
            payload["runs"][run.run_id] = run.model_dump(mode="json")
            payload["events"][run.run_id] = []
            self._write(payload)
        return run

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        with self._lock:
            payload = self._read()
        item = payload["runs"].get(run_id)
        if item is None:
            return None
        return RunRecord.model_validate(item)

    def list_runs(self, experiment_id: Optional[str] = None, owner_user_id: Optional[str] = None):
        with self._lock:
            payload = self._read()
        runs = [RunRecord.model_validate(item) for item in payload["runs"].values()]
        if experiment_id is not None:
            runs = [item for item in runs if item.experiment_id == experiment_id]
        if owner_user_id is not None:
            runs = [item for item in runs if item.owner_user_id == owner_user_id]
        runs.sort(key=lambda item: item.created_at)
        return runs

    def update_run(self, run_id: str, **updates):
        with self._lock:
            payload = self._read()
            item = payload["runs"].get(run_id)
            if item is None:
                return None
            current = RunRecord.model_validate(item)
            updated = current.model_copy(update={**updates, "updated_at": time.time()})
            payload["runs"][run_id] = updated.model_dump(mode="json")
            self._write(payload)
        return updated

    def replace_events(self, run_id: str, events: List[dict]):
        with self._lock:
            payload = self._read()
            payload["events"][run_id] = events
            self._write(payload)

    def list_events(self, run_id: str):
        with self._lock:
            payload = self._read()
        return payload["events"].get(run_id, [])
