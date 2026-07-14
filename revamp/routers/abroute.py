"""
app/routers/abroute.py

Same endpoints as Backend/API/testing_folder/abroute.py. The module-level
`_model: Optional[InstrumentedRagModel] = None` + `_get_model()` global
is gone — replaced by `Depends(get_instrumented_rag_service)`, which is
exactly the pattern the Phase 1 doc's Step 7 ("Remove globals") asks for.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette import status

from app.dependencies import get_ab_test_store, get_instrumented_rag_service
from app.services.ab_testing_service import ABTestResult, ABTestStore, InstrumentedRagModel

router = APIRouter(prefix="/ab-test", tags=["ab-testing"])

_batch_jobs: dict = {}  # job_id → progress dict; same in-memory registry as before


class ABTestRequest(BaseModel):
    query: str = Field(..., min_length=5, description="Cybersecurity query to test")
    test_id: Optional[str] = Field(None, description="Optional deterministic ID; auto-generated if omitted")


class BatchABTestRequest(BaseModel):
    queries: List[str] = Field(..., min_items=1, max_items=20, description="Queries to run sequentially (max 20 per batch)")


class DeleteResponse(BaseModel):
    deleted_count: int
    message: str


@router.post("/run", status_code=status.HTTP_200_OK, summary="Run a single A/B test")
async def run_single_ab_test(
    request: ABTestRequest,
    model: InstrumentedRagModel = Depends(get_instrumented_rag_service),
    store: ABTestStore = Depends(get_ab_test_store),
):
    try:
        result: ABTestResult = model.run_ab_test(user_query=request.query, test_id=request.test_id)
        store.save(result)
        return asdict(result)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"A/B test failed: {exc}")


@router.post("/run-batch", status_code=status.HTTP_202_ACCEPTED, summary="Submit a batch of A/B tests (async)")
async def run_batch_ab_test(
    request: BatchABTestRequest,
    background_tasks: BackgroundTasks,
    model: InstrumentedRagModel = Depends(get_instrumented_rag_service),
    store: ABTestStore = Depends(get_ab_test_store),
):
    job_id = str(uuid.uuid4())
    _batch_jobs[job_id] = {
        "status": "queued", "total": len(request.queries), "done": 0,
        "results": [], "started_at": time.time(), "completed_at": None,
    }

    def _run_batch():
        _batch_jobs[job_id]["status"] = "running"
        for query in request.queries:
            try:
                result = model.run_ab_test(user_query=query)
                store.save(result)
                _batch_jobs[job_id]["results"].append(asdict(result))
            except Exception as exc:
                _batch_jobs[job_id]["results"].append({"query": query, "error": str(exc)})
            _batch_jobs[job_id]["done"] += 1
        _batch_jobs[job_id]["status"] = "completed"
        _batch_jobs[job_id]["completed_at"] = time.time()

    background_tasks.add_task(_run_batch)
    return {"job_id": job_id, "status": "queued", "total_queries": len(request.queries), "poll_url": f"/ab-test/batch/{job_id}"}


@router.get("/batch/{job_id}", status_code=status.HTTP_200_OK, summary="Poll a batch job")
async def get_batch_status(job_id: str):
    job = _batch_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No batch job found with id '{job_id}'")
    return job


@router.get("/results", status_code=status.HTTP_200_OK, summary="List all stored A/B test results")
async def list_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    winner_filter: Optional[str] = Query(None, description="Filter by winner: A | B | TIE | ERROR"),
    healing_filter: Optional[bool] = Query(None, description="Filter by whether healing was triggered in variant B"),
    store: ABTestStore = Depends(get_ab_test_store),
):
    records = store.get_all()
    if winner_filter:
        records = [r for r in records if r.get("winner") == winner_filter.upper()]
    if healing_filter is not None:
        records = [r for r in records if r.get("variant_b", {}).get("healing_triggered") == healing_filter]

    total = len(records)
    start = (page - 1) * page_size
    paginated = records[start : start + page_size]
    return {"total": total, "page": page, "page_size": page_size, "results": paginated}


@router.get("/results/{test_id}", status_code=status.HTTP_200_OK, summary="Fetch a single A/B test result by ID")
async def get_result(test_id: str, store: ABTestStore = Depends(get_ab_test_store)):
    record = store.get_by_id(test_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No result found for test_id '{test_id}'")
    return record


@router.get("/summary", status_code=status.HTTP_200_OK, summary="Aggregate statistics across all stored tests")
async def get_summary(store: ABTestStore = Depends(get_ab_test_store)):
    return store.summary_statistics()


@router.delete("/results", status_code=status.HTTP_200_OK, response_model=DeleteResponse, summary="Clear all stored A/B test results")
async def clear_results(store: ABTestStore = Depends(get_ab_test_store)):
    count = store.clear()
    return DeleteResponse(deleted_count=count, message=f"Deleted {count} test result(s) from the store.")


@router.get("/health", status_code=status.HTTP_200_OK, summary="Framework health check")
async def ab_health(store: ABTestStore = Depends(get_ab_test_store)):
    records = store.get_all()
    return {"status": "ok", "stored_results": len(records), "results_file": store.results_file}