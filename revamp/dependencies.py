"""
app/dependencies.py

Every object the routers need comes from here via FastAPI's Depends().
Nothing is constructed inline in a router or in main.py's lifespan, and
there are no module-level singletons like testing_folder/abroute.py's
old `_model = None` / `_get_model()` global.

Updated for the upstream generation/evaluation provider split: anything
that used to build a single "the LLM" now builds `get_generation_llm()`
for actual generation and `get_evaluation_llm()` for judging, exactly
mirroring main.py's lifespan(), ab_testing.py's _build_evaluator_llm(),
and benchmark_suite.py's BenchmarkRunner.
"""
from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.llm_provider import get_evaluation_llm, get_generation_llm, get_llm
from app.providers.pinecone_provider import PineconeProvider
from app.services.ab_testing_service import ABTestStore, InstrumentedRagModel
from app.services.auth_service import AuthService
from app.services.code_analysis_service import SecurityCodeAnalyzer
from app.services.database_service import DatabaseService
from app.services.evaluation_service import CodeSecurityEvaluator, EvaluationService
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from langchain.llms.base import LLM


@lru_cache
def get_generation_llm_dependency() -> LLM:
    """Resolved from GENERATION_LLM_PROVIDER. Old main.py's `generation_llm`."""
    return get_generation_llm(get_settings())


@lru_cache
def get_evaluation_llm_dependency() -> LLM:
    """Resolved from EVALUATION_LLM_PROVIDER. Old main.py's `evaluation_llm`."""
    return get_evaluation_llm(get_settings())


@lru_cache
def get_evaluation_service() -> EvaluationService:
    return EvaluationService(evaluator_llm=get_evaluation_llm_dependency())


@lru_cache
def get_pinecone_provider() -> PineconeProvider:
    settings = get_settings()
    return PineconeProvider(settings=settings, index_name=settings.INDEX_NAME)


@lru_cache
def get_rag_service() -> RagService:
    settings = get_settings()
    return RagService(
        llm=get_generation_llm_dependency(),
        evaluation_llm=get_evaluation_llm_dependency(),
        pinecone=get_pinecone_provider(),
        namespaces=settings.namespace_list,
        min_score=settings.MIN_SCORE,
        evaluation_service=get_evaluation_service(),
    )


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService(settings=get_settings())


@lru_cache
def get_database_service() -> DatabaseService:
    return DatabaseService(settings=get_settings())


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(settings=get_settings())


@lru_cache
def get_code_analysis_service() -> SecurityCodeAnalyzer:
    """
    Old main.py: `SecurityCodeAnalyzer(llm=generation_llm, rag_model=rag_model)`
    — findings/RAG-context generation uses the generation LLM, not the judge.
    """
    return SecurityCodeAnalyzer(llm=get_generation_llm_dependency(), rag_model=get_rag_service())


@lru_cache
def get_code_evaluator() -> CodeSecurityEvaluator:
    """
    Old main.py: `CodeSecurityEvaluator(llm=evaluation_llm)` — judging code
    findings uses the evaluation LLM. NOTE: the current upstream main.py
    builds this evaluator in lifespan() but never assigns it to
    app.state.code_evaluator, so code_analysis_router.py's
    `/analyze-with-eval` endpoint crashes with an AttributeError as soon
    as it's hit (request.app.state.code_evaluator doesn't exist). Routing
    it through Depends() here, as everywhere else in this migration,
    fixes that — the object is always available regardless of what main.py
    remembers to attach to app.state.
    """
    return CodeSecurityEvaluator(llm=get_evaluation_llm_dependency())


@lru_cache
def get_instrumented_rag_service() -> InstrumentedRagModel:
    """
    Replaces testing_folder/abroute.py's module-level
    `_model: Optional[InstrumentedRagModel] = None` + `_get_model()`
    lazy-init pattern (which upstream still has). Cached the same way,
    but via lru_cache instead of a hand-rolled global + None-check.
    Generation LLM comes from get_generation_llm(), matching abroute.py's
    current `llm = get_generation_llm()` call.
    """
    settings = get_settings()
    return InstrumentedRagModel(
        llm=get_generation_llm_dependency(),
        pinecone=get_pinecone_provider(),
        namespaces=settings.namespace_list,
        min_score=settings.MIN_SCORE,
        evaluation_service=get_evaluation_service(),
        eval_llm=get_evaluation_llm_dependency(),
    )


@lru_cache
def get_ab_test_store() -> ABTestStore:
    return ABTestStore(settings=get_settings())


@lru_cache
def get_benchmark_store() -> "BenchmarkStore":
    """
    Single BenchmarkStore instance, resolved from Settings.BENCHMARK_RESULTS_DIR
    once. Avoids constructing a fresh one per-request in the benchmark router.
    """
    from app.services.benchmark_service import BenchmarkStore

    settings = get_settings()
    return BenchmarkStore(results_dir=settings.BENCHMARK_RESULTS_DIR)