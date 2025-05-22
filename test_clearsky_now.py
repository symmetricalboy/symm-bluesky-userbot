#!/usr/bin/env python3
"""
Test ClearSky functionality with current accounts
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
import asyncpg
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_db_connection():
    """Get database connection"""
    test_database_url = os.getenv('TEST_DATABASE_URL')
    if test_database_url:
        return await asyncpg.connect(test_database_url)
    
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', '5432'))
    database = os.getenv('DB_NAME', 'symm_blocks')
    user = os.getenv('DB_USER', 'postgres')
    password = os.getenv('DB_PASSWORD', '')
    
    return await asyncpg.connect(host=host, port=port, database=database, user=user, password=password)

async def test_clearsky_for_accounts():
    """Test clearsky functionality for all real accounts"""
    conn = await get_db_connection()
    
    try:
        # Get all accounts
        accounts = await conn.fetch("SELECT * FROM accounts ORDER BY is_primary DESC, id")
        logger.info("Current accounts in database:")
        
        for account in accounts:
            handle = account['handle']
            did = account['did']
            is_primary = account['is_primary']
            
            logger.info(f"\n{'==='*20}")
            logger.info(f"Testing account: {handle}")
            logger.info(f"DID: {did}")
            logger.info(f"Primary: {is_primary}")
            
            # Check if DID is placeholder
            if did.startswith('placeholder_'):
                logger.warning(f"⚠️  Account {handle} still has placeholder DID: {did}")
                logger.warning("This account needs to log in to get its real DID")
                continue
            
            # Test ClearSky API for this account
            try:
                logger.info(f"🔍 Testing ClearSky API for {handle}...")
                
                # Test get total blocked-by count
                total_count = await cs.get_total_blocked_by_count(did)
                if total_count is not None:
                    logger.info(f"✅ {handle} is blocked by {total_count} accounts")
                else:
                    logger.warning(f"❌ Failed to get blocked-by count for {handle}")
                
                # Test get profile
                profile = await cs.get_profile(did)
                if profile:
                    logger.info(f"✅ Profile found for {handle}")
                else:
                    logger.warning(f"❌ Failed to get profile for {handle}")
                
                logger.info(f"✅ ClearSky API working for {handle}")
                
            except Exception as e:
                logger.error(f"❌ ClearSky API test failed for {handle}: {e}")
    
    finally:
        await conn.close()

async def main():
    """Main test function"""
    logger.info("🧪 Testing ClearSky functionality with current accounts...")
    await test_clearsky_for_accounts()
    logger.info("\n🎉 ClearSky test completed!")

if __name__ == "__main__":
    asyncio.run(main()) 