"""
testing_folder/benchmark_router.py
====================================
FastAPI router exposing the research benchmark framework over HTTP.

Mount in main.py:
    from testing_folder import benchmark_router
    app.include_router(benchmark_router)

All benchmark endpoints require a valid JWT.

Endpoints
---------
POST   /benchmark/run                      – trigger full benchmark run (async)
POST   /benchmark/run-query/{query_id}     – single query, all scenarios
GET    /benchmark/runs                     – list all completed runs
GET    /benchmark/runs/{run_id}            – full run result JSON
GET    /benchmark/runs/{run_id}/report     – statistical report (JSON)
GET    /benchmark/runs/{run_id}/markdown   – publication-ready Markdown
GET    /benchmark/runs/{run_id}/status     – lightweight status poll
GET    /benchmark/compare                  – cross-run quality trend
DELETE /benchmark/runs/{run_id}            – delete a stored run
GET    /benchmark/queries                  – list the curated query bank
"""

from __future__ import annotations

import os
import uuid
import json
import time
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette import status

from auth import token_verifier
from testing_folder.benchmark_suite import (
    BenchmarkRunner, BenchmarkStore, TestScenario,
    BENCHMARK_QUERY_BANK, CODE_BENCHMARK_BANK,
)
from testing_folder.metrics_analyzer import BenchmarkAnalyzer

router = APIRouter(
    prefix="/benchmark",
    tags=["benchmark"],
    dependencies=[Depends(token_verifier)],   # all routes require JWT
)

# ---------------------------------------------------------------------------
# In-flight job registry
# ---------------------------------------------------------------------------

_jobs: dict = {}   # job_id → progress dict


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class BenchmarkRunRequest(BaseModel):
    scenarios: Optional[List[str]] = Field(
        None,
        description=(
            "Subset of scenarios to enable. "
            "Valid values: gemini_no_heal, gemini_heal, ollama_no_heal, ollama_heal. "
            "Defaults to all four."
        ),
    )
    query_ids: Optional[List[str]] = Field(
        None,
        description="Subset of query IDs from the bank (e.g. ['APT-01', 'CVE-02']). "
                    "Defaults to all 20 queries.",
    )
    run_code_bench: bool = Field(True, description="Include code vulnerability benchmarks.")

    class Config:
        schema_extra = {
            "example": {
                "scenarios":       ["gemini_no_heal", "gemini_heal"],
                "query_ids":       None,
                "run_code_bench":  True,
            }
        }


class SingleQueryRequest(BaseModel):
    scenarios: Optional[List[str]] = Field(
        None, description="Scenarios to run (defaults to all configured)."
    )


# ---------------------------------------------------------------------------
# Helper: validate and resolve scenario list
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/run",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a full benchmark run (async)",
)
async def trigger_benchmark_run(
    request: BenchmarkRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    Enqueues a full benchmark run as a background task.

    Returns a `job_id` immediately. Poll `GET /benchmark/runs/{run_id}/status`
    to track progress.  Results are persisted automatically after completion.

    **Expected wall time**: 20–60 minutes for all 4 scenarios × 20 queries,
    depending on LLM latency.  Use `query_ids` to run a subset for faster
    spot-testing.
    """
    scenarios = _resolve_scenarios(request.scenarios)
    run_id    = str(uuid.uuid4())

    _jobs[run_id] = {
        "run_id":     run_id,
        "status":     "queued",
        "started_at": None,
        "queries_done": 0,
        "total_queries": len(request.query_ids) if request.query_ids else 20,
    }

    def _run():
        _jobs[run_id]["status"]     = "running"
        _jobs[run_id]["started_at"] = time.time()
        try:
            runner = BenchmarkRunner(
                scenarios=scenarios,
                query_ids=request.query_ids,
                run_code_bench=request.run_code_bench,
            )
            run = runner.execute_full_run(run_id=run_id)
            _jobs[run_id]["status"]       = "completed"
            _jobs[run_id]["queries_done"] = run.total_queries
        except Exception as exc:
            _jobs[run_id]["status"] = "failed"
            _jobs[run_id]["error"]  = str(exc)

    background_tasks.add_task(_run)
    return {
        "run_id":   run_id,
        "status":   "queued",
        "poll_url": f"/benchmark/runs/{run_id}/status",
    }


@router.post(
    "/run-query/{query_id}",
    status_code=status.HTTP_200_OK,
    summary="Run a single benchmark query synchronously",
)
async def run_single_query(
    query_id: str,
    request: SingleQueryRequest,
):
    """
    Execute all enabled scenarios for a single query from the query bank.
    Useful for rapid spot-testing without launching a full async run.

    **Expected wall time**: 30–90 seconds per query.
    """
    scenarios = _resolve_scenarios(request.scenarios)
    try:
        runner = BenchmarkRunner(
            scenarios=scenarios,
            query_ids=[query_id],
            run_code_bench=False,
        )
        qr = runner.execute_single_query(query_id)
        if qr is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Query ID '{query_id}' not found in the benchmark bank.",
            )
        return asdict(qr)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/runs",
    status_code=status.HTTP_200_OK,
    summary="List all completed benchmark runs",
)
async def list_runs():
    """Returns summary metadata for every stored benchmark run, newest first."""
    return {"runs": BenchmarkStore.list_runs()}


@router.get(
    "/runs/{run_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Poll in-flight or completed run status",
)
async def get_run_status(run_id: str):
    """
    Returns the current status of a run: `queued | running | completed | failed`.
    For completed runs not in the in-flight registry, fetches metadata from disk.
    """
    if run_id in _jobs:
        return _jobs[run_id]
    stored = BenchmarkStore.load_run(run_id)
    if stored:
        return {
            "run_id":       run_id,
            "status":       stored.get("status"),
            "started_at":   stored.get("started_at"),
            "completed_at": stored.get("completed_at"),
            "total_queries": stored.get("total_queries"),
        }
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No run found with id '{run_id}'",
    )


@router.get(
    "/runs/{run_id}",
    status_code=status.HTTP_200_OK,
    summary="Fetch full run result data",
)
async def get_run_result(run_id: str):
    """Returns the complete result JSON for a finished benchmark run."""
    data = BenchmarkStore.load_run(run_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No result found for run '{run_id}'",
        )
    return data


@router.get(
    "/runs/{run_id}/report",
    status_code=status.HTTP_200_OK,
    summary="Get full statistical report as JSON",
)
async def get_statistical_report(run_id: str):
    """
    Computes and returns the full statistical analysis report for a completed run.

    Includes:
    - Per-scenario descriptive stats (mean, SD, 95% bootstrap CI)
    - Pairwise Wilcoxon tests and Cohen's d effect sizes
    - Per-category quality breakdown
    - Latency budget analysis
    - Self-healing ROI metrics
    - Code analysis detection rates
    """
    try:
        analyzer = BenchmarkAnalyzer(run_id)
        return analyzer.generate_research_report()
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No completed run found for '{run_id}'",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/runs/{run_id}/markdown",
    status_code=status.HTTP_200_OK,
    summary="Get publication-ready Markdown report",
    response_class=None,
)
async def get_markdown_report(run_id: str):
    """
    Returns the full benchmark report as a Markdown string suitable for
    direct inclusion in a research paper, technical report, or README.

    Content-Type: text/plain
    """
    from fastapi.responses import PlainTextResponse
    try:
        analyzer = BenchmarkAnalyzer(run_id)
        md       = analyzer.generate_markdown_report()
        return PlainTextResponse(md, media_type="text/markdown")
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No completed run found for '{run_id}'",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/compare",
    status_code=status.HTTP_200_OK,
    summary="Compare quality trends across multiple runs",
)
async def compare_runs(
    run_ids: List[str] = Query(..., description="Two or more run IDs to compare"),
    scenario: str = Query("gemini_heal", description="Scenario to compare across runs"),
):
    """
    Tracks quality and latency trends for a given scenario across multiple
    benchmark runs.  Useful for evaluating model updates or prompt changes
    over time.

    Requires at least 2 run IDs.
    """
    if len(run_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least 2 run_ids for comparison.",
        )
    trend = []
    for rid in run_ids:
        data = BenchmarkStore.load_run(rid)
        if data is None:
            trend.append({"run_id": rid, "error": "not found"})
            continue
        try:
            analyzer = BenchmarkAnalyzer(rid)
            ss       = analyzer.compute_scenario_stats()
            sd       = ss.get(scenario)
            if sd is None:
                trend.append({"run_id": rid, "error": f"scenario '{scenario}' not in run"})
                continue
            trend.append({
                "run_id":         rid,
                "started_at":     data.get("started_at"),
                "mean_quality":   sd["quality_score"]["mean"],
                "std_quality":    sd["quality_score"]["std"],
                "ci_95":          [sd["quality_score"]["ci_95_low"], sd["quality_score"]["ci_95_high"]],
                "mean_total_ms":  sd["latency_ms"]["total"]["mean"],
                "heal_rate":      sd["healing_trigger_rate"],
            })
        except Exception as exc:
            trend.append({"run_id": rid, "error": str(exc)})

    return {"scenario": scenario, "trend": trend}


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a stored benchmark run",
)
async def delete_run(run_id: str):
    """Permanently deletes the JSON result file for the given run ID."""
    import os as _os
    path = BenchmarkStore._path(run_id)
    if not _os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No run found with id '{run_id}'",
        )
    _os.remove(path)
    _jobs.pop(run_id, None)
    return {"deleted": run_id}


@router.get(
    "/queries",
    status_code=status.HTTP_200_OK,
    summary="List the curated benchmark query bank",
)
async def list_queries():
    """
    Returns all 20 curated cybersecurity queries with their IDs, categories,
    and expected keywords.  Use these IDs with `/benchmark/run-query/{query_id}`
    for targeted spot-testing.
    """
    return {
        "total": len(BENCHMARK_QUERY_BANK),
        "queries": [
            {
                "id":               q.id,
                "category":         q.category.value,
                "query":            q.query,
                "expected_keywords": q.expected_keywords,
            }
            for q in BENCHMARK_QUERY_BANK
        ],
        "code_samples": [
            {
                "id":               s.id,
                "language":         s.language,
                "known_cwes":       s.known_cwes,
                "expected_severity": s.expected_severity,
                "description":      s.description,
            }
            for s in CODE_BENCHMARK_BANK
        ],
    }