from __future__ import annotations

import logging
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.paper_radar_adapter import (
    delete_profile_payload,
    load_history_payload,
    load_profiles_payload,
    load_today_payload,
    run_history_survey_with_progress,
    run_history_survey_payload,
    run_today_check_with_progress,
    run_today_check_payload,
    save_profile_payload,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="PaperRadar Local Backend", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KeywordPayload(BaseModel):
    group: str
    weight: Literal["high", "medium", "low"] = "medium"
    text: str


class CheckRequest(BaseModel):
    daysBack: int = 7
    minScore: int = 0
    arxiv: bool = True
    journals: bool = True


class SurveyRequest(BaseModel):
    taskName: str = "当前方向历史调研"
    days: int = 365
    minScore: int = 0
    arxiv: bool = True
    journals: bool = True


class ProfilePayload(BaseModel):
    id: str
    name: str
    description: str = ""
    queryCount: int = Field(default=0, ge=0)
    keywordGroupCount: int = Field(default=0, ge=0)
    isCurrent: bool = False
    keywords: list[KeywordPayload] = Field(default_factory=list)


_TASK_LOCK = threading.Lock()
_TASKS: dict[str, dict] = {}
_ACTIVE_TASK_BY_KIND: dict[str, str] = {}


def _new_task(kind: str) -> tuple[str, threading.Event]:
    task_id = uuid.uuid4().hex
    stop_event = threading.Event()
    with _TASK_LOCK:
        _TASKS[task_id] = {
            "taskId": task_id,
            "kind": kind,
            "state": "running",
            "payload": {"papers": [], "summary": None},
            "error": None,
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
            "_stop": stop_event,
        }
        _ACTIVE_TASK_BY_KIND[kind] = task_id
    return task_id, stop_event


def _update_task(task_id: str, **updates: object) -> None:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updatedAt"] = datetime.now().isoformat(timespec="seconds")


def _public_task(task: dict | None) -> dict:
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {key: deepcopy(value) for key, value in task.items() if not key.startswith("_")}


def _get_task(task_id: str) -> dict:
    with _TASK_LOCK:
        return _public_task(_TASKS.get(task_id))


def _active_task(kind: str) -> dict:
    with _TASK_LOCK:
        task_id = _ACTIVE_TASK_BY_KIND.get(kind)
        return _public_task(_TASKS.get(task_id or ""))


def _start_background_task(kind: str, runner) -> dict:
    with _TASK_LOCK:
        current_id = _ACTIVE_TASK_BY_KIND.get(kind)
        current = _TASKS.get(current_id or "")
        if current and current.get("state") == "running":
            return _public_task(current)

    task_id, stop_event = _new_task(kind)

    def run() -> None:
        try:
            result = runner(stop_event, lambda payload: _update_task(task_id, payload=payload))
            _update_task(task_id, state="cancelled" if stop_event.is_set() else "success", payload=result)
        except Exception as exc:
            logger.exception("Background %s task failed", kind)
            _update_task(task_id, state="failed", error=str(exc))

    thread = threading.Thread(target=run, name=f"paperradar-{kind}-{task_id[:8]}", daemon=True)
    thread.start()
    return _get_task(task_id)


@app.get("/api/status")
def status() -> dict:
    return {
        "version": "0.4.0",
        "mode": "python-backend",
        "message": "PaperRadar Python backend is available.",
    }


@app.get("/api/papers/today")
def today_papers(min_score: int = 0) -> dict:
    try:
        return load_today_payload(min_score=min_score)
    except Exception as exc:
        logger.exception("Failed to load today papers")
        raise HTTPException(status_code=500, detail=f"读取今日论文缓存失败：{exc}") from exc


@app.post("/api/papers/check")
def check_today(request: CheckRequest) -> dict:
    try:
        return run_today_check_payload(
            days_back=request.daysBack,
            min_score=request.minScore,
            arxiv=request.arxiv,
            journals=request.journals,
        )
    except Exception as exc:
        logger.exception("Today check failed")
        raise HTTPException(status_code=500, detail=f"今日发现检索失败：{exc}") from exc


@app.post("/api/papers/check/task")
def check_today_task(request: CheckRequest) -> dict:
    return _start_background_task(
        "today",
        lambda stop_event, progress: run_today_check_with_progress(
            days_back=request.daysBack,
            min_score=request.minScore,
            arxiv=request.arxiv,
            journals=request.journals,
            should_stop=stop_event.is_set,
            progress=progress,
        ),
    )


@app.post("/api/papers/stop")
def stop_today() -> dict:
    with _TASK_LOCK:
        task = _TASKS.get(_ACTIVE_TASK_BY_KIND.get("today", ""))
        if task and task.get("state") == "running":
            task["_stop"].set()
            task["state"] = "cancelled"
            task["updatedAt"] = datetime.now().isoformat(timespec="seconds")
            return {"accepted": True}
    return {"accepted": False}


@app.get("/api/papers/history")
def history_papers(days: int = 365, min_score: int = 0) -> dict:
    try:
        return load_history_payload(days=days, min_score=min_score)
    except Exception as exc:
        logger.exception("Failed to load history papers")
        raise HTTPException(status_code=500, detail=f"读取历史调研缓存失败：{exc}") from exc


@app.post("/api/history/start")
def start_history(request: SurveyRequest) -> dict:
    try:
        return run_history_survey_payload(
            days=request.days,
            min_score=request.minScore,
            arxiv=request.arxiv,
            journals=request.journals,
            task_name=request.taskName,
        )
    except Exception as exc:
        logger.exception("History survey failed")
        raise HTTPException(status_code=500, detail=f"历史调研失败：{exc}") from exc


@app.post("/api/history/start/task")
def start_history_task(request: SurveyRequest) -> dict:
    return _start_background_task(
        "history",
        lambda stop_event, progress: run_history_survey_with_progress(
            days=request.days,
            min_score=request.minScore,
            arxiv=request.arxiv,
            journals=request.journals,
            task_name=request.taskName,
            should_stop=stop_event.is_set,
            progress=progress,
        ),
    )


@app.post("/api/history/stop")
def stop_history() -> dict:
    with _TASK_LOCK:
        task = _TASKS.get(_ACTIVE_TASK_BY_KIND.get("history", ""))
        if task and task.get("state") == "running":
            task["_stop"].set()
            task["state"] = "cancelled"
            task["updatedAt"] = datetime.now().isoformat(timespec="seconds")
            return {"accepted": True}
    return {"accepted": False}


@app.get("/api/tasks/active/{kind}")
def active_task_status(kind: str) -> dict:
    if kind not in {"today", "history"}:
        raise HTTPException(status_code=404, detail="Task kind not found")
    return _active_task(kind)


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str) -> dict:
    return _get_task(task_id)


@app.get("/api/profiles")
def profiles() -> dict:
    try:
        return load_profiles_payload()
    except Exception as exc:
        logger.exception("Failed to load profiles")
        raise HTTPException(status_code=500, detail=f"读取研究方向失败：{exc}") from exc


@app.post("/api/profiles")
def create_profile(profile: ProfilePayload) -> dict:
    return save_profile_payload(profile.model_dump())


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: str, profile: ProfilePayload) -> dict:
    payload = profile.model_dump()
    payload["id"] = profile_id
    return save_profile_payload(payload)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict:
    return delete_profile_payload(profile_id)


@app.post("/api/reports/today")
def today_report() -> dict:
    return {"accepted": True, "message": "今日报告入口已预留，下一步接入 generate_daily_report_file。"}


@app.post("/api/reports/history")
def history_report() -> dict:
    return {"accepted": True, "message": "历史调研报告入口已预留，下一步接入 generate_survey_report_file。"}


@app.get("/api/logs/recent")
def recent_logs() -> dict:
    return {"logs": []}


