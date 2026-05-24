"""
Code Analysis Router
All code analysis endpoints - follows auth.py router pattern.
Import this router and add to main.py with app.include_router()
"""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette import status
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import StreamingResponse

from models import (
    CodeAnalysisRequest, CodeAnalysisResponse,
    CodeSecurityReport, CodeSecurityReportRequest,
    VulnerabilityRemediationRequest, VulnerabilityRemediationResponse
)
from auth import token_verifier
from code_analyzer import SecurityCodeAnalyzer, Language
from code_evaluator import CodeSecurityEvaluator

logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create router with auth dependency
router = APIRouter(
    prefix='/code-analysis',
    tags=['code-analysis'],
    dependencies=[Depends(token_verifier)]  # All routes require JWT
)


def _extract_section(text: str, section_name: str) -> str:
    """Extract a section from LLM response"""
    pattern = f"{section_name}:?\s*\n?(.*?)(?=\n[A-Z_]+:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


# ==================== Endpoints ====================

@router.post("/analyze", response_model=CodeAnalysisResponse)
@limiter.limit("20/minute")
async def analyze_code(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier)
):
    """
    Analyze code for security vulnerabilities.
    
    Supports: Python, C++, Java, JavaScript
    Returns: Static findings + optional RAG-based threat intelligence
    
    **Rate limit**: 20 requests per minute per IP
    """
    try:
        # Validate code size
        if len(code_request.code) > 500000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Code size exceeds 500KB limit"
            )
        
        # Get analyzer from app state (initialized in main.py lifespan)
        analyzer: SecurityCodeAnalyzer = request.app.state.code_analyzer
        
        # Detect or validate language
        language = None
        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported language: {code_request.language}. "
                           f"Supported: python, cpp, java, javascript"
                )
        else:
            language = analyzer.detect_language(code_request.code)
            if not language:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not detect programming language. "
                           "Please specify language explicitly."
                )
        
        logger.info(
            f"User {token_payload['username']} analyzing {language.value} code "
            f"({len(code_request.code)} bytes)"
        )
        
        # Run static analysis
        static_findings = analyzer.analyze_code_static(code_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)
        
        # Filter by severity if requested
        if code_request.severity_filter:
            severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
            filter_level = severity_order.get(code_request.severity_filter, 999)
            formatted_findings = [
                f for f in formatted_findings 
                if severity_order.get(f['severity'], 999) <= filter_level
            ]
        
        # RAG-based analysis (optional)
        rag_analysis = None
        if code_request.include_rag_analysis:
            rag_analysis = analyzer.analyze_code_with_rag(
                code_request.code, language, static_findings
            )
        
        # Generate summary
        severity_counts = {}
        for finding in formatted_findings:
            severity = finding['severity']
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        summary_parts = [f"Found {len(formatted_findings)} vulnerabilities:"]
        for severity in ['critical', 'high', 'medium', 'low', 'info']:
            if severity in severity_counts:
                summary_parts.append(f"  - {severity_counts[severity]} {severity}")
        summary = '\n'.join(summary_parts)
        
        return CodeAnalysisResponse(
            language=language.value,
            static_findings=formatted_findings,
            rag_analysis=rag_analysis,
            summary=summary
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code analysis error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error analyzing code: {str(e)}"
        )


@router.post("/analyze-stream")
@limiter.limit("15/minute")
async def analyze_code_stream(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier)
):
    try:
        if len(code_request.code) > 500000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Code size exceeds 500KB limit"
            )

        analyzer: SecurityCodeAnalyzer = request.app.state.code_analyzer
        logger.info(f"User {token_payload['username']} streaming analysis")

        # Detect or validate language
        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported language {code_request.language}"
                )
        else:
            language = analyzer.detect_language(code_request.code)

        # Stream analysis results
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during streaming: {str(e)}"
        )

@router.post("/analyze-with-eval", response_model=CodeAnalysisResponse)
@limiter.limit("10/minute")
async def analyze_code_with_evaluation(
    request: Request,
    code_request: CodeAnalysisRequest,
    token_payload: dict = Depends(token_verifier)
):
    """
    Analyze code and evaluate analysis quality.
    
    Evaluation metrics:
    - False positive detection
    - Remediation quality
    - Completeness of findings
    - Severity accuracy
    - CWE/MITRE references
    
    **Note**: Takes longer (~5-10s extra)
    **Rate limit**: 10 requests per minute per IP
    """
    try:
        if len(code_request.code) > 500000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Code size exceeds 500KB limit"
            )
        
        analyzer: SecurityCodeAnalyzer = request.app.state.code_analyzer
        evaluator: CodeSecurityEvaluator = request.app.state.code_evaluator
        logger.info(f"User {token_payload['username']} analyzing with evaluation")
        
        # Detect or validate language
        language = None
        if code_request.language:
            try:
                language = Language[code_request.language.upper()]
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported language: {code_request.language}"
                )
        else:
            language = analyzer.detect_language(code_request.code)
            if not language:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not detect programming language"
                )
        
        # Static analysis
        static_findings = analyzer.analyze_code_static(code_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)
        
        # RAG analysis
        rag_analysis = None
        if code_request.include_rag_analysis:
            rag_analysis = analyzer.analyze_code_with_rag(
                code_request.code, language, static_findings
            )
        
        # Evaluate results
        evaluation_results = evaluator.run_full_evaluation(
            code_request.code,
            formatted_findings,
            rag_analysis or "No RAG analysis performed",
            language.value
        )
        
        # Generate summary with quality score
        severity_counts = {}
        for finding in formatted_findings:
            severity_counts[finding['severity']] = severity_counts.get(finding['severity'], 0) + 1
        
        summary_parts = [f"Found {len(formatted_findings)} vulnerabilities:"]
        for severity in ['critical', 'high', 'medium', 'low', 'info']:
            if severity in severity_counts:
                summary_parts.append(f"  - {severity_counts[severity]} {severity}")
        
        if evaluation_results.get("overall_quality_score"):
            score = evaluation_results['overall_quality_score']
            summary_parts.append(f"\nAnalysis Quality Score: {score:.2f}/1.0")
        
        summary = '\n'.join(summary_parts)
        
        return CodeAnalysisResponse(
            language=language.value,
            static_findings=formatted_findings,
            rag_analysis=rag_analysis,
            evaluation_results=evaluation_results,
            summary=summary
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code analysis with evaluation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error analyzing code: {str(e)}"
        )


@router.post("/remediate", response_model=VulnerabilityRemediationResponse)
@limiter.limit("20/minute")
async def remediate_vulnerability(
    request: Request,
    remediation_request: VulnerabilityRemediationRequest,
    token_payload: dict = Depends(token_verifier)
):
    """
    Get remediation for a vulnerability.
    
    Provides:
    - Fixed code example
    - Explanation of changes
    - Best practices
    - CWE reference
    
    **Rate limit**: 20 requests per minute per IP
    """
    try:
        if remediation_request.language.lower() not in ['python', 'cpp', 'java', 'javascript']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported language"
            )
        
        llm = request.app.state.llm
        logger.info(
            f"User {token_payload['username']} requesting remediation for "
            f"{remediation_request.vulnerability_type}"
        )
        
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
        
        # Parse response
        remediated_code = _extract_section(response_text, "REMEDIATED_CODE")
        explanation = _extract_section(response_text, "EXPLANATION")
        best_practices_text = _extract_section(response_text, "BEST_PRACTICES")
        cwe = _extract_section(response_text, "CWE")
        
        best_practices = [
            p.strip() for p in best_practices_text.split('\n')
            if p.strip() and not p[0].isdigit()
        ]
        
        return VulnerabilityRemediationResponse(
            original_code=remediation_request.code,
            remediated_code=remediated_code,
            explanation=explanation,
            best_practices=best_practices,
            affected_cwe=cwe
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remediation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating remediation: {str(e)}"
        )


@router.post("/report", response_model=CodeSecurityReport)
@limiter.limit("10/minute")
async def generate_security_report(
    request: Request,
    report_request: CodeSecurityReportRequest,
    token_payload: dict = Depends(token_verifier)
):
    """
    Generate comprehensive security report.
    
    Includes:
    - All findings by severity
    - Remediation guidance (optional)
    - Threat intelligence context (optional)
    - Overall risk score (0-10)
    
    **Rate limit**: 10 requests per minute per IP
    """
    try:
        if len(report_request.code) > 500000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Code size exceeds 500KB limit"
            )
        
        analyzer: SecurityCodeAnalyzer = request.app.state.code_analyzer
        llm = request.app.state.llm
        logger.info(f"User {token_payload['username']} generating security report")
        
        # Validate language
        try:
            language = Language[report_request.language.upper()]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported language: {report_request.language}"
            )
        
        # Static analysis
        static_findings = analyzer.analyze_code_static(report_request.code, language)
        formatted_findings = analyzer.format_findings_for_output(static_findings)
        
        # Count by severity
        severity_counts = {s: 0 for s in ['critical', 'high', 'medium', 'low', 'info']}
        for finding in formatted_findings:
            severity_counts[finding['severity']] += 1
        
        # Calculate risk score (0-10)
        risk_score = (
            severity_counts['critical'] * 10 +
            severity_counts['high'] * 7 +
            severity_counts['medium'] * 4 +
            severity_counts['low'] * 1
        ) / (len(formatted_findings) if formatted_findings else 1)
        risk_score = min(10.0, risk_score)
        
        # Remediations (optional)
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
        
        # Threat intelligence (optional)
        threat_intelligence = None
        if report_request.include_threat_intelligence and formatted_findings:
            threat_intelligence = request.app.state.rag_model._vector_data_retriever(
                f"Security vulnerabilities in {report_request.language}: {severity_counts}"
            )
        
        return CodeSecurityReport(
            language=report_request.language,
            findings_count=len(formatted_findings),
            critical_count=severity_counts['critical'],
            high_count=severity_counts['high'],
            medium_count=severity_counts['medium'],
            low_count=severity_counts['low'],
            findings=formatted_findings,
            remediations=remediations,
            threat_intelligence=threat_intelligence,
            overall_risk_score=risk_score
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating report: {str(e)}"
        )