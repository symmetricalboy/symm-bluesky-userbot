import os
import asyncio
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from database import Database
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Set up logging with clear formatting
log_file = f"sync_mod_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger()
logger.info(f"Starting mod list sync - logging to {log_file}")

# Constants - Updated for better rate limiting
BATCH_SIZE = 3  # Much more conservative batch size (reduced from 5)
DELAY_BETWEEN_REQUESTS = 2.0  # Increased delay between individual requests (was 1.0)
DELAY_BETWEEN_BATCHES = 60  # Much longer wait between batches (was 30 seconds, now 60)
DELAY_AFTER_RATE_LIMIT = 900  # 15 minutes wait after hitting rate limit (was 10 minutes)
CHECKPOINT_FILE = "sync_checkpoint.txt"  # Store progress

# Additional safety constants
MAX_OPERATIONS_PER_HOUR = 1200  # Well under the 1666 limit
MAX_OPERATIONS_PER_DAY = 8000   # Well under the 11666 limit

async def sync_mod_list():
    """Synchronize all DIDs from database to moderation list."""
    try:
        start_time = time.time()
        
        # Connect to production database (no test suffix)
        db = Database(test_mode=False)
        logger.info("Connecting to production database...")
        
        if not await db.test_connection():
            logger.error("Database connection failed - cannot continue")
            return False
            
        # Get primary account credentials  
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            logger.error("Missing account credentials in .env file")
            return False
        
        # Login to Bluesky
        logger.info(f"Logging in to Bluesky as {primary_handle}...")
        client = AsyncClient()
        await client.login(primary_handle, primary_password)
        logger.info(f"Login successful - DID: {client.me.did}")
        
        # Get primary account from database
        primary_account = await db.get_primary_account()
        if not primary_account:
            logger.error("No primary account found in database")
            return False
            
        # Get all DIDs that should be in moderation list
        logger.info("Fetching DIDs that should be in moderation list...")
        all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
        blocked_dids = set()
        for did_record in all_dids_to_list:
            blocked_dids.add(did_record['did'])
        
        logger.info(f"Found {len(blocked_dids)} unique DIDs to add")
        
        if not blocked_dids:
            logger.info("No DIDs found - nothing to add")
            return True
        
        # Find existing moderation list
        logger.info("Finding existing moderation lists...")
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
        
        mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
        
        if mod_lists:
            mod_list = mod_lists[0]
            logger.info(f"Using existing list: {mod_list.name}")
        else:
            logger.info("Creating new moderation list...")
            list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
            list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by any of our managed accounts')
            
            list_record = {
                "$type": "app.bsky.graph.list",
                "purpose": "app.bsky.graph.defs#modlist",
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
            logger.info(f"Created new list '{list_name}'")
            
            # Fetch the list again to get all properties
            await asyncio.sleep(1)  # Give a moment before refetching
            lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
            mod_lists = [lst for lst in lists_response.lists if lst.uri == mod_list_uri]
            mod_list = mod_lists[0] if mod_lists else None
            
            if not mod_list:
                logger.error("Could not retrieve the newly created list")
                return False
        
        # Get existing DIDs in moderation list with pagination
        logger.info("Fetching existing DIDs in moderation list...")
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
                logger.info(f"No items found on page {page_count}")
                break
                
            items_count = len(list_items_response.items)
            
            for item in list_items_response.items:
                if hasattr(item.subject, 'did'):
                    existing_dids.add(item.subject.did)
            
            if page_count % 5 == 0 or page_count == 1:
                logger.info(f"Retrieved {len(existing_dids)} existing items so far (page {page_count})")
            
            cursor = list_items_response.cursor
            if not cursor:
                logger.info("No more pages to fetch")
                break
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(existing_dids)} DIDs already in the list")
        
        # Find DIDs to add
        dids_to_add = blocked_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} new DIDs")
        
        if not dids_to_add:
            logger.info("No new DIDs to add - already in sync")
            return True
        
        # Check for checkpoint
        start_index = 0
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, 'r') as f:
                checkpoint = f.read().strip()
                if checkpoint:
                    try:
                        start_index = int(checkpoint)
                        logger.info(f"Resuming from checkpoint: item #{start_index}")
                    except ValueError:
                        logger.warning(f"Invalid checkpoint value: {checkpoint}")
        
        # Prepare for processing
        dids_list = list(dids_to_add)
        total_dids = len(dids_list)
        dids_remaining = total_dids - start_index
        
        # Calculate batches
        total_batches = (dids_remaining + BATCH_SIZE - 1) // BATCH_SIZE
        
        # Estimate time
        # Each DID takes ~0.5s to process + delay between requests
        time_per_batch = BATCH_SIZE * (DELAY_BETWEEN_REQUESTS + 0.5) + DELAY_BETWEEN_BATCHES
        estimated_seconds = total_batches * time_per_batch
        
        # Add extra time for rate limits (rough estimate)
        estimated_rate_limits = max(1, total_batches // 50)  # Assume a rate limit every ~50 batches
        estimated_seconds += estimated_rate_limits * DELAY_AFTER_RATE_LIMIT
        
        estimated_hours = estimated_seconds // 3600
        estimated_minutes = (estimated_seconds % 3600) // 60
        
        logger.info("-" * 50)
        logger.info("SYNC PLAN:")
        logger.info(f"Items to add: {dids_remaining} DIDs")
        logger.info(f"Processing in {total_batches} batches of {BATCH_SIZE} DIDs")
        logger.info(f"Delays: {DELAY_BETWEEN_REQUESTS}s between requests, {DELAY_BETWEEN_BATCHES}s between batches")
        logger.info(f"Estimated time: ~{estimated_hours}h {estimated_minutes}m (may be longer with rate limits)")
        logger.info("-" * 50)
        
        # Start processing batches
        success_count = 0
        error_count = 0
        skipped_count = 0
        rate_limit_hits = 0
        
        batch_start_time = time.time()
        progress_report_time = batch_start_time
        
        # Process all batches
        for batch_num in range(total_batches):
            start_idx = start_index + (batch_num * BATCH_SIZE)
            end_idx = min(start_idx + BATCH_SIZE, total_dids)
            
            if start_idx >= total_dids:
                logger.info("All DIDs processed - sync complete!")
                break
                
            batch = dids_list[start_idx:end_idx]
            
            # Calculate progress percentage
            progress_pct = (batch_num / total_batches) * 100 if total_batches > 0 else 100
            logger.info(f"Batch {batch_num + 1}/{total_batches} ({progress_pct:.1f}%) - {len(batch)} DIDs")
            
            batch_success = 0
            batch_error = 0
            batch_skipped = 0
            rate_limited = False
            
            # Process each DID in the batch
            for did_idx, did in enumerate(batch):
                current_idx = start_idx + did_idx
                try:
                    list_item_record = {
                        "$type": "app.bsky.graph.listitem",
                        "subject": did,
                        "list": mod_list.uri,
                        "createdAt": client.get_current_time_iso()
                    }
                    
                    await client.com.atproto.repo.create_record({
                        "repo": client.me.did,
                        "collection": "app.bsky.graph.listitem",
                        "record": list_item_record
                    })
                    
                    batch_success += 1
                    success_count += 1
                    
                    # Save checkpoint immediately after each successful addition
                    with open(CHECKPOINT_FILE, 'w') as f:
                        f.write(str(current_idx + 1))
                    
                    # Delay between individual requests to avoid rate limiting
                    await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
                    
                except Exception as e:
                    error_message = str(e).lower()
                    
                    if "already exists" in error_message or "conflict" in error_message:
                        batch_skipped += 1
                        skipped_count += 1
                    elif "rate limit" in error_message or "ratelimit" in error_message:
                        logger.warning(f"Rate limit hit at DID #{current_idx + 1} ({did})")
                        rate_limited = True
                        rate_limit_hits += 1
                        
                        # Save checkpoint
                        with open(CHECKPOINT_FILE, 'w') as f:
                            f.write(str(current_idx))
                        
                        break
                    else:
                        logger.error(f"Error adding DID {did}: {e}")
                        batch_error += 1
                        error_count += 1
                        
                        # Small delay after error before continuing
                        await asyncio.sleep(1)
            
            # Log batch results
            batch_time = time.time() - batch_start_time
            logger.info(f"Batch results: Added {batch_success}, Skipped {batch_skipped}, Errors {batch_error} in {batch_time:.1f}s")
            
            # Update progress if needed
            current_time = time.time()
            if current_time - progress_report_time >= 60:  # Report progress every minute
                elapsed_time = current_time - start_time
                progress_ratio = (batch_num + 1) / total_batches if total_batches > 0 else 1.0
                
                # Avoid division by zero
                if progress_ratio > 0:
                    remaining_time = (elapsed_time / progress_ratio) * (1 - progress_ratio)
                else:
                    remaining_time = 0
                
                # Format times
                elapsed_hours = int(elapsed_time // 3600)
                elapsed_minutes = int((elapsed_time % 3600) // 60)
                elapsed_seconds = int(elapsed_time % 60)
                
                remaining_hours = int(remaining_time // 3600)
                remaining_minutes = int((remaining_time % 3600) // 60)
                
                logger.info("-" * 30)
                logger.info(f"PROGRESS UPDATE:")
                logger.info(f"Completed: {progress_ratio:.1%}")
                logger.info(f"Time elapsed: {elapsed_hours}h {elapsed_minutes}m {elapsed_seconds}s")
                logger.info(f"Time remaining: ~{remaining_hours}h {remaining_minutes}m")
                logger.info(f"Items: {success_count} added, {skipped_count} skipped, {error_count} errors")
                logger.info(f"Rate limits hit: {rate_limit_hits}")
                logger.info("-" * 30)
                
                progress_report_time = current_time
            
            # Handle rate limits
            if rate_limited:
                minutes = DELAY_AFTER_RATE_LIMIT // 60
                logger.warning(f"Pausing for {minutes} minutes due to rate limit (batch {batch_num + 1}/{total_batches})")
                await asyncio.sleep(DELAY_AFTER_RATE_LIMIT)
                logger.info(f"Resuming after rate limit pause at batch {batch_num + 1}")
            elif batch_num < total_batches - 1:
                logger.info(f"Waiting {DELAY_BETWEEN_BATCHES}s before next batch")
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)
            
            batch_start_time = time.time()
        
        # Log final results
        total_time = time.time() - start_time
        hours = int(total_time // 3600)
        minutes = int((total_time % 3600) // 60)
        seconds = int(total_time % 60)
        
        logger.info("=" * 50)
        logger.info("SYNC COMPLETED")
        logger.info(f"Total time: {hours}h {minutes}m {seconds}s")
        logger.info(f"Results:")
        logger.info(f"  - {success_count} DIDs added")
        logger.info(f"  - {skipped_count} DIDs skipped")
        logger.info(f"  - {error_count} errors")
        logger.info(f"  - {rate_limit_hits} rate limit hits")
        logger.info("=" * 50)
        
        # Remove checkpoint if complete
        if success_count + skipped_count == len(dids_to_add):
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)
                logger.info("Checkpoint file removed - sync completed successfully")
        else:
            logger.warning(f"Sync incomplete - still need to add {len(dids_to_add) - (success_count + skipped_count)} DIDs")
            logger.warning(f"Run the script again to continue from checkpoint")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    asyncio.run(sync_mod_list()) 