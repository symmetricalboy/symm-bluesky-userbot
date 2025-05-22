import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("deduplicate_dids.log")
    ]
)
logger = logging.getLogger(__name__)

async def find_duplicate_dids():
    """Find all duplicate DIDs in the database"""
    logger.info("Looking for duplicate DIDs in the database...")
    
    db = Database()
    if not await db.test_connection():
        logger.error("Database connection test failed. Cannot check for duplicates.")
        return []
    
    # Query to find duplicate DIDs
    query = """
        SELECT did, block_type, source_account_id, COUNT(*) as count
        FROM blocked_accounts
        GROUP BY did, block_type, source_account_id
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    """
    
    try:
        results = await db.execute_query(query)
        
        if results and len(results) > 0:
            logger.info(f"Found {len(results)} instances of duplicate DIDs")
            for row in results:
                logger.info(f"Duplicate: DID={row['did']}, Type={row['block_type']}, Source={row['source_account_id']}, Count={row['count']}")
            return results
        else:
            logger.info("No duplicate DIDs found")
            return []
    except Exception as e:
        logger.error(f"Error finding duplicate DIDs: {e}")
        return []

async def clean_duplicate_dids(duplicates):
    """Clean up duplicate DIDs by keeping only the most recent entry"""
    if not duplicates:
        logger.info("No duplicates to clean up")
        return 0
    
    logger.info(f"Cleaning up {len(duplicates)} sets of duplicate DIDs...")
    
    db = Database()
    if not await db.test_connection():
        logger.error("Database connection test failed. Cannot clean up duplicates.")
        return 0
    
    cleaned_count = 0
    
    for duplicate in duplicates:
        did = duplicate['did']
        block_type = duplicate['block_type']
        source_account_id = duplicate['source_account_id']
        
        try:
            # Find all entries for this DID, block_type, and source_account_id
            entries_query = """
                SELECT id, did, block_type, source_account_id, first_seen, last_seen
                FROM blocked_accounts
                WHERE did = $1 AND block_type = $2 AND source_account_id = $3
                ORDER BY last_seen DESC, id DESC
            """
            
            entries = await db.execute_query(entries_query, [did, block_type, source_account_id])
            
            if len(entries) <= 1:
                logger.info(f"Only one entry found for DID {did}, block_type {block_type}, source {source_account_id}. Skipping.")
                continue
            
            # Keep the first entry (most recent by last_seen, then highest ID)
            keep_id = entries[0]['id']
            
            # Delete all other entries
            delete_ids = [entry['id'] for entry in entries[1:]]
            
            if delete_ids:
                delete_query = """
                    DELETE FROM blocked_accounts
                    WHERE id = ANY($1::int[])
                """
                
                result = await db.execute_query(delete_query, [delete_ids], commit=True)
                logger.info(f"Deleted {len(delete_ids)} duplicate entries for DID {did}, keeping ID {keep_id}")
                cleaned_count += len(delete_ids)
        except Exception as e:
            logger.error(f"Error cleaning up duplicates for DID {did}: {e}")
    
    logger.info(f"Cleanup complete. Removed {cleaned_count} duplicate entries.")
    return cleaned_count

async def verify_no_duplicates():
    """Verify there are no more duplicates after cleanup"""
    logger.info("Verifying no duplicates remain...")
    
    remaining_duplicates = await find_duplicate_dids()
    
    if remaining_duplicates:
        logger.warning(f"Found {len(remaining_duplicates)} sets of duplicates after cleanup. Manual investigation needed.")
        return False
    else:
        logger.info("No duplicates remain. Cleanup successful.")
        return True

async def main():
    """Main function to find and clean up duplicate DIDs"""
    logger.info("=" * 60)
    logger.info(f"DUPLICATE DID CHECK AND CLEANUP: Started at {datetime.now().isoformat()}")
    logger.info("=" * 60)
    
    try:
        # Find duplicates
        duplicates = await find_duplicate_dids()
        
        if duplicates:
            # Clean up duplicates
            cleaned_count = await clean_duplicate_dids(duplicates)
            logger.info(f"Cleaned up {cleaned_count} duplicate entries")
            
            # Verify no duplicates remain
            success = await verify_no_duplicates()
            
            if success:
                logger.info("Duplicate DID cleanup completed successfully")
            else:
                logger.warning("Some duplicates remain after cleanup")
        else:
            logger.info("No duplicate DIDs found. Database is clean.")
    except Exception as e:
        logger.error(f"Error during duplicate DID check and cleanup: {e}")
    
    logger.info("=" * 60)
    logger.info(f"DUPLICATE DID CHECK AND CLEANUP: Completed at {datetime.now().isoformat()}")
    logger.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(main()) 