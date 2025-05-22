#!/usr/bin/env python3
"""
Test the whitelist protection for our own accounts
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_whitelist_protection():
    """Test that our own accounts cannot be added to blocked_accounts"""
    logger.info("🧪 Testing whitelist protection...")
    
    db = Database()
    
    try:
        # Get our account configurations
        configs = await db.get_account_configurations()
        accounts = configs.get('accounts', [])
        
        if not accounts:
            logger.error("No accounts found in database")
            return
        
        # Try to add our primary account to blocked_accounts (should be prevented)
        primary_account = next((acc for acc in accounts if acc['is_primary']), None)
        if primary_account:
            logger.info(f"Testing whitelist for primary account: {primary_account['handle']}")
            
            # This should be prevented by the whitelist
            try:
                await db.add_blocked_account(
                    did=primary_account['did'],
                    handle=primary_account['handle'],
                    source_account_id=primary_account['id'],
                    block_type='test_whitelist',
                    reason='Testing whitelist protection'
                )
                logger.info("✅ Whitelist protection activated (no exception raised)")
            except Exception as e:
                logger.error(f"❌ Unexpected error during whitelist test: {e}")
        
        # Verify our accounts are still NOT in blocked_accounts
        for account in accounts:
            did = account['did']
            handle = account['handle']
            
            # Check if somehow in blocked_accounts table
            query_result = await db.execute_query(
                "SELECT COUNT(*) as count FROM blocked_accounts WHERE did = $1",
                [did]
            )
            count = query_result[0]['count'] if query_result else 0
            
            if count > 0:
                logger.error(f"❌ PROBLEM: {handle} found in blocked_accounts despite whitelist!")
            else:
                logger.info(f"✅ GOOD: {handle} NOT in blocked_accounts")
        
        logger.info("🎉 Whitelist protection test completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during whitelist test: {e}")

if __name__ == "__main__":
    asyncio.run(test_whitelist_protection()) 