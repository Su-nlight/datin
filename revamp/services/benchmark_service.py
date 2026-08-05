"""
app/services/benchmark_service.py

Same query bank, code bank, ScenarioRunner, and BenchmarkRunner logic as
Backend/API/testing_folder/benchmark_suite.py.

Two things fixed during migration, both flagged in the original file's
own docstring/behavior:
  1. Import style — the old docstring documented relative imports
     (`from ..evaluator import ...`) but the code actually used flat
     imports (`from evaluator import ...`). Everything here uses
     absolute `app.*` imports, matching every other file in this
     migration.
  2. Triple-duplicated settings lookup — PINECONE_API_KEY/INDEX_NAME/
     NAMESPACES/MIN_SCORE were independently re-read via os.getenv() in
     old main.py, ab_testing.py, AND benchmark_suite.py. BenchmarkRunner
     now takes a single `settings: Settings` instead.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.config import Settings, get_settings
from app.providers.llm_provider import get_evaluation_llm, get_generation_llm, get_llm, is_provider_ready
from app.providers.pinecone_provider import PineconeProvider
from app.services.ab_testing_service import InstrumentedRagModel, QualityScores
from app.services.code_analysis_service import Language, SecurityCodeAnalyzer
from app.services.evaluation_service import CodeSecurityEvaluator, EvaluationService

_HEAL_SUFFIX = "_heal"
_NO_HEAL_SUFFIX = "_no_heal"


class QueryCategory(str, Enum):
    APT_THREAT_ACTOR = "apt_threat_actor"
    MALWARE_ANALYSIS = "malware_analysis"
    CVE_EXPLOITATION = "cve_exploitation"
    SHELLCODE_PAYLOAD = "shellcode_payload"
    NETWORK_ATTACK = "network_attack"
    CRYPTOGRAPHIC_ATTACK = "cryptographic_attack"


def scenario_name(provider: str, healing: bool) -> str:
    """'groq' + True -> 'groq_heal'; 'groq' + False -> 'groq_no_heal'."""
    return f"{provider}{_HEAL_SUFFIX}" if healing else f"{provider}{_NO_HEAL_SUFFIX}"


def parse_scenario(scenario: str) -> tuple[str, bool]:
    """Inverse of scenario_name(). Suffix-matched (not split-on-'_') so it
    works regardless of the provider name's own formatting."""
    if scenario.endswith(_NO_HEAL_SUFFIX):
        return scenario[: -len(_NO_HEAL_SUFFIX)], False
    if scenario.endswith(_HEAL_SUFFIX):
        return scenario[: -len(_HEAL_SUFFIX)], True
    raise ValueError(f"Malformed scenario name: '{scenario}' (expected '<provider>_heal' or '<provider>_no_heal')")


def available_scenarios(settings: Settings) -> List[str]:
    """
    All scenario names that can be *requested* for a benchmark run, driven
    by Settings.BENCHMARK_PROVIDERS rather than a fixed gemini/ollama pair.
    This lists everything configured, not just what's currently reachable
    — a provider missing its API key still produces valid scenario names,
    it just resolves to an per-query error at run time (mirrors the old
    "Ollama not configured" behavior, generalized to any provider).
    """
    return [scenario_name(p, heal) for p in settings.benchmark_provider_list for heal in (False, True)]


@dataclass
class BenchmarkQuery:
    id: str
    query: str
    category: QueryCategory
    expected_keywords: List[str]


BENCHMARK_QUERY_BANK: List[BenchmarkQuery] = [
    BenchmarkQuery(id="APT-01", query="Describe the initial access and lateral movement techniques used by APT28 (Fancy Bear) against NATO member states, including specific MITRE ATT&CK technique IDs.", category=QueryCategory.APT_THREAT_ACTOR, expected_keywords=["APT28", "spearphishing", "T1566", "lateral movement", "credential"]),
    BenchmarkQuery(id="APT-02", query="What are the command and control infrastructure patterns and communication protocols attributed to the Lazarus Group in their financial sector attacks?", category=QueryCategory.APT_THREAT_ACTOR, expected_keywords=["Lazarus", "C2", "DPRK", "SWIFT", "beaconing"]),
    BenchmarkQuery(id="APT-03", query="How does APT41 combine nation-state espionage operations with financially motivated cybercrime, and what TTPs distinguish these two operational modes?", category=QueryCategory.APT_THREAT_ACTOR, expected_keywords=["APT41", "espionage", "ransomware", "supply chain", "China"]),
    BenchmarkQuery(id="APT-04", query="Explain the supply chain attack methodology used in the SolarWinds SUNBURST campaign, including the build-system compromise and TEARDROP payload delivery mechanism.", category=QueryCategory.APT_THREAT_ACTOR, expected_keywords=["SolarWinds", "SUNBURST", "Orion", "build system", "DGA"]),
    BenchmarkQuery(id="MAL-01", query="Describe the persistence mechanisms, propagation method via EternalBlue, and kill-switch domain mechanism of WannaCry ransomware.", category=QueryCategory.MALWARE_ANALYSIS, expected_keywords=["WannaCry", "EternalBlue", "kill switch", "SMB", "MBR"]),
    BenchmarkQuery(id="MAL-02", query="How does Emotet achieve lateral movement using pass-the-hash and credential dumping, and what network-based indicators of compromise should SOC teams monitor?", category=QueryCategory.MALWARE_ANALYSIS, expected_keywords=["Emotet", "pass-the-hash", "credential", "network", "IOC"]),
    BenchmarkQuery(id="MAL-03", query="What kernel-level rootkit techniques does the Necurs botnet employ for self-preservation, and how can these be detected using memory forensics?", category=QueryCategory.MALWARE_ANALYSIS, expected_keywords=["Necurs", "rootkit", "kernel", "DKOM", "memory forensics"]),
    BenchmarkQuery(id="MAL-04", query="Explain the EDR evasion techniques used by TrickBot, specifically its use of process injection and anti-analysis mechanisms including timing-based sandbox detection.", category=QueryCategory.MALWARE_ANALYSIS, expected_keywords=["TrickBot", "EDR", "process injection", "sandbox", "evasion"]),
    BenchmarkQuery(id="CVE-01", query="Explain the full exploitation chain of CVE-2021-44228 Log4Shell, including the JNDI lookup injection vector, LDAP callback mechanism, and RCE payload delivery.", category=QueryCategory.CVE_EXPLOITATION, expected_keywords=["Log4Shell", "JNDI", "LDAP", "RCE", "Java"]),
    BenchmarkQuery(id="CVE-02", query="Describe how CVE-2017-0144 EternalBlue exploits the SMBv1 Transaction2 request handling vulnerability to achieve remote code execution without authentication.", category=QueryCategory.CVE_EXPLOITATION, expected_keywords=["EternalBlue", "SMBv1", "buffer overflow", "RCE", "NSA"]),
    BenchmarkQuery(id="CVE-03", query="What is the complete attack chain for CVE-2021-26855 ProxyLogon in Microsoft Exchange, including SSRF pre-auth, credential theft, and web shell deployment?", category=QueryCategory.CVE_EXPLOITATION, expected_keywords=["ProxyLogon", "SSRF", "Exchange", "web shell", "authentication bypass"]),
    BenchmarkQuery(id="CVE-04", query="Explain the heap spray and pool grooming technique used in CVE-2020-0796 SMBGhost to achieve kernel-level code execution from an unauthenticated remote attacker.", category=QueryCategory.CVE_EXPLOITATION, expected_keywords=["SMBGhost", "heap spray", "kernel", "SMBv3", "pool grooming"]),
    BenchmarkQuery(id="SHC-01", query="Describe the egg hunting shellcode technique for dynamically locating a second-stage payload in memory when the initial buffer is too small for full shellcode.", category=QueryCategory.SHELLCODE_PAYLOAD, expected_keywords=["egg hunter", "SEH", "memory", "NtAccessCheckAndAuditAlarm", "tag"]),
    BenchmarkQuery(id="SHC-02", query="How does polymorphic shellcode use XOR encryption and instruction substitution to evade signature-based antivirus detection while maintaining functional equivalence?", category=QueryCategory.SHELLCODE_PAYLOAD, expected_keywords=["polymorphic", "XOR", "encoder", "NOP sled", "signature evasion"]),
    BenchmarkQuery(id="SHC-03", query="Explain the process hollowing technique, including how it unmaps a legitimate process, injects a malicious payload, and resumes execution to evade process-based detection.", category=QueryCategory.SHELLCODE_PAYLOAD, expected_keywords=["process hollowing", "NtUnmapViewOfSection", "injection", "CreateProcess", "SUSPENDED"]),
    BenchmarkQuery(id="NET-01", query="Describe the LLMNR and NBT-NS poisoning attack chain for capturing NTLMv2 hashes on a Windows network, including the Responder tool mechanism and offline cracking methodology.", category=QueryCategory.NETWORK_ATTACK, expected_keywords=["LLMNR", "NBT-NS", "Responder", "NTLMv2", "hash capture"]),
    BenchmarkQuery(id="NET-02", query="How does a Kerberoasting attack extract service principal name tickets from Active Directory and what offline cracking techniques are used against RC4-encrypted TGS tickets?", category=QueryCategory.NETWORK_ATTACK, expected_keywords=["Kerberoasting", "SPN", "TGS", "RC4", "hashcat"]),
    BenchmarkQuery(id="NET-03", query="Explain the VLAN hopping attack using double 802.1Q tagging, the conditions required on a misconfigured trunk port, and the detection mechanism using VLAN ACLs.", category=QueryCategory.NETWORK_ATTACK, expected_keywords=["VLAN hopping", "802.1Q", "double tagging", "trunk port", "DTP"]),
    BenchmarkQuery(id="CRY-01", query="Describe the BEAST attack against TLS 1.0 using CBC mode block cipher chaining, including the chosen-plaintext attack methodology and how the IV reuse creates the vulnerability.", category=QueryCategory.CRYPTOGRAPHIC_ATTACK, expected_keywords=["BEAST", "TLS 1.0", "CBC", "IV", "chosen-plaintext"]),
    BenchmarkQuery(id="CRY-02", query="Explain how padding oracle attacks against AES-CBC leverage error responses to decrypt ciphertext byte-by-byte without the encryption key.", category=QueryCategory.CRYPTOGRAPHIC_ATTACK, expected_keywords=["padding oracle", "AES-CBC", "PKCS7", "oracle", "ciphertext"]),
]


@dataclass
class VulnerableCodeSample:
    id: str
    language: str
    code: str
    known_cwes: List[str]
    expected_severity: str
    description: str


CODE_BENCHMARK_BANK: List[VulnerableCodeSample] = [
    VulnerableCodeSample(id="CODE-01", language="python", code="""
import sqlite3
def get_user(user_id, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return cursor.execute(query).fetchall()
""", known_cwes=["CWE-89"], expected_severity="critical", description="SQL injection via f-string interpolation"),
    VulnerableCodeSample(id="CODE-02", language="python", code="""
import os, subprocess
def run_scan(target_ip):
    os.system(f"nmap -sV {target_ip}")
    subprocess.call(f"ping {target_ip}", shell=True)
""", known_cwes=["CWE-78"], expected_severity="critical", description="OS command injection via unsanitized shell interpolation"),
    VulnerableCodeSample(id="CODE-03", language="javascript", code="""
const express = require('express');
const app = express();
app.get('/search', (req, res) => {
    const term = req.query.q;
    res.send(`<h1>Results for: ${term}</h1>`);
});
""", known_cwes=["CWE-79"], expected_severity="high", description="Reflected XSS via unescaped query parameter"),
    VulnerableCodeSample(id="CODE-04", language="cpp", code="""
#include <cstring>
#include <stdio.h>
void process_packet(const char* payload) {
    char buffer[64];
    strcpy(buffer, payload);
    printf("Processed: %s\\n", buffer);
}
""", known_cwes=["CWE-120", "CWE-787"], expected_severity="critical", description="Stack buffer overflow via unbounded strcpy"),
    VulnerableCodeSample(id="CODE-05", language="java", code="""
public class DatabaseConfig {
    private static final String DB_HOST = "prod-db.internal";
    private static final String DB_USER = "admin";
    private static final String DB_PASS = "Sup3rS3cr3t!2024";
    public static Connection getConnection() throws SQLException {
        return DriverManager.getConnection(DB_HOST, DB_USER, DB_PASS);
    }
}
""", known_cwes=["CWE-798", "CWE-259"], expected_severity="high", description="Hardcoded credentials in source code"),
    VulnerableCodeSample(id="CODE-06", language="python", code="""
import pickle, base64
from flask import Flask, request
app = Flask(__name__)
@app.route('/restore')
def restore_session():
    data = base64.b64decode(request.cookies.get('session'))
    return str(pickle.loads(data))
""", known_cwes=["CWE-502"], expected_severity="critical", description="Insecure deserialization of user-controlled pickle data"),
]


@dataclass
class ScenarioResult:
    scenario: str
    query_id: str
    response: str
    timing: Dict[str, float]
    quality: Dict[str, Any]
    healing_triggered: bool
    keyword_recall: float = 0.0
    error: Optional[str] = None
    evaluation_error: Optional[str] = None  # set only if the judge failed; response/error stay untouched
    healing_error: Optional[str] = None
    generation_provider: str = ""  # filled per-scenario in ScenarioRunner.run(), e.g. "gemini" or "ollama"
    evaluation_provider: str = field(default_factory=lambda: get_settings().EVALUATION_LLM_PROVIDER)


@dataclass
class QueryBenchmarkResult:
    query_id: str
    query: str
    category: str
    run_id: str
    timestamp: float
    scenario_results: Dict[str, ScenarioResult] = field(default_factory=dict)


@dataclass
class CodeBenchmarkResult:
    sample_id: str
    language: str
    known_cwes: List[str]
    expected_severity: str
    run_id: str
    timestamp: float
    detected_cwes: List[str] = field(default_factory=list)
    detection_rate: float = 0.0
    severity_correct: bool = False
    false_positive_count: int = 0
    total_findings: int = 0
    analysis_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class BenchmarkRun:
    run_id: str
    started_at: float
    completed_at: Optional[float]
    scenarios_enabled: List[str]
    total_queries: int
    status: str = "running"
    query_results: List[Dict] = field(default_factory=list)
    code_results: List[Dict] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


def _keyword_recall(response: str, expected: List[str]) -> float:
    if not expected:
        return 1.0
    resp_lower = response.lower()
    found = sum(1 for kw in expected if kw.lower() in resp_lower)
    return round(found / len(expected), 3)


class ScenarioRunner:
    def __init__(self, scenario: str, rag_model: InstrumentedRagModel, eval_service: EvaluationService, apply_healing: bool):
        self.scenario = scenario
        self.rag_model = rag_model
        self.eval_service = eval_service
        self.apply_healing = apply_healing

    def run(self, bq: BenchmarkQuery, context: str) -> ScenarioResult:
        t0 = time.perf_counter()
        error: Optional[str] = None
        evaluation_error: Optional[str] = None
        healing_error: Optional[str] = None
        response = ""
        quality: Dict[str, Any] = {}
        timing: Dict[str, float] = {}
        healing_triggered = False
        gen_ms = 0.0
        eval_ms = 0.0
        heal_ms = 0.0
        rate_limited_ms = 0.0  # time spent sleeping out 429s — excluded from gen/eval/heal above, kept separately
        # Scenario names are "<provider>_no_heal" / "<provider>_heal" — the
        # provider prefix tells us which backend actually generated this run.
        generation_provider, _ = parse_scenario(self.scenario)
        gen_llm = self.rag_model.llm
        eval_llm = self.eval_service.llm

        def wait_s(llm) -> float:
            # Only GroqLLM currently tracks this; any other provider is
            # simply 0 via getattr's default, so this is safe everywhere.
            return getattr(llm, "rate_limit_wait_s", 0.0)

        try:
            prompt = self.rag_model._build_rag_prompt(bq.query, context, history=[])

            t_g = time.perf_counter()
            w0 = wait_s(gen_llm)
            response = self.rag_model.llm.predict(prompt)
            gen_wait_ms = (wait_s(gen_llm) - w0) * 1_000
            gen_ms = (time.perf_counter() - t_g) * 1_000 - gen_wait_ms
            rate_limited_ms += gen_wait_ms

            # Evaluation (+ healing) is wrapped in its own try/except: a judge
            # failure (e.g. a 429 from the evaluation provider) must not
            # discard the response we already generated successfully above.
            try:
                t_e = time.perf_counter()
                w0 = wait_s(eval_llm)
                eval_res = self.eval_service.evaluate_rag_parameters(
                    inputs={"question": bq.query}, outputs={"answer": response},
                    context={"documents": [s.strip() for s in context.split("---")]},
                )
                eval_wait_ms = (wait_s(eval_llm) - w0) * 1_000
                eval_ms = (time.perf_counter() - t_e) * 1_000 - eval_wait_ms
                rate_limited_ms += eval_wait_ms

                if self.apply_healing:
                    healing = self.eval_service.eval_reflection(eval_res)
                    healing_triggered = healing["Healing_required"]
                    t_h = time.perf_counter()
                    heal_wait_ms = 0.0
                    if healing_triggered:
                        w0 = wait_s(gen_llm)
                        response = self.rag_model.llm.predict(
                            f'For the AI generated response: "{response}".\n'
                            f'{healing["Healing_Prompt"]}\n'
                            "Correct the answer per healing instructions."
                        )
                        heal_wait_ms += (wait_s(gen_llm) - w0) * 1_000
                        # Re-evaluate healed output — also isolated, so a
                        # failure here still leaves the healed `response` and
                        # the pre-heal quality scores intact.
                        try:
                            t_re = time.perf_counter()
                            w0 = wait_s(eval_llm)
                            eval_res = self.eval_service.evaluate_rag_parameters(
                                inputs={"question": bq.query}, outputs={"answer": response},
                                context={"documents": [s.strip() for s in context.split("---")]},
                            )
                            reeval_wait_ms = (wait_s(eval_llm) - w0) * 1_000
                            eval_ms += (time.perf_counter() - t_re) * 1_000 - reeval_wait_ms
                            rate_limited_ms += reeval_wait_ms
                            heal_wait_ms += reeval_wait_ms
                        except Exception as reeval_exc:
                            evaluation_error = f"re_evaluation_error: {reeval_exc}"
                    heal_ms = (time.perf_counter() - t_h) * 1_000 - heal_wait_ms

                qs = QualityScores.from_evaluation(eval_res)
                quality = {
                    "correctness": qs.correctness, "helpfulness": qs.helpfulness,
                    "groundedness": qs.groundedness, "retrieval_relevance": qs.retrieval_relevance,
                    "overall_score": qs.overall_score,
                }
            except Exception as eval_exc:
                evaluation_error = f"evaluation_error: {eval_exc}"

            timing = {
                "generation_ms": round(max(gen_ms, 0.0), 2), "evaluation_ms": round(max(eval_ms, 0.0), 2),
                "healing_ms": round(max(heal_ms, 0.0), 2), "total_ms": round((time.perf_counter() - t0) * 1_000, 2),
                "rate_limited_ms": round(rate_limited_ms, 2),
            }
        except Exception as exc:
            # Generation itself failed — this is the only case that marks
            # the whole scenario as failed.
            error = str(exc)
            timing = {"total_ms": round((time.perf_counter() - t0) * 1_000, 2)}

        return ScenarioResult(
            scenario=self.scenario, query_id=bq.id, response=response, timing=timing,
            quality=quality, healing_triggered=healing_triggered,
            keyword_recall=_keyword_recall(response, bq.expected_keywords), error=error,
            evaluation_error=evaluation_error, generation_provider=generation_provider,
        )


class BenchmarkRunner:
    """
    Orchestrates the full benchmark run. `settings` is now injected once
    instead of being independently re-read via os.getenv() (previously
    duplicated across old main.py, ab_testing.py, and this file).
    """

    def __init__(
        self,
        settings: Settings,
        scenarios: Optional[List[str]] = None,
        query_ids: Optional[List[str]] = None,
        run_code_bench: bool = True,
    ):
        self.settings = settings
        self.query_ids = set(query_ids) if query_ids else None
        self.run_code_bench = run_code_bench

        self.results_dir = settings.BENCHMARK_RESULTS_DIR
        os.makedirs(self.results_dir, exist_ok=True)
        self.store = BenchmarkStore(results_dir=self.results_dir)

        eval_llm = get_evaluation_llm(settings)
        self.eval_llm = eval_llm
        self.eval_service = EvaluationService(evaluator_llm=eval_llm)

        pinecone = PineconeProvider(settings=settings, index_name=settings.INDEX_NAME)

        # Build one InstrumentedRagModel per provider listed in
        # Settings.BENCHMARK_PROVIDERS that's actually ready to be called
        # (has its API key / base URL set) — replaces the old fixed
        # gemini+ollama pair. A provider that's listed but not ready is
        # recorded in self._unavailable instead of raising, so a run can
        # still proceed with whatever *is* ready (mirrors the old "Ollama
        # not configured" skip behavior, generalized to any provider).
        self._models: Dict[str, InstrumentedRagModel] = {}
        self._unavailable: Dict[str, str] = {}
        for provider in settings.benchmark_provider_list:
            if not is_provider_ready(settings, provider):
                self._unavailable[provider] = f"'{provider}' is not configured (missing API key / base URL)"
                continue
            try:
                llm = get_llm(settings, provider=provider)
            except Exception as exc:
                self._unavailable[provider] = str(exc)
                continue
            self._models[provider] = InstrumentedRagModel(
                llm=llm, pinecone=pinecone,
                namespaces=settings.namespace_list, min_score=settings.MIN_SCORE,
                evaluation_service=self.eval_service, eval_llm=eval_llm,
            )

        if not self._models:
            raise ValueError(
                "No benchmark generation providers are ready. Configure at least one of "
                f"BENCHMARK_PROVIDERS={settings.BENCHMARK_PROVIDERS!r} "
                f"(unavailable: {self._unavailable})."
            )

        self.scenarios: List[str] = (
            scenarios if scenarios is not None
            else [scenario_name(p, heal) for p in self._models for heal in (False, True)]
        )

        # Code-vulnerability benchmark now follows GENERATION_LLM_PROVIDER —
        # reuse that provider's already-built model if it's one of the
        # benchmark providers, otherwise resolve it directly so the code
        # benchmark still reflects the app's actual generation LLM even if
        # it isn't part of this particular comparison run.
        gen_provider = settings.GENERATION_LLM_PROVIDER.lower()
        code_llm = self._models[gen_provider].llm if gen_provider in self._models else get_generation_llm(settings)
        self._code_analyzer = SecurityCodeAnalyzer(llm=code_llm)
        self._code_evaluator = CodeSecurityEvaluator(llm=eval_llm)

        # Retrieval is provider-agnostic (pure pinecone lookup, doesn't
        # touch .llm) — any ready model can serve as the retriever.
        self._retriever_model = next(iter(self._models.values()))

    def _get_runner(self, scenario: str) -> Optional[ScenarioRunner]:
        provider, healing = parse_scenario(scenario)
        model = self._models.get(provider)
        if model is None:
            return None
        return ScenarioRunner(scenario=scenario, rag_model=model, eval_service=self.eval_service, apply_healing=healing)

    def _run_single_query(self, bq: BenchmarkQuery, run_id: str) -> QueryBenchmarkResult:
        context = self._retriever_model._vector_data_retriever(query=bq.query)
        result = QueryBenchmarkResult(query_id=bq.id, query=bq.query, category=bq.category.value, run_id=run_id, timestamp=time.time())
        for scenario in self.scenarios:
            runner = self._get_runner(scenario)
            if runner is None:
                provider, _ = parse_scenario(scenario)
                reason = self._unavailable.get(provider, f"Provider '{provider}' is not part of this benchmark run")
                result.scenario_results[scenario] = ScenarioResult(
                    scenario=scenario, query_id=bq.id, response="", timing={}, quality={},
                    healing_triggered=False, error=reason,
                )
                continue
            result.scenario_results[scenario] = runner.run(bq, context)
        return result

    def _run_code_sample(self, sample: VulnerableCodeSample, run_id: str) -> CodeBenchmarkResult:
        t0 = time.perf_counter()
        res = CodeBenchmarkResult(
            sample_id=sample.id, language=sample.language, known_cwes=sample.known_cwes,
            expected_severity=sample.expected_severity, run_id=run_id, timestamp=time.time(),
        )
        try:
            lang_enum = Language[sample.language.upper()]
            findings = self._code_analyzer.analyze_code_static(sample.code, lang_enum)
            formatted = self._code_analyzer.format_findings_for_output(findings)
            res.total_findings = len(formatted)

            all_text = " ".join(f"{f.get('category','')} {f.get('description','')}" for f in formatted).lower()
            detected = [cwe for cwe in sample.known_cwes if cwe.lower() in all_text]
            res.detected_cwes = detected
            res.detection_rate = round(len(detected) / len(sample.known_cwes), 3)

            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
            if formatted:
                max_sev = max(formatted, key=lambda f: sev_order.get(f.get("severity", "info"), 0))
                res.severity_correct = max_sev.get("severity") == sample.expected_severity

            expected_rank = sev_order.get(sample.expected_severity, 0)
            res.false_positive_count = sum(1 for f in formatted if sev_order.get(f.get("severity", "info"), 0) < expected_rank - 1)
        except Exception as exc:
            res.error = str(exc)
        res.analysis_ms = round((time.perf_counter() - t0) * 1_000, 2)
        return res

    def execute_full_run(self, run_id: Optional[str] = None) -> BenchmarkRun:
        run_id = run_id or str(uuid.uuid4())
        queries = [bq for bq in BENCHMARK_QUERY_BANK if self.query_ids is None or bq.id in self.query_ids]
        run = BenchmarkRun(
            run_id=run_id, started_at=time.time(), completed_at=None,
            scenarios_enabled=list(self.scenarios), total_queries=len(queries),
            config={
                "min_score": self.settings.MIN_SCORE,
                "providers_available": list(self._models.keys()),
                "providers_unavailable": dict(self._unavailable),
                # Read straight off the instantiated LLM objects — every
                # provider class (GeminiLLM/OllamaLLM/GrokLLM/GroqLLM) has a
                # model_name field, so this can never drift from what was
                # actually called, unlike the old hardcoded strings.
                "generation_models": {p: m.llm.model_name for p, m in self._models.items()},
                "evaluator_provider": self.settings.EVALUATION_LLM_PROVIDER,
                "evaluator_model": self.eval_llm.model_name,
                "code_analysis_provider": self.settings.GENERATION_LLM_PROVIDER,
                "code_analysis_model": self._code_analyzer.llm.model_name,
            },
        )

        for bq in queries:
            qr = self._run_single_query(bq, run_id)
            run.query_results.append(asdict(qr))
            self.store.stream_append(run_id, "query", asdict(qr))

        if self.run_code_bench:
            for sample in CODE_BENCHMARK_BANK:
                cr = self._run_code_sample(sample, run_id)
                run.code_results.append(asdict(cr))
                self.store.stream_append(run_id, "code", asdict(cr))

        run.completed_at = time.time()
        run.status = "completed"
        self.store.save_run(run)
        return run

    def execute_single_query(self, query_id: str, run_id: Optional[str] = None) -> Optional[QueryBenchmarkResult]:
        bq = next((q for q in BENCHMARK_QUERY_BANK if q.id == query_id), None)
        if bq is None:
            return None
        return self._run_single_query(bq, run_id or str(uuid.uuid4()))


class BenchmarkStore:
    """JSON-file store; results_dir now comes from Settings.BENCHMARK_RESULTS_DIR."""

    def __init__(self, results_dir: str):
        self.results_dir = results_dir

    def _path(self, run_id: str) -> str:
        return os.path.join(self.results_dir, f"{run_id}.json")

    def _staging_path(self, run_id: str) -> str:
        return os.path.join(self.results_dir, f"{run_id}_staging.jsonl")

    def save_run(self, run: BenchmarkRun) -> None:
        with open(self._path(run.run_id), "w", encoding="utf-8") as fh:
            json.dump(asdict(run), fh, indent=2, default=str)
        sp = self._staging_path(run.run_id)
        if os.path.exists(sp):
            os.remove(sp)

    def stream_append(self, run_id: str, kind: str, record: Dict) -> None:
        with open(self._staging_path(run_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "record": record}, default=str) + "\n")

    def load_run(self, run_id: str) -> Optional[Dict]:
        p = self._path(run_id)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_runs(self) -> List[Dict]:
        runs = []
        for fname in os.listdir(self.results_dir):
            if fname.endswith(".json") and not fname.endswith("_staging.json"):
                p = os.path.join(self.results_dir, fname)
                try:
                    with open(p) as fh:
                        data = json.load(fh)
                    runs.append({
                        "run_id": data.get("run_id"), "started_at": data.get("started_at"),
                        "completed_at": data.get("completed_at"), "status": data.get("status"),
                        "total_queries": data.get("total_queries"), "scenarios_enabled": data.get("scenarios_enabled"),
                    })
                except Exception:
                    pass
        return sorted(runs, key=lambda r: r.get("started_at", 0), reverse=True)