#!/usr/bin/env python3
"""
Simple script to clean up test users and placeholder DIDs
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
import asyncpg

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_db_connection():
    """Get database connection"""
    # Use TEST_DATABASE_URL if available, otherwise construct connection string
    test_database_url = os.getenv('TEST_DATABASE_URL')
    if test_database_url:
        return await asyncpg.connect(test_database_url)
    
    # Fallback to individual parameters
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', '5432'))
    database = os.getenv('DB_NAME', 'symm_blocks')
    user = os.getenv('DB_USER', 'postgres')
    password = os.getenv('DB_PASSWORD', '')
    
    return await asyncpg.connect(host=host, port=port, database=database, user=user, password=password)

async def main():
    """Main cleanup function"""
    logger.info("🔧 Starting test user cleanup...")
    
    conn = await get_db_connection()
    
    try:
        # Get all accounts to show current state
        accounts = await conn.fetch("SELECT * FROM accounts ORDER BY id")
        logger.info("Current accounts in database:")
        for account in accounts:
            logger.info(f"  ID: {account['id']}, Handle: {account['handle']}, DID: {account['did']}, Primary: {account['is_primary']}")
        
        # Find test accounts
        test_accounts = [acc for acc in accounts if 'test' in acc['handle'].lower() or acc['did'].startswith('placeholder_')]
        
        if not test_accounts:
            logger.info("No test accounts found to clean up.")
            return
        
        logger.info(f"\nFound {len(test_accounts)} test accounts to remove:")
        for account in test_accounts:
            logger.info(f"  - {account['handle']} (DID: {account['did']})")
        
        response = input("\nDo you want to remove these test accounts? (y/N): ")
        if response.lower() != 'y':
            logger.info("Cleanup aborted by user")
            return
        
        # Remove test accounts and associated data
        for account in test_accounts:
            account_id = account['id']
            handle = account['handle']
            did = account['did']
            
            # Remove associated blocked accounts
            await conn.execute("DELETE FROM blocked_accounts WHERE source_account_id = $1", account_id)
            logger.info(f"Removed blocked accounts for {handle}")
            
            # Remove associated mod lists
            await conn.execute("DELETE FROM mod_lists WHERE owner_did = $1", did)
            logger.info(f"Removed mod lists for {handle}")
            
            # Remove the account itself
            await conn.execute("DELETE FROM accounts WHERE id = $1", account_id)
            logger.info(f"✅ Removed account: {handle}")
        
        logger.info(f"\n🎉 Successfully cleaned up {len(test_accounts)} test accounts!")
        
        # Show final state
        remaining_accounts = await conn.fetch("SELECT * FROM accounts ORDER BY id")
        logger.info("\nRemaining accounts:")
        for account in remaining_accounts:
            logger.info(f"  ID: {account['id']}, Handle: {account['handle']}, DID: {account['did']}, Primary: {account['is_primary']}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main()) 