import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient
import requests

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_accounts_i_block():
    """Test specifically for fetching and handling accounts that our primary account blocks"""
    logger.info("=== TESTING ACCOUNTS I BLOCK ===")
    
    # Initialize database
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed.")
        return False
    
    # Get primary account credentials
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    # Login to Bluesky
    logger.info(f"Logging in as primary account {primary_handle}...")
    client = AsyncClient()
    try:
        await client.login(primary_handle, primary_password)
        logger.info(f"Successfully logged in as {primary_handle} (DID: {client.me.did})")
    except Exception as e:
        logger.error(f"Failed to login: {e}")
        return False
    
    # Get primary account from database
    primary_account = db.get_primary_account()
    if not primary_account:
        logger.error("No primary account found in database")
        return False
    
    # Get accounts I block from ClearSky
    logger.info("Fetching accounts I block from ClearSky API...")
    clearsky_url = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.social/api/v1')
    endpoint = f"{clearsky_url}/users/{primary_handle}/blocks"
    
    try:
        response = requests.get(endpoint)
        if response.status_code != 200:
            logger.error(f"Failed to fetch blocks from ClearSky: {response.status_code} - {response.text}")
            return False
        
        blocks_data = response.json()
        blocking_count = len(blocks_data.get('blocking', []))
        logger.info(f"Found {blocking_count} accounts that {primary_handle} blocks")
        
        # Process accounts I block
        account_id = primary_account['id']
        block_type = 'blocking'
        
        # Store each account in database
        count = 0
        for block in blocks_data.get('blocking', []):
            did = block.get('did')
            handle = block.get('handle')
            
            if not did:
                logger.warning(f"Skipping block with missing DID: {block}")
                continue
                
            # Add to database
            db.add_blocked_account(
                did=did,
                handle=handle,
                source_account_id=account_id,
                block_type=block_type
            )
            
            count += 1
            logger.info(f"Added blocking relationship: {primary_handle} blocks {handle} ({did})")
        
        logger.info(f"Added {count} blocking relationships to database")
        
        # Verify accounts are in database
        blocks_in_db = db.get_all_blocked_accounts()
        blocking_in_db = [b for b in blocks_in_db if b['block_type'] == 'blocking']
        logger.info(f"Total blocking relationships in database: {len(blocking_in_db)}")
        
        # Check if these blocks are reflected in moderation lists
        logger.info("Checking if blocks are reflected in moderation lists...")
        mod_lists = db.get_mod_lists_by_owner(primary_account['did'])
        
        if not mod_lists:
            logger.warning("No moderation list found in database")
        else:
            mod_list_uri = mod_lists[0]['list_uri']
            logger.info(f"Found moderation list: {mod_list_uri}")
            
            # Get existing items in the moderation list
            try:
                existing_items_response = await client.app.bsky.graph.get_list({
                    "list": mod_list_uri,
                    "limit": 100
                })
                
                existing_dids = set()
                for item in existing_items_response.items:
                    existing_dids.add(item.subject.did)
                
                logger.info(f"Found {len(existing_dids)} existing items in moderation list")
                
                # Compare with database
                db_blocking_dids = set(b['did'] for b in blocking_in_db)
                in_list_not_db = existing_dids - db_blocking_dids
                in_db_not_list = db_blocking_dids - existing_dids
                
                logger.info(f"DIDs in list but not in DB (blocking): {len(in_list_not_db)}")
                logger.info(f"DIDs in DB (blocking) but not in list: {len(in_db_not_list)}")
                
                if in_db_not_list:
                    logger.warning(f"Some blocked accounts are not in the moderation list")
                else:
                    logger.info("All blocked accounts are properly reflected in the moderation list")
                    
            except Exception as e:
                logger.error(f"Error checking moderation list: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing blocks: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_accounts_i_block()) 