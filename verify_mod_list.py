import os
import asyncio
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Define log symbols
LOG_SYMBOLS = {
    'START': '[START]',
    'SUCCESS': '[OK]',
    'ERROR': '[ERROR]',
    'WARNING': '[WARN]',
    'INFO': '[INFO]',
    'PROGRESS': '[PROG]',
    'COMPLETE': '[DONE]',
    'DATA': '[DATA]',
    'LIST': '[LIST]',
    'API': '[API]'
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
        elif "progress" in message.lower():
            symbol = LOG_SYMBOLS['PROGRESS']
        elif "complete" in message.lower() or "result" in message.lower() or "verification" in message.lower():
            symbol = LOG_SYMBOLS['COMPLETE']
        elif "found" in message.lower() and "item" in message.lower():
            symbol = LOG_SYMBOLS['DATA']
        elif "list" in message.lower():
            symbol = LOG_SYMBOLS['LIST']
        elif "fetch" in message.lower() or "api" in message.lower():
            symbol = LOG_SYMBOLS['API']
            
        # Create formatted message with symbol
        formatted_msg = f"{symbol} {message}"
        
        # Use the parent class's format method
        record.msg = formatted_msg
        return super().format(record)

# Configure logging
log_file = f"verify_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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

async def verify_mod_list():
    """Verify the number of items in the moderation list in production."""
    logger.info("Starting moderation list verification")
    logger.info(f"Output will be saved to: {log_file}")
    
    start_time = time.time()
    
    try:
        # Get primary account credentials
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            logger.error("Missing account credentials in .env file")
            return False
        
        # Login to Bluesky
        logger.info(f"Logging in to Bluesky as {primary_handle}")
        client = AsyncClient()
        await client.login(primary_handle, primary_password)
        logger.debug(f"Login successful (DID: {client.me.did})")
        
        # Get lists owned by the account
        logger.info("Fetching account lists")
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": client.me.did})
        
        if not hasattr(lists_response, 'lists') or not lists_response.lists:
            logger.error("No lists found for this account")
            return False
        
        logger.info(f"Found {len(lists_response.lists)} lists for {primary_handle}")
        
        # Find moderation lists
        mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
        
        if not mod_lists:
            logger.error("No moderation lists found")
            return False
        
        logger.info(f"Found {len(mod_lists)} moderation lists: {', '.join([lst.name for lst in mod_lists])}")
        
        # Use the first moderation list
        mod_list = mod_lists[0]
        logger.info(f"Checking contents of list: {mod_list.name}")
        logger.debug(f"List URI: {mod_list.uri}")
        
        # Count items with pagination
        cursor = None
        total_items = 0
        page_count = 0
        batch_start_time = time.time()
        last_progress_report = batch_start_time
        progress_report_interval = 60  # Report progress every 60 seconds
        
        logger.info("Starting pagination through list items")
        
        while True:
            page_count += 1
            logger.debug(f"Fetching page {page_count} of list items")
            
            list_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list.uri,
                "limit": 100,
                "cursor": cursor
            })
            
            if not list_items_response.items:
                logger.debug(f"No more items found on page {page_count}")
                break
            
            items_count = len(list_items_response.items)
            total_items += items_count
            
            # Only log every 5 pages to reduce noise
            if page_count % 5 == 0 or page_count == 1:
                logger.info(f"Progress: {total_items} items retrieved ({page_count} pages)")
            
            cursor = list_items_response.cursor
            if not cursor:
                logger.debug("No more pages to fetch")
                break
            
            # Check if we should report progress
            current_time = time.time()
            if current_time - last_progress_report >= progress_report_interval:
                elapsed_time = current_time - batch_start_time
                items_per_second = total_items / elapsed_time if elapsed_time > 0 else 0
                logger.info(f"Progress report: {total_items} items, {page_count} pages, {items_per_second:.1f} items/sec")
                last_progress_report = current_time
            
            # Avoid rate limiting
            await asyncio.sleep(0.2)
        
        # Calculate timing
        total_time = time.time() - start_time
        minutes = int(total_time // 60)
        seconds = int(total_time % 60)
        
        logger.info(f"===== VERIFICATION RESULTS =====")
        logger.info(f"List: {mod_list.name}")
        logger.info(f"Total items: {total_items}")
        logger.info(f"Total pages: {page_count}")
        logger.info(f"Time taken: {minutes}m {seconds}s")
        logger.info(f"===============================")
        
        return True
    
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        return False
    
if __name__ == "__main__":
    asyncio.run(verify_mod_list()) 