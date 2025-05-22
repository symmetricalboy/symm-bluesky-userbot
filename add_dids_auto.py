import os
import asyncio
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Set up logging with clear formatting
log_file = f"add_dids_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# Constants - Updated for much better rate limiting
DIDS_FILE = "dids_to_add.txt"
DELAY_BETWEEN_ADDS = 10.0  # Increased from 5.0 to 10.0 seconds between adds
DELAY_AFTER_ERROR = 30.0  # Increased from 10.0 to 30.0 seconds after error
DELAY_AFTER_RATE_LIMIT = 1200.0  # Increased to 20 minutes after rate limit (was 10 minutes)
MAX_ADDS_PER_SESSION = 50  # Reduced from 100 to 50 to be more conservative

# Additional safety limits
MAX_ADDS_PER_HOUR = 300  # Well under the 1666 theoretical limit
MAX_ADDS_PER_DAY = 5000  # Well under the 11666 theoretical limit

async def add_dids_from_file():
    """Add DIDs from file to moderation list with proper rate limiting."""
    start_time = time.time()
    logger.info(f"Starting DID addition - logging to {log_file}")
    
    # Check if DIDs file exists
    if not os.path.exists(DIDS_FILE):
        logger.error(f"DIDs file '{DIDS_FILE}' not found.")
        logger.error("Run extract_dids.py first to create the file.")
        return
    
    # Read DIDs from file
    with open(DIDS_FILE, 'r') as f:
        all_dids = [line.strip() for line in f.readlines() if line.strip()]
    
    total_dids = len(all_dids)
    if total_dids == 0:
        logger.info("No DIDs found in file - nothing to do")
        return
    
    logger.info(f"Found {total_dids} DIDs to process")
    
    # Login to Bluesky
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Missing account credentials in .env file")
        return
    
    logger.info(f"Logging in as {primary_handle}...")
    client = AsyncClient()
    try:
        await client.login(primary_handle, primary_password)
        logger.info(f"Login successful as {client.me.did}")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return
    
    # Get lists
    logger.info("Finding moderation list...")
    lists_response = await client.app.bsky.graph.get_lists(params={"actor": client.me.did})
    
    # Find moderation lists
    mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
    
    if not mod_lists:
        logger.error("No moderation lists found")
        return
        
    # Use the first moderation list
    mod_list = mod_lists[0]
    logger.info(f"Using list: '{mod_list.name}' ({mod_list.uri})")
    
    # Process DIDs
    success_count = 0
    error_count = 0
    skip_count = 0
    rate_limit_count = 0
    
    # Limit the number of DIDs to process in a single run
    process_count = min(total_dids, MAX_ADDS_PER_SESSION)
    logger.info(f"Will process {process_count} DIDs in this session")
    
    for i in range(process_count):
        current_did = all_dids[0]
        logger.info(f"Processing DID {i+1}/{process_count}: {current_did} ({(i+1)/process_count:.1%})")
        
        try:
            list_item_record = {
                "$type": "app.bsky.graph.listitem",
                "subject": current_did,
                "list": mod_list.uri,
                "createdAt": client.get_current_time_iso()
            }
            
            await client.com.atproto.repo.create_record({
                "repo": client.me.did,
                "collection": "app.bsky.graph.listitem",
                "record": list_item_record
            })
            
            success_count += 1
            logger.info(f"[OK] Successfully added DID")
            
            # Remove processed DID from list and update file
            all_dids.pop(0)
            with open(DIDS_FILE, 'w') as f:
                for did in all_dids:
                    f.write(f"{did}\n")
            
            logger.debug(f"Updated {DIDS_FILE} - {len(all_dids)} DIDs remaining")
            
            # Wait between adds
            logger.debug(f"Waiting {DELAY_BETWEEN_ADDS}s before next add...")
            await asyncio.sleep(DELAY_BETWEEN_ADDS)
            
        except Exception as e:
            error_message = str(e).lower()
            
            if "already exists" in error_message or "conflict" in error_message:
                logger.info(f"[SKIP] DID already in list - skipping")
                skip_count += 1
                
                # Remove processed DID from list and update file
                all_dids.pop(0)
                with open(DIDS_FILE, 'w') as f:
                    for did in all_dids:
                        f.write(f"{did}\n")
                
                # Shorter delay for already existing items
                await asyncio.sleep(1)
                
            elif "rate limit" in error_message or "ratelimit" in error_message:
                logger.warning(f"[LIMIT] Rate limit hit - pausing for {DELAY_AFTER_RATE_LIMIT/60:.1f} minutes")
                rate_limit_count += 1
                
                # Save current state
                with open(DIDS_FILE, 'w') as f:
                    for did in all_dids:
                        f.write(f"{did}\n")
                
                # Wait longer after rate limit
                await asyncio.sleep(DELAY_AFTER_RATE_LIMIT)
                logger.info("Resuming after rate limit pause")
                
            else:
                logger.error(f"⚠ Error adding DID: {e}")
                error_count += 1
                
                # Wait after error
                logger.info(f"Waiting {DELAY_AFTER_ERROR}s after error...")
                await asyncio.sleep(DELAY_AFTER_ERROR)
    
    # Report final stats
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    
    logger.info("=" * 40)
    logger.info("PROCESSING COMPLETE")
    logger.info(f"Total time: {minutes}m {seconds}s")
    logger.info(f"DIDs added: {success_count}")
    logger.info(f"DIDs skipped: {skip_count}")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Rate limits: {rate_limit_count}")
    logger.info(f"DIDs remaining: {len(all_dids)}")
    logger.info("=" * 40)
    
    if len(all_dids) > 0:
        logger.info("Run this script again to process more DIDs")
    else:
        logger.info("All DIDs have been processed!")

if __name__ == "__main__":
    asyncio.run(add_dids_from_file()) 