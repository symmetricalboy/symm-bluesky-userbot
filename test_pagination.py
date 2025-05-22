import os
import httpx
import asyncio
import logging
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
            response = await client.get(url)
            
            if response.status_code == 404:
                logger.warning(f"404 Not Found for {url}")
                return None
                
            response.raise_for_status()
            data = response.json()
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

async def test_pagination(handle):
    """Test the pagination functionality by counting all accounts that block the given handle"""
    # Get total count from the dedicated endpoint
    total_count = await get_total_blocked_by_count(handle)
    if total_count is None:
        logger.error("Unable to proceed with pagination test due to missing total count")
        return
    
    # Now fetch all pages and count manually to verify
    all_blockers = []
    page = 1
    blockers_per_page = 100  # ClearSky returns 100 records per page
    
    while True:
        logger.info(f"Fetching page {page} of blocked-by accounts")
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
        
        # Validate each blocker record has the expected structure
        valid_blockers = []
        for blocker in blockers:
            if 'did' in blocker and 'blocked_date' in blocker:
                valid_blockers.append(blocker)
            else:
                logger.warning(f"Blocker record missing required fields: {blocker}")
        
        logger.info(f"Found {len(valid_blockers)} valid blocker records on page {page}")
        all_blockers.extend(valid_blockers)
        
        # If we got fewer records than the expected per page, we've reached the end
        if len(blockers) < blockers_per_page:
            logger.info(f"Reached last page with {len(blockers)} records")
            break
        
        # Move to next page
        page += 1
        
        # Add a small delay to be nice to the API
        await asyncio.sleep(0.5)
    
    # Compare counts
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
    
    return all_blockers

async def main():
    logger.info("Starting pagination test")
    
    if not TEST_PAGINATION_BLUESKY_PASSWORD:
        logger.error("TEST_PAGINATION_BLUESKY_PASSWORD environment variable is not set")
        return
    
    # Run the pagination test
    await test_pagination(TEST_PAGINATION_BLUESKY_HANDLE)
    
    logger.info("Pagination test completed")

if __name__ == "__main__":
    asyncio.run(main()) 