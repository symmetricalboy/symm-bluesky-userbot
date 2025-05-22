import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_mod_list_sync():
    """Test syncing blocks from database to moderation list"""
    logger.info("=== TESTING MOD LIST SYNCHRONIZATION ===")
    
    # Initialize database
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed. Cannot test mod list sync.")
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
    
    # Get moderation list from database
    mod_lists = db.get_mod_lists_by_owner(primary_account['did'])
    if not mod_lists:
        logger.info("No moderation list found in database. Creating one...")
        
        # Create moderation list
        list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
        list_purpose = 'app.bsky.graph.defs#modlist'
        list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by any of our managed accounts')
        
        list_record = {
            "$type": "app.bsky.graph.list",
            "purpose": list_purpose,
            "name": list_name, 
            "description": list_description,
            "createdAt": client.get_current_time_iso()
        }
        
        try:
            create_response = await client.com.atproto.repo.create_record({
                "repo": client.me.did,
                "collection": "app.bsky.graph.list",
                "record": list_record
            })
            
            mod_list_uri = create_response.uri
            mod_list_cid = str(create_response.cid)
            
            logger.info(f"Created new moderation list: {mod_list_uri}")
            
            # Register mod list in database
            db.register_mod_list(
                list_uri=mod_list_uri,
                list_cid=mod_list_cid,
                owner_did=client.me.did,
                name=list_name
            )
            
            logger.info(f"Registered moderation list in database: {mod_list_uri}")
        except Exception as e:
            logger.error(f"Failed to create moderation list: {e}")
            return False
    else:
        mod_list_uri = mod_lists[0]['list_uri']
        logger.info(f"Found existing moderation list in database: {mod_list_uri}")
    
    # Get all blocked accounts from database
    logger.info("Getting blocked accounts from database...")
    
    # Get all blocks from the database (not filtered by account)
    blocks = db.get_all_blocked_accounts()
    
    # Filter to only include 'blocking' type blocks
    blocking_blocks = [block for block in blocks if block['block_type'] == 'blocking']
    logger.info(f"Found {len(blocking_blocks)} 'blocking' type blocks in database")
    
    # Extract unique DIDs
    blocked_dids = set()
    for block in blocking_blocks:
        blocked_did = block['did']
        source_handle = block.get('source_account_handle', 'unknown')
        logger.info(f"Found block: {source_handle} blocks {blocked_did}")
        blocked_dids.add(blocked_did)
    
    logger.info(f"Found {len(blocked_dids)} unique blocked DIDs across all accounts")
    
    if not blocked_dids:
        logger.warning("No blocked accounts found in database. Nothing to sync to mod list.")
        return True
    
    # Get existing items in the moderation list
    try:
        logger.info(f"Getting existing items in moderation list {mod_list_uri}...")
        
        existing_items_response = await client.app.bsky.graph.get_list({
            "list": mod_list_uri,
            "limit": 100  # Adjust as needed for larger lists
        })
        
        existing_dids = set()
        for item in existing_items_response.items:
            existing_dids.add(item.subject.did)
        
        logger.info(f"Found {len(existing_dids)} existing items in moderation list")
        
        # Find DIDs to add (blocked_dids - existing_dids)
        dids_to_add = blocked_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} new DIDs to moderation list")
        
        # Add DIDs to moderation list
        success_count = 0
        for did in dids_to_add:
            try:
                logger.info(f"Adding DID to mod list: {did}")
                
                list_item_record = {
                    "$type": "app.bsky.graph.listitem",
                    "subject": did,
                    "list": mod_list_uri,
                    "createdAt": client.get_current_time_iso()
                }
                
                await client.com.atproto.repo.create_record({
                    "repo": client.me.did,
                    "collection": "app.bsky.graph.listitem",
                    "record": list_item_record
                })
                
                success_count += 1
                
                # Add a small delay to avoid rate limiting
                await asyncio.sleep(0.5)
            except Exception as e:
                if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                    logger.warning(f"DID {did} already in list (concurrent addition or race condition)")
                    success_count += 1
                else:
                    logger.error(f"Error adding DID {did} to moderation list: {e}")
        
        logger.info(f"Successfully added {success_count} out of {len(dids_to_add)} DIDs to moderation list")
        
        if success_count == len(dids_to_add):
            logger.info("Moderation list synchronization test completed successfully!")
        else:
            logger.warning("Moderation list synchronization test completed with some errors.")
        
        return success_count == len(dids_to_add)
        
    except Exception as e:
        logger.error(f"Error working with moderation list: {e}")
        return False

async def sync_mod_list_from_db():
    """Sync the moderation list from the database - can be called from other scripts"""
    return await test_mod_list_sync()

if __name__ == "__main__":
    asyncio.run(test_mod_list_sync()) 