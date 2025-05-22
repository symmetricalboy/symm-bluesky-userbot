import os
import asyncio
import logging
import sys
from main import populate_blocks_from_clearsky, sync_blocks_to_modlist
from deduplicate_dids import deduplicate_dids
from check_duplicate_dids import check_duplicate_dids
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("reboot_sync.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def reboot_sync():
    """Perform a one-time full sync and deduplication on reboot"""
    logger.info("Starting reboot sync process...")
    
    try:
        # Check for duplicate DIDs
        logger.info("Checking for duplicate DIDs...")
        check_duplicate_dids()
        
        # Remove duplicate DIDs
        logger.info("Deduplicating DIDs...")
        deduplicate_dids()
        
        # Populate blocks from ClearSky
        logger.info("Populating blocks from ClearSky...")
        await populate_blocks_from_clearsky()
        
        # Sync blocks to moderation list
        logger.info("Syncing blocks to moderation list...")
        await sync_blocks_to_modlist()
        
        logger.info("Reboot sync completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Error during reboot sync: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(reboot_sync())
    sys.exit(0 if success else 1) 