import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient
from datetime import datetime
import time

# Load environment variables
load_dotenv()

from account_agent import AccountAgent

# Set up logging with conditional file logging
log_file = f"mod_list_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

try:
    from utils import setup_conditional_logging
    logger = setup_conditional_logging(__name__, log_file)
except ImportError:
    # Fallback if utils is not available
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Fallback logging setup - file: {log_file}")

async def test_mod_list_sync():
    """Test syncing blocks from database to moderation list"""
    db = Database(test_mode=True)
    
    # Test connection first
    if not await db.test_connection():
        logger.error("Database connection failed")
        return False
    
    logger.info("Starting moderation list sync test...")
    
    # Get primary account from environment variables
    primary_handle = os.getenv('TEST_PRIMARY_BLUESKY_HANDLE') or os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('TEST_PRIMARY_BLUESKY_PASSWORD') or os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in environment variables")
        return False
    
    # Login as primary account
    client = AsyncClient()
    try:
        profile = await client.login(primary_handle, primary_password)
        primary_did = profile.did
        logger.info(f"Logged in as primary account: {primary_handle} (DID: {primary_did})")
    except Exception as e:
        logger.error(f"Failed to login as primary account: {e}")
        return False
    
    # Get primary account from database
    primary_account = await db.get_primary_account()
    if not primary_account:
        logger.error("No primary account found in database")
        return False
    
    logger.info(f"Found primary account in database: {primary_account['handle']} (DID: {primary_account['did']})")
    
    # Get existing moderation list from database
    existing_mod_list = await db.get_primary_mod_list()
    mod_list_uri = None
    
    if existing_mod_list:
        mod_list_uri = existing_mod_list['list_uri']
        logger.info(f"Found existing moderation list in database: {mod_list_uri}")
        
        # Verify it still exists on Bluesky
        try:
            list_response = await client.app.bsky.graph.get_list(params={"list": mod_list_uri})
            if list_response and list_response.list:
                logger.info(f"Verified moderation list exists on Bluesky: {list_response.list.name}")
            else:
                logger.warning(f"Moderation list {mod_list_uri} not found on Bluesky, will search for existing lists")
                mod_list_uri = None
        except Exception as e:
            logger.warning(f"Could not verify moderation list {mod_list_uri} on Bluesky: {e}")
            mod_list_uri = None
    
    # If no database record or verification failed, search for existing lists on Bluesky
    if not mod_list_uri:
        try:
            logger.info("Searching for existing moderation lists on Bluesky...")
            lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_did})
            
            # Look for a moderation list
            for lst in lists_response.lists:
                if lst.purpose == 'app.bsky.graph.defs#modlist':
                    mod_list_uri = lst.uri
                    logger.info(f"Found existing moderation list on Bluesky: {lst.uri} (name: '{lst.name}')")
                    
                    # Register it in the database
                    await db.register_mod_list(
                        list_uri=lst.uri,
                        list_cid=str(lst.cid) if hasattr(lst, 'cid') else "unknown",
                        owner_did=primary_did,
                        name=lst.name
                    )
                    logger.info(f"Registered existing moderation list in database")
                    break
        except Exception as e:
            logger.error(f"Error searching for existing moderation lists: {e}")
    
    # If still no list found, create a new one
    if not mod_list_uri:
        logger.info("No moderation list found. Creating new one...")
        
        list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
        list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by any of our managed accounts')
        
        try:
            list_record = {
                "$type": "app.bsky.graph.list",
                "purpose": 'app.bsky.graph.defs#modlist',
                "name": list_name, 
                "description": list_description,
                "createdAt": client.get_current_time_iso()
            }
            
            create_response = await client.com.atproto.repo.create_record({
                "repo": client.me.did,
                "collection": "app.bsky.graph.list",
                "record": list_record
            })
            
            mod_list_uri = create_response.uri
            mod_list_cid = str(create_response.cid)
            
            logger.info(f"Created new moderation list: {mod_list_uri}")
            
            # Register in database
            await db.register_mod_list(
                list_uri=mod_list_uri,
                list_cid=mod_list_cid,
                owner_did=client.me.did,
                name=list_name
            )
            logger.info(f"Registered new moderation list in database")
        except Exception as e:
            logger.error(f"Failed to create moderation list: {e}")
            return False

    # Get all blocks from the database (not filtered by account)
    blocks = await db.get_all_blocked_accounts()
    logger.info(f"Found {len(blocks)} total blocks in database")
    
    # Count by type for logging purposes
    blocking_blocks = [block for block in blocks if block['block_type'] == 'blocking']
    blocked_by_blocks = [block for block in blocks if block['block_type'] == 'blocked_by']
    logger.info(f"Found {len(blocking_blocks)} 'blocking' and {len(blocked_by_blocks)} 'blocked_by' type blocks")
    
    # Get all DIDs that should be in the primary's mod list directly from the database
    # This should include blocks from all accounts and in both directions
    all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
    blocked_dids = set()
    for did_record in all_dids_to_list:
        blocked_dids.add(did_record['did'])
    
    logger.info(f"Found {len(blocked_dids)} unique DIDs that should be in the moderation list")
    
    if not blocked_dids:
        logger.warning("No blocked accounts found in database. Nothing to sync to mod list.")
        return True
    
    # Get existing items in the moderation list (with pagination)
    try:
        logger.info(f"Getting existing items in moderation list {mod_list_uri} (with pagination)...")
        
        existing_dids = set()
        cursor = None
        page_count = 0
        
        # Fetch all pages of the existing moderation list
        while True:
            page_count += 1
            logger.info(f"Fetching page {page_count} of existing mod list items...")
            
            existing_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list_uri,
                "limit": 100,  # Max page size
                "cursor": cursor
            })
            
            if not existing_items_response.items:
                logger.info(f"No more items on page {page_count}. Pagination complete.")
                break
                
            for item in existing_items_response.items:
                if hasattr(item.subject, 'did'):
                    existing_dids.add(item.subject.did)
            
            logger.info(f"Retrieved {len(existing_items_response.items)} items on page {page_count}. Total so far: {len(existing_dids)}")
            
            cursor = existing_items_response.cursor
            if not cursor:
                logger.info("No more pages to fetch.")
                break
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.2)
        
        logger.info(f"Found a total of {len(existing_dids)} existing items in moderation list after pagination")
        
        # Find DIDs to add (blocked_dids - existing_dids)
        dids_to_add = blocked_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} new DIDs to moderation list")
        
        # Process in batches to avoid overwhelming the API
        BATCH_SIZE = 100
        total_dids = len(dids_to_add)
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        dids_list = list(dids_to_add)
        total_batches = (total_dids + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division
        
        # Track overall progress
        start_time = time.time()
        last_progress_report = start_time
        progress_report_interval = 60  # Report progress every 60 seconds
        
        logger.info(f"=== SYNC PLAN ===")
        logger.info(f"Total DIDs to add: {len(dids_to_add)}")
        logger.info(f"Processing in {total_batches} batches of {BATCH_SIZE} DIDs each")
        logger.info(f"Estimated time: ~{(total_batches * 3) // 60} minutes (with 2-3 seconds per batch)")
        logger.info(f"================")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, total_dids)
            batch = dids_list[start_idx:end_idx]
            
            logger.info(f"Processing batch {batch_num + 1}/{total_batches} with {len(batch)} DIDs...")
            
            for did_idx, did in enumerate(batch):
                try:
                    logger.debug(f"Adding DID to mod list: {did} (Batch {batch_num + 1}, Item {did_idx + 1}/{len(batch)})")
                    
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
                    await asyncio.sleep(0.2)
                except Exception as e:
                    if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                        logger.debug(f"DID {did} already in list (concurrent addition or race condition)")
                        skipped_count += 1
                    else:
                        logger.error(f"Error adding DID {did} to moderation list: {e}")
                        error_count += 1
            
            # Add a larger delay between batches to avoid rate limiting
            if batch_num < total_batches - 1:  # Skip delay after last batch
                logger.info(f"Completed batch {batch_num + 1}/{total_batches}. Waiting before next batch...")
                await asyncio.sleep(2)
            
            # Update progress
            current_time = time.time()
            if current_time - last_progress_report >= progress_report_interval:
                elapsed_time = current_time - start_time
                progress = (batch_num + 1) / total_batches
                estimated_remaining_time = (elapsed_time / progress) * (1 - progress)
                logger.info(f"Progress: {batch_num + 1}/{total_batches} ({progress:.2%})")
                logger.info(f"Estimated remaining time: ~{estimated_remaining_time // 60} minutes")
                last_progress_report = current_time
        
        logger.info(f"Mod list sync summary: Added {success_count}, Skipped {skipped_count}, Errors {error_count} out of {len(dids_to_add)} DIDs")
        
        if success_count + skipped_count == len(dids_to_add):
            logger.info("Moderation list synchronization completed successfully!")
        else:
            logger.warning("Moderation list synchronization completed with some errors.")
        
        return success_count + skipped_count == len(dids_to_add)
        
    except Exception as e:
        logger.error(f"Error working with moderation list: {e}")
        return False

async def sync_mod_list_from_db():
    """Sync the moderation list from the database - can be called from other scripts"""
    return await test_mod_list_sync()

if __name__ == "__main__":
    asyncio.run(test_mod_list_sync()) 