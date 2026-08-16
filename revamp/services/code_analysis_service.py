"""
app/services/code_analysis_service.py

Same StaticAnalyzer / SecurityCodeAnalyzer logic as Backend/API/code_analyzer.py.
No load_dotenv() existed in the original file, so nothing config-related
changes here — the only structural change is that SecurityCodeAnalyzer
now type-hints `rag_model` as `RagService` (the new service) instead of
the untyped `rag_model=None` the old class used, and it's constructed
via dependencies.py instead of inline in main.py's lifespan().
"""
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
from pathlib import Path

from langchain.llms.base import LLM

from app.services.rag_service import RagService
from app.models.code_analysis_models import CodeAnalysisResult, CodeAnalysisRequest, SecurityFinding

logger = logging.getLogger(__name__)


class Language(Enum):
    PYTHON = "python"
    CPP = "cpp"
    JAVA = "java"
    JAVASCRIPT = "javascript"



class StaticAnalyzer:
    """Unified static code analyzer for multiple languages"""

    def __init__(self):
        self.semgrep_available = self._check_tool("semgrep")
        self.bandit_available = self._check_tool("bandit")
        self.eslint_available = self._check_tool("eslint")

        if not any([self.semgrep_available, self.bandit_available, self.eslint_available]):
            logger.warning("No static analysis tools available. Install: semgrep, bandit, eslint")

    @staticmethod
    def _check_tool(tool_name: str) -> bool:
        try:
            subprocess.run([tool_name, "--version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def analyze_python(self, code: str) -> List[SecurityFinding]:
        findings = []
        if self.bandit_available:
            findings.extend(self._run_bandit(code))
        if self.semgrep_available:
            findings.extend(self._run_semgrep(code, Language.PYTHON))
        return findings

    def analyze_cpp(self, code: str) -> List[SecurityFinding]:
        findings = []
        if self.semgrep_available:
            findings.extend(self._run_semgrep(code, Language.CPP))
        findings.extend(self._run_cppcheck(code))
        return findings

    def analyze_java(self, code: str) -> List[SecurityFinding]:
        if self.semgrep_available:
            return self._run_semgrep(code, Language.JAVA)
        return []

    def analyze_javascript(self, code: str) -> List[SecurityFinding]:
        findings = []
        if self.semgrep_available:
            findings.extend(self._run_semgrep(code, Language.JAVASCRIPT))
        if self.eslint_available:
            findings.extend(self._run_eslint(code))
        return findings

    def _run_semgrep(self, code: str, language: Language) -> List[SecurityFinding]:
        findings = []
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=f".{language.value}", delete=False) as f:
                f.write(code)
                temp_file = f.name
            try:
                result = subprocess.run(
                    ["semgrep", "--json", "--config=p/security-audit", "--config=p/owasp-top-ten", temp_file],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode in [0, 1]:
                    output = json.loads(result.stdout)
                    for res in output.get("results", []):
                        severity_map = {"ERROR": "critical", "WARNING": "high", "INFO": "medium"}
                        findings.append(SecurityFinding(
                            rule_id=res.get("check_id", "unknown"),
                            message=res.get("extra", {}).get("message", res.get("message", "Unknown")),
                            path="",  # semgrep doesn't provide file path in this context
                            line=res.get("start", {}).get("line", 0),
                            severity=severity_map.get(res.get("extra", {}).get("severity", "ERROR"), "high").lower(),
                            tool="semgrep",
                        ))
            finally:
                os.unlink(temp_file)
        except Exception as e:
            logger.warning(f"Semgrep error: {e}")
        return findings

    def _run_bandit(self, code: str) -> List[SecurityFinding]:
        findings = []
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                temp_file = f.name
            try:
                result = subprocess.run(["bandit", "-f", "json", temp_file], capture_output=True, text=True, timeout=15)
                output = json.loads(result.stdout)
                severity_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
                for res_item in output.get("results", []):
                    findings.append(SecurityFinding(
                        severity=severity_map.get(res_item.get("severity", "MEDIUM"), "medium"),
                        category=res_item.get("test_id", "unknown"),
                        description=res_item.get("issue_text", "Unknown"),
                        line=res_item.get("line_number", 0),
                        column=0,
                        remediation="See bandit docs",
                        source="static_analysis",
                    ))
            finally:
                os.unlink(temp_file)
        except Exception as e:
            logger.warning(f"Bandit error: {e}")
        return findings

    def _run_cppcheck(self, code: str) -> List[SecurityFinding]:
        findings = []
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False) as f:
                f.write(code)
                temp_file = f.name
            try:
                result = subprocess.run(["cppcheck", "--template=json", "--enable=security", temp_file], capture_output=True, text=True, timeout=15)
                output = json.loads(result.stdout)
                severity_map = {"error": "critical", "warning": "high", "style": "low", "information": "info"}
                for error in output.get("errors", []):
                    findings.append(SecurityFinding(
                        rule_id=error.get("id", "unknown"),
                        message=error.get("message", "Unknown"),
                        path="",
                        line=error.get("location", {}).get("info", [{}])[0].get("line", 0),
                        severity=severity_map.get(error.get("severity", "warning"), "high").lower(),
                        tool="cppcheck",
                    ))
            finally:
                os.unlink(temp_file)
        except Exception as e:
            logger.warning(f"Cppcheck error: {e}")
        return findings

    def _run_eslint(self, code: str) -> List[SecurityFinding]:
        findings = []
        # Skip if no eslint config exists — avoids config-error "findings"
        eslint_rc = any(Path(p).exists() for p in [".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.yml", ".eslintrc.yaml"])
        if not eslint_rc:
            return findings
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
                f.write(code)
                temp_file = f.name
            try:
                result = subprocess.run(["eslint", "--format", "json", temp_file], capture_output=True, text=True, timeout=15)
                output = json.loads(result.stdout) if result.stdout else []
                for file_res in output:
                    for msg in file_res.get("messages", []):
                        severity_map = {2: "critical", 1: "high"}
                        findings.append(SecurityFinding(
                            rule_id=msg.get("ruleId", "unknown"),
                            message=msg.get("message", "Unknown"),
                            path="",
                            line=msg.get("line", 0),
                            severity=severity_map.get(msg.get("severity", 1), "high").lower(),
                            tool="eslint",
                        ))
            finally:
                os.unlink(temp_file)
        except Exception as e:
            logger.warning(f"ESLint error: {e}")
        return findings


class SecurityCodeAnalyzer:
    """
    Main analyzer: combines static analysis + RAG threat intelligence.

    Injected dependencies (via app/dependencies.py):
    - llm: GeminiLLM or OllamaLLM (app/providers/llm_provider.py)
    - rag_model: RagService instance (optional, for threat intel)
    """

    def __init__(self, llm: LLM, rag_model: Optional[RagService] = None):
        self.llm = llm
        self.rag_model = rag_model
        self.static_analyzer = StaticAnalyzer()

    def detect_language(self, code: str) -> Optional[Language]:
        indicators = {
            Language.PYTHON: [r"^import\s+\w+", r"^from\s+\w+\s+import", r"^\s*def\s+\w+\(", r"^\s*class\s+\w+:"],
            Language.JAVA: [r"public\s+class\s+\w+", r"public\s+static\s+void\s+main", r"package\s+\w+", r"import\s+java\."],
            Language.CPP: [r'#include\s+[<"]', r"std::", r"int\s+main\(", r"template\s*<"],
            Language.JAVASCRIPT: [r"const\s+\w+\s*=", r"function\s+\w+\(", r"console\.log\(", r"=>"],
        }
        lines = code.split("\n")[:20]
        code_sample = "\n".join(lines)
        scores = {}
        for lang, patterns in indicators.items():
            scores[lang] = sum(1 for p in patterns if re.search(p, code_sample, re.MULTILINE))
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        return None

    def analyze_code_static(self, code: str, language: Language) -> List[SecurityFinding]:
        if language == Language.PYTHON:
            return self.static_analyzer.analyze_python(code)
        elif language == Language.CPP:
            return self.static_analyzer.analyze_cpp(code)
        elif language == Language.JAVA:
            return self.static_analyzer.analyze_java(code)
        elif language == Language.JAVASCRIPT:
            return self.static_analyzer.analyze_javascript(code)
        return []

    def analyze_code_with_rag(self, code: str, language: Language, static_findings: List[SecurityFinding]) -> str:
        if not self.rag_model:
            return "RAG context not available"

        findings_summary = self._summarize_findings(static_findings)
        analysis_prompt = f"""
Analyze this {language.value} code for security vulnerabilities.

CODE:
```{language.value}
{code}
```

STATIC ANALYSIS FINDINGS:
{findings_summary}

Provide:
1. Additional security risks (cybersecurity perspective)
2. MITRE ATT&CK technique references
3. Specific remediation steps
4. Exploitation risks
5. Secure coding practices
"""
        try:
            rag_context = self.rag_model._vector_data_retriever(analysis_prompt)
            full_prompt = f"{analysis_prompt}\n\nTHREAT INTELLIGENCE CONTEXT:\n{rag_context}"
            return self.llm.predict(full_prompt)
        except Exception as e:
            logger.error(f"RAG analysis error: {e}")
            return f"Error: {str(e)}"

    @staticmethod
    def _summarize_findings(findings: List[SecurityFinding]) -> str:
        if not findings:
            return "No static analysis findings."
        summary_lines = []
        severity_groups: Dict[str, List[SecurityFinding]] = {}
        for finding in findings:
            severity_groups.setdefault(finding.severity, []).append(finding)
        for severity in ["critical", "high", "medium", "low", "info"]:
            if severity in severity_groups:
                summary_lines.append(f"\n{severity.upper()} ({len(severity_groups[severity])} issues):")
                for finding in severity_groups[severity][:5]:
                    summary_lines.append(f"  - Line {finding.line}: {finding.category} - {finding.description}")
        return "\n".join(summary_lines)

    def format_findings_for_output(self, findings: List[SecurityFinding]) -> List[SecurityFinding]:
        return findings  # Already pydantic SecurityFinding instances

    def analyze_stream(self, code: str, language: Optional[Language] = None):
        if language is None:
            language = self.detect_language(code)
            if language is None:
                yield "error: Could not detect programming language\n"
                return
            yield f"Detected language: {language.value}\n---\n"

        yield "Starting static analysis...\n"
        static_findings = self.analyze_code_static(code, language)
        for finding in static_findings:
            yield f"[{finding.severity.upper()}] Line {finding.line}: {finding.category} - {finding.description}\n"
        yield "\n---\n"

        if self.rag_model:
            yield "Performing contextual security analysis with threat intelligence...\n"
            yield self.analyze_code_with_rag(code, language, static_findings)
