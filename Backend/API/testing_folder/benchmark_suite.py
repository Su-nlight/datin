"""
testing_folder/benchmark_suite.py
===================================
Research-grade benchmarking engine for the DATIN RAG pipeline.

Benchmark dimensions
--------------------
  Scenarios  :  4  (GEMINI_NO_HEAL, GEMINI_HEAL, OLLAMA_NO_HEAL, OLLAMA_HEAL)
  Queries    :  20  curated cybersecurity queries
  Categories :  6  (APT, Malware, CVE, Shellcode, Network, Crypto)
  Code bench :  6  snippets with known CWEs (Python, JS, C++, Java)

Design decisions
----------------
- Fixed Gemini Flash-Lite evaluator across ALL scenarios ensures the judge
  is provider-neutral when comparing Gemini vs Ollama output quality.
- Context is retrieved once per query and shared across all scenarios
  for that query, isolating the LLM + healing as the independent variables.
- Code analysis benchmarks are evaluated against a ground-truth CWE mapping
  to produce detection rate, severity accuracy, and false positive rate.
- All results are persisted under BENCHMARK_RESULTS_DIR/{run_id}.json
  to support cross-run longitudinal comparison.

Import path
-----------
    from ..evaluator        import evaluate_rag_parameters, eval_reflection
    from ..llm_provider     import GeminiLLM, OllamaLLM, get_llm
    from ..ragroute         import RagModel
    from ..code_analyzer    import SecurityCodeAnalyzer, Language
    from ..code_evaluator   import CodeSecurityEvaluator
    from .ab_testing        import (InstrumentedRagModel, QualityScores,
                                    TimingBreakdown, _build_evaluator_llm)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ..evaluator     import evaluate_rag_parameters, eval_reflection
from ..llm_provider  import GeminiLLM, OllamaLLM, get_llm
from ..ragroute      import RagModel
from ..code_analyzer import SecurityCodeAnalyzer, Language
from ..code_evaluator import CodeSecurityEvaluator
from .ab_testing     import (InstrumentedRagModel, QualityScores,
                              TimingBreakdown, _build_evaluator_llm)

load_dotenv("API.env")

BENCHMARK_RESULTS_DIR = os.getenv("BENCHMARK_RESULTS_DIR", "benchmark_results")
os.makedirs(BENCHMARK_RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QueryCategory(str, Enum):
    APT_THREAT_ACTOR     = "apt_threat_actor"
    MALWARE_ANALYSIS     = "malware_analysis"
    CVE_EXPLOITATION     = "cve_exploitation"
    SHELLCODE_PAYLOAD    = "shellcode_payload"
    NETWORK_ATTACK       = "network_attack"
    CRYPTOGRAPHIC_ATTACK = "cryptographic_attack"


class TestScenario(str, Enum):
    GEMINI_NO_HEAL  = "gemini_no_heal"   # Gemini 2.5 Flash, no self-healing
    GEMINI_HEAL     = "gemini_heal"       # Gemini 2.5 Flash, with self-healing
    OLLAMA_NO_HEAL  = "ollama_no_heal"   # Llama 3.1 via Ollama, no self-healing
    OLLAMA_HEAL     = "ollama_heal"       # Llama 3.1 via Ollama, with self-healing


# ---------------------------------------------------------------------------
# Curated query bank – 20 research-grade cybersecurity queries
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkQuery:
    id:               str
    query:            str
    category:         QueryCategory
    expected_keywords: List[str]   # used for keyword-recall metric


BENCHMARK_QUERY_BANK: List[BenchmarkQuery] = [
    # ── APT / Threat Actor (4) ────────────────────────────────────────────
    BenchmarkQuery(
        id="APT-01",
        query="Describe the initial access and lateral movement techniques used by APT28 (Fancy Bear) against NATO member states, including specific MITRE ATT&CK technique IDs.",
        category=QueryCategory.APT_THREAT_ACTOR,
        expected_keywords=["APT28", "spearphishing", "T1566", "lateral movement", "credential"]
    ),
    BenchmarkQuery(
        id="APT-02",
        query="What are the command and control infrastructure patterns and communication protocols attributed to the Lazarus Group in their financial sector attacks?",
        category=QueryCategory.APT_THREAT_ACTOR,
        expected_keywords=["Lazarus", "C2", "DPRK", "SWIFT", "beaconing"]
    ),
    BenchmarkQuery(
        id="APT-03",
        query="How does APT41 combine nation-state espionage operations with financially motivated cybercrime, and what TTPs distinguish these two operational modes?",
        category=QueryCategory.APT_THREAT_ACTOR,
        expected_keywords=["APT41", "espionage", "ransomware", "supply chain", "China"]
    ),
    BenchmarkQuery(
        id="APT-04",
        query="Explain the supply chain attack methodology used in the SolarWinds SUNBURST campaign, including the build-system compromise and TEARDROP payload delivery mechanism.",
        category=QueryCategory.APT_THREAT_ACTOR,
        expected_keywords=["SolarWinds", "SUNBURST", "Orion", "build system", "DGA"]
    ),

    # ── Malware Analysis (4) ──────────────────────────────────────────────
    BenchmarkQuery(
        id="MAL-01",
        query="Describe the persistence mechanisms, propagation method via EternalBlue, and kill-switch domain mechanism of WannaCry ransomware.",
        category=QueryCategory.MALWARE_ANALYSIS,
        expected_keywords=["WannaCry", "EternalBlue", "kill switch", "SMB", "MBR"]
    ),
    BenchmarkQuery(
        id="MAL-02",
        query="How does Emotet achieve lateral movement using pass-the-hash and credential dumping, and what network-based indicators of compromise should SOC teams monitor?",
        category=QueryCategory.MALWARE_ANALYSIS,
        expected_keywords=["Emotet", "pass-the-hash", "credential", "network", "IOC"]
    ),
    BenchmarkQuery(
        id="MAL-03",
        query="What kernel-level rootkit techniques does the Necurs botnet employ for self-preservation, and how can these be detected using memory forensics?",
        category=QueryCategory.MALWARE_ANALYSIS,
        expected_keywords=["Necurs", "rootkit", "kernel", "DKOM", "memory forensics"]
    ),
    BenchmarkQuery(
        id="MAL-04",
        query="Explain the EDR evasion techniques used by TrickBot, specifically its use of process injection and anti-analysis mechanisms including timing-based sandbox detection.",
        category=QueryCategory.MALWARE_ANALYSIS,
        expected_keywords=["TrickBot", "EDR", "process injection", "sandbox", "evasion"]
    ),

    # ── CVE / Exploitation (4) ────────────────────────────────────────────
    BenchmarkQuery(
        id="CVE-01",
        query="Explain the full exploitation chain of CVE-2021-44228 Log4Shell, including the JNDI lookup injection vector, LDAP callback mechanism, and RCE payload delivery.",
        category=QueryCategory.CVE_EXPLOITATION,
        expected_keywords=["Log4Shell", "JNDI", "LDAP", "RCE", "Java"]
    ),
    BenchmarkQuery(
        id="CVE-02",
        query="Describe how CVE-2017-0144 EternalBlue exploits the SMBv1 Transaction2 request handling vulnerability to achieve remote code execution without authentication.",
        category=QueryCategory.CVE_EXPLOITATION,
        expected_keywords=["EternalBlue", "SMBv1", "buffer overflow", "RCE", "NSA"]
    ),
    BenchmarkQuery(
        id="CVE-03",
        query="What is the complete attack chain for CVE-2021-26855 ProxyLogon in Microsoft Exchange, including SSRF pre-auth, credential theft, and web shell deployment?",
        category=QueryCategory.CVE_EXPLOITATION,
        expected_keywords=["ProxyLogon", "SSRF", "Exchange", "web shell", "authentication bypass"]
    ),
    BenchmarkQuery(
        id="CVE-04",
        query="Explain the heap spray and pool grooming technique used in CVE-2020-0796 SMBGhost to achieve kernel-level code execution from an unauthenticated remote attacker.",
        category=QueryCategory.CVE_EXPLOITATION,
        expected_keywords=["SMBGhost", "heap spray", "kernel", "SMBv3", "pool grooming"]
    ),

    # ── Shellcode / Payload (3) ───────────────────────────────────────────
    BenchmarkQuery(
        id="SHC-01",
        query="Describe the egg hunting shellcode technique for dynamically locating a second-stage payload in memory when the initial buffer is too small for full shellcode.",
        category=QueryCategory.SHELLCODE_PAYLOAD,
        expected_keywords=["egg hunter", "SEH", "memory", "NtAccessCheckAndAuditAlarm", "tag"]
    ),
    BenchmarkQuery(
        id="SHC-02",
        query="How does polymorphic shellcode use XOR encryption and instruction substitution to evade signature-based antivirus detection while maintaining functional equivalence?",
        category=QueryCategory.SHELLCODE_PAYLOAD,
        expected_keywords=["polymorphic", "XOR", "encoder", "NOP sled", "signature evasion"]
    ),
    BenchmarkQuery(
        id="SHC-03",
        query="Explain the process hollowing technique, including how it unmaps a legitimate process, injects a malicious payload, and resumes execution to evade process-based detection.",
        category=QueryCategory.SHELLCODE_PAYLOAD,
        expected_keywords=["process hollowing", "NtUnmapViewOfSection", "injection", "CreateProcess", "SUSPENDED"]
    ),

    # ── Network Attack (3) ────────────────────────────────────────────────
    BenchmarkQuery(
        id="NET-01",
        query="Describe the LLMNR and NBT-NS poisoning attack chain for capturing NTLMv2 hashes on a Windows network, including the Responder tool mechanism and offline cracking methodology.",
        category=QueryCategory.NETWORK_ATTACK,
        expected_keywords=["LLMNR", "NBT-NS", "Responder", "NTLMv2", "hash capture"]
    ),
    BenchmarkQuery(
        id="NET-02",
        query="How does a Kerberoasting attack extract service principal name tickets from Active Directory and what offline cracking techniques are used against RC4-encrypted TGS tickets?",
        category=QueryCategory.NETWORK_ATTACK,
        expected_keywords=["Kerberoasting", "SPN", "TGS", "RC4", "hashcat"]
    ),
    BenchmarkQuery(
        id="NET-03",
        query="Explain the VLAN hopping attack using double 802.1Q tagging, the conditions required on a misconfigured trunk port, and the detection mechanism using VLAN ACLs.",
        category=QueryCategory.NETWORK_ATTACK,
        expected_keywords=["VLAN hopping", "802.1Q", "double tagging", "trunk port", "DTP"]
    ),

    # ── Cryptographic Attack (2) ──────────────────────────────────────────
    BenchmarkQuery(
        id="CRY-01",
        query="Describe the BEAST attack against TLS 1.0 using CBC mode block cipher chaining, including the chosen-plaintext attack methodology and how the IV reuse creates the vulnerability.",
        category=QueryCategory.CRYPTOGRAPHIC_ATTACK,
        expected_keywords=["BEAST", "TLS 1.0", "CBC", "IV", "chosen-plaintext"]
    ),
    BenchmarkQuery(
        id="CRY-02",
        query="Explain how padding oracle attacks against AES-CBC leverage error responses to decrypt ciphertext byte-by-byte without the encryption key.",
        category=QueryCategory.CRYPTOGRAPHIC_ATTACK,
        expected_keywords=["padding oracle", "AES-CBC", "PKCS7", "oracle", "ciphertext"]
    ),
]


# ---------------------------------------------------------------------------
# Code vulnerability benchmark – 6 snippets with ground-truth CWE mapping
# ---------------------------------------------------------------------------

@dataclass
class VulnerableCodeSample:
    id:                str
    language:          str            # matches Language enum value
    code:              str
    known_cwes:        List[str]      # ground-truth CWE IDs
    expected_severity: str            # critical | high | medium | low
    description:       str


CODE_BENCHMARK_BANK: List[VulnerableCodeSample] = [
    VulnerableCodeSample(
        id="CODE-01", language="python",
        code="""
import sqlite3
def get_user(user_id, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return cursor.execute(query).fetchall()
""",
        known_cwes=["CWE-89"],
        expected_severity="critical",
        description="SQL injection via f-string interpolation"
    ),
    VulnerableCodeSample(
        id="CODE-02", language="python",
        code="""
import os, subprocess
def run_scan(target_ip):
    os.system(f"nmap -sV {target_ip}")
    subprocess.call(f"ping {target_ip}", shell=True)
""",
        known_cwes=["CWE-78"],
        expected_severity="critical",
        description="OS command injection via unsanitized shell interpolation"
    ),
    VulnerableCodeSample(
        id="CODE-03", language="javascript",
        code="""
const express = require('express');
const app = express();
app.get('/search', (req, res) => {
    const term = req.query.q;
    res.send(`<h1>Results for: ${term}</h1>`);
});
""",
        known_cwes=["CWE-79"],
        expected_severity="high",
        description="Reflected XSS via unescaped query parameter"
    ),
    VulnerableCodeSample(
        id="CODE-04", language="cpp",
        code="""
#include <cstring>
#include <stdio.h>
void process_packet(const char* payload) {
    char buffer[64];
    strcpy(buffer, payload);
    printf("Processed: %s\\n", buffer);
}
""",
        known_cwes=["CWE-120", "CWE-787"],
        expected_severity="critical",
        description="Stack buffer overflow via unbounded strcpy"
    ),
    VulnerableCodeSample(
        id="CODE-05", language="java",
        code="""
public class DatabaseConfig {
    private static final String DB_HOST = "prod-db.internal";
    private static final String DB_USER = "admin";
    private static final String DB_PASS = "Sup3rS3cr3t!2024";
    public static Connection getConnection() throws SQLException {
        return DriverManager.getConnection(DB_HOST, DB_USER, DB_PASS);
    }
}
""",
        known_cwes=["CWE-798", "CWE-259"],
        expected_severity="high",
        description="Hardcoded credentials in source code"
    ),
    VulnerableCodeSample(
        id="CODE-06", language="python",
        code="""
import pickle, base64
from flask import Flask, request
app = Flask(__name__)
@app.route('/restore')
def restore_session():
    data = base64.b64decode(request.cookies.get('session'))
    return str(pickle.loads(data))
""",
        known_cwes=["CWE-502"],
        expected_severity="critical",
        description="Insecure deserialization of user-controlled pickle data"
    ),
]


# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario:          str               # TestScenario value
    query_id:          str
    response:          str
    timing:            Dict[str, float]
    quality:           Dict[str, Any]
    healing_triggered: bool
    keyword_recall:    float = 0.0       # fraction of expected_keywords found
    error:             Optional[str] = None


@dataclass
class QueryBenchmarkResult:
    query_id:         str
    query:            str
    category:         str
    run_id:           str
    timestamp:        float
    scenario_results: Dict[str, ScenarioResult] = field(default_factory=dict)


@dataclass
class CodeBenchmarkResult:
    sample_id:             str
    language:              str
    known_cwes:            List[str]
    expected_severity:     str
    run_id:                str
    timestamp:             float
    detected_cwes:         List[str] = field(default_factory=list)
    detection_rate:        float = 0.0   # fraction of known CWEs found
    severity_correct:      bool  = False
    false_positive_count:  int   = 0
    total_findings:        int   = 0
    analysis_ms:           float = 0.0
    error:                 Optional[str] = None


@dataclass
class BenchmarkRun:
    run_id:              str
    started_at:          float
    completed_at:        Optional[float]
    scenarios_enabled:   List[str]
    total_queries:       int
    status:              str = "running"   # running | completed | failed
    query_results:       List[Dict] = field(default_factory=list)
    code_results:        List[Dict] = field(default_factory=list)
    config:              Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _keyword_recall(response: str, expected: List[str]) -> float:
    """
    Fraction of expected_keywords (case-insensitive) present in the response.
    Provides a lightweight, deterministic quality proxy independent of the LLM judge.
    """
    if not expected:
        return 1.0
    resp_lower = response.lower()
    found = sum(1 for kw in expected if kw.lower() in resp_lower)
    return round(found / len(expected), 3)


# ---------------------------------------------------------------------------
# Per-scenario runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    """
    Executes a single named scenario (e.g. GEMINI_HEAL) against a given query
    and pre-retrieved context.

    Parameters
    ----------
    scenario     : TestScenario value
    rag_model    : InstrumentedRagModel initialised with the appropriate LLM
    eval_llm     : Fixed neutral evaluator (Gemini Flash-Lite)
    apply_healing: Whether to run the self-healing pass
    """

    def __init__(
        self,
        scenario: TestScenario,
        rag_model: InstrumentedRagModel,
        eval_llm: GeminiLLM,
        apply_healing: bool,
    ):
        self.scenario       = scenario
        self.rag_model      = rag_model
        self.eval_llm       = eval_llm
        self.apply_healing  = apply_healing

    def run(self, bq: BenchmarkQuery, context: str) -> ScenarioResult:
        t0 = time.perf_counter()
        error: Optional[str] = None
        response = ""
        quality: Dict[str, Any] = {}
        timing: Dict[str, float] = {}
        healing_triggered = False

        try:
            prompt = self.rag_model._build_rag_prompt(bq.query, context, history=[])

            t_g = time.perf_counter()
            response = self.rag_model.llm.predict(prompt)
            gen_ms = (time.perf_counter() - t_g) * 1_000

            t_e = time.perf_counter()
            eval_res = evaluate_rag_parameters(
                llm=self.eval_llm,
                inputs={"question": bq.query},
                outputs={"answer": response},
                context={"documents": [s.strip() for s in context.split("---")]},
            )
            eval_ms = (time.perf_counter() - t_e) * 1_000

            heal_ms = 0.0
            if self.apply_healing:
                healing = eval_reflection(eval_res)
                healing_triggered = healing["Healing_required"]
                t_h = time.perf_counter()
                if healing_triggered:
                    response = self.rag_model.llm.predict(
                        f'For the AI generated response: "{response}".\n'
                        f'{healing["Healing_Prompt"]}\n'
                        "Correct the answer per healing instructions."
                    )
                    # Re-evaluate healed output
                    t_re = time.perf_counter()
                    eval_res = evaluate_rag_parameters(
                        llm=self.eval_llm,
                        inputs={"question": bq.query},
                        outputs={"answer": response},
                        context={"documents": [s.strip() for s in context.split("---")]},
                    )
                    eval_ms += (time.perf_counter() - t_re) * 1_000
                heal_ms = (time.perf_counter() - t_h) * 1_000

            qs = QualityScores.from_evaluation(eval_res)
            quality = {
                "correctness":        qs.correctness,
                "helpfulness":        qs.helpfulness,
                "groundedness":       qs.groundedness,
                "retrieval_relevance": qs.retrieval_relevance,
                "overall_score":      qs.overall_score,
            }
            timing = {
                "generation_ms": round(gen_ms, 2),
                "evaluation_ms": round(eval_ms, 2),
                "healing_ms":    round(heal_ms, 2),
                "total_ms":      round((time.perf_counter() - t0) * 1_000, 2),
            }
        except Exception as exc:
            error = str(exc)
            timing = {"total_ms": round((time.perf_counter() - t0) * 1_000, 2)}

        return ScenarioResult(
            scenario=self.scenario.value,
            query_id=bq.id,
            response=response,
            timing=timing,
            quality=quality,
            healing_triggered=healing_triggered,
            keyword_recall=_keyword_recall(response, bq.expected_keywords),
            error=error,
        )


# ---------------------------------------------------------------------------
# Main benchmark runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """
    Orchestrates the full benchmark run across all enabled scenarios and queries.

    Scenarios are initialised lazily to avoid loading Ollama when it is not
    configured.  If OLLAMA_BASE_URL is unset, Ollama scenarios are skipped
    and flagged as 'skipped' in the results.

    Usage
    -----
        runner = BenchmarkRunner(scenarios=[
            TestScenario.GEMINI_NO_HEAL,
            TestScenario.GEMINI_HEAL,
        ])
        run = runner.execute_full_run()
    """

    def __init__(
        self,
        scenarios: Optional[List[TestScenario]] = None,
        query_ids: Optional[List[str]] = None,   # subset; None = all 20
        run_code_bench: bool = True,
    ):
        self.scenarios      = scenarios or list(TestScenario)
        self.query_ids      = set(query_ids) if query_ids else None
        self.run_code_bench = run_code_bench
        self.eval_llm       = _build_evaluator_llm()

        # Initialise shared infra
        PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
        INDEX_NAME       = os.getenv("INDEX_NAME")
        ns_raw           = os.getenv("NAMESPACES", "")
        NameSpaces       = [n.strip() for n in ns_raw.split(",") if n.strip()]
        min_score        = float(os.getenv("MIN_SCORE", "0.75"))

        # Build one InstrumentedRagModel per provider (shared across healing variants)
        gemini_llm = get_llm("gemini")
        self._gemini_model = InstrumentedRagModel(
            llm=gemini_llm,
            PineconeAPIKey=PINECONE_API_KEY,
            NameSpaces=NameSpaces,
            Index_Name=INDEX_NAME,
            min_score=min_score,
        )

        ollama_available = bool(os.getenv("OLLAMA_BASE_URL"))
        if ollama_available:
            ollama_llm = get_llm("ollama")
            self._ollama_model = InstrumentedRagModel(
                llm=ollama_llm,
                PineconeAPIKey=PINECONE_API_KEY,
                NameSpaces=NameSpaces,
                Index_Name=INDEX_NAME,
                min_score=min_score,
            )
        else:
            self._ollama_model = None

        # Code analysis objects
        self._code_analyzer  = SecurityCodeAnalyzer(llm=gemini_llm)
        self._code_evaluator = CodeSecurityEvaluator(llm=self.eval_llm)

        # Map scenario → (rag_model, apply_healing)
        self._scenario_map: Dict[TestScenario, tuple] = {
            TestScenario.GEMINI_NO_HEAL: (self._gemini_model, False),
            TestScenario.GEMINI_HEAL:    (self._gemini_model, True),
            TestScenario.OLLAMA_NO_HEAL: (self._ollama_model, False),
            TestScenario.OLLAMA_HEAL:    (self._ollama_model, True),
        }

    # ------------------------------------------------------------------

    def _get_runner(self, scenario: TestScenario) -> Optional[ScenarioRunner]:
        model, healing = self._scenario_map[scenario]
        if model is None:
            return None  # Ollama not configured
        return ScenarioRunner(
            scenario=scenario,
            rag_model=model,
            eval_llm=self.eval_llm,
            apply_healing=healing,
        )

    def _run_single_query(
        self, bq: BenchmarkQuery, run_id: str
    ) -> QueryBenchmarkResult:
        """
        Retrieve context once, then run all enabled scenarios against it.
        Context is shared to isolate the LLM + healing as independent variables.
        """
        context = self._gemini_model._vector_data_retriever(query=bq.query)
        result = QueryBenchmarkResult(
            query_id=bq.id,
            query=bq.query,
            category=bq.category.value,
            run_id=run_id,
            timestamp=time.time(),
        )
        for scenario in self.scenarios:
            runner = self._get_runner(scenario)
            if runner is None:
                result.scenario_results[scenario.value] = ScenarioResult(
                    scenario=scenario.value,
                    query_id=bq.id,
                    response="",
                    timing={},
                    quality={},
                    healing_triggered=False,
                    error="Ollama not configured — set OLLAMA_BASE_URL to enable",
                )
                continue
            sr = runner.run(bq, context)
            result.scenario_results[scenario.value] = sr
        return result

    def _run_code_sample(
        self, sample: VulnerableCodeSample, run_id: str
    ) -> CodeBenchmarkResult:
        t0 = time.perf_counter()
        res = CodeBenchmarkResult(
            sample_id=sample.id,
            language=sample.language,
            known_cwes=sample.known_cwes,
            expected_severity=sample.expected_severity,
            run_id=run_id,
            timestamp=time.time(),
        )
        try:
            lang_enum = Language[sample.language.upper()]
            findings  = self._code_analyzer.analyze_code_static(sample.code, lang_enum)
            formatted = self._code_analyzer.format_findings_for_output(findings)
            res.total_findings = len(formatted)

            # Detection rate: fraction of known CWEs mentioned in findings
            all_text = " ".join(
                f"{f.get('category','')} {f.get('description','')}" for f in formatted
            ).lower()
            detected = [cwe for cwe in sample.known_cwes if cwe.lower() in all_text]
            res.detected_cwes   = detected
            res.detection_rate  = round(len(detected) / len(sample.known_cwes), 3)

            # Severity accuracy: does the highest-severity finding match expected?
            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
            if formatted:
                max_sev = max(formatted, key=lambda f: sev_order.get(f.get("severity","info"), 0))
                res.severity_correct = (max_sev.get("severity") == sample.expected_severity)

            # False positive heuristic: findings with severity < expected are FPs
            expected_rank = sev_order.get(sample.expected_severity, 0)
            res.false_positive_count = sum(
                1 for f in formatted
                if sev_order.get(f.get("severity","info"), 0) < expected_rank - 1
            )
        except Exception as exc:
            res.error = str(exc)
        res.analysis_ms = round((time.perf_counter() - t0) * 1_000, 2)
        return res

    def execute_full_run(
        self,
        run_id: Optional[str] = None,
    ) -> BenchmarkRun:
        """
        Execute the complete benchmark.  Results are streamed to disk after
        each query to guard against mid-run failures.

        Returns a BenchmarkRun dataclass with all results embedded.
        """
        run_id = run_id or str(uuid.uuid4())
        queries = [
            bq for bq in BENCHMARK_QUERY_BANK
            if self.query_ids is None or bq.id in self.query_ids
        ]
        run = BenchmarkRun(
            run_id=run_id,
            started_at=time.time(),
            completed_at=None,
            scenarios_enabled=[s.value for s in self.scenarios],
            total_queries=len(queries),
            config={
                "min_score":        float(os.getenv("MIN_SCORE", "0.75")),
                "ollama_available": self._ollama_model is not None,
                "gemini_model":     "gemini-2.5-flash",
                "ollama_model":     os.getenv("OLLAMA_MODEL", "llama3.1"),
                "evaluator_model":  "gemini-2.0-flash-lite-001",
            },
        )

        for bq in queries:
            qr = self._run_single_query(bq, run_id)
            run.query_results.append(asdict(qr))
            BenchmarkStore.stream_append(run_id, "query", asdict(qr))

        if self.run_code_bench:
            for sample in CODE_BENCHMARK_BANK:
                cr = self._run_code_sample(sample, run_id)
                run.code_results.append(asdict(cr))
                BenchmarkStore.stream_append(run_id, "code", asdict(cr))

        run.completed_at = time.time()
        run.status       = "completed"
        BenchmarkStore.save_run(run)
        return run

    def execute_single_query(
        self,
        query_id: str,
        run_id: Optional[str] = None,
    ) -> Optional[QueryBenchmarkResult]:
        """Run a single query from the bank for quick spot-testing."""
        bq = next((q for q in BENCHMARK_QUERY_BANK if q.id == query_id), None)
        if bq is None:
            return None
        return self._run_single_query(bq, run_id or str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Persistent benchmark store
# ---------------------------------------------------------------------------

class BenchmarkStore:
    """
    JSON-file store.  Each run is persisted in its own file:
        {BENCHMARK_RESULTS_DIR}/{run_id}.json

    Streaming appends are written to a staging file during execution to
    prevent data loss on failure.
    """

    @staticmethod
    def _path(run_id: str) -> str:
        return os.path.join(BENCHMARK_RESULTS_DIR, f"{run_id}.json")

    @staticmethod
    def _staging_path(run_id: str) -> str:
        return os.path.join(BENCHMARK_RESULTS_DIR, f"{run_id}_staging.jsonl")

    @staticmethod
    def save_run(run: BenchmarkRun) -> None:
        with open(BenchmarkStore._path(run.run_id), "w", encoding="utf-8") as fh:
            json.dump(asdict(run), fh, indent=2, default=str)
        # Clean up staging file
        sp = BenchmarkStore._staging_path(run.run_id)
        if os.path.exists(sp):
            os.remove(sp)

    @staticmethod
    def stream_append(run_id: str, kind: str, record: Dict) -> None:
        """Append a single result to the staging JSONL file."""
        with open(BenchmarkStore._staging_path(run_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "record": record}, default=str) + "\n")

    @staticmethod
    def load_run(run_id: str) -> Optional[Dict]:
        p = BenchmarkStore._path(run_id)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def list_runs() -> List[Dict]:
        """Return summary metadata for all completed runs."""
        runs = []
        for fname in os.listdir(BENCHMARK_RESULTS_DIR):
            if fname.endswith(".json") and not fname.endswith("_staging.json"):
                p = os.path.join(BENCHMARK_RESULTS_DIR, fname)
                try:
                    with open(p) as fh:
                        data = json.load(fh)
                    runs.append({
                        "run_id":           data.get("run_id"),
                        "started_at":       data.get("started_at"),
                        "completed_at":     data.get("completed_at"),
                        "status":           data.get("status"),
                        "total_queries":    data.get("total_queries"),
                        "scenarios_enabled": data.get("scenarios_enabled"),
                    })
                except Exception:
                    pass
        return sorted(runs, key=lambda r: r.get("started_at", 0), reverse=True)