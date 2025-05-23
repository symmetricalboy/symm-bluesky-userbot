#!/usr/bin/env python3
"""
Fix Deployment Issues

This script fixes two main issues:
1. Creates a valid session for this.is-a.bot using manual authentication
2. Resolves placeholder DIDs before ClearSky checks are run

Usage:
    python fix_deployment_issues.py
"""

import asyncio
import os
import logging
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from database import Database
from account_agent import AccountAgent
from atproto import AsyncClient as ATProtoAsyncClient

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def create_valid_session_for_this_is_a_bot():
    """Create a valid session for this.is-a.bot using manual authentication"""
    logger.info("🔧 Creating valid session for this.is-a.bot...")
    
    # Get credentials from environment
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    
    # Find this.is-a.bot credentials
    this_is_a_bot_password = None
    for account_str in secondary_accounts_str.split(';'):
        if ':' in account_str:
            handle, password = account_str.split(':', 1)
        elif ',' in account_str:
            handle, password = account_str.split(',', 1)
        else:
            continue
        
        handle = handle.strip()
        password = password.strip()
        
        if handle == 'this.is-a.bot':
            this_is_a_bot_password = password
            break
    
    if not this_is_a_bot_password:
        logger.error("❌ No password found for this.is-a.bot in SECONDARY_ACCOUNTS")
        return False
    
    # Create a temporary client for authentication
    client = ATProtoAsyncClient()
    
    try:
        logger.info("🔐 Attempting authentication for this.is-a.bot...")
        
        # First try to create session using existing session file if it has real tokens
        session_file = "session_this_is-a_bot.json"
        
        # If session file exists and has real tokens, try to use it
        if os.path.exists(session_file):
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            
            # Check if it has real tokens (not mock)
            if not session_data.get('accessJwt', '').startswith('mock_'):
                logger.info("📁 Found existing valid session file, using it...")
                # Save to database
                db = Database()
                success = await db.save_session_data(
                    handle=session_data['handle'],
                    did=session_data['did'],
                    access_jwt=session_data['accessJwt'],
                    refresh_jwt=session_data['refreshJwt']
                )
                if success:
                    logger.info("✅ Saved existing session to database")
                    return True
                else:
                    logger.error("❌ Failed to save existing session to database")
        
        # Create new session through authentication
        logger.info("🔑 Creating new session through authentication...")
        
        # Use a minimal approach to avoid rate limits
        # We'll create the session manually and save it
        profile = await client.login('this.is-a.bot', this_is_a_bot_password)
        did = profile.did
        
        logger.info(f"✅ Authentication successful! DID: {did}")
        
        # Get session string and parse it
        session_string = client.export_session_string()
        from atproto_client.client.session import Session
        session_obj = Session.decode(session_string)
        
        # Create session data structure
        session_data = {
            'handle': 'this.is-a.bot',
            'did': did,
            'accessJwt': session_obj.access_jwt,
            'refreshJwt': session_obj.refresh_jwt,
            'accessDate': datetime.now(timezone.utc).isoformat(),
            'refreshDate': datetime.now(timezone.utc).isoformat()
        }
        
        # Save to database
        db = Database()
        success = await db.save_session_data(
            handle=session_data['handle'],
            did=session_data['did'],
            access_jwt=session_data['accessJwt'],
            refresh_jwt=session_data['refreshJwt']
        )
        
        if success:
            logger.info("✅ Session saved to database successfully")
            
            # Also save to file for backup
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            logger.info("✅ Session also saved to file for backup")
            
            return True
        else:
            logger.error("❌ Failed to save session to database")
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "ratelimitexceeded" in error_msg or "429" in str(e):
            logger.error(f"🚫 Rate limited when trying to create session for this.is-a.bot: {e}")
            logger.error("⏳ You may need to wait ~24 hours before retrying")
            return False
        else:
            logger.error(f"❌ Failed to create session for this.is-a.bot: {e}")
            return False

async def resolve_placeholder_dids():
    """Resolve placeholder DIDs to real DIDs before ClearSky processing"""
    logger.info("🔧 Resolving placeholder DIDs...")
    
    db = Database()
    
    # Get all accounts
    accounts_config = await db.get_account_configurations()
    accounts = accounts_config['accounts']
    
    placeholder_accounts = []
    for account in accounts:
        if account['did'].startswith('placeholder_'):
            placeholder_accounts.append(account)
    
    if not placeholder_accounts:
        logger.info("✅ No placeholder DIDs found - all accounts have real DIDs")
        return True
    
    logger.info(f"🔍 Found {len(placeholder_accounts)} accounts with placeholder DIDs:")
    for account in placeholder_accounts:
        logger.info(f"  - {account['handle']} (DID: {account['did']})")
    
    # Get credentials from environment
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    
    # Build credential mapping
    credentials = {}
    if primary_handle:
        credentials[primary_handle] = primary_password
    
    if secondary_accounts_str:
        for account_str in secondary_accounts_str.split(';'):
            if ':' in account_str:
                handle, password = account_str.split(':', 1)
            elif ',' in account_str:
                handle, password = account_str.split(',', 1)
            else:
                continue
            credentials[handle.strip()] = password.strip()
    
    # Try to resolve DIDs using existing session data first
    session_resolved = 0
    
    for account in placeholder_accounts:
        handle = account['handle']
        
        try:
            # First try to load existing session from database
            session_data = await db.load_session_data(handle)
            
            if session_data and session_data.get('did') and not session_data['did'].startswith('placeholder_'):
                real_did = session_data['did']
                logger.info(f"✅ Found real DID in session data for {handle}: {real_did}")
                
                # Update in database
                await db.execute_query(
                    "UPDATE accounts SET did = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    [real_did, account['id']],
                    commit=True
                )
                
                logger.info(f"✅ Updated {handle} DID from {account['did']} to {real_did}")
                session_resolved += 1
                continue
                
        except Exception as e:
            logger.debug(f"No session data found for {handle}: {e}")
    
    # For remaining accounts, try to authenticate to get DIDs
    remaining_placeholders = []
    updated_accounts = await db.get_account_configurations()
    for account in updated_accounts['accounts']:
        if account['did'].startswith('placeholder_'):
            remaining_placeholders.append(account)
    
    if remaining_placeholders:
        logger.info(f"🔐 Attempting to authenticate remaining {len(remaining_placeholders)} accounts to get DIDs...")
        
        for account in remaining_placeholders:
            handle = account['handle']
            
            if handle not in credentials:
                logger.warning(f"⚠️ No credentials found for {handle}, skipping DID resolution")
                continue
            
            try:
                logger.info(f"🔑 Authenticating {handle} to get real DID...")
                
                # Use the existing AccountAgent which handles rate limiting
                temp_agent = AccountAgent(
                    handle=handle,
                    password=credentials[handle],
                    is_primary=account['is_primary'],
                    database=db
                )
                
                # The login() method will automatically update the DID in the database
                if await temp_agent.login():
                    real_did = temp_agent.did
                    logger.info(f"✅ Got real DID for {handle}: {real_did}")
                else:
                    logger.warning(f"⚠️ Failed to authenticate {handle} - may be rate limited")
                    
            except Exception as e:
                logger.error(f"❌ Failed to authenticate {handle}: {e}")
    
    # Final verification
    final_accounts = await db.get_account_configurations()
    final_placeholders = [acc for acc in final_accounts['accounts'] if acc['did'].startswith('placeholder_')]
    
    if final_placeholders:
        logger.warning(f"⚠️ Still have {len(final_placeholders)} accounts with placeholder DIDs:")
        for account in final_placeholders:
            logger.warning(f"  - {account['handle']} (DID: {account['did']})")
        return False
    else:
        logger.info("✅ All placeholder DIDs have been resolved!")
        return True

async def verify_clearsky_readiness():
    """Verify that all accounts are ready for ClearSky processing"""
    logger.info("🔍 Verifying ClearSky readiness...")
    
    db = Database()
    accounts_config = await db.get_account_configurations()
    accounts = accounts_config['accounts']
    
    ready_count = 0
    not_ready_count = 0
    
    for account in accounts:
        if account['did'].startswith('placeholder_'):
            logger.warning(f"❌ Not ready: {account['handle']} (DID: {account['did']})")
            not_ready_count += 1
        else:
            logger.info(f"✅ Ready: {account['handle']} (DID: {account['did']})")
            ready_count += 1
    
    logger.info(f"📊 Summary: {ready_count} ready, {not_ready_count} not ready")
    
    if not_ready_count == 0:
        logger.info("🎉 All accounts are ready for ClearSky processing!")
        return True
    else:
        logger.warning("⚠️ Some accounts still need DID resolution before ClearSky can run")
        return False

async def main():
    """Main function to fix deployment issues"""
    logger.info("🚀 Starting deployment issue fixes...")
    
    # Step 1: Try to create valid session for this.is-a.bot
    logger.info("\n" + "="*60)
    logger.info("STEP 1: Fixing this.is-a.bot session issue")
    logger.info("="*60)
    
    session_success = await create_valid_session_for_this_is_a_bot()
    if session_success:
        logger.info("✅ this.is-a.bot session issue fixed!")
    else:
        logger.warning("⚠️ Could not fix this.is-a.bot session issue (may be rate limited)")
    
    # Step 2: Resolve placeholder DIDs
    logger.info("\n" + "="*60)
    logger.info("STEP 2: Resolving placeholder DID issues")
    logger.info("="*60)
    
    dids_success = await resolve_placeholder_dids()
    if dids_success:
        logger.info("✅ Placeholder DID issues fixed!")
    else:
        logger.warning("⚠️ Some placeholder DIDs could not be resolved")
    
    # Step 3: Final verification
    logger.info("\n" + "="*60)
    logger.info("STEP 3: Final verification")
    logger.info("="*60)
    
    all_ready = await verify_clearsky_readiness()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("SUMMARY")
    logger.info("="*60)
    
    if session_success:
        logger.info("✅ this.is-a.bot session: FIXED")
    else:
        logger.warning("⚠️ this.is-a.bot session: NEEDS ATTENTION")
    
    if dids_success and all_ready:
        logger.info("✅ Placeholder DIDs: FIXED")
        logger.info("✅ ClearSky checks: READY TO RUN")
    else:
        logger.warning("⚠️ Placeholder DIDs: SOME ISSUES REMAIN")
        logger.warning("⚠️ ClearSky checks: NOT READY")
    
    if session_success and dids_success and all_ready:
        logger.info("\n🎉 ALL ISSUES FIXED! Your deployment should now work correctly.")
        logger.info("💡 You can now restart your application and ClearSky checks should run properly.")
    else:
        logger.warning("\n⚠️ Some issues remain. Check the logs above for details.")
        if not session_success:
            logger.warning("   • this.is-a.bot may be rate limited - wait 24 hours and retry")
        if not (dids_success and all_ready):
            logger.warning("   • Some accounts may be rate limited - wait and retry authentication")

if __name__ == "__main__":
    asyncio.run(main()) 