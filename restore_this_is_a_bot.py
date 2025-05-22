#!/usr/bin/env python3
"""
Restore this.is-a.bot account to the database
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
    """Restore this.is-a.bot account"""
    logger.info("🔧 Restoring this.is-a.bot account...")
    
    conn = await get_db_connection()
    
    try:
        # Check if this.is-a.bot already exists
        existing = await conn.fetchrow("SELECT * FROM accounts WHERE handle = $1", "this.is-a.bot")
        
        if existing:
            logger.info("this.is-a.bot already exists in database:")
            logger.info(f"  Handle: {existing['handle']}, DID: {existing['did']}, Primary: {existing['is_primary']}")
            return
        
        # Add this.is-a.bot as a secondary account with placeholder DID
        # The real DID will be filled in when the account agent logs in
        await conn.execute("""
            INSERT INTO accounts (handle, did, is_primary, created_at, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, "this.is-a.bot", "placeholder_secondary_this.is-a.bot", False)
        
        logger.info("✅ Successfully restored this.is-a.bot to the database")
        logger.info("   DID will be updated to real DID when account agent logs in")
        
        # Show all accounts now
        accounts = await conn.fetch("SELECT * FROM accounts ORDER BY is_primary DESC, handle")
        logger.info("\nAll accounts in database:")
        for account in accounts:
            logger.info(f"  {account['handle']}: {account['did']} (Primary: {account['is_primary']})")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main()) 