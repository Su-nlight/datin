"""
app/routers/code_analysis.py

Same endpoints as Backend/API/code_analysis_router.py. Every
`request.app.state.code_analyzer` / `request.app.state.rag_model` /
`request.app.state.llm` lookup is replaced with a Depends() parameter —
no more reaching into app.state.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain.llms.base import LLM
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette import status

from app.dependencies import get_code_analysis_service, get_code_evaluator, get_generation_llm_dependency
from app.models.code_analysis_models import (
    CodeAnalysisRequest, CodeAnalysisResponse, CodeSecurityReport,
    CodeSecurityReportRequest, VulnerabilityRemediationRequest,
    VulnerabilityRemediationResponse,
)
from app.routers.auth import token_verifier
from app.services.code_analysis_service import Language, SecurityCodeAnalyzer
from app.services.evaluation_service import CodeSecurityEvaluator

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/code-analysis",
    tags=["code-analysis"],
    dependencies=[Depends(token_verifier)],
)


def _extract_section(text: str, section_name: str) -> str:
    pattern = f"{section_name}:?\\s*\\n?(.*?)(?=\\n[A-Z_]+:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


@router.post("/analyze", response_model=CodeAnalysisResponse)
@limiter.limit("20/minute")
async def analyze_code(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier),
    analyzer: SecurityCodeAnalyzer = Depends(get_code_analysis_service),
):
    try:
        if len(code_request.code) > 500000:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Code size exceeds 500KB limit")

        language = None
        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported language: {code_request.language}. Supported: python, cpp, java, javascript",
                )
        else:
            language = analyzer.detect_language(code_request.code)
            if not language:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not detect programming language. Please specify language explicitly.")

        logger.info(f"User {token_payload['username']} analyzing {language.value} code ({len(code_request.code)} bytes)")

        static_findings = analyzer.analyze_code_static(code_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)

        if code_request.severity_filter:
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            filter_level = severity_order.get(code_request.severity_filter, 999)
            formatted_findings = [f for f in formatted_findings if severity_order.get(f["severity"], 999) <= filter_level]

        rag_analysis = None
        if code_request.include_rag_analysis:
            rag_analysis = analyzer.analyze_code_with_rag(code_request.code, language, static_findings)

        severity_counts = {}
        for finding in formatted_findings:
            severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1

        summary_parts = [f"Found {len(formatted_findings)} vulnerabilities:"]
        for severity in ["critical", "high", "medium", "low", "info"]:
            if severity in severity_counts:
                summary_parts.append(f"  - {severity_counts[severity]} {severity}")

        return CodeAnalysisResponse(
            language=language.value, static_findings=formatted_findings,
            rag_analysis=rag_analysis, summary="\n".join(summary_parts),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code analysis error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error analyzing code: {str(e)}")


@router.post("/analyze-stream")
@limiter.limit("15/minute")
async def analyze_code_stream(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier),
    analyzer: SecurityCodeAnalyzer = Depends(get_code_analysis_service),
):
    try:
        if len(code_request.code) > 500000:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Code size exceeds 500KB limit")

        logger.info(f"User {token_payload['username']} streaming analysis")

        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Unsupported language {code_request.language}")
        else:
            language = analyzer.detect_language(code_request.code)

        async def stream_generator():
            try:
                for chunk in analyzer.analyze_stream(code_request.code, language):
                    yield chunk
            except Exception as e:
                yield f"Error: {str(e)}\n"

        return StreamingResponse(stream_generator(), media_type="text/plain")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Streaming analysis error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error during streaming: {str(e)}")


@router.post("/analyze-with-eval", response_model=CodeAnalysisResponse)
@limiter.limit("10/minute")
async def analyze_code_with_evaluation(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier),
    analyzer: SecurityCodeAnalyzer = Depends(get_code_analysis_service),
    evaluator: CodeSecurityEvaluator = Depends(get_code_evaluator),
):
    try:
        if len(code_request.code) > 500000:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Code size exceeds 500KB limit")

        logger.info(f"User {token_payload['username']} analyzing with evaluation")

        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {code_request.language}")
        else:
            language = analyzer.detect_language(code_request.code)
            if not language:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not detect programming language")

        static_findings = analyzer.analyze_code_static(code_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)

        rag_analysis = None
        if code_request.include_rag_analysis:
            rag_analysis = analyzer.analyze_code_with_rag(code_request.code, language, static_findings)

        evaluation_results = evaluator.run_full_evaluation(
            code_request.code, formatted_findings, rag_analysis or "No RAG analysis performed", language.value
        )

        severity_counts = {}
        for finding in formatted_findings:
            severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1

        summary_parts = [f"Found {len(formatted_findings)} vulnerabilities:"]
        for severity in ["critical", "high", "medium", "low", "info"]:
            if severity in severity_counts:
                summary_parts.append(f"  - {severity_counts[severity]} {severity}")
        if evaluation_results.get("overall_quality_score"):
            summary_parts.append(f"\nAnalysis Quality Score: {evaluation_results['overall_quality_score']:.2f}/1.0")

        return CodeAnalysisResponse(
            language=language.value, static_findings=formatted_findings,
            rag_analysis=rag_analysis, evaluation_results=evaluation_results,
            summary="\n".join(summary_parts),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code analysis with evaluation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error analyzing code: {str(e)}")


@router.post("/remediate", response_model=VulnerabilityRemediationResponse)
@limiter.limit("20/minute")
async def remediate_vulnerability(
    request: Request,
    remediation_request: VulnerabilityRemediationRequest,
    token_payload: dict = Depends(token_verifier),
    llm: LLM = Depends(get_generation_llm_dependency),
):
    try:
        if remediation_request.language.lower() not in ["python", "cpp", "java", "javascript"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported language")

        logger.info(f"User {token_payload['username']} requesting remediation for {remediation_request.vulnerability_type}")

        prompt = f"""
You are a security expert in {remediation_request.language}.
Provide a secure remediation for this vulnerability.

VULNERABILITY TYPE: {remediation_request.vulnerability_type}
LANGUAGE: {remediation_request.language}

VULNERABLE CODE:
```{remediation_request.language}
{remediation_request.code}
```

Provide:
1. Remediated code that fixes the vulnerability
2. Explanation of what was changed and why
3. 3-5 best practices for preventing this vulnerability
4. Reference the relevant CWE identifier

Format your response as:
REMEDIATED_CODE:
[code here]

EXPLANATION:
[explanation here]

BEST_PRACTICES:
1. [practice 1]
2. [practice 2]
...

CWE:
[CWE reference]
"""
        response_text = llm.predict(prompt)

        remediated_code = _extract_section(response_text, "REMEDIATED_CODE")
        explanation = _extract_section(response_text, "EXPLANATION")
        best_practices_text = _extract_section(response_text, "BEST_PRACTICES")
        cwe = _extract_section(response_text, "CWE")

        best_practices = [p.strip() for p in best_practices_text.split("\n") if p.strip() and not p[0].isdigit()]

        return VulnerabilityRemediationResponse(
            original_code=remediation_request.code, remediated_code=remediated_code,
            explanation=explanation, best_practices=best_practices, affected_cwe=cwe,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remediation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generating remediation: {str(e)}")


@router.post("/report", response_model=CodeSecurityReport)
@limiter.limit("10/minute")
async def generate_security_report(
    request: Request,
    report_request: CodeSecurityReportRequest,
    token_payload: dict = Depends(token_verifier),
    analyzer: SecurityCodeAnalyzer = Depends(get_code_analysis_service),
    llm: LLM = Depends(get_generation_llm_dependency),
):
    try:
        if len(report_request.code) > 500000:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Code size exceeds 500KB limit")

        logger.info(f"User {token_payload['username']} generating security report")

        try:
            language = Language[report_request.language.upper()]
        except KeyError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {report_request.language}")

        static_findings = analyzer.analyze_code_static(report_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)

        severity_counts = {s: 0 for s in ["critical", "high", "medium", "low", "info"]}
        for finding in formatted_findings:
            severity_counts[finding["severity"]] += 1

        risk_score = (
            severity_counts["critical"] * 10 + severity_counts["high"] * 7
            + severity_counts["medium"] * 4 + severity_counts["low"] * 1
        ) / (len(formatted_findings) if formatted_findings else 1)
        risk_score = min(10.0, risk_score)

        remediations = None
        if report_request.include_remediation and formatted_findings:
            remediation_prompt = f"""
Provide concise remediation guidance for these vulnerabilities in {report_request.language}:

FINDINGS:
{analyzer._summarize_findings(static_findings)}

CODE:
{report_request.code}

For each vulnerability, provide specific, actionable remediation steps.
"""
            remediations = llm.predict(remediation_prompt)

        threat_intelligence = None
        if report_request.include_threat_intelligence and formatted_findings and analyzer.rag_model:
            threat_intelligence = analyzer.rag_model._vector_data_retriever(
                f"Security vulnerabilities in {report_request.language}: {severity_counts}"
            )

        return CodeSecurityReport(
            language=report_request.language, findings_count=len(formatted_findings),
            critical_count=severity_counts["critical"], high_count=severity_counts["high"],
            medium_count=severity_counts["medium"], low_count=severity_counts["low"],
            findings=formatted_findings, remediations=remediations,
            threat_intelligence=threat_intelligence, overall_risk_score=risk_score,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generating report: {str(e)}")