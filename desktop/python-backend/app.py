from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.paper_radar_adapter import (
    delete_profile_payload,
    load_history_payload,
    load_profiles_payload,
    load_today_payload,
    run_history_survey_payload,
    run_today_check_payload,
    save_profile_payload,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="PaperRadar Local Backend", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
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


@app.get("/api/status")
def status() -> dict:
    return {
        "version": "0.3.0",
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


@app.post("/api/papers/stop")
def stop_today() -> dict:
    return {"accepted": True, "message": "停止今日发现任务入口已预留。"}


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


@app.post("/api/history/stop")
def stop_history() -> dict:
    return {"accepted": True, "message": "停止历史调研任务入口已预留。"}


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


