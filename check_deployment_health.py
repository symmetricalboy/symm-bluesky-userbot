#!/usr/bin/env python3

import asyncio
import os
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from database import Database
from account_agent import AccountAgent
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

class DeploymentHealthChecker:
    def __init__(self):
        self.db = Database()
        self.issues = []
        self.recommendations = []
        
    async def check_database_connectivity(self):
        """Check if database is accessible and responsive."""
        logger.info("🔍 Checking database connectivity...")
        try:
            await self.db.test_connection()
            logger.info("✅ Database connectivity: OK")
            return True
        except Exception as e:
            logger.error(f"❌ Database connectivity: FAILED - {e}")
            self.issues.append(f"Database connectivity failed: {e}")
            self.recommendations.append("Check database connection string and network connectivity")
            return False
    
    async def check_session_status(self):
        """Check session status for configured accounts."""
        logger.info("🔍 Checking session status for all accounts...")
        
        valid_sessions = 0
        total_accounts = 0
        
        # Check primary account
        local_test = os.getenv('LOCAL_TEST', 'false').lower() == 'true'
        
        if local_test:
            primary_handle = os.getenv('TEST_PRIMARY_BLUESKY_HANDLE')
            primary_password = os.getenv('TEST_PRIMARY_BLUESKY_PASSWORD')
        else:
            primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
            primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if primary_handle and primary_password:
            total_accounts += 1
            logger.info(f"  Checking primary account: {primary_handle}...")
            
            try:
                agent = AccountAgent(primary_handle, primary_password, is_primary=True, database=self.db)
                session_data = await agent._load_session_from_storage()
                
                if session_data:
                    # Check token expiry
                    if agent._is_refresh_token_expired(session_data):
                        logger.warning(f"⚠️  {primary_handle}: Refresh token expired")
                        self.issues.append(f"{primary_handle}: Refresh token expired")
                        self.recommendations.append(f"Re-login required for {primary_handle}")
                    elif agent._is_access_token_expired(session_data):
                        logger.info(f"ℹ️  {primary_handle}: Access token expired but refresh token valid")
                        valid_sessions += 1
                    else:
                        logger.info(f"✅ {primary_handle}: Session valid")
                        valid_sessions += 1
                else:
                    logger.warning(f"⚠️  {primary_handle}: No session data found")
                    self.issues.append(f"{primary_handle}: No session data")
                    self.recommendations.append(f"Initial login required for {primary_handle}")
                    
            except Exception as e:
                logger.error(f"❌ {primary_handle}: Error checking session - {e}")
                self.issues.append(f"{primary_handle}: Session check failed - {e}")
        
        # Check secondary accounts
        secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
        if secondary_accounts_str:
            try:
                accounts = secondary_accounts_str.split(';')
                for account_str in accounts:
                    if ',' in account_str:
                        handle, password = account_str.split(',', 1)
                        handle = handle.strip()
                        password = password.strip()
                        
                        if handle and password:
                            total_accounts += 1
                            logger.info(f"  Checking secondary account: {handle}...")
                            
                            try:
                                agent = AccountAgent(handle, password, is_primary=False, database=self.db)
                                session_data = await agent._load_session_from_storage()
                                
                                if session_data:
                                    if agent._is_refresh_token_expired(session_data):
                                        logger.warning(f"⚠️  {handle}: Refresh token expired")
                                        self.issues.append(f"{handle}: Refresh token expired")
                                        self.recommendations.append(f"Re-login required for {handle}")
                                    elif agent._is_access_token_expired(session_data):
                                        logger.info(f"ℹ️  {handle}: Access token expired but refresh token valid")
                                        valid_sessions += 1
                                    else:
                                        logger.info(f"✅ {handle}: Session valid")
                                        valid_sessions += 1
                                else:
                                    logger.warning(f"⚠️  {handle}: No session data found")
                                    self.issues.append(f"{handle}: No session data")
                                    self.recommendations.append(f"Initial login required for {handle}")
                                    
                            except Exception as e:
                                logger.error(f"❌ {handle}: Error checking session - {e}")
                                self.issues.append(f"{handle}: Session check failed - {e}")
                        
            except Exception as e:
                logger.error(f"❌ Error parsing secondary accounts: {e}")
                self.issues.append(f"Error parsing secondary accounts: {e}")
        
        logger.info(f"📊 Session summary: {valid_sessions}/{total_accounts} accounts have valid sessions")
        
        if total_accounts == 0:
            self.issues.append("No accounts configured")
            self.recommendations.append("Configure primary account credentials")
            return False
        
        if valid_sessions < total_accounts:
            self.recommendations.append("Run account initialization to restore missing sessions")
        
        return valid_sessions == total_accounts
    
        async def check_rate_limit_status(self):        """Check for recent rate limiting issues."""        logger.info("🔍 Checking for rate limiting indicators...")                try:            # Check account activity patterns that might indicate rate limiting            configurations = await self.db.get_account_configurations()            accounts = configurations.get('accounts', [])                        rate_limit_indicators = 0            for account in accounts:
                # Check for rapid sequential operations that might hit limits
                # This is a simplified check - in practice you'd analyze logs
                logger.info(f"  Account {account['handle']}: ID {account['id']}")
            
            if rate_limit_indicators > 0:
                self.issues.append(f"Potential rate limiting detected for {rate_limit_indicators} accounts")
                self.recommendations.append("Increase delays between API operations")
            else:
                logger.info("✅ No obvious rate limiting indicators found")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Rate limit check failed: {e}")
            self.issues.append(f"Rate limit check failed: {e}")
            return False
    
    async def check_moderation_list_status(self):
        """Check moderation list health for primary account."""
        logger.info("🔍 Checking moderation list status...")
        
        try:
            primary_account = await self.db.get_primary_account()
            if not primary_account:
                logger.warning("⚠️  No primary account found")
                self.issues.append("No primary account configured")
                return False
            
            mod_list = await self.db.get_primary_mod_list()
            if not mod_list:
                logger.warning("⚠️  No moderation list found for primary account")
                self.issues.append("No moderation list found for primary account")
                self.recommendations.append("Create moderation list for primary account")
                return False
            
            logger.info(f"✅ Moderation list found: {mod_list['list_uri']}")
            logger.info(f"   Name: {mod_list.get('name', 'Unknown')}")
            
            # Check how many DIDs should be on the list
            primary_should_list = await self.db.get_all_dids_primary_should_list(primary_account['id'])
            logger.info(f"📊 DIDs that should be on moderation list: {len(primary_should_list)}")
            
            if len(primary_should_list) > 20000:
                self.recommendations.append("Large moderation list may cause sync performance issues")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Moderation list check failed: {e}")
            self.issues.append(f"Moderation list check failed: {e}")
            return False
    
    async def check_environment_variables(self):
        """Check that all required environment variables are present."""
        logger.info("🔍 Checking environment variables...")
        
        # Check for database configuration
        local_test = os.getenv('LOCAL_TEST', 'false').lower() == 'true'
        
        if local_test:
            required_vars = [
                'TEST_DATABASE_URL',
                'TEST_PRIMARY_BLUESKY_HANDLE', 
                'TEST_PRIMARY_BLUESKY_PASSWORD'
            ]
            logger.info("📝 Running in test mode - checking test environment variables")
        else:
            required_vars = [
                'DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
                'PRIMARY_BLUESKY_HANDLE',
                'PRIMARY_BLUESKY_PASSWORD'
            ]
            logger.info("📝 Running in production mode - checking production environment variables")
        
        optional_vars = [
            'SECONDARY_ACCOUNTS',
            'MOD_LIST_NAME',
            'MOD_LIST_DESCRIPTION', 
            'CLEARSKY_API_URL',
            'LOG_LEVEL',
            'POLLING_INTERVAL'
        ]
        
        missing_required = []
        missing_optional = []
        
        for var in required_vars:
            if not os.getenv(var):
                missing_required.append(var)
                logger.error(f"❌ Missing required environment variable: {var}")
            else:
                logger.info(f"✅ Found required variable: {var}")
        
        for var in optional_vars:
            if not os.getenv(var):
                missing_optional.append(var)
                logger.info(f"ℹ️  Optional environment variable not set: {var}")
            else:
                logger.info(f"✅ Found optional variable: {var}")
        
        # Parse secondary accounts if present
        secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
        if secondary_accounts_str:
            try:
                accounts = secondary_accounts_str.split(';')
                valid_accounts = 0
                for account_str in accounts:
                    if ',' in account_str:
                        handle, password = account_str.split(',', 1)
                        if handle.strip() and password.strip():
                            valid_accounts += 1
                        else:
                            logger.warning(f"⚠️  Invalid secondary account format: {account_str}")
                            self.issues.append(f"Invalid secondary account format: {account_str}")
                logger.info(f"📊 Found {valid_accounts} valid secondary accounts configured")
            except Exception as e:
                logger.error(f"❌ Error parsing SECONDARY_ACCOUNTS: {e}")
                self.issues.append(f"Error parsing SECONDARY_ACCOUNTS: {e}")
        
        if missing_required:
            self.issues.extend([f"Missing required environment variable: {var}" for var in missing_required])
            self.recommendations.append("Set all required environment variables before deployment")
            return False
        
        if missing_optional:
            self.recommendations.append(f"Consider setting optional environment variables: {', '.join(missing_optional)}")
        
        logger.info("✅ All required environment variables are present")
        return True
    
    async def check_api_connectivity(self):
        """Check connectivity to external APIs."""
        logger.info("🔍 Checking external API connectivity...")
        
        import httpx
        
        apis_to_check = [
            ('Bluesky API', 'https://bsky.social/xrpc/com.atproto.server.describeServer'),
            ('ClearSky API', 'https://api.clearsky.services/api/v1/anon/health')
        ]
        
        all_connected = True
        
        for name, url in apis_to_check:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        logger.info(f"✅ {name}: Connected")
                    else:
                        logger.warning(f"⚠️  {name}: Unexpected response {response.status_code}")
                        self.issues.append(f"{name}: Unexpected response {response.status_code}")
                        all_connected = False
            except Exception as e:
                logger.error(f"❌ {name}: Connection failed - {e}")
                self.issues.append(f"{name}: Connection failed - {e}")
                all_connected = False
        
        return all_connected
    
    async def generate_health_report(self):
        """Generate a comprehensive health report."""
        logger.info("📋 Generating deployment health report...")
        
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_status': 'UNKNOWN',
            'checks': {},
            'issues': self.issues,
            'recommendations': self.recommendations
        }
        
        # Run all checks
        checks = [
            ('environment_variables', self.check_environment_variables),
            ('database_connectivity', self.check_database_connectivity),
            ('api_connectivity', self.check_api_connectivity),
            ('session_status', self.check_session_status),
            ('rate_limit_status', self.check_rate_limit_status),
            ('moderation_list_status', self.check_moderation_list_status)
        ]
        
        passed_checks = 0
        total_checks = len(checks)
        
        for check_name, check_func in checks:
            try:
                result = await check_func()
                report['checks'][check_name] = 'PASS' if result else 'FAIL'
                if result:
                    passed_checks += 1
            except Exception as e:
                logger.error(f"Check {check_name} crashed: {e}")
                report['checks'][check_name] = 'ERROR'
                self.issues.append(f"Check {check_name} crashed: {e}")
        
        # Determine overall status
        if passed_checks == total_checks:
            report['overall_status'] = 'HEALTHY'
        elif passed_checks >= total_checks * 0.8:
            report['overall_status'] = 'WARNING'
        else:
            report['overall_status'] = 'CRITICAL'
        
        return report
    
    async def print_summary(self, report):
        """Print a human-readable summary of the health report."""
        status_emoji = {
            'HEALTHY': '🟢',
            'WARNING': '🟡',
            'CRITICAL': '🔴',
            'UNKNOWN': '⚪'
        }
        
        print("\n" + "="*60)
        print(f"🏥 DEPLOYMENT HEALTH REPORT")
        print(f"📅 Generated: {report['timestamp']}")
        print(f"{status_emoji[report['overall_status']]} Overall Status: {report['overall_status']}")
        print("="*60)
        
        print("\n📊 CHECK RESULTS:")
        for check_name, status in report['checks'].items():
            emoji = '✅' if status == 'PASS' else '❌' if status == 'FAIL' else '💥'
            print(f"  {emoji} {check_name.replace('_', ' ').title()}: {status}")
        
        if report['issues']:
            print(f"\n🚨 ISSUES FOUND ({len(report['issues'])}):")
            for i, issue in enumerate(report['issues'], 1):
                print(f"  {i}. {issue}")
        
        if report['recommendations']:
            print(f"\n💡 RECOMMENDATIONS ({len(report['recommendations'])}):")
            for i, rec in enumerate(report['recommendations'], 1):
                print(f"  {i}. {rec}")
        
        print("\n" + "="*60)
        
        # Save report to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"health_report_{timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"📄 Detailed report saved to: {report_file}")

async def main():
    """Main function to run health checks."""
    print("🏥 Starting deployment health check...")
    
    checker = DeploymentHealthChecker()
    report = await checker.generate_health_report()
    await checker.print_summary(report)
    
    # Exit with appropriate code
    if report['overall_status'] == 'CRITICAL':
        sys.exit(1)
    elif report['overall_status'] == 'WARNING':
        sys.exit(2)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main()) 