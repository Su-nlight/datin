from typing import List, Optional

from pydantic import BaseModel, Field


class SecurityFinding(BaseModel):
    """Represents a single security vulnerability finding."""
    severity: str
    category: str
    description: str
    line: int
    column: int
    remediation: str
    source: str


class CodeAnalysisRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=500000)
    language: Optional[str] = Field(
        None, description="python, cpp, java, javascript (auto-detect if None)"
    )
    include_rag_analysis: bool = Field(True, description="Include RAG-based threat intelligence")
    include_evaluation: bool = Field(False, description="Include quality evaluation metrics")
    severity_filter: Optional[str] = Field(
        None, description="Filter by severity: critical, high, medium, low"
    )


class CodeAnalysisResponse(BaseModel):
    language: str
    static_findings: List[SecurityFinding]
    rag_analysis: Optional[str] = None
    evaluation_results: Optional[dict] = None
    summary: str


class VulnerabilityRemediationRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(..., description="python, cpp, java, javascript")
    vulnerability_type: str = Field(..., description="sql_injection, xss, command_injection, etc.")
    line_number: Optional[int] = None


class VulnerabilityRemediationResponse(BaseModel):
    original_code: str
    remediated_code: str
    explanation: str
    best_practices: List[str]
    affected_cwe: Optional[str] = None


class CodeSecurityReportRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=500000)
    language: str = Field(..., description="python, cpp, java, javascript")
    include_remediation: bool = Field(True)
    include_threat_intelligence: bool = Field(True)


class CodeSecurityReport(BaseModel):
    language: str
    findings_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    findings: List[SecurityFinding]
    remediations: Optional[str] = None
    threat_intelligence: Optional[str] = None
    overall_risk_score: Optional[float] = None
