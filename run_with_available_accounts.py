#!/usr/bin/env python3
"""
Run Bot with Available Accounts Only

This script runs the bot system but gracefully handles rate-limited accounts
by skipping them and continuing with accounts that can login successfully.
"""

import asyncio
import os
import logging
from dotenv import load_dotenv

from account_agent import AccountAgent
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

async def test_account_login(handle, password, is_primary=False):
    """Test if an account can login successfully."""
    try:
        logger.info(f"🧪 Testing login for {handle}...")
        
        agent = AccountAgent(
            handle=handle,
            password=password,
            is_primary=is_primary,
            database=Database()
        )
        
        success = await agent.login()
        if success:
            logger.info(f"✅ {handle} login successful")
            return agent
        else:
            logger.warning(f"❌ {handle} login failed")
            return None
            
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "ratelimitexceeded" in error_msg:
            logger.error(f"🚫 {handle} is rate limited - skipping")
        else:
            logger.error(f"❌ {handle} error: {e}")
        return None

async def run_with_available_accounts():
    """Run the bot with only accounts that can login."""
    logger.info("🚀 Starting bot with available accounts only")
    
    # Set up database
    db = Database()
    if not await db.test_connection():
        logger.error("❌ Database connection failed")
        return False
    
    # Test primary account
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("❌ Primary account credentials not configured")
        return False
    
    logger.info("🔑 Testing primary account...")
    primary_agent = await test_account_login(primary_handle, primary_password, is_primary=True)
    
    available_agents = []
    if primary_agent:
        available_agents.append(primary_agent)
        logger.info(f"✅ Primary account available: {primary_handle}")
    else:
        logger.warning(f"⚠️  Primary account {primary_handle} is not available")
        logger.info("💡 You can still run with secondary accounts only")
    
    # Test secondary accounts
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    if secondary_accounts_str:
        logger.info("🔑 Testing secondary accounts...")
        accounts = secondary_accounts_str.split(';')
        
        for i, account_str in enumerate(accounts):
            try:
                # Parse credentials
                if ':' in account_str:
                    handle, password = account_str.split(':', 1)
                elif ',' in account_str:
                    handle, password = account_str.split(',', 1)
                else:
                    logger.warning(f"Invalid format: {account_str}")
                    continue
                
                handle = handle.strip()
                password = password.strip()
                
                # Add delay between tests
                if i > 0:
                    logger.info("⏳ Waiting 30s between login tests...")
                    await asyncio.sleep(30)
                
                agent = await test_account_login(handle, password, is_primary=False)
                if agent:
                    available_agents.append(agent)
                    
            except Exception as e:
                logger.error(f"Error testing {account_str}: {e}")
                continue
    
    # Summary
    logger.info(f"📊 Available accounts: {len(available_agents)}")
    for agent in available_agents:
        logger.info(f"   ✅ {agent.handle}")
    
    if not available_agents:
        logger.error("❌ No accounts available! All may be rate limited.")
        logger.info("💡 Suggestions:")
        logger.info("   • Wait 24 hours for rate limits to reset")
        logger.info("   • Create session files manually with create_manual_session.py")
        logger.info("   • Check session status with check_session_status.py")
        return False
    
    # Start monitoring with available agents
    logger.info("🤖 Starting monitoring with available accounts...")
    
    try:
        # Start all agents
        start_tasks = []
        for agent in available_agents:
            start_tasks.append(agent.start_monitoring())
        
        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)
            logger.info(f"✅ Started monitoring for {len(available_agents)} agents")
        
        # Keep running
        logger.info("🔄 Bot is running... Press Ctrl+C to stop")
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                logger.debug(f"📊 Monitoring {len(available_agents)} agents...")
        except KeyboardInterrupt:
            logger.info("🛑 Shutdown requested")
        
        # Stop all agents
        stop_tasks = []
        for agent in available_agents:
            stop_tasks.append(agent.stop_monitoring())
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
            logger.info("✅ All agents stopped")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during monitoring: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(run_with_available_accounts()) 