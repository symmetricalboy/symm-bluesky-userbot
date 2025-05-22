import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

async def check_mod_list_info():
    """Get information about the moderation list and DIDs to be added."""
    try:
        # Initialize database (production)
        logger.info("Connecting to production database...")
        db = Database(test_mode=False)
        if not await db.test_connection():
            logger.error("Database connection failed")
            return
        
        # Login to Bluesky
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            logger.error("Missing account credentials in .env file")
            return
        
        logger.info(f"Logging in as {primary_handle}...")
        client = AsyncClient()
        await client.login(primary_handle, primary_password)
        logger.info(f"Login successful")
        
        # Get primary account DID
        primary_account = await db.get_primary_account()
        if not primary_account:
            logger.error("No primary account found in database")
            return
            
        # Count DIDs in database
        logger.info("Counting DIDs in database...")
        unique_dids_db_query = "SELECT COUNT(DISTINCT did) FROM blocked_accounts"
        result = await db.execute_query(unique_dids_db_query)
        unique_dids_count = result[0]['count']
        logger.info(f"Found {unique_dids_count} unique DIDs in database")
        
        # Get all DIDs that should be in moderation list
        logger.info("Counting DIDs that should be in moderation list...")
        all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
        blocked_dids = set()
        for did_record in all_dids_to_list:
            blocked_dids.add(did_record['did'])
        logger.info(f"Found {len(blocked_dids)} unique DIDs that should be in moderation list")
        
        # Find moderation list
        logger.info(f"Getting mod lists for {primary_account['did']}...")
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
        
        # Find all moderation lists
        mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
        logger.info(f"Found {len(mod_lists)} moderation lists")
        
        if not mod_lists:
            logger.info("No moderation lists found")
            return
            
        # Get the first moderation list
        mod_list = mod_lists[0]
        logger.info(f"Using list: '{mod_list.name}' ({mod_list.uri})")
        
        # Count items in the moderation list
        logger.info("Counting items in moderation list...")
        existing_dids = set()
        cursor = None
        page_count = 0
        total_items = 0
        
        while True:
            page_count += 1
            list_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list.uri,
                "limit": 100,
                "cursor": cursor
            })
            
            if not hasattr(list_items_response, 'items') or not list_items_response.items:
                break
                
            items_this_page = len(list_items_response.items)
            total_items += items_this_page
            
            for item in list_items_response.items:
                if hasattr(item.subject, 'did'):
                    existing_dids.add(item.subject.did)
            
            logger.info(f"Page {page_count}: Retrieved {items_this_page} items. Total so far: {total_items}")
            
            cursor = list_items_response.cursor
            if not cursor:
                break
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(existing_dids)} unique DIDs already in moderation list")
        
        # Calculate DIDs to add
        dids_to_add = blocked_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} DIDs to moderation list")
        
        # Summary
        logger.info("==== SUMMARY ====")
        logger.info(f"Total unique DIDs in database: {unique_dids_count}")
        logger.info(f"DIDs that should be in moderation list: {len(blocked_dids)}")
        logger.info(f"DIDs already in moderation list: {len(existing_dids)}")
        logger.info(f"DIDs to add: {len(dids_to_add)}")
        logger.info("================")
        
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_mod_list_info()) 