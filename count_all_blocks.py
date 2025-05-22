import asyncio
import logging
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def count_all_blocks():
    """Count all records in the blocked_accounts table with no filtering."""
    logger.info("Counting all records in blocked_accounts table...")
    
    # Explicitly use production database (no _test suffix)
    db = Database(test_mode=False)
    logger.info("Using production database tables (no _test suffix)")
    
    if not await db.test_connection():
        logger.error("Failed to connect to database")
        return
    
    try:
        await db.ensure_pool()
        
        # Execute a direct query to count all records
        results = await db.execute_query("SELECT COUNT(*) as total FROM blocked_accounts")
        total_count = results[0]['total']
        logger.info(f"Total records in blocked_accounts table: {total_count}")
        
        # Count by block type
        blocking_results = await db.execute_query("SELECT COUNT(*) as blocking_count FROM blocked_accounts WHERE block_type = 'blocking'")
        blocking_count = blocking_results[0]['blocking_count']
        logger.info(f"Records with block_type = 'blocking': {blocking_count}")
        
        blocked_by_results = await db.execute_query("SELECT COUNT(*) as blocked_by_count FROM blocked_accounts WHERE block_type = 'blocked_by'")
        blocked_by_count = blocked_by_results[0]['blocked_by_count']
        logger.info(f"Records with block_type = 'blocked_by': {blocked_by_count}")
        
        # Count unique DIDs
        unique_dids_results = await db.execute_query("SELECT COUNT(DISTINCT did) as unique_dids FROM blocked_accounts")
        unique_dids_count = unique_dids_results[0]['unique_dids']
        logger.info(f"Unique DIDs in blocked_accounts table: {unique_dids_count}")
        
        # Check by source account
        accounts_results = await db.execute_query("""
            SELECT a.handle, COUNT(*) as count
            FROM blocked_accounts b
            JOIN accounts a ON b.source_account_id = a.id
            GROUP BY a.handle
            ORDER BY count DESC
        """)
        
        logger.info(f"Counts by source account:")
        for row in accounts_results:
            logger.info(f"  {row['handle']}: {row['count']}")
        
        # Check for test table suffix
        if db.table_suffix:
            logger.info(f"Using test tables with suffix: {db.table_suffix}")
        else:
            logger.info("Using production tables (no suffix)")
            
        # List all tables in the database for verification
        tables_results = await db.execute_query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        logger.info(f"Tables in database:")
        for row in tables_results:
            logger.info(f"  {row['table_name']}")
        
    except Exception as e:
        logger.error(f"Error counting blocks: {e}")

if __name__ == "__main__":
    asyncio.run(count_all_blocks()) 