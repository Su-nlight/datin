"""
app/services/ab_testing_service.py

Same data-classes and InstrumentedRagModel logic as
Backend/API/testing_folder/ab_testing.py, updated for the new service
layer:

  - InstrumentedRagModel now subclasses app.services.rag_service.RagService
    instead of the old ragroute.RagModel — same method bodies.
  - The fixed evaluator LLM comes from
    app.providers.llm_provider.get_evaluation_llm(settings) instead of a
    locally-defined _build_evaluator_llm() — matches upstream's own fix,
    which now resolves the judge through get_evaluation_llm() driven by
    EVALUATION_LLM_PROVIDER rather than hardcoding Gemini Flash-Lite.
  - ABTestStore reads AB_RESULTS_FILE from Settings instead of
    os.getenv() at import time.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from langchain.llms.base import LLM

from app.config import Settings
from app.providers.pinecone_provider import PineconeProvider
from app.services.evaluation_service import EvaluationService
from app.services.rag_service import RagService


@dataclass
class TimingBreakdown:
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    evaluation_ms: float = 0.0
    healing_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class QualityScores:
    correctness: Optional[bool] = None
    helpfulness: Optional[bool] = None
    groundedness: Optional[bool] = None
    retrieval_relevance: Optional[bool] = None
    overall_score: float = 0.0
    raw_evaluation: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_evaluation(cls, eval_results: Dict[str, Any]) -> "QualityScores":
        def _b(k):
            return eval_results.get(k, {}).get("score")

        # Count only explicitly True/False as valid for overall_score calculation
        valid_scores = [s for s in scores if s is not None]
        true_cnt = sum(1 for s in valid_scores if s is True) 

        return cls(
            correctness=_b("correctness"),
            helpfulness=_b("helpfulness"),
            groundedness=_b("groundedness"),
            retrieval_relevance=_b("retrieval_relevance"),
            overall_score=round(true_cnt / len(valid_scores), 3) if valid_scores else 0.0,
            raw_evaluation=eval_results,
        )


@dataclass
class VariantResult:
    name: str
    response: str = ""
    timing: TimingBreakdown = field(default_factory=TimingBreakdown)
    quality: QualityScores = field(default_factory=QualityScores)
    healing_triggered: bool = False
    healing_prompt: Optional[str] = None
    healing_error: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ABTestResult:
    test_id: str
    query: str
    timestamp: float
    variant_a: VariantResult
    variant_b: VariantResult
    winner: str = "TIE"
    quality_delta: float = 0.0
    time_overhead_ms: float = 0.0


class InstrumentedRagModel(RagService):
    """
    Subclass of RagService exposing phase-level timing for A/B tests.
    Uses self.llm.predict(prompt) directly — works with both GeminiLLM
    and OllamaLLM, same as the base class.
    """

    def __init__(
        self,
        llm: LLM,
        pinecone: PineconeProvider,
        namespaces: List[str],
        min_score: float,
        evaluation_service: EvaluationService,
        eval_llm: LLM,
    ):
        super().__init__(
            llm=llm,
            pinecone=pinecone,
            namespaces=namespaces,
            min_score=min_score,
            evaluation_service=evaluation_service,
            evaluation_llm=eval_llm,
        )
        # Fixed neutral evaluator — used directly by run_variant_a/b below
        # (rather than through self.evaluation_service, which was built
        # once for the base class) so each variant's judge call is explicit.
        self._eval_llm = eval_llm
        self._eval_service = EvaluationService(evaluator_llm=eval_llm)

    def run_variant_a(self, user_query: str, context: str) -> VariantResult:
        result = VariantResult(name="A – No Healing")
        t0 = time.perf_counter()
        try:
            prompt = self._build_rag_prompt(user_query, context, history=[])

            t_g = time.perf_counter()
            response = self.llm.predict(prompt)
            gen_ms = (time.perf_counter() - t_g) * 1_000

            t_e = time.perf_counter()
            eval_res = self._eval_service.evaluate_rag_parameters(
                inputs={"question": user_query},
                outputs={"answer": response},
                context={"documents": [s.strip() for s in context.split("---")]},
            )
            eval_ms = (time.perf_counter() - t_e) * 1_000

            result.response = response
            result.quality = QualityScores.from_evaluation(eval_res)
            result.timing = TimingBreakdown(
                generation_ms=gen_ms, evaluation_ms=eval_ms, total_ms=(time.perf_counter() - t0) * 1_000
            )
        except Exception as exc:
            result.error = str(exc)
            result.timing.total_ms = (time.perf_counter() - t0) * 1_000
        return result

    def run_variant_b(self, user_query: str, context: str) -> VariantResult:
        result = VariantResult(name="B – With Healing")
        t0 = time.perf_counter()
        try:
            prompt = self._build_rag_prompt(user_query, context, history=[])

            t_g = time.perf_counter()
            response = self.llm.predict(prompt)
            gen_ms = (time.perf_counter() - t_g) * 1_000

            t_e = time.perf_counter()
            eval_res = self._eval_service.evaluate_rag_parameters(
                inputs={"question": user_query},
                outputs={"answer": response},
                context={"documents": [s.strip() for s in context.split("---")]},
            )
            healing = self._eval_service.eval_reflection(eval_res, question=user_query)
            eval_ms = (time.perf_counter() - t_e) * 1_000

            t_h = time.perf_counter()
            triggered = healing["Healing_required"]
            heal_prompt_used: Optional[str] = None
            # if triggered:
            #     heal_prompt_used = healing["Healing_Prompt"]
            #     response = self.llm.predict(
            #         f'For the AI generated response: "{response}".\n'
            #         f"{heal_prompt_used}\n"
            #         "Correct the answer per the healing instructions and return accurate response."
            #     )
            # heal_ms = (time.perf_counter() - t_h) * 1_000

            # if triggered:
            #     t_re = time.perf_counter()
            #     eval_res = self._eval_service.evaluate_rag_parameters(
            #         inputs={"question": user_query},
            #         outputs={"answer": response},
            #         context={"documents": [s.strip() for s in context.split("---")]},
            #     )
            #     eval_ms += (time.perf_counter() - t_re) * 1_000
            if triggered:
                heal_prompt_used = healing["Healing_Prompt"]
                pre_heal_response = response

                response = self.llm.predict(
                    f"ORIGINAL QUESTION:\n{user_query}\n\n"
                    f'AI GENERATED RESPONSE (to be corrected):\n"{response}"\n\n'
                    f"{heal_prompt_used}\n"
                    "Correct the answer per the healing instructions and return accurate response. "
                    "Reply with the corrected answer only, directly addressing the ORIGINAL QUESTION."
                )

                if (
                    not response.strip()
                    or response.strip() == pre_heal_response.strip()
                ):
                    result.healing_error = (
                        "healing_error: heal pass returned empty/unchanged response"
                    )

            heal_ms = (time.perf_counter() - t_h) * 1_000

            if triggered and not result.healing_error:
                t_re = time.perf_counter()

                eval_res = self._eval_service.evaluate_rag_parameters(
                    inputs={"question": user_query},
                    outputs={"answer": response},
                    context={
                        "documents": [
                            s.strip() for s in context.split("---")
                        ]
                    },
                )

                eval_ms += (time.perf_counter() - t_re) * 1_000

            result.response = response
            result.quality = QualityScores.from_evaluation(eval_res)
            result.healing_triggered = triggered
            result.healing_prompt = heal_prompt_used
            result.timing = TimingBreakdown(
                generation_ms=gen_ms, evaluation_ms=eval_ms, healing_ms=heal_ms,
                total_ms=(time.perf_counter() - t0) * 1_000,
            )
        except Exception as exc:
            result.error = str(exc)
            result.timing.total_ms = (time.perf_counter() - t0) * 1_000
        return result

    def run_ab_test(self, user_query: str, test_id: Optional[str] = None) -> ABTestResult:
        test_id = test_id or str(uuid.uuid4())

        t_ret = time.perf_counter()
        context = self._vector_data_retriever(query=user_query)
        ret_ms = (time.perf_counter() - t_ret) * 1_000

        var_a = self.run_variant_a(user_query, context)
        var_b = self.run_variant_b(user_query, context)

        for v in (var_a, var_b):
            v.timing.retrieval_ms = ret_ms
            v.timing.total_ms += ret_ms

        if var_a.error and var_b.error:
            winner = "ERROR"
        elif var_a.error:
            winner = "B"
        elif var_b.error:
            winner = "A"
        elif var_b.quality.overall_score > var_a.quality.overall_score:
            winner = "B"
        elif var_a.quality.overall_score > var_b.quality.overall_score:
            winner = "A"
        else:
            winner = "TIE"

        return ABTestResult(
            test_id=test_id, query=user_query, timestamp=time.time(),
            variant_a=var_a, variant_b=var_b, winner=winner,
            quality_delta=round(var_b.quality.overall_score - var_a.quality.overall_score, 3),
            time_overhead_ms=round(var_b.timing.total_ms - var_a.timing.total_ms, 2),
        )


class ABTestStore:
    """JSON-file store, path from Settings.AB_RESULTS_FILE."""

    def __init__(self, settings: Settings):
        self.results_file = settings.AB_RESULTS_FILE

    def _load(self) -> List[Dict]:
        if not os.path.exists(self.results_file):
            return []
        try:
            with open(self.results_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, records: List[Dict]) -> None:
        with open(self.results_file, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, default=str)

    def save(self, result: ABTestResult) -> None:
        records = self._load()
        records.append(asdict(result))
        self._save(records)

    def get_all(self) -> List[Dict]:
        return self._load()

    def get_by_id(self, test_id: str) -> Optional[Dict]:
        return next((r for r in self._load() if r.get("test_id") == test_id), None)

    def clear(self) -> int:
        n = len(self._load())
        self._save([])
        return n

    def summary_statistics(self) -> Dict[str, Any]:
        records = self._load()
        if not records:
            return {"total_tests": 0, "message": "No results stored yet."}
        total = len(records)
        winners: Dict[str, int] = {"A": 0, "B": 0, "TIE": 0, "ERROR": 0}
        healing_cnt = 0
        q_a, q_b, deltas, overheads = [], [], [], []
        ret_ms, gen_a, gen_b, eval_a, eval_b, heal_ms = [], [], [], [], [], []

        for r in records:
            va, vb = r.get("variant_a", {}), r.get("variant_b", {})
            w = r.get("winner", "ERROR")
            winners[w] = winners.get(w, 0) + 1
            if vb.get("healing_triggered"):
                healing_cnt += 1
            q_a.append(va.get("quality", {}).get("overall_score", 0))
            q_b.append(vb.get("quality", {}).get("overall_score", 0))
            deltas.append(r.get("quality_delta", 0))
            overheads.append(r.get("time_overhead_ms", 0))
            ta, tb = va.get("timing", {}), vb.get("timing", {})
            ret_ms.append(ta.get("retrieval_ms", 0))
            gen_a.append(ta.get("generation_ms", 0))
            gen_b.append(tb.get("generation_ms", 0))
            eval_a.append(ta.get("evaluation_ms", 0))
            eval_b.append(tb.get("evaluation_ms", 0))
            heal_ms.append(tb.get("healing_ms", 0))

        def _avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else 0.0

        return {
            "total_tests": total,
            "healing_triggered_count": healing_cnt,
            "healing_triggered_pct": round(healing_cnt / total * 100, 1),
            "winner_distribution": winners,
            "avg_quality_A": _avg(q_a),
            "avg_quality_B": _avg(q_b),
            "avg_quality_delta": _avg(deltas),
            "avg_time_overhead_ms": _avg(overheads),
            "avg_retrieval_ms": _avg(ret_ms),
            "avg_generation_ms_A": _avg(gen_a),
            "avg_generation_ms_B": _avg(gen_b),
            "avg_evaluation_ms_A": _avg(eval_a),
            "avg_evaluation_ms_B": _avg(eval_b),
            "avg_healing_ms": _avg(heal_ms),
        }