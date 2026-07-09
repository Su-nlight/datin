"""
abroute.py
==========
FastAPI router for the A/B testing framework.

Mount this router in main.py with:

    from abroute import router as ab_router
    app.include_router(ab_router)

Endpoints
---------
POST   /ab-test/run                  – run a single A/B test
POST   /ab-test/run-batch            – run a batch of queries
GET    /ab-test/results              – list all stored results (paginated)
GET    /ab-test/results/{test_id}    – fetch one result by ID
GET    /ab-test/summary              – aggregate statistics
DELETE /ab-test/results              – clear all stored results
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from starlette import status

from testing_folder.ab_testing import ABTestResult, ABTestStore, InstrumentedRagModel
from llm_provider import get_llm

load_dotenv("API.env")

router = APIRouter(prefix="/ab-test", tags=["ab-testing"])

# ---------------------------------------------------------------------------
# Lazy-initialised model singleton
# ---------------------------------------------------------------------------

_model: Optional[InstrumentedRagModel] = None


def _get_model() -> InstrumentedRagModel:
    global _model
    if _model is None:
        llm = get_llm(provider=os.getenv("LLM_PROVIDER", "gemini"))
        _model = InstrumentedRagModel(
            llm=llm,
            PineconeAPIKey=os.getenv("PINECONE_API_KEY"),
            NameSpaces=[
                ns.strip()
                for ns in os.getenv("NAMESPACES", "").split(",")
                if ns.strip()
            ],
            Index_Name=os.getenv("INDEX_NAME"),
            min_score=float(os.getenv("MIN_SCORE", "0.75")),
        )
    return _model


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class ABTestRequest(BaseModel):
    query: str = Field(..., min_length=5, description="Cybersecurity query to test")
    test_id: Optional[str] = Field(
        None,
        description="Optional deterministic ID; auto-generated if omitted",
    )

    class Config:
        schema_extra = {
            "example": {
                "query": "Explain the TTPs used by APT28 against NATO infrastructure",
            }
        }


class BatchABTestRequest(BaseModel):
    queries: List[str] = Field(
        ...,
        min_items=1,
        max_items=20,
        description="List of queries to run sequentially (max 20 per batch)",
    )

    class Config:
        schema_extra = {
            "example": {
                "queries": [
                    "What is a SQL injection attack?",
                    "Explain CVE-2024-1234 exploitation technique",
                ]
            }
        }


class ABTestSummaryResponse(BaseModel):
    total_tests: int
    healing_triggered_count: int
    healing_triggered_pct: float
    winner_distribution: dict
    avg_quality_A: float
    avg_quality_B: float
    avg_quality_delta: float
    avg_time_overhead_ms: float
    avg_retrieval_ms: float
    avg_generation_ms_A: float
    avg_generation_ms_B: float
    avg_evaluation_ms_A: float
    avg_evaluation_ms_B: float
    avg_healing_ms: float


class DeleteResponse(BaseModel):
    deleted_count: int
    message: str


# ---------------------------------------------------------------------------
# In-flight task registry  (for async batch jobs)
# ---------------------------------------------------------------------------

_batch_jobs: dict = {}          # job_id → {"status", "results", "total", "done"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/run",
    status_code=status.HTTP_200_OK,
    summary="Run a single A/B test",
    response_description="Full A/B test result including timing and quality metrics",
)
async def run_single_ab_test(request: ABTestRequest):
    """
    Run Variant A (no healing) and Variant B (with healing) for the same query.

    Both variants share identical retrieved context so that the only
    variable under test is the self-healing loop.

    **Timing fields** are in milliseconds.

    **quality.overall_score** is a 0–1 fraction of four boolean evaluation
    dimensions that were `True` (correctness, helpfulness, groundedness,
    retrieval_relevance).

    **winner** is `"A"`, `"B"`, or `"TIE"` based purely on quality.
    """
    model = _get_model()
    try:
        result: ABTestResult = model.run_ab_test(
            user_query=request.query,
            test_id=request.test_id,
        )
        ABTestStore.save(result)
        return asdict(result)

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"A/B test failed: {exc}",
        )


@router.post(
    "/run-batch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a batch of A/B tests (async)",
    response_description="Job ID to poll via GET /ab-test/batch/{job_id}",
)
async def run_batch_ab_test(
    request: BatchABTestRequest,
    background_tasks: BackgroundTasks,
):
    """
    Enqueue up to **20** queries as a background batch job.

    Returns a `job_id` immediately.  Poll `GET /ab-test/batch/{job_id}`
    to check progress and retrieve results once complete.
    """
    job_id = str(uuid.uuid4())
    _batch_jobs[job_id] = {
        "status": "queued",
        "total": len(request.queries),
        "done": 0,
        "results": [],
        "started_at": time.time(),
        "completed_at": None,
    }

    def _run_batch():
        model = _get_model()
        _batch_jobs[job_id]["status"] = "running"
        for query in request.queries:
            try:
                result = model.run_ab_test(user_query=query)
                ABTestStore.save(result)
                _batch_jobs[job_id]["results"].append(asdict(result))
            except Exception as exc:
                _batch_jobs[job_id]["results"].append(
                    {"query": query, "error": str(exc)}
                )
            _batch_jobs[job_id]["done"] += 1

        _batch_jobs[job_id]["status"] = "completed"
        _batch_jobs[job_id]["completed_at"] = time.time()

    background_tasks.add_task(_run_batch)

    return {
        "job_id": job_id,
        "status": "queued",
        "total_queries": len(request.queries),
        "poll_url": f"/ab-test/batch/{job_id}",
    }


@router.get(
    "/batch/{job_id}",
    status_code=status.HTTP_200_OK,
    summary="Poll a batch job",
)
async def get_batch_status(job_id: str):
    """
    Check the status and partial/full results of a batch A/B test job.

    `status` is one of: `queued` | `running` | `completed`.
    """
    job = _batch_jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No batch job found with id '{job_id}'",
        )
    return job


@router.get(
    "/results",
    status_code=status.HTTP_200_OK,
    summary="List all stored A/B test results",
)
async def list_results(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Results per page"),
    winner_filter: Optional[str] = Query(
        None,
        description="Filter by winner: A | B | TIE | ERROR",
    ),
    healing_filter: Optional[bool] = Query(
        None,
        description="Filter by whether healing was triggered in variant B",
    ),
):
    """
    Return a paginated list of all stored A/B test results with optional
    filters for `winner` and `healing_triggered`.
    """
    records = ABTestStore.get_all()

    # Apply filters
    if winner_filter:
        records = [r for r in records if r.get("winner") == winner_filter.upper()]
    if healing_filter is not None:
        records = [
            r for r in records
            if r.get("variant_b", {}).get("healing_triggered") == healing_filter
        ]

    total = len(records)
    start = (page - 1) * page_size
    paginated = records[start : start + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": paginated,
    }


@router.get(
    "/results/{test_id}",
    status_code=status.HTTP_200_OK,
    summary="Fetch a single A/B test result by ID",
)
async def get_result(test_id: str):
    """
    Retrieve the full result for a specific A/B test by its `test_id`.
    """
    record = ABTestStore.get_by_id(test_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No result found for test_id '{test_id}'",
        )
    return record


@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    summary="Aggregate statistics across all stored tests",
)
async def get_summary():
    """
    Returns aggregate metrics over all stored A/B test results:

    - **winner_distribution** – how often A, B, or TIE wins
    - **healing_triggered_pct** – percentage of tests where healing fired
    - **avg_quality_delta** – mean improvement in overall score (B − A)
    - **avg_time_overhead_ms** – mean extra latency introduced by healing
    - Per-phase average timings for both variants
    """
    return ABTestStore.summary_statistics()


@router.delete(
    "/results",
    status_code=status.HTTP_200_OK,
    response_model=DeleteResponse,
    summary="Clear all stored A/B test results",
)
async def clear_results():
    """
    Permanently delete all stored A/B test results.

    **This operation is irreversible.**
    """
    count = ABTestStore.clear()
    return DeleteResponse(
        deleted_count=count,
        message=f"Deleted {count} test result(s) from the store.",
    )


# ---------------------------------------------------------------------------
# Health / introspection
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Framework health check",
)
async def ab_health():
    """
    Confirms the A/B testing router is reachable and returns the number of
    stored results without loading their content.
    """
    records = ABTestStore.get_all()
    return {
        "status": "ok",
        "stored_results": len(records),
        "results_file": os.path.abspath(
            os.getenv("AB_RESULTS_FILE", "ab_results.json")
        ),
    }