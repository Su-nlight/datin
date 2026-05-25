"""
testing_folder
==============
A/B testing + research benchmark framework for the DATIN RAG pipeline.

Package layout
--------------
testing_folder/
    __init__.py          ← this file; re-exports all routers
    ab_testing.py        ← data-classes, InstrumentedRagModel, ABTestStore
    abroute.py           ← FastAPI router  /ab-test/*   (8 endpoints)
    benchmark_suite.py   ← BenchmarkRunner, query bank, code bank, stores
    benchmark_router.py  ← FastAPI router  /benchmark/* (10 endpoints)
    metrics_analyzer.py  ← Bootstrap CI, Cohen's d, Wilcoxon, Markdown report

"""

from testing_folder.abroute          import router as ab_router
from testing_folder.benchmark_router import router as benchmark_router

__all__ = ["ab_router", "benchmark_router"]