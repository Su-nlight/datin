"""
testing_folder/ab_testing.py
==============================
A/B testing framework – updated for revised RagModel API.

Breaking changes addressed vs previous version
-----------------------------------------------
1.  RagModel.__init__ signature changed:
        Old: RagModel(PineconeAPIKey, GenAIKey, NameSpaces, Index_Name, min_score)
        New: RagModel(PineconeAPIKey, NameSpaces, Index_Name, min_score, llm)
    InstrumentedRagModel now accepts an injected `llm` and forwards it.

2.  GeminiLLM moved from evaluator.py → llm_provider.py.
    Import path updated accordingly.

3.  LLM generation now routes through self.llm.predict() (LangChain interface)
    instead of direct google-genai SDK calls — supports both Gemini and Ollama.

4.  A dedicated fixed-provider evaluator (Gemini Flash-Lite) is used for ALL
    quality assessments regardless of the variant's main LLM.  This ensures
    the judge is neutral when comparing Gemini vs Ollama variants.

Import paths
------------
    from ..evaluator    import evaluate_rag_parameters, eval_reflection
    from ..llm_provider import GeminiLLM                   ← moved here
    from ..ragroute     import RagModel
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain.llms.base import LLM

from evaluator    import evaluate_rag_parameters, eval_reflection
from llm_provider import GeminiLLM                # ← was in evaluator.py
from ragroute     import RagModel

load_dotenv("API.env")


# ---------------------------------------------------------------------------
# Data-class hierarchy
# ---------------------------------------------------------------------------

@dataclass
class TimingBreakdown:
    retrieval_ms:  float = 0.0
    generation_ms: float = 0.0
    evaluation_ms: float = 0.0
    healing_ms:    float = 0.0
    total_ms:      float = 0.0


@dataclass
class QualityScores:
    correctness:        Optional[bool] = None
    helpfulness:        Optional[bool] = None
    groundedness:       Optional[bool] = None
    retrieval_relevance: Optional[bool] = None
    overall_score:      float = 0.0
    raw_evaluation:     Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_evaluation(cls, eval_results: Dict[str, Any]) -> "QualityScores":
        def _b(k): return eval_results.get(k, {}).get("score")
        scores = [_b("correctness"), _b("helpfulness"),
                  _b("groundedness"), _b("retrieval_relevance")]
        true_cnt  = sum(1 for s in scores if s is True)
        valid_cnt = sum(1 for s in scores if s is not None)
        return cls(
            correctness=_b("correctness"),
            helpfulness=_b("helpfulness"),
            groundedness=_b("groundedness"),
            retrieval_relevance=_b("retrieval_relevance"),
            overall_score=round(true_cnt / valid_cnt, 3) if valid_cnt else 0.0,
            raw_evaluation=eval_results,
        )


@dataclass
class VariantResult:
    name:              str
    response:          str = ""
    timing:            TimingBreakdown = field(default_factory=TimingBreakdown)
    quality:           QualityScores   = field(default_factory=QualityScores)
    healing_triggered: bool = False
    healing_prompt:    Optional[str] = None
    error:             Optional[str] = None


@dataclass
class ABTestResult:
    test_id:          str
    query:            str
    timestamp:        float
    variant_a:        VariantResult
    variant_b:        VariantResult
    winner:           str  = "TIE"
    quality_delta:    float = 0.0
    time_overhead_ms: float = 0.0


# ---------------------------------------------------------------------------
# Fixed evaluator LLM – Gemini Flash-Lite regardless of main provider
# ---------------------------------------------------------------------------

def _build_evaluator_llm() -> GeminiLLM:
    """
    Returns a lightweight, fixed Gemini Flash-Lite instance used exclusively
    as the LLM-as-Judge.  Using a fixed provider ensures evaluation quality
    scores are comparable across Gemini vs Ollama variants.
    """
    return GeminiLLM(
        api_key=os.getenv("GENAI_API_KEY"),
        model_name="gemini-2.0-flash-lite-001",
        temperature=0.3,
        system_instruction=(
            "You are a JUDGE for evaluating LLM responses. "
            "Provide SCORE (True or False) and a single-line COMMENT."
        ),
    )


# ---------------------------------------------------------------------------
# Instrumented model
# ---------------------------------------------------------------------------

class InstrumentedRagModel(RagModel):
    """
    Subclass of RagModel that exposes phase-level timing for A/B tests.

    Constructor changes vs previous version
    ----------------------------------------
    - Removed:  GenAIKey  (no longer in RagModel)
    - Added:    llm       (injected LangChain LLM, matches new RagModel API)
    - Added:    _eval_llm (fixed lightweight evaluator, set internally)

    Generation path
    ---------------
    Uses self.llm.predict(prompt) — works with both GeminiLLM and OllamaLLM.
    """

    def __init__(
        self,
        llm: LLM,
        PineconeAPIKey: str,
        NameSpaces: list,
        Index_Name: str,
        min_score: float,
    ):
        super().__init__(
            PineconeAPIKey=PineconeAPIKey,
            NameSpaces=NameSpaces,
            Index_Name=Index_Name,
            min_score=min_score,
            llm=llm,
        )
        # Fixed neutral evaluator – Gemini Flash-Lite for ALL quality assessments
        self._eval_llm: GeminiLLM = _build_evaluator_llm()

    # ------------------------------------------------------------------
    # Variant A – generate + evaluate, no healing
    # ------------------------------------------------------------------

    def run_variant_a(self, user_query: str, context: str) -> VariantResult:
        result = VariantResult(name="A – No Healing")
        t0 = time.perf_counter()
        try:
            prompt = self._build_rag_prompt(user_query, context, history=[])

            t_g = time.perf_counter()
            response = self.llm.predict(prompt)
            gen_ms = (time.perf_counter() - t_g) * 1_000

            t_e = time.perf_counter()
            eval_res = evaluate_rag_parameters(
                llm=self._eval_llm,
                inputs={"question": user_query},
                outputs={"answer": response},
                context={"documents": [s.strip() for s in context.split("---")]},
            )
            eval_ms = (time.perf_counter() - t_e) * 1_000

            result.response = response
            result.quality  = QualityScores.from_evaluation(eval_res)
            result.timing   = TimingBreakdown(
                generation_ms=gen_ms,
                evaluation_ms=eval_ms,
                total_ms=(time.perf_counter() - t0) * 1_000,
            )
        except Exception as exc:
            result.error = str(exc)
            result.timing.total_ms = (time.perf_counter() - t0) * 1_000
        return result

    # ------------------------------------------------------------------
    # Variant B – generate + evaluate + conditional healing + re-evaluate
    # ------------------------------------------------------------------

    def run_variant_b(self, user_query: str, context: str) -> VariantResult:
        result = VariantResult(name="B – With Healing")
        t0 = time.perf_counter()
        try:
            prompt = self._build_rag_prompt(user_query, context, history=[])

            t_g = time.perf_counter()
            response = self.llm.predict(prompt)
            gen_ms = (time.perf_counter() - t_g) * 1_000

            t_e = time.perf_counter()
            eval_res = evaluate_rag_parameters(
                llm=self._eval_llm,
                inputs={"question": user_query},
                outputs={"answer": response},
                context={"documents": [s.strip() for s in context.split("---")]},
            )
            healing = eval_reflection(eval_res)
            eval_ms = (time.perf_counter() - t_e) * 1_000

            t_h = time.perf_counter()
            triggered = healing["Healing_required"]
            heal_prompt_used: Optional[str] = None
            if triggered:
                heal_prompt_used = healing["Healing_Prompt"]
                response = self.llm.predict(
                    f'For the AI generated response: "{response}".\n'
                    f"{heal_prompt_used}\n"
                    "Correct the answer per the healing instructions and return accurate response."
                )
            heal_ms = (time.perf_counter() - t_h) * 1_000

            # Re-evaluate the healed response so quality reflects final output
            if triggered:
                t_re = time.perf_counter()
                eval_res = evaluate_rag_parameters(
                    llm=self._eval_llm,
                    inputs={"question": user_query},
                    outputs={"answer": response},
                    context={"documents": [s.strip() for s in context.split("---")]},
                )
                eval_ms += (time.perf_counter() - t_re) * 1_000

            result.response          = response
            result.quality           = QualityScores.from_evaluation(eval_res)
            result.healing_triggered = triggered
            result.healing_prompt    = heal_prompt_used
            result.timing            = TimingBreakdown(
                generation_ms=gen_ms,
                evaluation_ms=eval_ms,
                healing_ms=heal_ms,
                total_ms=(time.perf_counter() - t0) * 1_000,
            )
        except Exception as exc:
            result.error = str(exc)
            result.timing.total_ms = (time.perf_counter() - t0) * 1_000
        return result

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run_ab_test(self, user_query: str, test_id: Optional[str] = None) -> ABTestResult:
        test_id = test_id or str(uuid.uuid4())

        t_ret = time.perf_counter()
        context = self._vector_data_retriever(query=user_query)
        ret_ms  = (time.perf_counter() - t_ret) * 1_000

        var_a = self.run_variant_a(user_query, context)
        var_b = self.run_variant_b(user_query, context)

        for v in (var_a, var_b):
            v.timing.retrieval_ms = ret_ms
            v.timing.total_ms    += ret_ms

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
            test_id=test_id,
            query=user_query,
            timestamp=time.time(),
            variant_a=var_a,
            variant_b=var_b,
            winner=winner,
            quality_delta=round(var_b.quality.overall_score - var_a.quality.overall_score, 3),
            time_overhead_ms=round(var_b.timing.total_ms - var_a.timing.total_ms, 2),
        )


# ---------------------------------------------------------------------------
# Persistent result store
# ---------------------------------------------------------------------------

RESULTS_FILE = os.getenv("AB_RESULTS_FILE", "ab_results.json")


def _load_store() -> List[Dict]:
    if not os.path.exists(RESULTS_FILE):
        return []
    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def _save_store(records: List[Dict]) -> None:
    with open(RESULTS_FILE, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, default=str)


class ABTestStore:

    @staticmethod
    def save(result: ABTestResult) -> None:
        records = _load_store()
        records.append(asdict(result))
        _save_store(records)

    @staticmethod
    def get_all() -> List[Dict]:
        return _load_store()

    @staticmethod
    def get_by_id(test_id: str) -> Optional[Dict]:
        return next((r for r in _load_store() if r.get("test_id") == test_id), None)

    @staticmethod
    def clear() -> int:
        n = len(_load_store())
        _save_store([])
        return n

    @staticmethod
    def summary_statistics() -> Dict[str, Any]:
        records = _load_store()
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

        def _avg(lst): return round(sum(lst) / len(lst), 2) if lst else 0.0

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