"""
Code Security Evaluator Module
Evaluates quality of security analysis results.
No FastAPI routes - just reusable evaluation logic.
"""

import re
from typing import Dict, List, Optional
from langchain.llms.base import LLM
from evaluator import parse_gemini_judgment
import logging

logger = logging.getLogger(__name__)


class CodeSecurityEvaluator:
    """
    Evaluates quality of code analysis.
    Works with both GeminiLLM and OllamaLLM via LLM interface.
    """
    
    def __init__(self, llm: LLM):
        """
        Args:
            llm: LangChain LLM instance (GeminiLLM or OllamaLLM)
        """
        self.llm = llm
    
    def evaluate_false_positives(self, code: str, findings: List[Dict]) -> Dict:
        """Check if findings are real vulnerabilities or false positives"""
        if not findings:
            return {
                "score": 1.0,
                "comment": "No findings to evaluate",
                "false_positive_risk": 0.0
            }
        
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
                "score": parsed["score"],
                "comment": parsed["comment"],
                "false_positive_risk": fp_risk,
                "raw_judgment": raw_judgment
            }
        except Exception as e:
            logger.error(f"False positive evaluation error: {e}")
            return {
                "score": None,
                "comment": str(e),
                "false_positive_risk": 0.5
            }
    
    def evaluate_remediation_quality(self, code: str, findings: List[Dict], remediations: str) -> Dict:
        """Check if remediations are specific and actionable"""
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
                "score": parsed["score"],
                "comment": parsed["comment"],
                "actionability_score": actionability,
                "raw_judgment": raw_judgment
            }
        except Exception as e:
            logger.error(f"Remediation quality evaluation error: {e}")
            return {
                "score": None,
                "comment": str(e),
                "actionability_score": 0.5
            }
    
    def evaluate_completeness(self, code: str, findings: List[Dict], language: str) -> Dict:
        """Check if all significant vulnerabilities were found"""
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
            
            return {
                "score": parsed["score"],
                "comment": parsed["comment"],
                "raw_judgment": raw_judgment
            }
        except Exception as e:
            logger.error(f"Completeness evaluation error: {e}")
            return {
                "score": None,
                "comment": str(e)
            }
    
    def evaluate_severity_accuracy(self, code: str, findings: List[Dict]) -> Dict:
        """Check if severity levels are correct"""
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
            
            return {
                "score": parsed["score"],
                "comment": parsed["comment"],
                "raw_judgment": raw_judgment
            }
        except Exception as e:
            logger.error(f"Severity accuracy evaluation error: {e}")
            return {
                "score": None,
                "comment": str(e)
            }
    
    def evaluate_cwe_references(self, findings: List[Dict]) -> Dict:
        """Check if findings reference CWE/MITRE techniques"""
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
            
            return {
                "score": parsed["score"],
                "comment": parsed["comment"],
                "raw_judgment": raw_judgment
            }
        except Exception as e:
            logger.error(f"CWE evaluation error: {e}")
            return {
                "score": None,
                "comment": str(e)
            }
    
    @staticmethod
    def _format_findings(findings: List[Dict]) -> str:
        """Format findings for LLM evaluation"""
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
        return '\n'.join(formatted)
    
    @staticmethod
    def _extract_metric(text: str) -> float:
        """Extract numeric quality metric from text"""
        # Try percentage
        percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
        if percent_match:
            return float(percent_match.group(1)) / 100.0
        
        # Try ratio
        ratio_match = re.search(r'(\d+)\s*(?:out\s+of|/)\s*(\d+)', text)
        if ratio_match:
            return float(ratio_match.group(1)) / float(ratio_match.group(2))
        
        return 0.5
    
    def run_full_evaluation(self, code: str, findings: List[Dict], remediations: str, language: str) -> Dict:
        """Run all 5 quality evaluations"""
        results = {
            "false_positives": self.evaluate_false_positives(code, findings),
            "remediation_quality": self.evaluate_remediation_quality(code, findings, remediations),
            "completeness": self.evaluate_completeness(code, findings, language),
            "severity_accuracy": self.evaluate_severity_accuracy(code, findings),
            "cwe_references": self.evaluate_cwe_references(findings)
        }
        
        # Calculate overall score
        scores = [r.get("score") for r in results.values() if r.get("score") is not None]
        overall_score = sum(scores) / len(scores) if scores else None
        results["overall_quality_score"] = overall_score
        
        return results