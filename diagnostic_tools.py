#!/usr/bin/env python3
"""
Enhanced Diagnostic Tools for Symm Bluesky Userbot

This module provides comprehensive system diagnostics with:
- Beautiful, accessible output with colors and emojis
- Database connectivity and performance testing
- API health monitoring
- Environment validation
- Interactive diagnostic sessions
- Export capabilities for troubleshooting
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from colorama import Fore, Style, init

# Import our enhanced utilities
from utils import (
    StructuredLogger, get_logger, get_performance_monitor,
    RetryConfig, async_retry, HealthChecker, format_error, safe_json_serialize, create_timestamped_filename
)

# Import application modules
from database import Database
from account_agent import AccountAgent, CLEARSKY_API_BASE_URL
import clearsky_helpers as cs

# Initialize colorama
init(autoreset=True)

# Also import additional required modules that are used in this file
import httpx
import psutil
from datetime import datetime

# Check if enhanced utilities are available
try:
    # Test imports to set availability flag
    from utils import get_logger
    use_enhanced_utils = True
except ImportError:
    use_enhanced_utils = False

class DiagnosticResult:
    """Represents the result of a diagnostic check"""
    
    def __init__(self, name: str, status: str, message: str, details: Dict[str, Any] = None, 
                 duration: float = 0.0, recommendations: List[str] = None):
        self.name = name
        self.status = status  # 'pass', 'warn', 'fail', 'skip'
        self.message = message
        self.details = details or {}
        self.duration = duration
        self.recommendations = recommendations or []
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'status': self.status,
            'message': self.message,
            'details': self.details,
            'duration': self.duration,
            'recommendations': self.recommendations,
            'timestamp': self.timestamp.isoformat()
        }

class SystemDiagnostics:
    """Comprehensive system diagnostics with beautiful output"""
    
    def __init__(self):
        self.results: List[DiagnosticResult] = []
        self.health_checker = HealthChecker() if use_enhanced_utils else None
    
    def _format_status(self, status: str) -> str:
        """Format status with colors and emojis"""
        status_map = {
            'pass': f"{Fore.GREEN}✅ PASS{Style.RESET_ALL}",
            'warn': f"{Fore.YELLOW}⚠️  WARN{Style.RESET_ALL}",
            'fail': f"{Fore.RED}❌ FAIL{Style.RESET_ALL}",
            'skip': f"{Fore.CYAN}⏭️  SKIP{Style.RESET_ALL}"
        }
        return status_map.get(status, status)
    
    def _print_header(self, title: str):
        """Print a beautiful header"""
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{title.center(80)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")
    
    def _print_section(self, title: str):
        """Print a section header"""
        print(f"\n{Fore.BLUE}{'─' * 60}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{title}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 60}{Style.RESET_ALL}")
    
    def _print_result(self, result: DiagnosticResult):
        """Print a diagnostic result with formatting"""
        status_str = self._format_status(result.status)
        duration_str = f"({result.duration:.2f}s)" if result.duration > 0 else ""
        
        print(f"  {status_str} {result.name} {duration_str}")
        if result.message:
            print(f"    💬 {result.message}")
        
        if result.details:
            for key, value in result.details.items():
                if isinstance(value, (int, float)) and key.endswith(('_bytes', '_mb', '_gb')):
                    if key.endswith('_bytes'):
                        value = f"{value / (1024**3):.2f} GB"
                    elif key.endswith('_mb'):
                        value = f"{value / 1024:.2f} GB"
                    elif key.endswith('_gb'):
                        value = f"{value:.2f} GB"
                elif isinstance(value, float) and key.endswith(('_percent', '_usage')):
                    value = f"{value:.1f}%"
                
                print(f"      📊 {key}: {value}")
        
        if result.recommendations:
            print(f"    {Fore.YELLOW}💡 Recommendations:{Style.RESET_ALL}")
            for rec in result.recommendations:
                print(f"      • {rec}")
        print()
    
    async def check_database_connectivity(self) -> DiagnosticResult:
        """Check database connectivity and basic operations"""
        start_time = time.time()
        
        try:
            database = Database()
            
            # Test basic connection
            connection_ok = await database.test_connection()
            duration = time.time() - start_time
            
            if not connection_ok:
                return DiagnosticResult(
                    "Database Connectivity",
                    "fail",
                    "Cannot connect to database",
                    {"duration": duration},
                    duration,
                    [
                        "Check database credentials in .env file",
                        "Ensure database server is running",
                        "Verify network connectivity to database"
                    ]
                )
            
            # Test table existence
            try:
                query = """
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """
                tables_result = await database.execute_query(query)
                existing_tables = [row.get('table_name') for row in tables_result]
                
                required_tables = ['accounts', 'blocked_accounts', 'mod_lists']
                missing_tables = [table for table in required_tables if table not in existing_tables]
                
                details = {
                    "existing_tables": len(existing_tables),
                    "required_tables": len(required_tables),
                    "missing_tables": missing_tables
                }
                
                if missing_tables:
                    return DiagnosticResult(
                        "Database Connectivity",
                        "warn",
                        f"Database connected but missing tables: {', '.join(missing_tables)}",
                        details,
                        duration,
                        ["Run database setup script to create missing tables"]
                    )
                else:
                    return DiagnosticResult(
                        "Database Connectivity",
                        "pass",
                        "Database connection and schema OK",
                        details,
                        duration
                    )
                    
            except Exception as e:
                return DiagnosticResult(
                    "Database Connectivity",
                    "warn",
                    f"Connected but schema check failed: {str(e)}",
                    {"duration": duration},
                    duration,
                    ["Verify database schema and permissions"]
                )
                
        except Exception as e:
            duration = time.time() - start_time
            return DiagnosticResult(
                "Database Connectivity",
                "fail",
                f"Database connection failed: {str(e)}",
                {"error": str(e)},
                duration,
                [
                    "Check database configuration in .env",
                    "Ensure database service is running",
                    "Verify credentials and network access"
                ]
            )
    
    async def check_clearsky_api(self) -> DiagnosticResult:
        """Check ClearSky API connectivity and health"""
        start_time = time.time()
        
        try:
            # Test basic connectivity
            test_url = f"{CLEARSKY_API_BASE_URL}/lists/fun-facts"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(test_url)
                duration = time.time() - start_time
                
                details = {
                    "status_code": response.status_code,
                    "response_time_ms": duration * 1000,
                    "api_url": CLEARSKY_API_BASE_URL
                }
                
                if response.status_code == 200:
                    # Try to parse response
                    try:
                        data = response.json()
                        details["response_valid"] = True
                        details["response_size_bytes"] = len(response.content)
                        
                        return DiagnosticResult(
                            "ClearSky API",
                            "pass",
                            "ClearSky API is accessible and responding",
                            details,
                            duration
                        )
                    except Exception:
                        return DiagnosticResult(
                            "ClearSky API",
                            "warn",
                            "API responding but invalid JSON",
                            details,
                            duration,
                            ["API may be experiencing issues, monitor responses"]
                        )
                else:
                    return DiagnosticResult(
                        "ClearSky API",
                        "warn",
                        f"API returned status {response.status_code}",
                        details,
                        duration,
                        ["Check ClearSky service status", "Verify API endpoint URL"]
                    )
                    
        except httpx.TimeoutException:
            duration = time.time() - start_time
            return DiagnosticResult(
                "ClearSky API",
                "fail",
                "API request timed out",
                {"timeout": True, "duration": duration},
                duration,
                ["Check network connectivity", "ClearSky API may be slow/down"]
            )
        except Exception as e:
            duration = time.time() - start_time
            return DiagnosticResult(
                "ClearSky API",
                "fail",
                f"API check failed: {str(e)}",
                {"error": str(e)},
                duration,
                ["Verify internet connectivity", "Check API URL configuration"]
            )
    
    def check_environment_variables(self) -> DiagnosticResult:
        """Check required environment variables"""
        start_time = time.time()
        
        required_vars = {
            'PRIMARY_BLUESKY_HANDLE': 'Primary Bluesky account handle',
            'PRIMARY_BLUESKY_PASSWORD': 'Primary Bluesky account password',
            'DB_HOST': 'Database host',
            'DB_NAME': 'Database name',
            'DB_USER': 'Database username',
            'DB_PASSWORD': 'Database password'
        }
        
        optional_vars = {
            'SECONDARY_ACCOUNTS': 'Secondary account credentials',
            'CLEARSKY_API_URL': 'ClearSky API base URL',
            'LOG_LEVEL': 'Logging level',
            'MOD_LIST_NAME': 'Moderation list name',
            'MOD_LIST_DESCRIPTION': 'Moderation list description'
        }
        
        missing_required = []
        missing_optional = []
        present_vars = {}
        
        for var, description in required_vars.items():
            value = os.getenv(var)
            if not value:
                missing_required.append(f"{var} - {description}")
            else:
                # Mask sensitive values
                if 'password' in var.lower() or 'secret' in var.lower():
                    present_vars[var] = '***MASKED***'
                else:
                    present_vars[var] = value[:50] + '...' if len(value) > 50 else value
        
        for var, description in optional_vars.items():
            value = os.getenv(var)
            if not value:
                missing_optional.append(f"{var} - {description}")
            else:
                present_vars[var] = value[:50] + '...' if len(value) > 50 else value
        
        duration = time.time() - start_time
        
        details = {
            "required_vars_count": len(required_vars),
            "missing_required_count": len(missing_required),
            "optional_vars_count": len(optional_vars),
            "missing_optional_count": len(missing_optional),
            "present_vars": present_vars
        }
        
        if missing_required:
            return DiagnosticResult(
                "Environment Variables",
                "fail",
                f"Missing {len(missing_required)} required environment variables",
                details,
                duration,
                [f"Set missing variables: {', '.join(missing_required)}"]
            )
        elif missing_optional:
            return DiagnosticResult(
                "Environment Variables",
                "warn",
                f"All required vars present, {len(missing_optional)} optional vars missing",
                details,
                duration,
                [f"Consider setting: {', '.join(missing_optional)}"]
            )
        else:
            return DiagnosticResult(
                "Environment Variables",
                "pass",
                "All environment variables are properly configured",
                details,
                duration
            )
    
    def check_system_resources(self) -> DiagnosticResult:
        """Check system resource usage"""
        start_time = time.time()
        
        try:
            # Get system info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            
            duration = time.time() - start_time
            
            details = {
                "cpu_usage_percent": cpu_percent,
                "memory_total_gb": memory.total / (1024**3),
                "memory_available_gb": memory.available / (1024**3),
                "memory_usage_percent": memory.percent,
                "disk_total_gb": disk.total / (1024**3),
                "disk_free_gb": disk.free / (1024**3),
                "disk_usage_percent": disk.percent,
                "system_uptime_hours": uptime / 3600
            }
            
            recommendations = []
            status = "pass"
            
            # Check for resource issues
            if cpu_percent > 80:
                status = "warn"
                recommendations.append(f"High CPU usage: {cpu_percent:.1f}%")
            
            if memory.percent > 85:
                status = "warn"
                recommendations.append(f"High memory usage: {memory.percent:.1f}%")
            
            if disk.percent > 90:
                status = "warn"
                recommendations.append(f"Low disk space: {disk.percent:.1f}% used")
            
            if memory.available < (1024**3):  # Less than 1GB available
                status = "warn"
                recommendations.append("Less than 1GB RAM available")
            
            message = "System resources are healthy"
            if status == "warn":
                message = "System resources need attention"
            
            return DiagnosticResult(
                "System Resources",
                status,
                message,
                details,
                duration,
                recommendations
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return DiagnosticResult(
                "System Resources",
                "fail",
                f"Failed to check system resources: {str(e)}",
                {"error": str(e)},
                duration,
                ["Check system monitoring tools", "Verify psutil package installation"]
            )
    
    async def check_account_authentication(self) -> DiagnosticResult:
        """Check account authentication without full login"""
        start_time = time.time()
        
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            duration = time.time() - start_time
            return DiagnosticResult(
                "Account Authentication",
                "fail",
                "Primary account credentials not configured",
                {},
                duration,
                ["Set PRIMARY_BLUESKY_HANDLE and PRIMARY_BLUESKY_PASSWORD in .env"]
            )
        
        try:
            # Test authentication (without full initialization)
            from atproto import Client
            client = Client(base_url="https://bsky.social")
            
            # Attempt login
            response = client.login(primary_handle, primary_password)
            did = response.did
            
            duration = time.time() - start_time
            
            details = {
                "primary_handle": primary_handle,
                "primary_did": did,
                "auth_time_ms": duration * 1000
            }
            
            # Check secondary accounts if configured
            secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
            if secondary_accounts_str:
                accounts = secondary_accounts_str.split(';')
                details["secondary_accounts_configured"] = len(accounts)
                
                # Validate format (don't actually authenticate)
                valid_format = True
                for account_str in accounts:
                    if ':' not in account_str and ',' not in account_str:
                        valid_format = False
                        break
                
                details["secondary_accounts_format_valid"] = valid_format
                
                if not valid_format:
                    return DiagnosticResult(
                        "Account Authentication",
                        "warn",
                        "Primary auth OK, but secondary accounts format invalid",
                        details,
                        duration,
                        ["Fix SECONDARY_ACCOUNTS format: 'handle:password;handle2:password2'"]
                    )
            else:
                details["secondary_accounts_configured"] = 0
            
            return DiagnosticResult(
                "Account Authentication",
                "pass",
                "Account authentication successful",
                details,
                duration
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return DiagnosticResult(
                "Account Authentication",
                "fail",
                f"Authentication failed: {str(e)}",
                {"error": str(e), "handle": primary_handle},
                duration,
                [
                    "Verify account credentials",
                    "Check if account exists and is active",
                    "Ensure network connectivity to Bluesky"
                ]
            )
    
    async def run_all_checks(self) -> List[DiagnosticResult]:
        """Run all diagnostic checks"""
        self.results = []
        
        checks = [
            ("Environment Variables", self.check_environment_variables),
            ("System Resources", self.check_system_resources),
            ("Database Connectivity", self.check_database_connectivity),
            ("ClearSky API", self.check_clearsky_api),
            ("Account Authentication", self.check_account_authentication)
        ]
        
        self._print_header("🔍 SYSTEM DIAGNOSTICS")
        
        for check_name, check_func in checks:
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                
                self.results.append(result)
                self._print_result(result)
                
            except Exception as e:
                error_result = DiagnosticResult(
                    check_name,
                    "fail",
                    f"Check failed with exception: {str(e)}",
                    {"error": str(e)},
                    0.0,
                    ["Check diagnostic tool implementation"]
                )
                self.results.append(error_result)
                self._print_result(error_result)
        
        # Summary
        self._print_summary()
        return self.results
    
    def _print_summary(self):
        """Print diagnostic summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == 'pass')
        warned = sum(1 for r in self.results if r.status == 'warn')
        failed = sum(1 for r in self.results if r.status == 'fail')
        
        self._print_section("📊 DIAGNOSTIC SUMMARY")
        
        print(f"  Total Checks: {total}")
        print(f"  {Fore.GREEN}✅ Passed: {passed}{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}⚠️  Warnings: {warned}{Style.RESET_ALL}")
        print(f"  {Fore.RED}❌ Failed: {failed}{Style.RESET_ALL}")
        
        if failed > 0:
            print(f"\n  {Fore.RED}🚨 CRITICAL ISSUES DETECTED{Style.RESET_ALL}")
            print(f"  System may not function properly with {failed} failed checks.")
        elif warned > 0:
            print(f"\n  {Fore.YELLOW}⚠️  WARNINGS PRESENT{Style.RESET_ALL}")
            print(f"  System should work but {warned} issues may affect performance.")
        else:
            print(f"\n  {Fore.GREEN}✅ ALL SYSTEMS OPERATIONAL{Style.RESET_ALL}")
            print(f"  System is ready for production use.")
        
        print()
    
    def save_results(self, filename: Optional[str] = None) -> str:
        """Save diagnostic results to JSON file"""
        if not filename:
            filename = create_timestamped_filename("diagnostic_results", "json")
        
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_checks": len(self.results),
                "passed": sum(1 for r in self.results if r.status == 'pass'),
                "warned": sum(1 for r in self.results if r.status == 'warn'),
                "failed": sum(1 for r in self.results if r.status == 'fail')
            },
            "checks": [result.to_dict() for result in self.results]
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"  💾 Results saved to: {filename}")
        return filename

class DatabaseDiagnostics:
    """Specialized database diagnostics"""
    
    def __init__(self):
        self.database = Database()
    
    async def analyze_database(self) -> Dict[str, Any]:
        """Comprehensive database analysis"""
        results = {}
        
        try:
            # Table statistics
            tables_query = """
                SELECT 
                    schemaname,
                    tablename,
                    n_tup_ins as inserts,
                    n_tup_upd as updates,
                    n_tup_del as deletes,
                    n_live_tup as live_rows,
                    n_dead_tup as dead_rows
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC
            """
            
            table_stats = await self.database.execute_query(tables_query)
            results["table_statistics"] = table_stats
            
            # Database size
            size_query = """
                SELECT 
                    pg_size_pretty(pg_database_size(current_database())) as database_size,
                    pg_database_size(current_database()) as database_size_bytes
            """
            size_result = await self.database.execute_query(size_query)
            results["database_size"] = size_result[0] if size_result else {}
            
            # Connection info
            conn_query = """
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
            """
            conn_result = await self.database.execute_query(conn_query)
            results["connections"] = conn_result[0] if conn_result else {}
            
            # Performance metrics
            performance_query = """
                SELECT 
                    sum(blks_read) as blocks_read,
                    sum(blks_hit) as blocks_hit,
                    round(sum(blks_hit) * 100.0 / nullif(sum(blks_read) + sum(blks_hit), 0), 2) as cache_hit_ratio
                FROM pg_stat_database 
                WHERE datname = current_database()
            """
            perf_result = await self.database.execute_query(performance_query)
            results["performance"] = perf_result[0] if perf_result else {}
            
            return results
            
        except Exception as e:
            logger.error(f"Database analysis failed: {e}")
            return {"error": str(e)}
    
    async def check_data_integrity(self) -> Dict[str, Any]:
        """Check for data integrity issues"""
        issues = []
        
        try:
            # Check for duplicate DIDs
            duplicate_query = """
                SELECT did, block_type, source_account_id, COUNT(*) as count
                FROM blocked_accounts
                GROUP BY did, block_type, source_account_id
                HAVING COUNT(*) > 1
                ORDER BY count DESC
                LIMIT 10
            """
            duplicates = await self.database.execute_query(duplicate_query)
            
            if duplicates:
                issues.append({
                    "type": "duplicate_blocked_accounts",
                    "count": len(duplicates),
                    "description": "Duplicate blocked account entries found",
                    "severity": "medium",
                    "samples": duplicates
                })
            
            # Check for orphaned records
            orphan_query = """
                SELECT ba.id, ba.did, ba.source_account_id
                FROM blocked_accounts ba
                LEFT JOIN accounts a ON ba.source_account_id = a.id
                WHERE a.id IS NULL
                LIMIT 5
            """
            orphans = await self.database.execute_query(orphan_query)
            
            if orphans:
                issues.append({
                    "type": "orphaned_blocked_accounts",
                    "count": len(orphans),
                    "description": "Blocked accounts referencing non-existent source accounts",
                    "severity": "high",
                    "samples": orphans
                })
            
            # Check for accounts without DIDs
            missing_did_query = """
                SELECT id, handle FROM accounts 
                WHERE did IS NULL OR did = ''
                LIMIT 5
            """
            missing_dids = await self.database.execute_query(missing_did_query)
            
            if missing_dids:
                issues.append({
                    "type": "accounts_missing_did",
                    "count": len(missing_dids),
                    "description": "Accounts missing DID information",
                    "severity": "high",
                    "samples": missing_dids
                })
            
            return {
                "issues_found": len(issues),
                "issues": issues,
                "status": "clean" if not issues else "issues_detected"
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "status": "check_failed"
            }

async def run_interactive_diagnostics():
    """Interactive diagnostic session"""
    print(f"{Fore.CYAN}🔧 INTERACTIVE DIAGNOSTIC SESSION{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 50}{Style.RESET_ALL}")
    
    diagnostics = SystemDiagnostics()
    db_diagnostics = DatabaseDiagnostics()
    
    while True:
        print(f"\n{Fore.BLUE}Available Diagnostic Options:{Style.RESET_ALL}")
        print("  1. 🔍 Run Full System Diagnostics")
        print("  2. 🗄️  Database Analysis")
        print("  3. 🔍 Data Integrity Check")
        print("  4. 📊 Performance Metrics")
        print("  5. 💾 Save Results")
        print("  6. 🚪 Exit")
        
        try:
            choice = input(f"\n{Fore.GREEN}Select option (1-6): {Style.RESET_ALL}").strip()
            
            if choice == '1':
                print(f"\n{Fore.YELLOW}Running full system diagnostics...{Style.RESET_ALL}")
                await diagnostics.run_all_checks()
                
            elif choice == '2':
                print(f"\n{Fore.YELLOW}Analyzing database...{Style.RESET_ALL}")
                analysis = await db_diagnostics.analyze_database()
                
                if "error" in analysis:
                    print(f"{Fore.RED}❌ Database analysis failed: {analysis['error']}{Style.RESET_ALL}")
                else:
                    print(f"\n{Fore.BLUE}📊 DATABASE ANALYSIS{Style.RESET_ALL}")
                    
                    if "database_size" in analysis:
                        size_info = analysis["database_size"]
                        print(f"  Database Size: {size_info.get('database_size', 'Unknown')}")
                    
                    if "connections" in analysis:
                        conn_info = analysis["connections"]
                        print(f"  Total Connections: {conn_info.get('total_connections', 0)}")
                        print(f"  Active Connections: {conn_info.get('active_connections', 0)}")
                    
                    if "performance" in analysis:
                        perf_info = analysis["performance"]
                        cache_ratio = perf_info.get('cache_hit_ratio', 0)
                        print(f"  Cache Hit Ratio: {cache_ratio}%")
                    
                    if "table_statistics" in analysis:
                        print(f"\n  📋 Table Statistics:")
                        for table in analysis["table_statistics"][:5]:  # Show top 5
                            print(f"    {table['tablename']}: {table['live_rows']} rows")
                
            elif choice == '3':
                print(f"\n{Fore.YELLOW}Checking data integrity...{Style.RESET_ALL}")
                integrity = await db_diagnostics.check_data_integrity()
                
                if integrity.get("status") == "clean":
                    print(f"{Fore.GREEN}✅ No data integrity issues found{Style.RESET_ALL}")
                elif integrity.get("status") == "issues_detected":
                    print(f"{Fore.YELLOW}⚠️  Found {integrity['issues_found']} integrity issues:{Style.RESET_ALL}")
                    for issue in integrity["issues"]:
                        severity_color = Fore.RED if issue["severity"] == "high" else Fore.YELLOW
                        print(f"  {severity_color}• {issue['description']} ({issue['count']} items){Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}❌ Integrity check failed: {integrity.get('error', 'Unknown error')}{Style.RESET_ALL}")
            
            elif choice == '4':
                if performance_monitor:
                    stats = performance_monitor.get_all_stats()
                    print(f"\n{Fore.BLUE}📈 PERFORMANCE METRICS{Style.RESET_ALL}")
                    
                    if stats["operations"]:
                        print("  Operation Statistics:")
                        for op, metrics in stats["operations"].items():
                            print(f"    {op}: {metrics.get('count', 0)} calls, avg {metrics.get('avg', 0):.3f}s")
                    
                    if stats["counters"]:
                        print("  Counters:")
                        for counter, value in stats["counters"].items():
                            print(f"    {counter}: {value}")
                    
                    if not stats["operations"] and not stats["counters"]:
                        print("  No performance data available yet.")
                else:
                    print(f"{Fore.YELLOW}⚠️  Performance monitoring not available{Style.RESET_ALL}")
            
            elif choice == '5':
                if diagnostics.results:
                    filename = diagnostics.save_results()
                    print(f"{Fore.GREEN}✅ Results saved successfully{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}⚠️  No diagnostic results to save. Run diagnostics first.{Style.RESET_ALL}")
            
            elif choice == '6':
                print(f"\n{Fore.GREEN}👋 Goodbye!{Style.RESET_ALL}")
                break
            
            else:
                print(f"{Fore.RED}❌ Invalid option. Please choose 1-6.{Style.RESET_ALL}")
                
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Interrupted by user{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"{Fore.RED}❌ Error: {str(e)}{Style.RESET_ALL}")

async def main():
    """Main diagnostic function"""
    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        await run_interactive_diagnostics()
    else:
        diagnostics = SystemDiagnostics()
        results = await diagnostics.run_all_checks()
        diagnostics.save_results()

if __name__ == "__main__":
    asyncio.run(main()) 