#!/usr/bin/env python3

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from database import Database
from account_agent import AccountAgent

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

async def wait_for_rate_limit_reset():
    """Wait for rate limits to reset based on the deployment logs."""
    # From the logs, we can see the rate limit reset time: 'ratelimit-reset': '1747958429'
    # This is a Unix timestamp for when the rate limit resets
    
    # For now, let's wait a conservative amount of time
    logger.info("🕐 Waiting for rate limits to reset...")
    logger.info("   Based on deployment logs, the system hit 5000/hour API limits")
    logger.info("   Waiting 1 hour for limits to reset...")
    
    # Wait 1 hour (3600 seconds)
    await asyncio.sleep(3600)
    logger.info("✅ Rate limit wait period completed")

async def check_account_session_validity():
    """Check and repair account sessions."""
    logger.info("🔍 Checking account session validity...")
    
    db = Database()
    accounts = [
        ('symm.social', True),
        ('symm.app', False),
        ('symm.now', False),
        ('this.is-a.bot', False),
        ('gemini.is-a.bot', False)
    ]
    
    for handle, is_primary in accounts:
        password_env = handle.replace('.', '_').replace('-', '_').upper() + '_PASSWORD'
        password = os.getenv(password_env)
        
        if not password:
            logger.warning(f"⚠️  No password for {handle}, skipping")
            continue
        
        try:
            agent = AccountAgent(handle, password, is_primary=is_primary, database=db)
            session_data = await agent._load_session_from_storage()
            
            if session_data:
                if agent._is_refresh_token_expired(session_data):
                    logger.warning(f"🔄 {handle}: Refresh token expired, will need fresh login")
                elif agent._is_access_token_expired(session_data):
                    logger.info(f"🔄 {handle}: Access token expired, attempting refresh...")
                    refreshed = await agent._refresh_access_token(session_data)
                    if refreshed:
                        logger.info(f"✅ {handle}: Session refreshed successfully")
                    else:
                        logger.warning(f"❌ {handle}: Session refresh failed")
                else:
                    logger.info(f"✅ {handle}: Session is valid")
            else:
                logger.info(f"ℹ️  {handle}: No existing session found")
                
        except Exception as e:
            logger.error(f"❌ {handle}: Error checking session - {e}")

async def perform_conservative_mod_list_sync():
    """Perform a very conservative moderation list sync to avoid rate limits."""
    logger.info("🔄 Starting conservative moderation list sync...")
    
    db = Database()
    
    # Get primary account
    primary_account = await db.get_primary_account()
    if not primary_account:
        logger.error("❌ No primary account found")
        return
    
    # Initialize primary agent
    password = os.getenv('SYMM_SOCIAL_PASSWORD')
    if not password:
        logger.error("❌ No password for primary account")
        return
    
    agent = AccountAgent('symm.social', password, is_primary=True, database=db)
    
    try:
        # Login with session management
        login_success = await agent._login_with_session_management()
        if not login_success:
            logger.error("❌ Failed to login to primary account")
            return
        
        logger.info("✅ Successfully logged in to primary account")
        
        # Check if we have a moderation list
        if not agent.mod_list_uri:
            logger.info("🔧 Creating moderation list...")
            await agent.create_or_update_moderation_list()
        
        if agent.mod_list_uri:
            logger.info(f"📋 Moderation list URI: {agent.mod_list_uri}")
            
            # Get DIDs that should be on the list
            dids_to_sync = await db.get_all_dids_primary_should_list(agent.account_id)
            logger.info(f"📊 Found {len(dids_to_sync)} DIDs to potentially sync")
            
            if len(dids_to_sync) > 1000:
                logger.warning("⚠️  Large number of DIDs to sync - this will take a long time")
                logger.warning("   Consider running this sync during off-peak hours")
                
                # Ask for confirmation
                print(f"\nFound {len(dids_to_sync)} DIDs to sync to moderation list.")
                print("This will take several hours with conservative rate limiting.")
                response = input("Continue? (y/N): ").strip().lower()
                
                if response != 'y':
                    logger.info("❌ Sync cancelled by user")
                    return
            
            # Perform sync with very conservative settings
            logger.info("🚀 Starting conservative moderation list sync...")
            await agent.sync_mod_list_with_database()
            logger.info("✅ Moderation list sync completed")
        
    except Exception as e:
        logger.error(f"❌ Error during moderation list sync: {e}")
    finally:
        await agent.stop_monitoring()

async def main():
    """Main recovery function."""
    logger.info("🚀 Starting rate limit recovery process...")
    
    print("\n" + "="*60)
    print("🚨 RATE LIMIT RECOVERY TOOL")
    print("="*60)
    print()
    print("This tool will help recover from rate limiting issues by:")
    print("1. Waiting for rate limits to reset")
    print("2. Checking and repairing account sessions") 
    print("3. Performing conservative moderation list sync")
    print()
    
    # Ask what to do
    print("Select an option:")
    print("1. Wait for rate limits to reset (1 hour)")
    print("2. Check account sessions only")
    print("3. Perform conservative mod list sync")
    print("4. Full recovery (all of the above)")
    print("5. Exit")
    
    choice = input("\nEnter your choice (1-5): ").strip()
    
    if choice == '1':
        await wait_for_rate_limit_reset()
    elif choice == '2':
        await check_account_session_validity()
    elif choice == '3':
        await perform_conservative_mod_list_sync()
    elif choice == '4':
        logger.info("🔧 Starting full recovery process...")
        await wait_for_rate_limit_reset()
        await check_account_session_validity()
        await perform_conservative_mod_list_sync()
        logger.info("✅ Full recovery process completed")
    elif choice == '5':
        logger.info("👋 Exiting...")
        return
    else:
        logger.error("❌ Invalid choice")
        return
    
    logger.info("🎉 Recovery process completed!")

if __name__ == "__main__":
    asyncio.run(main()) 