import os

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.dependencies import ARTIFACTS_DIR, get_current_user_id, get_runtime_manager, get_store
from ..core.configuration import write_bird_conf_artifact, write_config_artifact
from ..core.models import EventCreate, ExperimentCreate, ExperimentUpdate, RunStatus

router = APIRouter()


def _require_experiment(store, experiment_id: str, user_id: str):
    experiment = store.get_experiment(experiment_id)
    if experiment is None or experiment.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail="experiment not found")
    return experiment


def _require_run(store, run_id: str, user_id: str):
    run = store.get_run(run_id)
    if run is None or run.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _experiment_dir(experiment_id: str):
    return ARTIFACTS_DIR / "experiments" / experiment_id


def _persist_experiment_artifacts(store, experiment):
    experiment_dir = _experiment_dir(experiment.experiment_id)
    config_path = experiment_dir / "experiment_config.json"
    generated_config_path = write_config_artifact(experiment, config_path)
    generated_bird_conf_path = write_bird_conf_artifact(
        experiment,
        experiment_dir / "bird.conf",
    )
    return store.update_experiment_fields(
        experiment.experiment_id,
        config_path=generated_config_path,
        bird_conf_path=generated_bird_conf_path,
    )


@router.post("/experiments", status_code=status.HTTP_201_CREATED)
def create_experiment(
        payload: ExperimentCreate,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    experiment = store.create_experiment(user_id, payload)
    return _persist_experiment_artifacts(store, experiment)


@router.get("/experiments")
def list_experiments(
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    return store.list_experiments(user_id)


@router.get("/experiments/{experiment_id}")
def get_experiment(
        experiment_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    return _require_experiment(store, experiment_id, user_id)


@router.patch("/experiments/{experiment_id}")
def update_experiment(
        experiment_id: str,
        payload: ExperimentUpdate,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    _require_experiment(store, experiment_id, user_id)
    updated = store.update_experiment(experiment_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if (
        payload.configuration is not None
        or payload.name is not None
        or payload.bird_conf_content is not None
    ):
        updated = _persist_experiment_artifacts(store, updated)
    return updated


@router.get("/experiments/{experiment_id}/runs")
def list_runs_for_experiment(
        experiment_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    _require_experiment(store, experiment_id, user_id)
    return store.list_runs(experiment_id=experiment_id, owner_user_id=user_id)


@router.post("/experiments/{experiment_id}/runs", status_code=status.HTTP_201_CREATED)
def create_run(
        experiment_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    experiment = _require_experiment(store, experiment_id, user_id)
    artifact_dir = ARTIFACTS_DIR / "experiments" / experiment_id / "runs"
    os.makedirs(artifact_dir, exist_ok=True)
    run = store.create_run(experiment, str(artifact_dir / "pending"))
    final_artifact_dir = artifact_dir / run.run_id
    os.makedirs(final_artifact_dir, exist_ok=True)
    run = store.update_run(run.run_id, artifact_dir=str(final_artifact_dir))
    runtime_manager.get_or_create(experiment, run).ensure_runtime()
    return run


@router.get("/runs/{run_id}")
def get_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store)):
    return _require_run(store, run_id, user_id)


@router.post("/runs/{run_id}/start")
def start_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    if run.status not in (RunStatus.READY, RunStatus.FAILED):
        raise HTTPException(status_code=409, detail=f"run cannot be started from status {run.status}")
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    managed.start()
    return store.get_run(run_id)


@router.post("/runs/{run_id}/stop")
def stop_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    managed.stop()
    return store.get_run(run_id)


@router.post("/runs/{run_id}/cleanup")
def cleanup_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    managed.cleanup()
    return store.get_run(run_id)


@router.get("/runs/{run_id}/topology")
def get_run_topology(
        run_id: str,
        time: int = Query(default=0, ge=0),
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.get_topology_snapshot(at_time=time)


@router.get("/runs/{run_id}/map")
def get_run_map(
        run_id: str,
        time: int = Query(default=0, ge=0),
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.get_map_snapshot(at_time=time)


@router.get("/runs/{run_id}/nodes")
def get_run_nodes(
        run_id: str,
        time: int = Query(default=0, ge=0),
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.list_nodes(at_time=time)


@router.get("/runs/{run_id}/events")
def list_run_events(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.list_events()


@router.post("/runs/{run_id}/events", status_code=status.HTTP_201_CREATED)
def create_run_event(
        run_id: str,
        payload: EventCreate,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    try:
        return managed.schedule_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/tasks")
def list_run_tasks(
        run_id: str,
        node: str | None = Query(default=None),
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.list_tasks(node=node)


@router.get("/runs/{run_id}/tasks/{task_id}")
def get_run_task(
        run_id: str,
        task_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.get_task(task_id)


@router.get("/runs/{run_id}/tasks/{task_id}/output")
def get_run_task_output(
        run_id: str,
        task_id: str,
        user_id: str = Depends(get_current_user_id),
        store=Depends(get_store),
        runtime_manager=Depends(get_runtime_manager)):
    run = _require_run(store, run_id, user_id)
    experiment = _require_experiment(store, run.experiment_id, user_id)
    managed = runtime_manager.get_or_create(experiment, run)
    return managed.get_task_output(task_id)
