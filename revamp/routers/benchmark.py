"""
app/routers/benchmark.py

Same endpoints as Backend/API/testing_folder/benchmark_router.py.
BenchmarkRunner takes request-specific args (scenarios, query_ids) so
it's still constructed per-job rather than cached via Depends() — same
as upstream, which builds a fresh BenchmarkRunner inside each background
task. What *is* injected now is `Settings` (instead of BenchmarkRunner
re-reading os.getenv() internally) and the shared `BenchmarkStore` for
read endpoints.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette import status

from app.config import Settings, get_settings
from app.dependencies import get_benchmark_store
from app.routers.auth import token_verifier
from app.services.benchmark_service import (
    BENCHMARK_QUERY_BANK, CODE_BENCHMARK_BANK, BenchmarkRunner, BenchmarkStore, TestScenario,
)
from app.services.metrics_analyzer_service import BenchmarkAnalyzer

router = APIRouter(
    prefix="/benchmark",
    tags=["benchmark"],
    dependencies=[Depends(token_verifier)],
)

_jobs: dict = {}  # job_id → progress dict; same in-memory registry as before


class BenchmarkRunRequest(BaseModel):
    scenarios: Optional[List[str]] = Field(
        None, description="Subset of scenarios to enable. Defaults to all four."
    )
    query_ids: Optional[List[str]] = Field(None, description="Subset of query IDs. Defaults to all 20.")
    run_code_bench: bool = Field(True, description="Include code vulnerability benchmarks.")


class SingleQueryRequest(BaseModel):
    scenarios: Optional[List[str]] = Field(None, description="Scenarios to run (defaults to all configured).")


def _resolve_scenarios(raw: Optional[List[str]]) -> List[TestScenario]:
    if not raw:
        return list(TestScenario)
    out = []
    for s in raw:
        try:
            out.append(TestScenario(s))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown scenario '{s}'. Valid: {[e.value for e in TestScenario]}",
            )
    return out


@router.post("/run", status_code=status.HTTP_202_ACCEPTED, summary="Trigger a full benchmark run (async)")
async def trigger_benchmark_run(
    request: BenchmarkRunRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    scenarios = _resolve_scenarios(request.scenarios)
    run_id = str(uuid.uuid4())

    _jobs[run_id] = {
        "run_id": run_id, "status": "queued", "started_at": None,
        "queries_done": 0, "total_queries": len(request.query_ids) if request.query_ids else 20,
    }

    def _run():
        _jobs[run_id]["status"] = "running"
        _jobs[run_id]["started_at"] = time.time()
        try:
            runner = BenchmarkRunner(
                settings=settings, scenarios=scenarios,
                query_ids=request.query_ids, run_code_bench=request.run_code_bench,
            )
            run = runner.execute_full_run(run_id=run_id)
            _jobs[run_id]["status"] = "completed"
            _jobs[run_id]["queries_done"] = run.total_queries
        except Exception as exc:
            _jobs[run_id]["status"] = "failed"
            _jobs[run_id]["error"] = str(exc)

    background_tasks.add_task(_run)
    return {"run_id": run_id, "status": "queued", "poll_url": f"/benchmark/runs/{run_id}/status"}


@router.post("/run-query/{query_id}", status_code=status.HTTP_200_OK, summary="Run a single benchmark query synchronously")
async def run_single_query(
    query_id: str,
    request: SingleQueryRequest,
    settings: Settings = Depends(get_settings),
):
    scenarios = _resolve_scenarios(request.scenarios)
    try:
        runner = BenchmarkRunner(settings=settings, scenarios=scenarios, query_ids=[query_id], run_code_bench=False)
        qr = runner.execute_single_query(query_id)
        if qr is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Query ID '{query_id}' not found in the benchmark bank.")
        return asdict(qr)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/runs", status_code=status.HTTP_200_OK, summary="List all completed benchmark runs")
async def list_runs(store: BenchmarkStore = Depends(get_benchmark_store)):
    return {"runs": store.list_runs()}


@router.get("/runs/{run_id}/status", status_code=status.HTTP_200_OK, summary="Poll in-flight or completed run status")
async def get_run_status(run_id: str, store: BenchmarkStore = Depends(get_benchmark_store)):
    if run_id in _jobs:
        return _jobs[run_id]
    stored = store.load_run(run_id)
    if stored:
        return {
            "run_id": run_id, "status": stored.get("status"), "started_at": stored.get("started_at"),
            "completed_at": stored.get("completed_at"), "total_queries": stored.get("total_queries"),
        }
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No run found with id '{run_id}'")


@router.get("/runs/{run_id}", status_code=status.HTTP_200_OK, summary="Fetch full run result data")
async def get_run_result(run_id: str, store: BenchmarkStore = Depends(get_benchmark_store)):
    data = store.load_run(run_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No result found for run '{run_id}'")
    return data


@router.get("/runs/{run_id}/report", status_code=status.HTTP_200_OK, summary="Get full statistical report as JSON")
async def get_statistical_report(run_id: str, store: BenchmarkStore = Depends(get_benchmark_store)):
    try:
        analyzer = BenchmarkAnalyzer(run_id, store=store)
        return analyzer.generate_research_report()
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No completed run found for '{run_id}'")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/runs/{run_id}/markdown", status_code=status.HTTP_200_OK, summary="Get publication-ready Markdown report")
async def get_markdown_report(run_id: str, store: BenchmarkStore = Depends(get_benchmark_store)):
    from fastapi.responses import PlainTextResponse
    try:
        analyzer = BenchmarkAnalyzer(run_id, store=store)
        md = analyzer.generate_markdown_report()
        return PlainTextResponse(md, media_type="text/markdown")
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No completed run found for '{run_id}'")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/compare", status_code=status.HTTP_200_OK, summary="Compare quality trends across multiple runs")
async def compare_runs(
    run_ids: List[str] = Query(..., description="Two or more run IDs to compare"),
    scenario: str = Query("gemini_heal", description="Scenario to compare across runs"),
    store: BenchmarkStore = Depends(get_benchmark_store),
):
    if len(run_ids) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide at least 2 run_ids for comparison.")
    trend = []
    for rid in run_ids:
        data = store.load_run(rid)
        if data is None:
            trend.append({"run_id": rid, "error": "not found"})
            continue
        try:
            analyzer = BenchmarkAnalyzer(rid, store=store)
            ss = analyzer.compute_scenario_stats()
            sd = ss.get(scenario)
            if sd is None:
                trend.append({"run_id": rid, "error": f"scenario '{scenario}' not in run"})
                continue
            trend.append({
                "run_id": rid, "started_at": data.get("started_at"),
                "mean_quality": sd["quality_score"]["mean"], "std_quality": sd["quality_score"]["std"],
                "ci_95": [sd["quality_score"]["ci_95_low"], sd["quality_score"]["ci_95_high"]],
                "mean_total_ms": sd["latency_ms"]["total"]["mean"], "heal_rate": sd["healing_trigger_rate"],
            })
        except Exception as exc:
            trend.append({"run_id": rid, "error": str(exc)})

    return {"scenario": scenario, "trend": trend}


@router.delete("/runs/{run_id}", status_code=status.HTTP_200_OK, summary="Delete a stored benchmark run")
async def delete_run(run_id: str, store: BenchmarkStore = Depends(get_benchmark_store)):
    path = store._path(run_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No run found with id '{run_id}'")
    os.remove(path)
    _jobs.pop(run_id, None)
    return {"deleted": run_id}


@router.get("/queries", status_code=status.HTTP_200_OK, summary="List the curated benchmark query bank")
async def list_queries():
    return {
        "total": len(BENCHMARK_QUERY_BANK),
        "queries": [
            {"id": q.id, "category": q.category.value, "query": q.query, "expected_keywords": q.expected_keywords}
            for q in BENCHMARK_QUERY_BANK
        ],
        "code_samples": [
            {"id": s.id, "language": s.language, "known_cwes": s.known_cwes, "expected_severity": s.expected_severity, "description": s.description}
            for s in CODE_BENCHMARK_BANK
        ],
    }