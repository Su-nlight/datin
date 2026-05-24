from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    wallet_address: Optional[str] = Field(None, description="Blockchain wallet address (e.g., Ethereum address)")
    name: str

    class Config:
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "password": "securepassword123",
                "wallet_address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
                "name": "User Actual Name"
            }
        }

class CreateUserDatabase(BaseModel):
    email: EmailStr
    username: str
    hashed_password: str
    wallet_address: str =""
    name: str

class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    wallet_address: Optional[str] = None
    is_active: bool
    oauth_provider: Optional[str] = None

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class RefreshRequest(BaseModel):
    """Request body for /authenticate/refresh."""
    refresh_token: str = Field(..., min_length=1)

class TokenData(BaseModel):
    username: Optional[str] = None

class GoogleAuthRequest(BaseModel):
    code: str

class RagResponse(BaseModel):
    query_resp : str

class ReportLog(BaseModel):
    title: str
    severity: int = Field(..., ge=1, le=5, description="Severity level between 1 to 5")

class LogReport(BaseModel):
    owner: str
    content: str
    tokenAddress: str
    reward: str

class ChatRequest(BaseModel):
<<<<<<< Updated upstream
    query: str = Field(..., min_length=1, max_length=3000)

# ==================== Code analysis agent ====================
class SecurityFinding(BaseModel):
    """Represents a single security vulnerability finding."""
    severity: str  # critical, high, medium, low, info
    category: str
    description: str
    line: int
    column: int
    remediation: str
    source: str  # static_analysis, rag_analysis, or hybrid
 
 
class CodeAnalysisRequest(BaseModel):
    """Request to analyze code for security vulnerabilities."""
    code: str = Field(..., min_length=1, max_length=500000)
    language: Optional[str] = Field(
        None, 
        description="python, cpp, java, javascript (auto-detect if None)"
    )
    include_rag_analysis: bool = Field(
        True, 
        description="Include RAG-based threat intelligence"
    )
    include_evaluation: bool = Field(
        False, 
        description="Include quality evaluation metrics"
    )
    severity_filter: Optional[str] = Field(
        None, 
        description="Filter by severity: critical, high, medium, low"
    )
 
    class Config:
        schema_extra = {
            "example": {
                "code": "import sqlite3\ndb = sqlite3.connect('test.db')\nquery = f'SELECT * FROM users WHERE id = {user_id}'",
                "language": "python",
                "include_rag_analysis": True,
                "include_evaluation": False,
                "severity_filter": None
            }
        }
 
 
class CodeAnalysisResponse(BaseModel):
    """Response from code security analysis."""
    language: str
    static_findings: List[SecurityFinding]
    rag_analysis: Optional[str] = None
    evaluation_results: Optional[dict] = None
    summary: str
 
    class Config:
        schema_extra = {
            "example": {
                "language": "python",
                "static_findings": [
                    {
                        "severity": "critical",
                        "category": "sql_injection",
                        "description": "SQL injection vulnerability - user input directly in query",
                        "line": 3,
                        "column": 10,
                        "remediation": "Use parameterized queries",
                        "source": "static_analysis"
                    }
                ],
                "rag_analysis": "This is CWE-89 SQL injection...",
                "evaluation_results": None,
                "summary": "Found 1 critical vulnerability"
            }
        }
 
 
class VulnerabilityRemediationRequest(BaseModel):
    """Request to get remediation for a vulnerability."""
    code: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(..., description="python, cpp, java, javascript")
    vulnerability_type: str = Field(..., description="sql_injection, xss, command_injection, etc.")
    line_number: Optional[int] = None
 
    class Config:
        schema_extra = {
            "example": {
                "code": "query = f'SELECT * FROM users WHERE id = {user_id}'",
                "language": "python",
                "vulnerability_type": "sql_injection",
                "line_number": 1
            }
        }
 
 
class VulnerabilityRemediationResponse(BaseModel):
    """Response with remediation guidance."""
    original_code: str
    remediated_code: str
    explanation: str
    best_practices: List[str]
    affected_cwe: Optional[str] = None
 
    class Config:
        schema_extra = {
            "example": {
                "original_code": "query = f'SELECT * FROM users WHERE id = {user_id}'",
                "remediated_code": "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
                "explanation": "Changed to parameterized query",
                "best_practices": [
                    "Always use parameterized queries",
                    "Never trust user input",
                    "Validate all inputs"
                ],
                "affected_cwe": "CWE-89"
            }
        }
 
 
class CodeSecurityReportRequest(BaseModel):
    """Request for comprehensive security report."""
    code: str = Field(..., min_length=1, max_length=500000)
    language: str = Field(..., description="python, cpp, java, javascript")
    include_remediation: bool = Field(True)
    include_threat_intelligence: bool = Field(True)
 
    class Config:
        schema_extra = {
            "example": {
                "code": "import requests\nresponse = requests.get(user_url, verify=False)",
                "language": "python",
                "include_remediation": True,
                "include_threat_intelligence": True
            }
        }
 
 
class CodeSecurityReport(BaseModel):
    """Comprehensive security report."""
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
 
    class Config:
        schema_extra = {
            "example": {
                "language": "python",
                "findings_count": 3,
                "critical_count": 1,
                "high_count": 2,
                "medium_count": 0,
                "low_count": 0,
                "findings": [],
                "overall_risk_score": 8.5
            }
        }
=======
    query: str = Field(..., min_length=1, max_length=3000)
>>>>>>> Stashed changes
