#!/usr/bin/env python3
"""
Fix Placeholder DIDs and Clean Test Users

This script:
1. Removes test users from the database
2. Updates placeholder DIDs to real DIDs by resolving them properly
3. Ensures clearsky processes can run properly
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
from database import Database
from account_agent import AccountAgent
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def clean_test_users():
    """Remove test users from the database"""
    db = Database()
    
    logger.info("Checking for test users to remove...")
    
    # Get all accounts
    accounts = await db.get_account_configurations()
    
    test_accounts = []
    for account in accounts['accounts']:
        handle = account['handle']
        did = account['did']
        
        # Identify test accounts
        if (handle.startswith('test.') or 
            'test' in handle.lower() or 
            did.startswith('placeholder_')):
            test_accounts.append(account)
    
    if not test_accounts:
        logger.info("No test accounts found to clean")
        return
    
    logger.info(f"Found {len(test_accounts)} test accounts to remove:")
    for account in test_accounts:
        logger.info(f"  - {account['handle']} (DID: {account['did']})")
    
    # Ask for confirmation
    response = input("Do you want to remove these test accounts? (y/N): ")
    if response.lower() != 'y':
        logger.info("Aborted by user")
        return
    
    # Remove test accounts
    for account in test_accounts:
        try:
            # Remove from accounts table
            await db.execute_query(
                "DELETE FROM accounts WHERE id = $1",
                [account['id']],
                commit=True
            )
            
            # Remove any associated blocked accounts
            await db.execute_query(
                "DELETE FROM blocked_accounts WHERE source_account_id = $1",
                [account['id']],
                commit=True
            )
            
            # Remove any associated mod lists
            await db.execute_query(
                "DELETE FROM mod_lists WHERE owner_did = $1",
                [account['did']],
                commit=True
            )
            
            logger.info(f"✅ Removed test account: {account['handle']}")
            
        except Exception as e:
            logger.error(f"❌ Failed to remove {account['handle']}: {e}")

async def update_placeholder_dids():
    """Update placeholder DIDs to real DIDs by re-authenticating accounts"""
    db = Database()
    
    logger.info("Checking for placeholder DIDs to update...")
    
    # Get all accounts
    accounts = await db.get_account_configurations()
    
    placeholder_accounts = []
    for account in accounts['accounts']:
        if account['did'].startswith('placeholder_'):
            placeholder_accounts.append(account)
    
    if not placeholder_accounts:
        logger.info("No placeholder DIDs found to update")
        return
    
    logger.info(f"Found {len(placeholder_accounts)} accounts with placeholder DIDs:")
    for account in placeholder_accounts:
        logger.info(f"  - {account['handle']} (DID: {account['did']})")
    
    # Get credentials and authenticate to get real DIDs
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
    
    # Update each placeholder account
    for account in placeholder_accounts:
        handle = account['handle']
        
        if handle not in credentials:
            logger.warning(f"No credentials found for {handle}, skipping")
            continue
        
        try:
            logger.info(f"Authenticating {handle} to get real DID...")
            
            # Create temporary agent to get real DID
            temp_agent = AccountAgent(
                handle=handle,
                password=credentials[handle],
                is_primary=account['is_primary'],
                database=db
            )
            
            # Login to get real DID
            if await temp_agent.login():
                real_did = temp_agent.did
                logger.info(f"✅ Got real DID for {handle}: {real_did}")
                
                # Update in database
                await db.execute_query(
                    "UPDATE accounts SET did = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    [real_did, account['id']],
                    commit=True
                )
                
                logger.info(f"✅ Updated {handle} DID from {account['did']} to {real_did}")
                
            else:
                logger.error(f"❌ Failed to authenticate {handle}")
                
        except Exception as e:
            logger.error(f"❌ Failed to update DID for {handle}: {e}")

async def verify_clearsky_readiness():
    """Verify that accounts are ready for clearsky processing"""
    db = Database()
    
    logger.info("Verifying accounts are ready for ClearSky processing...")
    
    # Get all accounts
    accounts = await db.get_account_configurations()
    
    ready_accounts = []
    not_ready_accounts = []
    
    for account in accounts['accounts']:
        if account['did'].startswith('placeholder_'):
            not_ready_accounts.append(account)
        else:
            ready_accounts.append(account)
    
    logger.info(f"✅ Ready for ClearSky: {len(ready_accounts)} accounts")
    for account in ready_accounts:
        logger.info(f"  - {account['handle']} (DID: {account['did']})")
    
    if not_ready_accounts:
        logger.warning(f"❌ Not ready (still have placeholder DIDs): {len(not_ready_accounts)} accounts")
        for account in not_ready_accounts:
            logger.warning(f"  - {account['handle']} (DID: {account['did']})")
        return False
    
    return True

async def test_clearsky_fetch():
    """Test that clearsky fetching works for our accounts"""
    db = Database()
    
    logger.info("Testing ClearSky API access for our accounts...")
    
    # Get primary account
    primary_account = await db.get_primary_account()
    
    if not primary_account:
        logger.error("No primary account found")
        return False
    
    if primary_account['did'].startswith('placeholder_'):
        logger.error(f"Primary account still has placeholder DID: {primary_account['did']}")
        return False
    
    try:
        # Test fetching blocked-by count
        logger.info(f"Testing ClearSky fetch for primary account: {primary_account['handle']}")
        
        total_count = await cs.get_total_blocked_by_count(primary_account['did'])
        if total_count is not None:
            logger.info(f"✅ ClearSky API working - {primary_account['handle']} is blocked by {total_count} accounts")
            return True
        else:
            logger.error("❌ ClearSky API returned None")
            return False
            
    except Exception as e:
        logger.error(f"❌ ClearSky API test failed: {e}")
        return False

async def main():
    """Main function to fix all issues"""
    logger.info("🔧 Starting DID resolution and cleanup process...")
    
    # Step 1: Clean test users
    logger.info("\n📝 Step 1: Cleaning test users...")
    await clean_test_users()
    
    # Step 2: Update placeholder DIDs
    logger.info("\n🔄 Step 2: Updating placeholder DIDs...")
    await update_placeholder_dids()
    
    # Step 3: Verify readiness
    logger.info("\n✅ Step 3: Verifying ClearSky readiness...")
    if await verify_clearsky_readiness():
        logger.info("🎉 All accounts are ready for ClearSky processing!")
        
        # Step 4: Test clearsky access
        logger.info("\n🌐 Step 4: Testing ClearSky API access...")
        if await test_clearsky_fetch():
            logger.info("🎉 ClearSky API test successful!")
            logger.info("\n✅ You can now run the main script and ClearSky checks will work properly!")
        else:
            logger.error("❌ ClearSky API test failed")
    else:
        logger.error("❌ Some accounts still have placeholder DIDs")

if __name__ == "__main__":
    asyncio.run(main()) 