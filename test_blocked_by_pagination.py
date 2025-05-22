import os
import httpx
import asyncio
import logging
from dotenv import load_dotenv
import json
import time
from datetime import datetime

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("blocked_by_pagination.log")
    ]
)
logger = logging.getLogger(__name__)

# ClearSky API base URL
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')

# Test account credentials for pagination testing
TEST_PAGINATION_BLUESKY_HANDLE = os.getenv('TEST_PAGINATION_BLUESKY_HANDLE', 'symm.social')
TEST_PAGINATION_BLUESKY_PASSWORD = os.getenv('TEST_PAGINATION_BLUESKY_PASSWORD')

async def fetch_from_clearsky(endpoint, page=1):
    """Fetch data from ClearSky API with specific page"""
    try:
        url = f"{CLEARSKY_API_BASE_URL}{endpoint}"
        if page > 1:
            url = f"{url}/{page}"
        
        logger.info(f"Fetching from ClearSky: {url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            start_time = time.time()
            response = await client.get(url)
            duration = time.time() - start_time
            
            if response.status_code == 404:
                logger.warning(f"404 Not Found for {url}")
                return None
                
            response.raise_for_status()
            data = response.json()
            logger.info(f"Received response in {duration:.2f} seconds")
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching or parsing {url}: {e}")
        return None

async def get_total_blocked_by_count(handle):
    """Get the total number of accounts that block the given handle"""
    logger.info(f"Getting total blocked-by count for: {handle}")
    data = await fetch_from_clearsky(f"/single-blocklist/total/{handle}")
    
    if data and 'data' in data and 'count' in data['data']:
        total_count = data['data']['count']
        logger.info(f"Total accounts blocking {handle}: {total_count}")
        return total_count
    else:
        logger.error(f"Failed to get total blocked-by count for {handle}")
        if data:
            logger.error(f"Unexpected response format: {json.dumps(data, indent=2)}")
        return None

async def fetch_all_blocked_by(handle, max_pages=None):
    """
    Fetch all accounts that block the given handle
    
    Args:
        handle: The Bluesky handle to check
        max_pages: Optional maximum number of pages to fetch (for testing)
        
    Returns:
        List of blocker records and total count
    """
    # Get total count first
    total_count = await get_total_blocked_by_count(handle)
    if total_count is None:
        logger.error("Unable to proceed with pagination test due to missing total count")
        return [], 0
    
    # Now fetch all pages
    all_blockers = []
    page = 1
    blockers_per_page = 100  # ClearSky returns 100 records per page
    expected_pages = (total_count + blockers_per_page - 1) // blockers_per_page
    
    logger.info(f"Expected number of pages: {expected_pages}")
    
    start_time = time.time()
    
    while True:
        if max_pages and page > max_pages:
            logger.info(f"Reached max page limit of {max_pages}")
            break
            
        logger.info(f"Fetching page {page} of blocked-by accounts ({page}/{expected_pages})")
        data = await fetch_from_clearsky(f"/single-blocklist/{handle}", page)
        
        if not data or 'data' not in data or 'blocklist' not in data['data']:
            logger.error(f"Failed to fetch page {page} or unexpected data structure")
            if data:
                logger.error(f"Response: {json.dumps(data, indent=2)}")
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
        
        logger.info(f"Found {len(valid_blockers)} valid blocker records on page {page}")
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
        await asyncio.sleep(0.5)
    
    elapsed_time = time.time() - start_time
    logger.info(f"Fetched {len(all_blockers)} records in {elapsed_time:.2f} seconds")
    logger.info(f"Average time per page: {elapsed_time/page:.2f} seconds")
    
    return all_blockers, total_count

async def test_pagination(handle, max_pages=None):
    """
    Test the pagination functionality by counting all accounts that block the given handle
    
    Args:
        handle: The Bluesky handle to test
        max_pages: Optional maximum number of pages to fetch (for testing)
    """
    logger.info(f"Starting pagination test for {handle}")
    
    # Fetch all blockers
    all_blockers, total_count = await fetch_all_blocked_by(handle, max_pages)
    
    # Compare counts (if we didn't limit pages)
    if not max_pages:
        logger.info(f"Total blockers reported by /single-blocklist/total: {total_count}")
        logger.info(f"Total blockers found by fetching all pages: {len(all_blockers)}")
        
        # Log some sample blockers
        if all_blockers:
            logger.info("Sample blocker records:")
            for blocker in all_blockers[:5]:
                logger.info(f"DID: {blocker['did']}, Blocked date: {blocker['blocked_date']}")
        
        # Verify if the counts match
        if total_count == len(all_blockers):
            logger.info("✅ Pagination test PASSED: Total count matches number of records fetched")
        else:
            logger.warning(f"❌ Pagination test FAILED: Count mismatch - API reports {total_count}, but found {len(all_blockers)}")
    else:
        logger.info(f"Limited test to {max_pages} pages, found {len(all_blockers)} blockers")
    
    return all_blockers, total_count

async def test_pagination_with_stats(handle, max_pages=None):
    """Run pagination test and collect performance statistics"""
    logger.info("=" * 60)
    logger.info(f"PAGINATION TEST: {handle}")
    logger.info(f"Date/Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)
    
    start_time = time.time()
    blockers, total_count = await test_pagination(handle, max_pages)
    total_time = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("TEST RESULTS SUMMARY:")
    logger.info(f"Handle tested: {handle}")
    logger.info(f"Total blockers reported: {total_count}")
    logger.info(f"Total blockers fetched: {len(blockers)}")
    logger.info(f"Total time: {total_time:.2f} seconds")
    logger.info(f"Records per second: {len(blockers)/total_time:.2f}")
    logger.info("=" * 60)
    
    return blockers, total_count, total_time

async def main():
    logger.info("Starting pagination test suite")
    
    if not TEST_PAGINATION_BLUESKY_PASSWORD:
        logger.error("TEST_PAGINATION_BLUESKY_PASSWORD environment variable is not set")
        return
    
    # Run full pagination test (might take a while for accounts with many blockers)
    await test_pagination_with_stats(TEST_PAGINATION_BLUESKY_HANDLE)
    
    # Optionally, run a limited test with just a few pages
    # await test_pagination_with_stats(TEST_PAGINATION_BLUESKY_HANDLE, max_pages=3)
    
    logger.info("Pagination test suite completed")

if __name__ == "__main__":
    asyncio.run(main()) 