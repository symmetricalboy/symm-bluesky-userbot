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

# Set up custom logging with symbols and colors
log_file = f"full_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Define log symbols
LOG_SYMBOLS = {
    'START': '[START]',
    'SUCCESS': '[OK]',
    'ERROR': '[ERROR]',
    'WARNING': '[WARN]',
    'INFO': '[INFO]',
    'PROGRESS': '[PROG]',
    'COMPLETE': '[DONE]',
    'RATE_LIMIT': '[LIMIT]',
    'WAITING': '[WAIT]',
    'BATCH': '[BATCH]',
    'DATABASE': '[DB]',
    'API': '[API]',
    'RESUME': '[RESUME]'
}

# Custom formatter to add symbols
class SymbolFormatter(logging.Formatter):
    def format(self, record):
        level_name = record.levelname
        message = record.getMessage()
        
        # Add appropriate symbol based on keywords in the message
        symbol = LOG_SYMBOLS['INFO']
        if "starting" in message.lower() or "begin" in message.lower():
            symbol = LOG_SYMBOLS['START']
        elif "success" in message.lower() or "completed" in message.lower():
            symbol = LOG_SYMBOLS['SUCCESS']
        elif "error" in message.lower() or "fail" in message.lower():
            symbol = LOG_SYMBOLS['ERROR']
        elif "warning" in message.lower() or "caution" in message.lower():
            symbol = LOG_SYMBOLS['WARNING']
        elif "progress" in message.lower() or "estimated" in message.lower():
            symbol = LOG_SYMBOLS['PROGRESS']
        elif "complete" in message.lower() or "finished" in message.lower():
            symbol = LOG_SYMBOLS['COMPLETE']
        elif "rate limit" in message.lower():
            symbol = LOG_SYMBOLS['RATE_LIMIT']
        elif "waiting" in message.lower() or "pause" in message.lower():
            symbol = LOG_SYMBOLS['WAITING']
        elif "batch" in message.lower():
            symbol = LOG_SYMBOLS['BATCH']
        elif "database" in message.lower() or "db" in message.lower():
            symbol = LOG_SYMBOLS['DATABASE']
        elif "api" in message.lower() or "fetch" in message.lower():
            symbol = LOG_SYMBOLS['API']
        elif "resume" in message.lower() or "checkpoint" in message.lower():
            symbol = LOG_SYMBOLS['RESUME']
            
        # Create formatted message with symbol
        formatted_msg = f"{symbol} {message}"
        
        # Use the parent class's format method
        record.msg = formatted_msg
        return super().format(record)

# Configure logging
file_handler = logging.FileHandler(log_file, mode='w')
file_formatter = SymbolFormatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler()
console_formatter = SymbolFormatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Configure root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info(f"Sync process starting - logs saved to: {log_file}")

# Rate limiting constants - Updated for better safety
BATCH_SIZE = 15  # Reduced batch size to be more conservative (was 20)
DELAY_BETWEEN_BATCHES = 10  # Increased from 5 to 10 seconds between batches
DELAY_AFTER_RATE_LIMIT = 900  # Increased to 15 minutes wait after hitting rate limit (was 5 minutes)
CHECKPOINT_FILE = "sync_checkpoint.txt"  # Store progress

# Additional safety constants  
MAX_REQUESTS_PER_HOUR = 2000  # Conservative limit well under 3000 per 5 minutes
REQUEST_INTERVAL_SECONDS = 2.0  # Minimum 2 seconds between requests

async def full_sync():
    """
    Synchronize all DIDs from the production database to the moderation list,
    respecting rate limits and allowing for resumption.
    """
    logger.info("===== STARTING FULL MODERATION LIST SYNC =====")
    
    # Initialize database (production)
    db = Database(test_mode=False)
    logger.debug("Using production database tables")
    
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
    try:
        await client.login(primary_handle, primary_password)
        logger.debug(f"Login successful (DID: {client.me.did})")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return False
    
    # Get primary account from database
    primary_account = await db.get_primary_account()
    if not primary_account:
        logger.error("No primary account found in database")
        return False
    
    # Check for existing moderation lists
    try:
        logger.debug(f"Retrieving lists for {primary_account['did']}...")
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
        
        # Find moderation lists
        mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
        
        if mod_lists:
            mod_list = mod_lists[0]  # Use the first one
            logger.info(f"Found existing moderation list: {mod_list.name}")
            logger.debug(f"Using list URI: {mod_list.uri}")
        else:
            logger.info("Creating new moderation list...")
            
            # Create a new moderation list
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
            logger.info(f"Successfully created new list '{list_name}'")
            
            # Get the list again to get all properties
            lists_response = await client.app.bsky.graph.get_lists(params={"actor": primary_account['did']})
            mod_lists = [lst for lst in lists_response.lists if lst.uri == mod_list_uri]
            if mod_lists:
                mod_list = mod_lists[0]
            else:
                logger.error("Could not retrieve the newly created moderation list")
                return False
    except Exception as e:
        logger.error(f"Error checking moderation lists: {e}")
        return False
    
    # Get all DIDs from the database
    try:
        logger.info("Getting DIDs that should be in the moderation list...")
        all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
        blocked_dids = set()
        for did_record in all_dids_to_list:
            blocked_dids.add(did_record['did'])
        
        logger.info(f"Found {len(blocked_dids)} unique DIDs to add to moderation list")
        
        if not blocked_dids:
            logger.warning("No DIDs found - nothing to add to moderation list")
            return True
            
    except Exception as e:
        logger.error(f"Error retrieving DIDs from database: {e}")
        return False
    
    # Get existing items in the moderation list with pagination
    try:
        logger.info(f"Fetching existing items in moderation list...")
        existing_dids = set()
        cursor = None
        page_count = 0
        total_pages_estimate = max(1, len(blocked_dids) // 100)
        
        # Fetch all pages of the existing moderation list
        while True:
            page_count += 1
            logger.debug(f"Fetching page {page_count} of existing list items...")
            
            existing_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list.uri,
                "limit": 100,  # Max page size
                "cursor": cursor
            })
            
            if not hasattr(existing_items_response, 'items') or not existing_items_response.items:
                logger.debug(f"No more items on page {page_count}")
                break
                
            for item in existing_items_response.items:
                if hasattr(item.subject, 'did'):
                    existing_dids.add(item.subject.did)
            
            # Only log progress occasionally for large lists
            if page_count % 5 == 0 or page_count == 1:
                logger.info(f"Progress: Retrieved {len(existing_dids)} items ({page_count}/{total_pages_estimate} pages)")
            
            cursor = existing_items_response.cursor
            if not cursor:
                logger.debug("No more pages to fetch")
                break
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(existing_dids)} DIDs already in the moderation list")
        
        # Find DIDs to add (not already in the list)
        dids_to_add = blocked_dids - existing_dids
        logger.info(f"Need to add {len(dids_to_add)} new DIDs to moderation list")
        
        # Check for checkpoint file to resume from previous run
        start_index = 0
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, 'r') as f:
                checkpoint = f.read().strip()
                if checkpoint:
                    try:
                        start_index = int(checkpoint)
                        logger.info(f"Resuming from previous checkpoint (item #{start_index})")
                    except ValueError:
                        logger.warning(f"Invalid checkpoint value: {checkpoint}. Starting from beginning.")
        
        # Convert to list for indexed access
        dids_list = list(dids_to_add)
        total_dids = len(dids_list)
        
        # Set up counters
        success_count = 0
        error_count = 0
        skipped_count = 0
        rate_limit_hits = 0
        
        # Calculate total batches
        total_batches = (total_dids - start_index + BATCH_SIZE - 1) // BATCH_SIZE
        remaining_dids = total_dids - start_index
        
        # Estimate time
        seconds_per_item = 0.3  # Conservative estimate
        seconds_per_batch = BATCH_SIZE * seconds_per_item + DELAY_BETWEEN_BATCHES
        estimated_time_seconds = total_batches * seconds_per_batch
        hours = estimated_time_seconds // 3600
        minutes = (estimated_time_seconds % 3600) // 60
        
        logger.info(f"==== SYNC PLAN ====")
        logger.info(f"Items to add: {remaining_dids} DIDs in {total_batches} batches")
        logger.info(f"Batch size: {BATCH_SIZE} DIDs with {DELAY_BETWEEN_BATCHES}s between batches")
        logger.info(f"Estimated time: {hours}h {minutes}m (may be longer with rate limits)")
        logger.info(f"Rate limit pause: {DELAY_AFTER_RATE_LIMIT}s when hitting limits")
        logger.info(f"==================")
        
        # Only start if there are DIDs to add
        if remaining_dids == 0:
            logger.info("No new DIDs to add - all items already in list")
            return True
            
        # Track overall progress
        start_time = time.time()
        last_progress_report = start_time
        progress_report_interval = 60  # Report progress every 60 seconds
        
        # Process in batches to avoid overwhelming the API
        for batch_num in range(total_batches):
            start_idx = start_index + (batch_num * BATCH_SIZE)
            end_idx = min(start_idx + BATCH_SIZE, total_dids)
            
            if start_idx >= total_dids:
                logger.info("All DIDs processed - sync completed!")
                break
                
            batch = dids_list[start_idx:end_idx]
            
            # Log batch start more concisely
            percent_complete = (batch_num / total_batches) * 100
            logger.info(f"Batch {batch_num + 1}/{total_batches} ({percent_complete:.1f}%) - Processing {len(batch)} DIDs")
            
            batch_start_time = time.time()
            batch_success = 0
            batch_error = 0
            batch_skipped = 0
            rate_limited = False
            
            for did_idx, did in enumerate(batch):
                current_idx = start_idx + did_idx
                try:
                    logger.debug(f"Adding DID: {did} (#{current_idx + 1}/{total_dids})")
                    
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
                    
                    # Save checkpoint after each successful addition
                    with open(CHECKPOINT_FILE, 'w') as f:
                        f.write(str(current_idx + 1))  # Save next index
                    
                    # Add a small delay between individual requests
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    error_message = str(e).lower()
                    if "already exists" in error_message or "conflict" in error_message:
                        logger.debug(f"DID {did} already in list (skipping)")
                        batch_skipped += 1
                        skipped_count += 1
                    elif "rate limit" in error_message or "ratelimit" in error_message:
                        logger.warning(f"Rate limit hit - will pause processing")
                        rate_limited = True
                        rate_limit_hits += 1
                        error_count += 1
                        
                        # Save checkpoint so we can resume
                        with open(CHECKPOINT_FILE, 'w') as f:
                            f.write(str(current_idx))
                        
                        # Break out of the loop to pause
                        break
                    else:
                        logger.error(f"Error adding DID {did}: {e}")
                        batch_error += 1
                        error_count += 1
            
            batch_time = time.time() - batch_start_time
            logger.info(f"Batch complete: Added {batch_success}, Skipped {batch_skipped}, Errors {batch_error} in {batch_time:.2f}s")
            
            # Update progress periodically rather than every batch
            current_time = time.time()
            if current_time - last_progress_report >= progress_report_interval:
                elapsed_time = current_time - start_time
                progress = (batch_num + 1) / total_batches
                estimated_remaining_time = (elapsed_time / progress) * (1 - progress) if progress > 0 else 0
                
                # Calculate hours, minutes for better readability
                hours_elapsed = int(elapsed_time // 3600)
                mins_elapsed = int((elapsed_time % 3600) // 60)
                hours_remaining = int(estimated_remaining_time // 3600)
                mins_remaining = int((estimated_remaining_time % 3600) // 60)
                
                logger.info(f"Progress: {progress:.1%} complete")
                logger.info(f"Time: {hours_elapsed}h {mins_elapsed}m elapsed, ~{hours_remaining}h {mins_remaining}m remaining")
                logger.info(f"Stats: {success_count} added, {skipped_count} skipped, {error_count} errors, {rate_limit_hits} rate limits")
                
                last_progress_report = current_time
            
            # Handle rate limiting
            if rate_limited:
                minutes = DELAY_AFTER_RATE_LIMIT // 60
                logger.warning(f"Rate limit pause: waiting {minutes} minutes before resuming")
                await asyncio.sleep(DELAY_AFTER_RATE_LIMIT)
                logger.info("Resuming after rate limit pause")
            elif batch_num < total_batches - 1:  # Skip delay after last batch
                logger.debug(f"Pausing {DELAY_BETWEEN_BATCHES}s before next batch")
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)
        
        # Sync complete - log final stats
        total_time = time.time() - start_time
        hours = int(total_time // 3600)
        minutes = int((total_time % 3600) // 60)
        seconds = int(total_time % 60)
        
        logger.info(f"===== SYNC COMPLETED =====")
        logger.info(f"Total time: {hours}h {minutes}m {seconds}s")
        logger.info(f"Results: {success_count} added, {skipped_count} skipped, {error_count} errors")
        logger.info(f"Rate limits encountered: {rate_limit_hits}")
        
        # Remove checkpoint file if complete
        if success_count + skipped_count == len(dids_to_add) and error_count == 0:
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)
                logger.info("Checkpoint file removed - sync completed successfully")
        
        return success_count + skipped_count == len(dids_to_add)
        
    except Exception as e:
        logger.error(f"Error during synchronization: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(full_sync()) 