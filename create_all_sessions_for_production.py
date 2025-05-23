#!/usr/bin/env python3
"""
Create All Sessions for Production

This script authenticates all accounts and saves their sessions to the database
so the production environment can use them without hitting rate limits.

IMPORTANT: This will use login attempts, so should only be run when needed
and when accounts aren't rate limited.

Usage:
    python create_all_sessions_for_production.py
"""

import asyncio
import os
import logging
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient as ATProtoAsyncClient

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_account_credentials():
    """Get all account credentials from environment variables"""
    credentials = {}
    
    # Primary account
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if primary_handle and primary_password:
        credentials[primary_handle] = {
            'password': primary_password,
            'is_primary': True
        }
        logger.info(f"📱 Found primary account: {primary_handle}")
    
    # Secondary accounts
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    if secondary_accounts_str:
        for account_str in secondary_accounts_str.split(';'):
            if ':' in account_str:
                handle, password = account_str.split(':', 1)
            elif ',' in account_str:
                handle, password = account_str.split(',', 1)
            else:
                logger.warning(f"⚠️ Invalid account format: {account_str}")
                continue
            
            handle = handle.strip()
            password = password.strip()
            
            credentials[handle] = {
                'password': password,
                'is_primary': False
            }
            logger.info(f"📱 Found secondary account: {handle}")
    
    logger.info(f"📊 Total accounts found: {len(credentials)}")
    return credentials

async def check_existing_session(handle, db):
    """Check if account already has a valid session in database"""
    try:
        session_data = await db.load_session_data(handle)
        if session_data:
            logger.info(f"✅ {handle}: Already has session in database (DID: {session_data['did']})")
            return True
        else:
            logger.info(f"❌ {handle}: No session found in database")
            return False
    except Exception as e:
        logger.error(f"❌ {handle}: Error checking session: {e}")
        return False

async def create_session_for_account(handle, password, is_primary, db):
    """Create a session for a single account"""
    logger.info(f"🔑 Creating session for {handle}...")
    
    client = ATProtoAsyncClient()
    
    try:
        # Attempt authentication
        logger.info(f"🔐 Authenticating {handle}...")
        profile = await client.login(handle, password)
        did = profile.did
        
        logger.info(f"✅ Authentication successful for {handle}! DID: {did}")
        
        # Get session data
        session_string = client.export_session_string()
        from atproto_client.client.session import Session
        session_obj = Session.decode(session_string)
        
        # Create session data structure
        session_data = {
            'handle': handle,
            'did': did,
            'accessJwt': session_obj.access_jwt,
            'refreshJwt': session_obj.refresh_jwt,
            'accessDate': datetime.now(timezone.utc).isoformat(),
            'refreshDate': datetime.now(timezone.utc).isoformat()
        }
        
        # Save to database
        success = await db.save_session_data(
            handle=session_data['handle'],
            did=session_data['did'],
            access_jwt=session_data['accessJwt'],
            refresh_jwt=session_data['refreshJwt']
        )
        
        if success:
            logger.info(f"✅ {handle}: Session saved to database")
            
            # Also save to local file for backup
            filename = f"session_{handle.replace('.', '_').replace('@', '_')}.json"
            with open(filename, 'w') as f:
                json.dump(session_data, f, indent=2)
            logger.info(f"✅ {handle}: Session also saved to {filename}")
            
            return True
        else:
            logger.error(f"❌ {handle}: Failed to save session to database")
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "ratelimitexceeded" in error_msg or "429" in str(e):
            logger.error(f"🚫 {handle}: Rate limited - {e}")
            logger.error(f"⏳ {handle}: Account has hit daily login limit. Wait ~24 hours before retrying.")
            return False
        else:
            logger.error(f"❌ {handle}: Authentication failed - {e}")
            return False

async def main():
    """Main function to create sessions for all accounts"""
    logger.info("🚀 Creating sessions for all accounts...")
    
    # Get account credentials
    credentials = await get_account_credentials()
    if not credentials:
        logger.error("❌ No account credentials found in environment variables")
        return
    
    # Initialize database
    try:
        db = Database()
        logger.info("✅ Database connection established")
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        return
    
    # Check existing sessions first
    logger.info("\n" + "="*60)
    logger.info("CHECKING EXISTING SESSIONS")
    logger.info("="*60)
    
    accounts_needing_sessions = []
    for handle, cred_info in credentials.items():
        if not await check_existing_session(handle, db):
            accounts_needing_sessions.append((handle, cred_info))
    
    if not accounts_needing_sessions:
        logger.info("🎉 All accounts already have sessions in database!")
        return
    
    logger.info(f"\n📊 {len(accounts_needing_sessions)} accounts need new sessions")
    
    # Ask for confirmation since this uses login attempts
    logger.info("\n⚠️ WARNING: This will attempt to login to accounts that don't have sessions.")
    logger.info("⚠️ This could hit rate limits if accounts have already logged in recently.")
    
    try:
        response = input("\nDo you want to proceed? (y/N): ")
        if response.lower() != 'y':
            logger.info("❌ Aborted by user")
            return
    except KeyboardInterrupt:
        logger.info("\n❌ Aborted by user")
        return
    
    # Create sessions for accounts that need them
    logger.info("\n" + "="*60)
    logger.info("CREATING NEW SESSIONS")
    logger.info("="*60)
    
    created_count = 0
    failed_count = 0
    
    for i, (handle, cred_info) in enumerate(accounts_needing_sessions):
        # Add delay between login attempts to avoid rate limiting
        if i > 0:
            delay = 30  # 30 seconds between attempts
            logger.info(f"⏳ Waiting {delay}s before next login attempt...")
            await asyncio.sleep(delay)
        
        if await create_session_for_account(handle, cred_info['password'], cred_info['is_primary'], db):
            created_count += 1
        else:
            failed_count += 1
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("FINAL SUMMARY")
    logger.info("="*60)
    
    total_accounts = len(credentials)
    existing_sessions = total_accounts - len(accounts_needing_sessions)
    
    logger.info(f"📊 Total accounts: {total_accounts}")
    logger.info(f"✅ Already had sessions: {existing_sessions}")
    logger.info(f"✅ Successfully created: {created_count}")
    logger.info(f"❌ Failed to create: {failed_count}")
    
    total_with_sessions = existing_sessions + created_count
    logger.info(f"🎯 Total accounts with sessions: {total_with_sessions}/{total_accounts}")
    
    if total_with_sessions == total_accounts:
        logger.info("\n🎉 ALL ACCOUNTS NOW HAVE SESSIONS IN DATABASE!")
        logger.info("✅ Production environment is ready to go!")
    else:
        logger.warning(f"\n⚠️ {failed_count} accounts still need sessions")
        logger.warning("💡 Check for rate limiting issues and retry later if needed")
    
    # List final status
    logger.info("\n📋 Final session status:")
    for handle in credentials.keys():
        session_exists = await check_existing_session(handle, db)
        status = "✅ HAS SESSION" if session_exists else "❌ NO SESSION"
        logger.info(f"  {handle}: {status}")

if __name__ == "__main__":
    asyncio.run(main()) 