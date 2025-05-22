import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from main import initialize_accounts_in_db, populate_blocks_from_clearsky
from test_mod_list_sync import sync_mod_list_from_db

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_full_sync():
    """Run a full block synchronization process"""
    logger.info("=== STARTING FULL BLOCK SYNCHRONIZATION ===")
    
    # Initialize database
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed. Cannot run full sync.")
        return False
    
    # Step 1: Initialize accounts in the database
    logger.info("\n=== STEP 1: INITIALIZING ACCOUNTS ===")
    accounts_init_success = await initialize_accounts_in_db()
    if not accounts_init_success:
        logger.error("Failed to initialize accounts in the database. Aborting.")
        return False
    
    # Step 2: Populate blocks from ClearSky
    logger.info("\n=== STEP 2: POPULATING BLOCKS FROM CLEARSKY ===")
    blocks_import_success = await populate_blocks_from_clearsky()
    if not blocks_import_success:
        logger.error("Failed to populate blocks from ClearSky. Aborting.")
        return False
    
    # Step 3: Sync blocks to moderation list
    logger.info("\n=== STEP 3: SYNCING BLOCKS TO MODERATION LIST ===")
    mod_list_sync_success = await sync_mod_list_from_db()
    if not mod_list_sync_success:
        logger.error("Failed to sync blocks to moderation list.")
        return False
    
    logger.info("\n=== FULL SYNCHRONIZATION COMPLETED SUCCESSFULLY ===")
    return True

if __name__ == "__main__":
    asyncio.run(run_full_sync()) 