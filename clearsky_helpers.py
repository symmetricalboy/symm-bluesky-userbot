import os
import httpx
import asyncio
import logging
from dotenv import load_dotenv
import time
from datetime import datetime

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# ClearSky API base URL
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')

async def fetch_from_clearsky(endpoint, page=1, timeout=30.0):
    """
    Fetch data from ClearSky API with specific page
    
    Args:
        endpoint: API endpoint to fetch
        page: Page number (default is 1)
        timeout: Request timeout in seconds
        
    Returns:
        Response data as JSON or None if request failed
    """
    try:
        url = f"{CLEARSKY_API_BASE_URL}{endpoint}"
        if page > 1:
            url = f"{url}/{page}"
        
        logger.debug(f"Fetching from ClearSky: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            start_time = time.time()
            response = await client.get(url)
            duration = time.time() - start_time
            
            if response.status_code == 404:
                logger.warning(f"404 Not Found for {url}")
                return None
                
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Received response from {url} in {duration:.2f} seconds")
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching or parsing {url}: {e}")
        return None

async def get_total_blocked_by_count(handle_or_did):
    """
    Get the total number of accounts that block the given handle/DID
    
    Args:
        handle_or_did: Bluesky handle or DID
        
    Returns:
        Total count or None if request failed
    """
    logger.debug(f"Getting total blocked-by count for: {handle_or_did}")
    data = await fetch_from_clearsky(f"/single-blocklist/total/{handle_or_did}")
    
    if data and 'data' in data and 'count' in data['data']:
        total_count = data['data']['count']
        logger.debug(f"Total accounts blocking {handle_or_did}: {total_count}")
        return total_count
    else:
        logger.error(f"Failed to get total blocked-by count for {handle_or_did}")
        return None

async def fetch_all_blocked_by(handle_or_did, max_pages=None, page_delay=0.5):
    """
    Fetch all accounts that block the given handle/DID with pagination
    
    Args:
        handle_or_did: Bluesky handle or DID
        max_pages: Optional maximum number of pages to fetch (for testing)
        page_delay: Delay between page requests in seconds
        
    Returns:
        List of blocker records and total count
    """
    # Get total count first
    total_count = await get_total_blocked_by_count(handle_or_did)
    if total_count is None:
        logger.error("Unable to fetch blocked-by accounts due to missing total count")
        return [], 0
    
    # Now fetch all pages
    all_blockers = []
    page = 1
    blockers_per_page = 100  # ClearSky returns 100 records per page
    expected_pages = (total_count + blockers_per_page - 1) // blockers_per_page
    
    logger.info(f"Fetching blocked-by accounts for {handle_or_did}. Expected pages: {expected_pages}")
    
    start_time = time.time()
    
    while True:
        if max_pages and page > max_pages:
            logger.info(f"Reached max page limit of {max_pages}")
            break
            
        logger.debug(f"Fetching page {page} of blocked-by accounts ({page}/{expected_pages})")
        data = await fetch_from_clearsky(f"/single-blocklist/{handle_or_did}", page)
        
        if not data or 'data' not in data or 'blocklist' not in data['data']:
            logger.error(f"Failed to fetch page {page} or unexpected data structure")
            break
        
        blockers = data['data']['blocklist']
        if not blockers or len(blockers) == 0:
            logger.info(f"No more blockers found on page {page}")
            break
        
        # Validate each blocker record
        valid_blockers = []
        invalid_count = 0
        for blocker in blockers:
            if 'did' in blocker and 'blocked_date' in blocker:
                valid_blockers.append(blocker)
            else:
                invalid_count += 1
                logger.warning(f"Blocker record missing required fields: {blocker}")
        
        logger.debug(f"Found {len(valid_blockers)} valid blocker records on page {page}")
        if invalid_count:
            logger.warning(f"Found {invalid_count} invalid records on page {page}")
            
        all_blockers.extend(valid_blockers)
        
        # If we got fewer records than the expected per page, we've reached the end
        if len(blockers) < blockers_per_page:
            logger.info(f"Reached last page with {len(blockers)} records")
            break
        
        # Move to next page
        page += 1
        
        # Add a small delay to be nice to the API
        if page_delay > 0:
            await asyncio.sleep(page_delay)
    
    elapsed_time = time.time() - start_time
    logger.info(f"Fetched {len(all_blockers)} blocked-by records in {elapsed_time:.2f} seconds")
    
    # Verify the count matches the expected total
    if len(all_blockers) != total_count:
        logger.warning(f"Count mismatch: API reported {total_count}, but found {len(all_blockers)} records")
    
    return all_blockers, total_count

async def get_handle_from_did(did):
    """
    Resolve a handle from a DID using ClearSky
    
    Args:
        did: The DID to resolve
        
    Returns:
        Handle string or None if not found
    """
    data = await fetch_from_clearsky(f"/get-handle/{did}")
    if data and 'data' in data and 'handle_identifier' in data['data']:
        return data['data']['handle_identifier']
    return None

async def get_did_from_handle(handle):
    """
    Resolve a DID from a handle using ClearSky
    
    Args:
        handle: The handle to resolve
        
    Returns:
        DID string or None if not found
    """
    data = await fetch_from_clearsky(f"/get-did/{handle}")
    if data and 'data' in data and 'did_identifier' in data['data']:
        return data['data']['did_identifier']
    return None

async def get_profile(handle_or_did):
    """
    Get profile information for a handle or DID
    
    Args:
        handle_or_did: Bluesky handle or DID
        
    Returns:
        Profile data or None if not found
    """
    data = await fetch_from_clearsky(f"/get-profile/{handle_or_did}")
    if data and 'data' in data:
        return data['data']
    return None 