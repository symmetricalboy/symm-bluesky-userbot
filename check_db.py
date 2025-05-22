import asyncio
import logging
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_database():
    logger.info("Checking database contents...")
    
    db = Database()
    if not await db.test_connection():
        logger.error("Failed to connect to database")
        return
    
    try:
        # Get all blocks
        blocks = await db.get_all_blocked_accounts()
        logger.info(f"Total blocks in database: {len(blocks)}")
        
        # Count by type
        blocking_blocks = [b for b in blocks if b['block_type'] == 'blocking']
        logger.info(f"'blocking' type blocks: {len(blocking_blocks)}")
        
        blocked_by_blocks = [b for b in blocks if b['block_type'] == 'blocked_by']
        logger.info(f"'blocked_by' type blocks: {len(blocked_by_blocks)}")
        
        # Count unique DIDs
        unique_dids = set(b['did'] for b in blocks)
        logger.info(f"Unique DIDs: {len(unique_dids)}")
        
        # Count by source account
        source_accounts = {}
        for block in blocks:
            source = block.get('source_account_handle', 'unknown')
            source_accounts[source] = source_accounts.get(source, 0) + 1
        
        logger.info(f"Blocks by source account:")
        for source, count in source_accounts.items():
            logger.info(f"  {source}: {count}")
        
        # Check what should be in mod list
        primary_account = await db.get_primary_account()
        if primary_account:
            primary_id = primary_account['id']
            all_intended_dids_on_list = await db.get_all_dids_primary_should_list(primary_id)
            logger.info(f"DIDs that should be on mod list: {len(all_intended_dids_on_list)}")
    
    except Exception as e:
        logger.error(f"Error checking database: {e}")

if __name__ == "__main__":
    asyncio.run(check_database()) 