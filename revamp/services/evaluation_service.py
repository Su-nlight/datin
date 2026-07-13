"""
app/services/evaluation_service.py

Same logic as Backend/API/evaluator.py, wrapped as an injectable service
instead of free functions that each took a raw `llm` positional arg.

Backend/API/code_evaluator.py's CodeSecurityEvaluator is merged in below
as a sibling class in this same module — it already imported
parse_gemini_judgment from evaluator.py, so keeping it here removes a
cross-file import instead of adding one.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from langchain.llms.base import LLM
from openevals.prompts import (
    CORRECTNESS_PROMPT,
    RAG_GROUNDEDNESS_PROMPT,
    RAG_HELPFULNESS_PROMPT,
    RAG_RETRIEVAL_RELEVANCE_PROMPT,
)

logger = logging.getLogger(__name__)


def parse_gemini_judgment(text: str) -> Dict[str, Any]:
    score_match = re.search(r"Score:\s*(True|False)", text, re.IGNORECASE)
    comment_match = re.search(r"Comment:\s*(.*)", text, re.IGNORECASE)

    score = None
    if score_match:
        score = score_match.group(1).lower() == "true"

    comment = comment_match.group(1).strip() if comment_match else ""
    return {"score": score, "comment": comment}


class EvaluationService:
    """
    llm here should always be the fixed evaluator LLM
    (see providers/llm_provider.build_evaluator_llm), injected once at
    construction — never the "main" generation LLM.
    """

    def __init__(self, evaluator_llm: LLM):
        self.llm = evaluator_llm

    def evaluate_rag_parameters(
        self,
        inputs: dict,
        outputs: dict,
        context: Optional[dict] = None,
        reference_outputs: Optional[dict] = None,
    ) -> Dict[str, Any]:
        results: Dict[str, Any] = {}

        if reference_outputs and "answer" in reference_outputs and "answer" in outputs and "question" in inputs:
            raw = self.llm.predict(
                CORRECTNESS_PROMPT.format(
                    inputs=inputs["question"],
                    outputs=outputs["answer"],
                    reference_outputs=reference_outputs["answer"],
                )
            )
            results["correctness"] = {**parse_gemini_judgment(raw), "raw_judgment": raw}
        else:
            results["correctness"] = {
                "score": None,
                "comment": "Missing required arguments: reference_outputs, outputs, or inputs",
                "raw_judgment": None,
            }

        if "question" in inputs and "answer" in outputs:
            raw = self.llm.predict(RAG_HELPFULNESS_PROMPT.format(inputs=inputs["question"], outputs=outputs["answer"]))
            results["helpfulness"] = {**parse_gemini_judgment(raw), "raw_judgment": raw}
        else:
            results["helpfulness"] = {"score": None, "comment": "Missing required arguments: inputs or outputs", "raw_judgment": None}

        if context and "documents" in context and "answer" in outputs:
            raw = self.llm.predict(RAG_GROUNDEDNESS_PROMPT.format(context=context["documents"], outputs=outputs["answer"]))
            results["groundedness"] = {**parse_gemini_judgment(raw), "raw_judgment": raw}
        else:
            results["groundedness"] = {"score": None, "comment": "Missing required arguments: context or outputs", "raw_judgment": None}

        if context and "documents" in context and "question" in inputs:
            raw = self.llm.predict(RAG_RETRIEVAL_RELEVANCE_PROMPT.format(inputs=inputs["question"], context=context["documents"]))
            results["retrieval_relevance"] = {**parse_gemini_judgment(raw), "raw_judgment": raw}
        else:
            results["retrieval_relevance"] = {"score": None, "comment": "Missing required arguments: context or inputs", "raw_judgment": None}

        return results

    @staticmethod
    def eval_reflection(results: dict) -> Dict[str, Any]:
        heal_flag = False
        healing_prompt = "Following is the reflection of the above response.\n"
        for eval_para, eval_result in results.items():
            if eval_result["score"] is False:
                heal_flag = True
                healing_prompt += (
                    f"For parameter {eval_para.upper()} following is the evaluation "
                    f"result's final comment:\n{eval_result['comment']}\n"
                )
        if not heal_flag:
            return {"Healing_required": False, "Healing_Prompt": ""}
        return {"Healing_required": True, "Healing_Prompt": healing_prompt}


class CodeSecurityEvaluator:
    """
    Moved from Backend/API/code_evaluator.py. Was already using
    parse_gemini_judgment from evaluator.py by import — now that function
    lives in this same module, so this class stays a sibling of
    EvaluationService instead of importing across files. Logic is
    otherwise unchanged.

    Works with both GeminiLLM and OllamaLLM via the LLM interface.
    """

    def __init__(self, llm: LLM):
        self.llm = llm

    def evaluate_false_positives(self, code: str, findings: List[Dict]) -> Dict:
        if not findings:
            return {"score": 1.0, "comment": "No findings to evaluate", "false_positive_risk": 0.0}

        prompt = f"""
You are a security expert. Evaluate these code findings for false positives.

CODE:
```
{code}
```

FINDINGS:
{self._format_findings(findings)}

For each finding:
1. Is it a real vulnerability? (True/False)
2. What is the false positive risk? (0.0=definitely real, 1.0=definitely false positive)

Score: True if >70% are legitimate. False otherwise.
Comment: Brief assessment.
"""
        try:
            raw_judgment = self.llm.predict(prompt)
            parsed = parse_gemini_judgment(raw_judgment)
            fp_risk = self._extract_metric(raw_judgment)
            return {
                "score": parsed["score"], "comment": parsed["comment"],
                "false_positive_risk": fp_risk, "raw_judgment": raw_judgment,
            }
        except Exception as e:
            logger.error(f"False positive evaluation error: {e}")
            return {"score": None, "comment": str(e), "false_positive_risk": 0.5}

    def evaluate_remediation_quality(self, code: str, findings: List[Dict], remediations: str) -> Dict:
        prompt = f"""
You are a security expert. Evaluate the remediation guidance.

VULNERABILITIES:
{self._format_findings(findings)}

CODE:
```
{code}
```

REMEDIATION PROVIDED:
{remediations}

Assess:
1. Are remediations specific?
2. Do they address root causes?
3. Are code examples provided?
4. Are they practical?

Score: True if high quality. False otherwise.
Comment: Feedback.
"""
        try:
            raw_judgment = self.llm.predict(prompt)
            parsed = parse_gemini_judgment(raw_judgment)
            actionability = self._extract_metric(raw_judgment)
            return {
                "score": parsed["score"], "comment": parsed["comment"],
                "actionability_score": actionability, "raw_judgment": raw_judgment,
            }
        except Exception as e:
            logger.error(f"Remediation quality evaluation error: {e}")
            return {"score": None, "comment": str(e), "actionability_score": 0.5}

    def evaluate_completeness(self, code: str, findings: List[Dict], language: str) -> Dict:
        prompt = f"""
You are a {language} security expert. Was the analysis comprehensive?

CODE:
```{language}
{code}
```

FINDINGS IDENTIFIED:
{self._format_findings(findings)}

Assess:
1. Were obvious vulnerabilities missed?
2. Do findings cover common {language} security issues?
3. Were language-specific concerns addressed?

Score: True if comprehensive. False if major issues missed.
Comment: What might be missing?
"""
        try:
            raw_judgment = self.llm.predict(prompt)
            parsed = parse_gemini_judgment(raw_judgment)
            return {"score": parsed["score"], "comment": parsed["comment"], "raw_judgment": raw_judgment}
        except Exception as e:
            logger.error(f"Completeness evaluation error: {e}")
            return {"score": None, "comment": str(e)}

    def evaluate_severity_accuracy(self, code: str, findings: List[Dict]) -> Dict:
        prompt = f"""
You are a security expert. Are the severity levels accurate?

CODE:
```
{code}
```

FINDINGS WITH SEVERITY:
{self._format_findings(findings)}

Assess:
1. Is severity assignment justified?
2. Should any be re-classified?
3. Are critical issues truly critical?

Score: True if well-calibrated. False if many misclassified.
Comment: Assessment.
"""
        try:
            raw_judgment = self.llm.predict(prompt)
            parsed = parse_gemini_judgment(raw_judgment)
            return {"score": parsed["score"], "comment": parsed["comment"], "raw_judgment": raw_judgment}
        except Exception as e:
            logger.error(f"Severity accuracy evaluation error: {e}")
            return {"score": None, "comment": str(e)}

    def evaluate_cwe_references(self, findings: List[Dict]) -> Dict:
        prompt = f"""
You are a security expert. Do findings include proper threat classification?

FINDINGS:
{self._format_findings(findings)}

Assess:
1. Are CWE identifiers included?
2. Are MITRE ATT&CK techniques referenced?
3. Is threat context provided?

Score: True if proper classification provided. False otherwise.
Comment: Feedback.
"""
        try:
            raw_judgment = self.llm.predict(prompt)
            parsed = parse_gemini_judgment(raw_judgment)
            return {"score": parsed["score"], "comment": parsed["comment"], "raw_judgment": raw_judgment}
        except Exception as e:
            logger.error(f"CWE evaluation error: {e}")
            return {"score": None, "comment": str(e)}

    @staticmethod
    def _format_findings(findings: List[Dict]) -> str:
        if not findings:
            return "No findings"
        formatted = []
        for i, finding in enumerate(findings, 1):
            formatted.append(f"""
Finding {i}:
  Severity: {finding.get('severity', 'unknown')}
  Category: {finding.get('category', 'unknown')}
  Description: {finding.get('description', 'N/A')}
  Line: {finding.get('line', 'N/A')}
  Remediation: {finding.get('remediation', 'N/A')}
""")
        return "\n".join(formatted)

    @staticmethod
    def _extract_metric(text: str) -> float:
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if percent_match:
            return float(percent_match.group(1)) / 100.0
        ratio_match = re.search(r"(\d+)\s*(?:out\s+of|/)\s*(\d+)", text)
        if ratio_match:
            return float(ratio_match.group(1)) / float(ratio_match.group(2))
        return 0.5

    def run_full_evaluation(self, code: str, findings: List[Dict], remediations: str, language: str) -> Dict:
        results = {
            "false_positives": self.evaluate_false_positives(code, findings),
            "remediation_quality": self.evaluate_remediation_quality(code, findings, remediations),
            "completeness": self.evaluate_completeness(code, findings, language),
            "severity_accuracy": self.evaluate_severity_accuracy(code, findings),
            "cwe_references": self.evaluate_cwe_references(findings),
        }
        scores = [r.get("score") for r in results.values() if r.get("score") is not None]
        results["overall_quality_score"] = sum(scores) / len(scores) if scores else None
        return results