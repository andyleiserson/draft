import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Request, status
from fastapi.responses import StreamingResponse

from ..local_paths import Paths
from ..query.base import Query
from ..query.demo_logger import DemoLoggerQuery
from ..query.ipa import GateType, IPACoordinatorQuery, IPAHelperQuery
from ..settings import get_settings
from .http_helpers import check_capacity, get_query_from_query_id

router = APIRouter(
    prefix="/start",
    tags=[
        "start",
    ],
)


class IncorrectRoleError(Exception):
    pass


@router.get("/capacity-available")
def capacity_available(
    request: Request,
):
    query_manager = request.app.state.QUERY_MANAGER
    return {"capacity_available": query_manager.capacity_available}


@router.get("/running-queries")
def running_queries(
    request: Request,
):
    query_manager = request.app.state.QUERY_MANAGER
    return {"running_queries": list(query_manager.running_queries.keys())}


@router.post("/demo-logger/{query_id}", status_code=status.HTTP_201_CREATED)
def demo_logger(
    query_id: str,
    num_lines: Annotated[int, Form()],
    total_runtime: Annotated[int, Form()],
    background_tasks: BackgroundTasks,
    request: Request,
):
    query_manager = request.app.state.QUERY_MANAGER
    check_capacity(query_manager)

    query = DemoLoggerQuery(
        query_id=query_id,
        num_lines=num_lines,
        total_runtime=total_runtime,
    )
    background_tasks.add_task(query_manager.run_query, query)
    return {"message": "Process started successfully", "query_id": query_id}


# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
@router.post("/ipa-helper/{query_id}")
def start_ipa_helper(
    query_id: str,
    commit_hash: Annotated[str, Form()],
    gate_type: Annotated[str, Form()],
    stall_detection: Annotated[bool, Form()],
    multi_threading: Annotated[bool, Form()],
    disable_metrics: Annotated[bool, Form()],
    reveal_aggregation: Annotated[bool, Form()],
    background_tasks: BackgroundTasks,
    request: Request,
):
    query_manager = request.app.state.QUERY_MANAGER
    check_capacity(query_manager)

    settings = get_settings()
    role = settings.role
    if not role or role == role.COORDINATOR:
        raise IncorrectRoleError(
            f"Cannot start helper without helper role. Currently running {role=}."
        )

    compiled_id = (
        f"{commit_hash}_{gate_type}"
        f"{'_stall-detection' if stall_detection else ''}"
        f"{'_multi-threading' if multi_threading else ''}"
        f"{'_disable-metrics' if disable_metrics else ''}"
        f"{'_reveal-aggregation' if reveal_aggregation else ''}"
    )

    paths = Paths(
        repo_path=settings.root_path / Path("ipa"),
        config_path=settings.config_path,
        compiled_id=compiled_id,
    )
    query = IPAHelperQuery(
        paths=paths,
        commit_hash=commit_hash,
        query_id=query_id,
        gate_type=GateType[gate_type.upper()],
        stall_detection=stall_detection,
        multi_threading=multi_threading,
        disable_metrics=disable_metrics,
        reveal_aggregation=reveal_aggregation,
        port=settings.helper_port,
    )
    background_tasks.add_task(query_manager.run_query, query)
    return {"message": "Process started successfully", "query_id": query_id}


@router.get("/{query_id}/status")
def get_query_status(
    query_id: str,
    request: Request,
):
    query = get_query_from_query_id(request.app.state.QUERY_MANAGER, Query, query_id)
    return query.status_event_json


@router.get("/{query_id}/log-file")
def get_ipa_helper_log_file(
    query_id: str,
    request: Request,
):
    query = get_query_from_query_id(request.app.state.QUERY_MANAGER, Query, query_id)
    settings = get_settings()

    def iterfile():
        with open(query.log_file_path, "rb") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    d = datetime.fromtimestamp(
                        float(data["record"]["time"]["timestamp"])
                    )
                    message = data["record"]["message"]
                    yield f"{d.isoformat()} - {message}\n"
                except (json.JSONDecodeError, KeyError):
                    yield line

    return StreamingResponse(
        iterfile(),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{query_id}-{settings.role.name.title()}.log"'
            )
        },
        media_type="text/plain",
    )


# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
@router.post("/ipa-query/{query_id}")
def start_ipa_query(
    query_id: str,
    commit_hash: Annotated[str, Form()],
    size: Annotated[int, Form()],
    max_breakdown_key: Annotated[int, Form()],
    max_trigger_value: Annotated[int, Form()],
    per_user_credit_cap: Annotated[int, Form()],
    malicious_security: Annotated[bool, Form()],
    background_tasks: BackgroundTasks,
    request: Request,
):
    query_manager = request.app.state.QUERY_MANAGER
    check_capacity(query_manager)

    settings = get_settings()
    role = settings.role
    if role != role.COORDINATOR:
        raise IncorrectRoleError(
            f"Attempting to start query with {role=}: "
            "Cannot start query without coordinator role."
        )

    paths = Paths(
        repo_path=settings.root_path / Path("ipa"),
        config_path=settings.config_path,
        compiled_id=commit_hash,
    )
    test_data_path = paths.repo_path / Path("test_data/input")
    query = IPACoordinatorQuery(
        query_id=query_id,
        paths=paths,
        commit_hash=commit_hash,
        test_data_file=test_data_path / Path(f"events-{size}.txt"),
        size=size,
        max_breakdown_key=max_breakdown_key,
        max_trigger_value=max_trigger_value,
        per_user_credit_cap=per_user_credit_cap,
        malicious_security=malicious_security,
    )

    background_tasks.add_task(query_manager.run_query, query)
    return {"message": "Process started successfully", "query_id": query_id}
