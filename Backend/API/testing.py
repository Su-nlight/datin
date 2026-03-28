#!/usr/bin/env python3
"""
Example usage of the Security Code Analyzer API.
Demonstrates all major endpoints and features.
"""

import requests
import json
from typing import Dict, List

# API Configuration
BASE_URL = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}


class SecurityAnalyzerClient:
    """Client for interacting with the Security Code Analyzer API."""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
    
    def analyze_code(self, code: str, language: str = None, 
                     include_rag: bool = True) -> Dict:
        """Analyze code for security vulnerabilities."""
        payload = {
            "code": code,
            "language": language,
            "include_rag_analysis": include_rag,
            "include_evaluation": False
        }
        
        response = self.session.post(
            f"{self.base_url}/analyze-code",
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()
        return response.json()
    
    def analyze_code_stream(self, code: str, language: str = None):
        """Stream code analysis results in real-time."""
        payload = {
            "code": code,
            "language": language,
            "include_rag_analysis": True
        }
        
        response = self.session.post(
            f"{self.base_url}/analyze-code-stream",
            json=payload,
            headers=HEADERS,
            stream=True
        )
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                yield line.decode('utf-8')
    
    def analyze_with_evaluation(self, code: str, language: str = None) -> Dict:
        """Analyze code with quality evaluation metrics."""
        payload = {
            "code": code,
            "language": language,
            "include_rag_analysis": True,
            "include_evaluation": True
        }
        
        response = self.session.post(
            f"{self.base_url}/analyze-code-with-evaluation",
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()
        return response.json()
    
    def remediate_vulnerability(self, code: str, language: str, 
                               vulnerability_type: str) -> Dict:
        """Get remediation for a specific vulnerability."""
        payload = {
            "code": code,
            "language": language,
            "vulnerability_type": vulnerability_type
        }
        
        response = self.session.post(
            f"{self.base_url}/remediate-vulnerability",
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()
        return response.json()
    
    def generate_report(self, code: str, language: str,
                       include_remediation: bool = True,
                       include_threat_intel: bool = True) -> Dict:
        """Generate comprehensive security report."""
        payload = {
            "code": code,
            "language": language,
            "include_remediation": include_remediation,
            "include_threat_intelligence": include_threat_intel
        }
        
        response = self.session.post(
            f"{self.base_url}/security-report",
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()
        return response.json()


def print_findings(findings: List[Dict]) -> None:
    """Pretty print vulnerability findings."""
    if not findings:
        print("✓ No vulnerabilities found!")
        return
    
    severity_colors = {
        'critical': '🔴',
        'high': '🟠',
        'medium': '🟡',
        'low': '🟢',
        'info': '🔵'
    }
    
    for finding in findings:
        icon = severity_colors.get(finding['severity'], '⚪')
        print(f"\n{icon} [{finding['severity'].upper()}] {finding['category']}")
        print(f"   Line {finding['line']}: {finding['description']}")
        print(f"   Remediation: {finding['remediation']}")


def example_python_sql_injection():
    """Example 1: Analyze Python code with SQL injection."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Python SQL Injection Detection")
    print("="*60)
    
    vulnerable_code = '''
import sqlite3

def get_user(user_id):
    db = sqlite3.connect('users.db')
    # Vulnerable: direct string interpolation
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor = db.cursor()
    results = cursor.execute(query).fetchall()
    return results
'''
    
    client = SecurityAnalyzerClient()
    analysis = client.analyze_code(vulnerable_code, language="python")
    
    print("\nVulnerabilities Found:")
    print_findings(analysis['static_findings'])
    
    if analysis['rag_analysis']:
        print("\n📚 Threat Intelligence Context:")
        print(analysis['rag_analysis'][:500] + "...")


def example_javascript_xss():
    """Example 2: Analyze JavaScript code with XSS vulnerability."""
    print("\n" + "="*60)
    print("EXAMPLE 2: JavaScript XSS Detection")
    print("="*60)
    
    vulnerable_code = '''
const express = require('express');
const app = express();

app.get('/profile/:username', (req, res) => {
  const username = req.params.username;
  // Vulnerable: directly inserting user input into HTML
  const html = `<h1>Welcome ${username}</h1>`;
  res.send(html);
});
'''
    
    client = SecurityAnalyzerClient()
    analysis = client.analyze_code(vulnerable_code, language="javascript")
    
    print("\nVulnerabilities Found:")
    print_findings(analysis['static_findings'])


def example_remediation():
    """Example 3: Get remediation for vulnerability."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Vulnerability Remediation")
    print("="*60)
    
    vulnerable_code = "query = f'SELECT * FROM users WHERE id = {user_id}'"
    
    client = SecurityAnalyzerClient()
    remediation = client.remediate_vulnerability(
        code=vulnerable_code,
        language="python",
        vulnerability_type="sql_injection"
    )
    
    print("\nOriginal Code:")
    print(f"  {remediation['original_code']}")
    
    print("\nRemediated Code:")
    print(f"  {remediation['remediated_code']}")
    
    print("\nExplanation:")
    print(f"  {remediation['explanation']}")
    
    print("\nBest Practices:")
    for i, practice in enumerate(remediation['best_practices'], 1):
        print(f"  {i}. {practice}")


def example_streaming():
    """Example 4: Stream analysis results."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Streaming Analysis")
    print("="*60)
    
    code_with_issues = '''
import os
import pickle

# Hardcoded credentials
db_password = "admin123"

# Insecure deserialization
data = pickle.loads(user_input)

# Command injection
os.system(f"rm {file_path}")
'''
    
    client = SecurityAnalyzerClient()
    print("\nStreaming results:")
    print("-" * 40)
    
    for line in client.analyze_code_stream(code_with_issues, language="python"):
        print(line)


def example_comprehensive_report():
    """Example 5: Generate comprehensive security report."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Comprehensive Security Report")
    print("="*60)
    
    code_to_analyze = '''
import hashlib
import requests

def login(username, password):
    # MD5 is cryptographically weak
    hashed = hashlib.md5(password.encode()).hexdigest()
    
    # Insecure SSL verification
    response = requests.get(
        "https://api.example.com/auth",
        verify=False
    )
    return response.json()

def download_file(filename):
    # Path traversal vulnerability
    filepath = f"/files/{filename}"
    with open(filepath, 'r') as f:
        return f.read()
'''
    
    client = SecurityAnalyzerClient()
    report = client.generate_report(
        code=code_to_analyze,
        language="python",
        include_remediation=True
    )
    
    print(f"\nLanguage: {report['language']}")
    print(f"\nRisk Severity Breakdown:")
    print(f"  🔴 Critical: {report['critical_count']}")
    print(f"  🟠 High: {report['high_count']}")
    print(f"  🟡 Medium: {report['medium_count']}")
    print(f"  🟢 Low: {report['low_count']}")
    print(f"\nOverall Risk Score: {report['overall_risk_score']}/10")
    
    print(f"\nFindings:")
    print_findings(report['findings'])
    
    if report['remediations']:
        print(f"\n✏️ Remediation Guidance:")
        print(report['remediations'][:500] + "...")


def example_cpp_analysis():
    """Example 6: Analyze C++ code."""
    print("\n" + "="*60)
    print("EXAMPLE 6: C++ Security Analysis")
    print("="*60)
    
    cpp_code = '''
#include <string>
#include <cstring>

void process_input(const char* input) {
    char buffer[10];
    // Buffer overflow vulnerability
    strcpy(buffer, input);
}

int main() {
    char* ptr = nullptr;
    // Null pointer dereference
    int value = *ptr;
    return 0;
}
'''
    
    client = SecurityAnalyzerClient()
    analysis = client.analyze_code(cpp_code, language="cpp")
    
    print("\nVulnerabilities Found:")
    print_findings(analysis['static_findings'])


def example_java_analysis():
    """Example 7: Analyze Java code."""
    print("\n" + "="*60)
    print("EXAMPLE 7: Java Security Analysis")
    print("="*60)
    
    java_code = '''
import javax.persistence.*;

@Entity
public class User {
    @Column(name = "username")
    private String username;
    
    @Column(name = "email")
    private String email;
    
    // Insecure password handling
    private String password;
    
    public User(String username, String password) {
        this.username = username;
        this.password = password; // Should be hashed
    }
}
'''
    
    client = SecurityAnalyzerClient()
    analysis = client.analyze_code(java_code, language="java")
    
    print("\nVulnerabilities Found:")
    print_findings(analysis['static_findings'])


def run_all_examples():
    """Run all example analyses."""
    try:
        # Check if API is running
        response = requests.get(f"{BASE_URL}/")
        print(f"✓ API is running: {response.json()['Status']}")
    except requests.ConnectionError:
        print("✗ Error: Cannot connect to API at", BASE_URL)
        print("  Please ensure the API is running: python -m uvicorn main:app --reload")
        return
    
    # Run examples
    example_python_sql_injection()
    example_javascript_xss()
    example_cpp_analysis()
    example_java_analysis()
    example_remediation()
    example_comprehensive_report()
    example_streaming()
    
    print("\n" + "="*60)
    print("All examples completed!")
    print("="*60)


if __name__ == "__main__":
    run_all_examples()