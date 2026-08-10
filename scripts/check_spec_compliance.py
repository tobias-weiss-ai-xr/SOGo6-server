#!/usr/bin/env python3
"""
SOGo6 Six Sigma Compliance Checker

Validates implementation against OpenSpec specifications.
Calculates DPMO and Sigma level for each feature.
"""

import re
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Endpoint:
    method: str
    path: str
    
    def full_signature(self) -> str:
        return f"{self.method} {self.path}"
    
    def __hash__(self):
        return hash(self.full_signature())
    
    def __eq__(self, other):
        return self.full_signature() == other.full_signature()


@dataclass
class ComplianceResult:
    feature_name: str
    spec_file: str
    total_requirements: int = 0
    implemented_requirements: int = 0
    missing_requirements: int = 0
    compliance_percentage: float = 0.0
    dpmo: float = 0.0
    sigma_level: float = 0.0
    implemented_endpoints: List[str] = field(default_factory=list)
    missing_endpoints: List[str] = field(default_factory=list)
    extra_endpoints: List[str] = field(default_factory=list)
    implemented_data_models: List[str] = field(default_factory=list)
    missing_data_models: List[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return asdict(self)


class SpecParser:
    def __init__(self, spec_path: Path):
        self.spec_path = spec_path
        with open(spec_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
    
    def extract_endpoints(self) -> Set[Endpoint]:
        endpoints = set()
        endpoint_pattern = r'(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([/\w\-:\{\}]+[/\w\-:\{\}]*)'
        for match in re.finditer(endpoint_pattern, self.content):
            method, path = match.groups()
            path = path.strip().replace('{ ', '{').replace(' }', '}')
            endpoints.add(Endpoint(method=method, path=path))
        return endpoints
    
    def extract_data_models(self) -> Set[str]:
        models = set()
        patterns = [
            r'`sogo6_(\w+)`',
            r'`(\w+_\w+)`',
            r'class\s+(\w+)\s*\(.*Model',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, self.content):
                models.add(match.group(1))
        return models
    
    def extract_error_codes(self) -> Set[str]:
        error_codes = set()
        patterns = [
            r'(HTTP_[0-9]{3})',
            r'(ERR_[A-Z_0-9]+)',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, self.content):
                error_codes.add(match.group(1))
        return error_codes


class CodeParser:
    def __init__(self, code_path: Path):
        self.code_path = code_path
    
    def extract_endpoints(self) -> Set[Endpoint]:
        endpoints = set()
        if not self.code_path.exists():
            return endpoints
        
        for py_file in self.code_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                route_patterns = [
                    r'@\w+\.route\("([^"]+)"\)',
                    r"@\w+\.route\(\'([^\']+)\"",
                    r'@\w+\.route\("([^"]+)",\s*methods=\s*\[([^\]]+)\]',
                    r'@app\.route\("([^"]+)"\)',
                ]
                
                for pattern in route_patterns:
                    for match in re.finditer(pattern, content):
                        path = match.group(1)
                        methods = ['GET']
                        if 'methods=' in pattern and match.group(2):
                            methods_str = match.group(2)
                            methods = [m.strip().strip("'\"") for m in methods_str.split(',')]
                        
                        for method in methods:
                            if method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
                                endpoints.add(Endpoint(method=method, path=path))
                
            except (IOError, UnicodeDecodeError):
                pass
        
        return endpoints
    
    def extract_data_models(self) -> Set[str]:
        models = set()
        if not self.code_path.exists():
            return models
        
        for py_file in self.code_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                patterns = [
                    r'TABLE_NAME\s*=\s*[\'\"]([^\'\"]+)[\'\"]',
                    r'class\s+(\w+)\s*\(.*Model',
                    r'class\s+(\w+Error)',
                ]
                
                for pattern in patterns:
                    for match in re.finditer(pattern, content):
                        model = match.group(1)
                        if model and len(model) > 2:
                            models.add(model)
                
                for match in re.finditer(r'CREATE\s+TABLE\s+(\w+)', content, re.IGNORECASE):
                    models.add(match.group(1))
                
            except (IOError, UnicodeDecodeError):
                pass
        
        return models
    
    def extract_error_codes(self) -> Set[str]:
        error_codes = set()
        if not self.code_path.exists():
            return error_codes
        
        for py_file in self.code_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                patterns = [
                    r'(HTTP_[0-9]{3})',
                    r'(ERR_[A-Z_0-9]+)',
                    r'raise\s+(\w+Error)',
                    r'status_code\s*=\s*([0-9]{3})',
                ]
                
                for pattern in patterns:
                    for match in re.finditer(pattern, content):
                        code = match.group(1)
                        if code and len(code) > 2:
                            error_codes.add(code)
                
            except (IOError, UnicodeDecodeError):
                pass
        
        return error_codes


class SigmaCalculator:
    @staticmethod
    def dpmo_to_sigma(dpmo: float) -> float:
        if dpmo <= 0:
            return 6.0
        sigma_table = [
            (690000, 2.0), (308000, 3.0), (66800, 4.0), (233, 5.0), (3.4, 6.0)
        ]
        for dpmo_threshold, sigma in sigma_table:
            if dpmo >= dpmo_threshold:
                return sigma
        return 6.0
    
    @staticmethod
    def compliance_to_dpmo(compliance_pct: float, total_requirements: int) -> float:
        if total_requirements <= 0:
            return 0.0
        defect_rate = (100.0 - compliance_pct) / 100.0
        defects = total_requirements * defect_rate
        dpmo = (defects / total_requirements) * 1_000_000
        return dpmo


class ComplianceChecker:
    FEATURE_SPEC_MAP = {
        'shared-mailboxes': '.openspec/specs/shared-mailboxes.spec.md',
        'resource-booking': '.openspec/specs/resource-booking.spec.md',
        'sieve-editor': '.openspec/specs/sieve-editor.spec.md',
        'team-calendars': '.openspec/specs/team-calendars.spec.md',
        'webauthn-passkeys': '.openspec/specs/webauthn-passkeys.spec.md',
        'dkim-dmarc-spf': '.openspec/specs/dkim-dmarc-spf.spec.md',
        'caldav': '.openspec/specs/caldav.spec.md',
        'caldav-server': '.openspec/specs/caldav-server.spec.md',
        'api-playground': '.openspec/specs/api-playground.spec.md',
    }
    
    FEATURE_IMPLEMENTATION_MAP = {
        'shared-mailboxes': 'app',
        'resource-booking': 'app',
        'sieve-editor': 'app',
        'team-calendars': 'app',
        'webauthn-passkeys': 'app',
        'dkim-dmarc-spf': 'app',
        'caldav': 'app',
        'caldav-server': 'app',
        'api-playground': 'app',
    }
    
    def __init__(self, base_path: Path = Path('.')):
        self.base_path = base_path
    
    def check_feature(self, feature_name: str) -> ComplianceResult:
        if feature_name not in self.FEATURE_SPEC_MAP:
            raise ValueError(f"Unknown feature: {feature_name}")
        
        spec_path = self.base_path / self.FEATURE_SPEC_MAP[feature_name]
        impl_path = self.base_path / self.FEATURE_IMPLEMENTATION_MAP[feature_name]
        
        if not spec_path.exists():
            raise FileNotFoundError(f"Specification file not found: {spec_path}")
        
        spec_parser = SpecParser(spec_path)
        spec_endpoints = spec_parser.extract_endpoints()
        spec_models = spec_parser.extract_data_models()
        spec_errors = spec_parser.extract_error_codes()
        
        code_parser = CodeParser(impl_path)
        impl_endpoints = code_parser.extract_endpoints()
        impl_models = code_parser.extract_data_models()
        impl_errors = code_parser.extract_error_codes()
        
        total_requirements = len(spec_endpoints) + len(spec_models) + len(spec_errors) + 100
        
        impl_endpoint_strings = {ep.full_signature() for ep in impl_endpoints}
        spec_endpoint_strings = {ep.full_signature() for ep in spec_endpoints}
        
        implemented_endpoints = spec_endpoint_strings & impl_endpoint_strings
        missing_endpoints = spec_endpoint_strings - impl_endpoint_strings
        extra_endpoints = impl_endpoint_strings - spec_endpoint_strings
        
        implemented_models = spec_models & impl_models
        missing_models = spec_models - impl_models
        
        implemented_errors = spec_errors & impl_errors
        missing_errors = spec_errors - impl_errors
        
        implemented_count = len(implemented_endpoints) + len(implemented_models) + len(implemented_errors)
        missing_count = len(missing_endpoints) + len(missing_models) + len(missing_errors)
        
        total_possible = len(spec_endpoints) + len(spec_models) + len(spec_errors)
        compliance_pct = (implemented_count / total_possible * 100) if total_possible > 0 else 0.0
        dpmo = SigmaCalculator.compliance_to_dpmo(compliance_pct, total_possible)
        sigma = SigmaCalculator.dpmo_to_sigma(dpmo)
        
        feature_display_name = feature_name.replace('-', ' ').title()
        
        return ComplianceResult(
            feature_name=feature_display_name,
            spec_file=str(spec_path.relative_to(self.base_path)),
            total_requirements=total_possible,
            implemented_requirements=implemented_count,
            missing_requirements=missing_count,
            compliance_percentage=round(compliance_pct, 2),
            dpmo=round(dpmo, 2),
            sigma_level=round(sigma, 2),
            implemented_endpoints=sorted(list(implemented_endpoints)),
            missing_endpoints=sorted(list(missing_endpoints)),
            extra_endpoints=sorted(list(extra_endpoints)),
            implemented_data_models=sorted(list(implemented_models)),
            missing_data_models=sorted(list(missing_models)),
        )
    
    def check_all_features(self) -> List[ComplianceResult]:
        results = []
        for feature_name in self.FEATURE_SPEC_MAP:
            try:
                result = self.check_feature(feature_name)
                results.append(result)
            except (FileNotFoundError, ValueError):
                pass
        return results
    
    def generate_markdown_report(self, results: List[ComplianceResult]) -> str:
        report = []
        report.append("# Six Sigma Compliance Report")
        report.append("")
        report.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        total_compliance = sum(r.compliance_percentage for r in results) / len(results) if results else 0
        features_at_100 = sum(1 for r in results if r.compliance_percentage >= 100)
        
        if total_compliance >= 95:
            status = "Excellent"
        elif total_compliance >= 80:
            status = "Good"
        elif total_compliance >= 60:
            status = "Fair"
        elif total_compliance >= 40:
            status = "Poor"
        else:
            status = "Critical"
        
        report.append("## Overall Summary")
        report.append("")
        report.append("| Metric | Value | Target | Status |")
        report.append("|--------|-------|--------|--------|")
        report.append(f"| Overall Compliance | {total_compliance:.1f}% | 100% | {status} |")
        report.append(f"| Features at 100% | {features_at_100}/{len(results)} | {len(results)}/{len(results)} | {'All' if features_at_100 == len(results) else 'Incomplete'} |")
        report.append("")
        
        report.append("## Feature Compliance Matrix")
        report.append("")
        report.append("| Feature | Compliance | Missing | Status |")
        report.append("|---------|------------|---------|--------|")
        
        for result in sorted(results, key=lambda r: r.compliance_percentage, reverse=True):
            if result.compliance_percentage >= 95:
                status = "Excellent"
            elif result.compliance_percentage >= 80:
                status = "Good"
            elif result.compliance_percentage >= 60:
                status = "Fair"
            elif result.compliance_percentage >= 40:
                status = "Poor"
            else:
                status = "Critical"
            
            report.append(
                f"| {result.feature_name} | {result.compliance_percentage:.1f}% | "
                f"{result.missing_requirements} | {status} |"
            )
        
        report.append("")
        
        report.append("## Gap Analysis")
        report.append("")
        for result in sorted(results, key=lambda r: r.sigma_level):
            if result.missing_requirements > 0:
                report.append(f"### {result.feature_name} ({result.compliance_percentage:.1f}%]")
                report.append("")
                
                if result.missing_endpoints:
                    report.append(f"- **Missing Endpoints**: {len(result.missing_endpoints)}")
                if result.missing_data_models:
                    report.append(f"- **Missing Models**: {len(result.missing_data_models)}")
                if result.extra_endpoints:
                    report.append(f"- **Extra Endpoints**: {len(result.extra_endpoints)}")
                report.append("")
        
        return "\\n".join(report)
    
    def generate_json_report(self, results: List[ComplianceResult]) -> str:
        return json.dumps([r.to_dict() for r in results], indent=2)


def main():
    parser = argparse.ArgumentParser(description='SOGo6 Six Sigma Compliance Checker')
    parser.add_argument('--feature', '-f', type=str, help='Check specific feature')
    parser.add_argument('--all', '-a', action='store_true', help='Check all features')
    parser.add_argument('--output', '-o', type=str, help='Output file')
    parser.add_argument('--markdown', '-m', action='store_true', help='Generate markdown report')
    parser.add_argument('--json', '-j', action='store_true', help='Generate JSON report')
    parser.add_argument('--base-path', type=str, default='.', help='Base path')
    
    args = parser.parse_args()
    
    if not args.feature and not args.all:
        parser.error('Either --feature or --all must be specified')
    
    if args.feature and args.all:
        parser.error('Cannot specify both --feature and --all')
    
    if not args.json and not args.markdown:
        args.json = True
    
    checker = ComplianceChecker(Path(args.base_path))
    
    if args.feature:
        results = [checker.check_feature(args.feature)]
    else:
        results = checker.check_all_features()
    
    if args.markdown:
        report = checker.generate_markdown_report(results)
    else:
        report = checker.generate_json_report(results)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)
    
    all_passing = all(r.missing_requirements == 0 for r in results)
    sys.exit(0 if all_passing else 1)


if __name__ == "__main__":
    main()
