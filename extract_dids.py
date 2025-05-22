import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
OUTPUT_FILE = "dids_to_add.txt"

async def extract_dids_to_file():
    """Extract DIDs from the database and save to file."""
    try:
        logger.info("Connecting to production database...")
        db = Database(test_mode=False)
        
        if not await db.test_connection():
            logger.error("Database connection failed")
            return
        
        # Get primary account
        primary_account = await db.get_primary_account()
        if not primary_account:
            logger.error("No primary account found in database")
            return
            
        logger.info(f"Primary account: {primary_account['did']}")
        
        # Login to Bluesky to get existing DIDs
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            logger.error("Missing account credentials in .env file")
            return
        
        logger.info(f"Logging in as {primary_handle}...")
        client = AsyncClient()
        await client.login(primary_handle, primary_password)
        logger.info(f"Login successful")
        
        # Get moderation list
        logger.info("Finding moderation list...")
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
        mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
        
        if not mod_lists:
            logger.error("No moderation list found")
            return
            
        mod_list = mod_lists[0]
        logger.info(f"Found list: {mod_list.name}")
        
        # Get existing DIDs in moderation list
        logger.info("Getting DIDs already in moderation list...")
        existing_dids = set()
        cursor = None
        page_count = 0
        
        while True:
            page_count += 1
            
            list_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list.uri,
                "limit": 100,
                "cursor": cursor
            })
            
            if not hasattr(list_items_response, 'items') or not list_items_response.items:
                break
                
            for item in list_items_response.items:
                if hasattr(item.subject, 'did'):
                    existing_dids.add(item.subject.did)
            
            if page_count % 5 == 0 or page_count == 1:
                logger.info(f"Retrieved {len(existing_dids)} DIDs from list (page {page_count})")
            
            cursor = list_items_response.cursor
            if not cursor:
                break
                
            # Small delay between pages
            await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(existing_dids)} DIDs already in moderation list")
        
        # Get DIDs from database
        logger.info("Getting DIDs from database...")
        all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
        db_dids = set()
        for did_record in all_dids_to_list:
            db_dids.add(did_record['did'])
        
        logger.info(f"Found {len(db_dids)} DIDs in database")
        
        # Find DIDs to add (in database but not in list)
        dids_to_add = db_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} DIDs to moderation list")
        
        # Save to file
        if not dids_to_add:
            logger.info("No DIDs need to be added - all are already in the list")
            return
            
        logger.info(f"Saving {len(dids_to_add)} DIDs to {OUTPUT_FILE}")
        with open(OUTPUT_FILE, 'w') as f:
            for did in dids_to_add:
                f.write(f"{did}\n")
        
        logger.info(f"DIDs successfully saved to {OUTPUT_FILE}")
        logger.info(f"You can now run add_one_did.py to add them one at a time")
        
    except Exception as e:
        logger.error(f"Error extracting DIDs: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(extract_dids_to_file()) 