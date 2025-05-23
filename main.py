#!/usr/bin/env python3
"""
Production Main Script for Symm Bluesky Userbot

This script provides a production-ready orchestrator with:
- Comprehensive health monitoring
- Intelligent retry mechanisms  
- Beautiful, accessible logging
- Graceful error recovery
- Performance tracking
- Interactive diagnostics
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Import enhanced utilities
try:
    from utils import (
        get_logger, get_performance_monitor, async_retry, RetryConfig,
        HealthChecker, logged_operation, create_timestamped_filename, format_error
    )
    from diagnostic_tools import SystemDiagnostics, run_interactive_diagnostics
    logger = get_logger('main')
    performance_monitor = get_performance_monitor()
    use_enhanced_utils = True
except ImportError:
    # Fallback for basic functionality
    import logging
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
    logger = logging.getLogger('main')
    performance_monitor = None
    use_enhanced_utils = False

# Import existing modules
from account_agent import AccountAgent
from database import Database, close_connection_pool
from setup_db import setup_database
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

class ProductionOrchestrator:
    """Production orchestrator for the Bluesky userbot system"""
    
    def __init__(self):
        self.logger = get_logger('orchestrator') if use_enhanced_utils else logger
        self.health_checker = HealthChecker() if use_enhanced_utils else None
        self.performance_monitor = get_performance_monitor() if use_enhanced_utils else None
        
        # System state
        self.agents: List[AccountAgent] = []
        self.database: Optional[Database] = None
        self.shutdown_event = asyncio.Event()
        self.is_healthy = True
        self.last_health_check = datetime.now()
        
        # Configuration
        self.health_check_interval = int(os.getenv('HEALTH_CHECK_INTERVAL', '300'))  # 5 minutes
        self.max_consecutive_failures = int(os.getenv('MAX_CONSECUTIVE_FAILURES', '3'))
        self.consecutive_failures = 0
        
        # Performance tracking
        self.operation_counts = {
            'database_operations': 0,
            'api_requests': 0,
            'health_checks': 0,
            'errors': 0
        }
        
        self.logger.info("🚀 Production Orchestrator initialized")
    
    async def startup_sequence(self, skip_diagnostics: bool = False, 
                             skip_clearsky_init: bool = False,
                             skip_modlist_sync: bool = False) -> bool:
        """Execute the complete startup sequence with comprehensive error handling"""
        self.logger.info("🔄 Starting production startup sequence")
        
        try:
            # Phase 1: Pre-flight checks
            if not skip_diagnostics:
                async with logged_operation("Pre-flight Diagnostics", self.logger):
                    if not await self._run_diagnostics():
                        self.logger.error("❌ Pre-flight diagnostics failed")
                        return False
            
            # Phase 2: Database setup
            async with logged_operation("Database Setup", self.logger):
                if not await self._setup_database():
                    self.logger.error("❌ Database setup failed")
                    return False
            
            # Phase 3: Account initialization (creates accounts with placeholder DIDs)
            async with logged_operation("Account Initialization", self.logger):
                if not await self._initialize_accounts():
                    self.logger.error("❌ Account initialization failed")
                    return False
            
            # Phase 4: Agent initialization (updates DIDs to real ones)
            async with logged_operation("Agent Initialization", self.logger):
                if not await self._initialize_agents():
                    self.logger.error("❌ Agent initialization failed")
                    return False
            
            # Phase 5: ClearSky population (now that we have real DIDs)
            if not skip_clearsky_init:
                async with logged_operation("ClearSky Population", self.logger):
                    await self._populate_clearsky_data()
            
            # Phase 6: Moderation list sync (optional)
            if not skip_modlist_sync:
                async with logged_operation("Moderation List Sync", self.logger):
                    await self._sync_moderation_lists()
            
            self.logger.success("✅ Startup sequence completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"💥 Startup sequence failed: {format_error(e)}")
            return False
    
    @async_retry(RetryConfig(max_attempts=3, base_delay=2.0))
    async def _setup_database(self) -> bool:
        """Setup and verify database with retry logic"""
        try:
            self.logger.info("🗄️  Setting up database schema...")
            await setup_database(force_local=False)
            
            # Verify database setup
            if not await self._verify_database_setup():
                raise Exception("Database verification failed after setup")
            
            self.database = Database()
            self.logger.success("✅ Database setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Database setup failed: {e}")
            raise
    
    async def _verify_database_setup(self) -> bool:
        """Verify database schema and connectivity"""
        try:
            db = Database()
            
            # Test connection
            if not await db.test_connection():
                self.logger.error("Database connection test failed")
                return False
            
            # Check required tables
            required_tables = ['accounts', 'blocked_accounts', 'mod_lists']
            query = """
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = ANY($1)
            """
            
            result = await db.execute_query(query, [required_tables])
            existing_tables = [row['table_name'] for row in result]
            
            missing_tables = set(required_tables) - set(existing_tables)
            if missing_tables:
                self.logger.error(f"Missing required tables: {missing_tables}")
                return False
            
            self.logger.success("✅ Database schema verified")
            return True
            
        except Exception as e:
            self.logger.error(f"Database verification failed: {e}")
            return False
    
    @async_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    async def _initialize_accounts(self) -> bool:
        """Initialize accounts in database with retry logic"""
        try:
            if not self.database:
                self.database = Database()
            
            success = await self.database.initialize_default_accounts()
            if not success:
                raise Exception("Account initialization returned False")
            
            # Verify accounts were created
            configurations = await self.database.get_account_configurations()
            accounts = configurations['accounts']
            
            if not accounts:
                raise Exception("No accounts found after initialization")
            
            self.logger.success(f"✅ Initialized {len(accounts)} accounts")
            for account in accounts:
                status = "PRIMARY" if account['is_primary'] else "secondary"
                self.logger.info(f"  📱 {account['handle']} ({status})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Account initialization failed: {e}")
            raise
    
    async def _populate_clearsky_data(self) -> bool:
        """Populate block data from ClearSky with error handling"""
        try:
            self.logger.info("🌐 Populating block data from ClearSky...")
            
            if not self.database:
                self.database = Database()
            
            # Get managed accounts
            primary_account = await self.database.get_primary_account()
            secondary_accounts = await self.database.get_secondary_accounts() or []
            
            if not primary_account:
                self.logger.warning("No primary account found, skipping ClearSky population")
                return False
            
            accounts = [primary_account] + secondary_accounts
            total_blocks_added = 0
            
            for account in accounts:
                try:
                    account_blocks = await self._fetch_account_blocks(account)
                    total_blocks_added += account_blocks
                    
                    # Rate limiting between accounts
                    await asyncio.sleep(2.0)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to fetch blocks for {account['handle']}: {e}")
                    continue
            
            self.logger.success(f"✅ ClearSky population completed. Added {total_blocks_added} block relationships")
            return True
            
        except Exception as e:
            self.logger.error(f"ClearSky population failed: {e}")
            return False
    
    async def _fetch_account_blocks(self, account: Dict) -> int:
        """Fetch blocks for a specific account from ClearSky"""
        account_did = account['did']
        account_handle = account['handle']
        account_id = account['id']
        
        # Skip if account has placeholder DID (not yet authenticated)
        if account_did.startswith('placeholder_'):
            self.logger.warning(f"⚠️  Skipping ClearSky fetch for {account_handle} - placeholder DID not yet updated")
            return 0
        
        blocks_added = 0
        
        try:
            # Fetch who this account is blocking
            self.logger.info(f"🔍 Fetching blocks for {account_handle}...")
            blocking_data = await cs.fetch_from_clearsky(f"/blocklist/{account_did}")
            
            if blocking_data and 'data' in blocking_data and 'blocklist' in blocking_data['data']:
                blocklist = blocking_data['data']['blocklist']
                if blocklist:
                    for block_info in blocklist:
                        blocked_did = block_info.get('did')
                        if blocked_did:
                            await self.database.add_blocked_account(
                                did=blocked_did,
                                handle=None,
                                source_account_id=account_id,
                                block_type='blocking',
                                reason="Imported from ClearSky"
                            )
                            blocks_added += 1
            
            # Fetch who is blocking this account
            self.logger.info(f"🔍 Fetching blocked-by for {account_handle}...")
            blocked_by_data, total_count = await cs.fetch_all_blocked_by(account_did)
            
            if blocked_by_data:
                processed_dids = set()
                for blocker in blocked_by_data:
                    blocker_did = blocker.get('did')
                    if blocker_did and blocker_did not in processed_dids:
                        processed_dids.add(blocker_did)
                        await self.database.add_blocked_account(
                            did=blocker_did,
                            handle=None,
                            source_account_id=account_id,
                            block_type='blocked_by',
                            reason="Imported from ClearSky"
                        )
                        blocks_added += 1
            
            self.logger.success(f"✅ Added {blocks_added} blocks for {account_handle}")
            return blocks_added
            
        except Exception as e:
            self.logger.error(f"Failed to fetch blocks for {account_handle}: {e}")
            return 0
    
    @async_retry(RetryConfig(max_attempts=3, base_delay=1.0))
    async def _initialize_agents(self) -> bool:
        """Initialize account agents with retry logic"""
        try:
            self.logger.info("🤖 Initializing account agents...")
            
            # Get account credentials
            primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
            primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
            
            if not primary_handle or not primary_password:
                raise Exception("Primary account credentials not configured")
            
            # Initialize primary agent
            primary_agent = AccountAgent(
                handle=primary_handle,
                password=primary_password,
                is_primary=True,
                database=self.database
            )
            
            if not await primary_agent.login():
                error_msg = f"Failed to login primary agent: {primary_handle}"
                self.logger.error(f"❌ {error_msg}")
                self.logger.error("💡 If this is a rate limit error:")
                self.logger.error("   • Wait 24 hours for the daily limit to reset")
                self.logger.error("   • Or create a session file manually using create_manual_session.py")
                self.logger.error("   • Or check existing session files with check_session_status.py")
                raise Exception(error_msg)
            
            self.agents.append(primary_agent)
            self.logger.success(f"✅ Primary agent initialized: {primary_handle}")
            
            # Initialize secondary agents
            secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
            if secondary_accounts_str:
                secondary_count = await self._initialize_secondary_agents(secondary_accounts_str)
                self.logger.info(f"📱 Initialized {secondary_count} secondary agents")
            
            self.logger.success(f"✅ All agents initialized ({len(self.agents)} total)")
            return True
            
        except Exception as e:
            self.logger.error(f"Agent initialization failed: {e}")
            raise
    
    async def _initialize_secondary_agents(self, secondary_accounts_str: str) -> int:
        """Initialize secondary account agents"""
        accounts = secondary_accounts_str.split(';')
        initialized_count = 0
        
        for i, account_str in enumerate(accounts):
            try:
                # Parse account credentials
                if ':' in account_str:
                    handle, password = account_str.split(':', 1)
                elif ',' in account_str:
                    handle, password = account_str.split(',', 1)
                else:
                    self.logger.warning(f"Invalid account format: {account_str}")
                    continue
                
                handle = handle.strip()
                password = password.strip()
                
                # Add delay between login attempts to avoid rate limiting
                if i > 0:
                    delay = 30  # 30 seconds between each login attempt
                    self.logger.info(f"⏳ Waiting {delay}s before next login attempt to avoid rate limits...")
                    await asyncio.sleep(delay)
                
                # Initialize agent
                agent = AccountAgent(
                    handle=handle,
                    password=password,
                    is_primary=False,
                    database=self.database
                )
                
                if await agent.login():
                    self.agents.append(agent)
                    initialized_count += 1
                    self.logger.success(f"✅ Secondary agent initialized: {handle}")
                else:
                    self.logger.warning(f"⚠️  Failed to login secondary agent: {handle}")
                    
            except Exception as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg or "too many requests" in error_msg:
                    self.logger.error(f"🚫 Rate limit hit for {handle}. You may need to wait 24 hours before retrying.")
                    # Continue with other accounts instead of failing completely
                    continue
                else:
                    self.logger.error(f"Error initializing secondary agent {account_str}: {e}")
                    continue
        
        return initialized_count
    
    async def _sync_moderation_lists(self) -> bool:
        """Sync blocks to moderation lists"""
        try:
            self.logger.info("📋 Syncing moderation lists...")
            
            # Use primary agent's sync method
            primary_agent = None
            for agent in self.agents:
                if agent.is_primary:
                    primary_agent = agent
                    break
            
            if primary_agent:
                success = await primary_agent.sync_mod_list_with_database()
                if success:
                    self.logger.success("✅ Moderation list sync completed")
                else:
                    self.logger.warning("⚠️  Moderation list sync reported failure")
                return success
            else:
                self.logger.warning("⚠️  No primary agent found for moderation list sync")
                return False
            
        except Exception as e:
            self.logger.error(f"Moderation list sync failed: {e}")
            return False
    
    async def _run_diagnostics(self) -> bool:
        """Run system diagnostics"""
        try:
            self.logger.info("🔍 Running system diagnostics...")
            
            if use_enhanced_utils:
                from diagnostic_tools import SystemDiagnostics
                diagnostics = SystemDiagnostics()
                results = await diagnostics.run_all_checks()
                
                # Check if any critical failures
                critical_failures = [r for r in results if r.status == 'fail']
                if critical_failures:
                    self.logger.error(f"❌ {len(critical_failures)} critical diagnostic failures")
                    return False
                
                # Save results
                filename = diagnostics.save_results()
                self.logger.info(f"📊 Diagnostic results saved to {filename}")
                
            else:
                self.logger.warning("Enhanced diagnostics not available, running basic checks")
                if not await self._basic_health_checks():
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Diagnostics failed: {e}")
            return False
    
    async def _basic_health_checks(self) -> bool:
        """Basic health checks when enhanced utils not available"""
        try:
            # Check database
            db = Database()
            if not await db.test_connection():
                self.logger.error("Database connection failed")
                return False
            
            # Check environment variables
            required_vars = ['PRIMARY_BLUESKY_HANDLE', 'PRIMARY_BLUESKY_PASSWORD']
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                self.logger.error(f"Missing environment variables: {missing_vars}")
                return False
            
            self.logger.success("✅ Basic health checks passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Basic health checks failed: {e}")
            return False
    
    async def run_production_mode(self) -> bool:
        """Run the system in production mode with monitoring"""
        try:
            self.logger.info("🚀 Starting production mode")
            
            # Start all agents
            await self._start_all_agents()
            
            # Set up signal handlers
            self._setup_signal_handlers()
            
            # Start health monitoring
            health_task = asyncio.create_task(self._health_monitoring_loop())
            
            # Main monitoring loop
            self.logger.success("✅ Production mode active - system is running")
            
            try:
                await self.shutdown_event.wait()
            except KeyboardInterrupt:
                self.logger.info("🛑 Keyboard interrupt received")
            
            # Cleanup
            health_task.cancel()
            await self._shutdown_all_agents()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Production mode failed: {format_error(e)}")
            return False
    
    async def _start_all_agents(self):
        """Start monitoring for all agents"""
        self.logger.info("🤖 Starting agent monitoring...")
        
        start_tasks = []
        for agent in self.agents:
            start_tasks.append(agent.start_monitoring())
        
        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)
            self.logger.success(f"✅ Started monitoring for {len(self.agents)} agents")
    
    async def _shutdown_all_agents(self):
        """Gracefully shutdown all agents"""
        self.logger.info("🛑 Shutting down agents...")
        
        shutdown_tasks = []
        for agent in self.agents:
            shutdown_tasks.append(agent.stop_monitoring())
        
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)
        
        # Close database connection pool
        await close_connection_pool()
        
        self.logger.success("✅ All agents shut down gracefully")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"🛑 Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self._initiate_shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _initiate_shutdown(self):
        """Initiate graceful shutdown"""
        self.logger.info("🛑 Initiating graceful shutdown...")
        self.shutdown_event.set()
    
    async def _health_monitoring_loop(self):
        """Continuous health monitoring loop"""
        self.logger.info(f"💚 Starting health monitoring (interval: {self.health_check_interval}s)")
        
        while not self.shutdown_event.is_set():
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(30)  # Brief pause before retrying
    
    async def _perform_health_check(self):
        """Perform periodic health checks"""
        try:
            self.operation_counts['health_checks'] += 1
            
            # Check database health
            if self.database:
                db_healthy = await self.database.test_connection()
                if not db_healthy:
                    self.consecutive_failures += 1
                    self.logger.warning(f"⚠️  Database health check failed (failures: {self.consecutive_failures})")
                else:
                    self.consecutive_failures = 0
            
            # Check if we've exceeded failure threshold
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.logger.error(f"❌ Max consecutive failures reached ({self.consecutive_failures})")
                self.is_healthy = False
                # Could implement recovery actions here
            
            # Update last health check time
            self.last_health_check = datetime.now()
            
            # Log periodic status
            if self.operation_counts['health_checks'] % 12 == 0:  # Every hour if 5min intervals
                self._log_system_status()
                
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self.consecutive_failures += 1
    
    def _log_system_status(self):
        """Log periodic system status"""
        uptime = datetime.now() - self.last_health_check
        
        self.logger.info("📊 System Status Report:")
        self.logger.info(f"  🤖 Active Agents: {len(self.agents)}")
        self.logger.info(f"  💚 System Health: {'Healthy' if self.is_healthy else 'Degraded'}")
        self.logger.info(f"  🔄 Health Checks: {self.operation_counts['health_checks']}")
        self.logger.info(f"  ❌ Consecutive Failures: {self.consecutive_failures}")
        
        if self.performance_monitor:
            stats = self.performance_monitor.get_all_stats()
            if stats['operations']:
                self.logger.info("  ⚡ Performance Summary:")
                for op, metrics in list(stats['operations'].items())[:3]:  # Top 3
                    self.logger.info(f"    {op}: {metrics.get('count', 0)} ops, avg {metrics.get('avg', 0):.3f}s")

async def run_test_mode() -> bool:
    """Run system in test mode"""
    logger.info("🧪 Running in test mode - no persistent changes")
    
    try:
        orchestrator = ProductionOrchestrator()
        
        # Run diagnostics only
        if not await orchestrator._run_diagnostics():
            logger.error("❌ Test mode diagnostics failed")
            return False
        
        # Test database connection
        if not await orchestrator._verify_database_setup():
            logger.warning("⚠️  Database verification failed in test mode")
            return False
        
        logger.success("✅ Test mode completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test mode failed: {format_error(e)}")
        return False

async def main():
    """Main entry point with comprehensive argument parsing"""
    parser = argparse.ArgumentParser(
        description='Symm Bluesky Userbot - Production Ready',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                     # Run in production mode
  python main.py --test              # Run in test mode
  python main.py --diagnostics       # Run diagnostics only
  python main.py --interactive       # Interactive diagnostic session
  python main.py --skip-clearsky     # Skip ClearSky initialization
        """
    )
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--test', action='store_true',
                           help='Run in test mode (no persistent changes)')
    mode_group.add_argument('--diagnostics', action='store_true',
                           help='Run diagnostics only and exit')
    mode_group.add_argument('--interactive', action='store_true',
                           help='Run interactive diagnostic session')
    
    # Skip options
    parser.add_argument('--skip-diagnostics', action='store_true',
                       help='Skip pre-flight diagnostics')
    parser.add_argument('--skip-clearsky', action='store_true',
                       help='Skip ClearSky data initialization')
    parser.add_argument('--skip-modlist-sync', action='store_true',
                       help='Skip moderation list synchronization')
    
    # Logging options
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default=os.getenv('LOG_LEVEL', 'INFO'),
                       help='Set logging level')
    parser.add_argument('--log-file', type=str,
                       help='Log to file in addition to console')
    
    args = parser.parse_args()
    
    # Set log level
    if use_enhanced_utils:
        # The enhanced logger will pick up the LOG_LEVEL env var
        os.environ['LOG_LEVEL'] = args.log_level
    
    # Handle different modes
    try:
        if args.interactive:
            logger.info("🔧 Starting interactive diagnostic session")
            await run_interactive_diagnostics()
            return True
            
        elif args.diagnostics:
            logger.info("🔍 Running diagnostics only")
            if use_enhanced_utils:
                from diagnostic_tools import SystemDiagnostics
                diagnostics = SystemDiagnostics()
                await diagnostics.run_all_checks()
                diagnostics.save_results()
            else:
                logger.warning("Enhanced diagnostics not available")
            return True
            
        elif args.test:
            return await run_test_mode()
            
        else:
            # Production mode
            logger.info("🚀 Starting production mode")
            orchestrator = ProductionOrchestrator()
            
            # Run startup sequence
            startup_success = await orchestrator.startup_sequence(
                skip_diagnostics=args.skip_diagnostics,
                skip_clearsky_init=args.skip_clearsky,
                skip_modlist_sync=args.skip_modlist_sync
            )
            
            if not startup_success:
                logger.error("❌ Startup sequence failed")
                return False
            
            # Run production mode
            return await orchestrator.run_production_mode()
            
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
        return True
    except Exception as e:
        logger.error(f"💥 Fatal error: {format_error(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit_code = 0 if success else 1
    logger.info(f"🏁 Exiting with code {exit_code}")
    sys.exit(exit_code) 