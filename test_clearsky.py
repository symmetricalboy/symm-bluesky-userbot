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

# Test DIDs - using the ones from the logs
TEST_DIDS = [
    "did:plc:57na4nqoqohad5wk47jlu4rk",  # gemini.is-a.bot
    "did:plc:5eq355e2dkl6lkdvugveu4oc",  # this.is-a.bot
    "did:plc:33d7gnwiagm6cimpiepefp72",  # symm.social
    "did:plc:4y4wmofpqlwz7e5q5nzjpzdd",  # symm.app
    "did:plc:kkylvufgv5shv2kpd74lca6o",  # symm.now
]

async def fetch_from_clearsky(endpoint, did=None, page=1):
    """Fetch data from ClearSky API"""
    try:
        url = f"{CLEARSKY_API_BASE_URL}{endpoint}"
        if did:
            url = url.replace("{did}", did)
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

async def test_get_profile(did):
    """Test fetching profile information"""
    logger.info(f"Testing profile endpoint for DID: {did}")
    data = await fetch_from_clearsky(f"/get-profile/{did}")
    if data:
        logger.info(f"Profile data: {json.dumps(data, indent=2)}")
    else:
        logger.error(f"Failed to fetch profile data for {did}")

async def test_get_handle(did):
    """Test resolving handle from DID"""
    logger.info(f"Testing handle resolution for DID: {did}")
    data = await fetch_from_clearsky(f"/get-handle/{did}")
    if data:
        logger.info(f"Handle data: {json.dumps(data, indent=2)}")
    else:
        logger.error(f"Failed to resolve handle for {did}")

async def test_single_blocklist(did):
    """Test fetching who is blocking the given DID - using the correct endpoint as per API docs"""
    logger.info(f"Testing single-blocklist endpoint for DID: {did}")
    data = await fetch_from_clearsky(f"/single-blocklist/{did}")
    if data:
        logger.info(f"Single-blocklist data: {json.dumps(data, indent=2)}")
        # Check if data has the expected structure
        if 'data' in data and 'blocklist' in data['data']:
            blocked_by = data['data']['blocklist']
            if blocked_by is None:
                logger.info(f"No accounts found blocking {did}")
            else:
                logger.info(f"Found {len(blocked_by)} accounts blocking {did}")
                for blocker in blocked_by[:5]:  # Show first 5 for brevity
                    logger.info(f"Blocker: {blocker}")
        else:
            logger.warning(f"Unexpected data structure for single-blocklist endpoint: {data}")
    else:
        logger.error(f"Failed to fetch single-blocklist data for {did}")

async def test_blocklist(did):
    """Test fetching who the given DID is blocking"""
    logger.info(f"Testing blocklist endpoint for DID: {did}")
    data = await fetch_from_clearsky(f"/blocklist/{did}")
    if data:
        logger.info(f"Blocklist data: {json.dumps(data, indent=2)}")
        # Check if data has the expected structure
        if 'data' in data and 'blocklist' in data['data']:
            blocklist = data['data']['blocklist']
            if blocklist is None:
                logger.info(f"No accounts being blocked by {did}")
            else:
                logger.info(f"Found {len(blocklist)} accounts being blocked by {did}")
                for blocked in blocklist[:5]:  # Show first 5 for brevity
                    logger.info(f"Blocked: {blocked}")
        else:
            logger.warning(f"Unexpected data structure for blocklist endpoint: {data}")
    else:
        logger.error(f"Failed to fetch blocklist data for {did}")

async def test_fun_facts():
    """Test fetching fun-facts data"""
    logger.info("Testing fun-facts endpoint")
    data = await fetch_from_clearsky("/lists/fun-facts")
    if data:
        logger.info(f"Fun-facts data: {json.dumps(data, indent=2)}")
        if 'data' in data:
            if 'blocked' in data['data']:
                blocked = data['data']['blocked']
                logger.info(f"Top blocked accounts: {len(blocked)}")
                for account in blocked[:5]:
                    logger.info(f"Blocked account: {account}")
            
            if 'blockers' in data['data']:
                blockers = data['data']['blockers']
                logger.info(f"Top blockers: {len(blockers)}")
                for account in blockers[:5]:
                    logger.info(f"Blocker account: {account}")
    else:
        logger.error("Failed to fetch fun-facts data")

async def test_moderation_issue():
    """Test the issue with moderation list creation"""
    from atproto import models, Client
    
    # Testing if models.AppBskyGraphList is correctly defined
    try:
        logger.info("Testing if models.AppBskyGraphList can be instantiated")
        
        # Check if AppBskyGraphList is a class or a module
        if hasattr(models, 'AppBskyGraphList'):
            logger.info(f"models.AppBskyGraphList exists, type: {type(models.AppBskyGraphList)}")
            
            if hasattr(models, 'app'):
                logger.info("models.app namespace exists")
                if hasattr(models.app, 'bsky'):
                    logger.info("models.app.bsky namespace exists")
                    if hasattr(models.app.bsky, 'graph'):
                        logger.info("models.app.bsky.graph namespace exists")
                        if hasattr(models.app.bsky.graph, 'list'):
                            logger.info("models.app.bsky.graph.list exists")
            
            # Try to create a list record
            try:
                # Check if it's callable directly
                list_record = models.AppBskyGraphList(
                    purpose="app.bsky.graph.defs#modlist",
                    name="Test List",
                    description="Test Description",
                    created_at="2023-01-01T00:00:00Z"
                )
                logger.info("Successfully created list record via models.AppBskyGraphList")
            except Exception as e:
                logger.error(f"Error creating list record via models.AppBskyGraphList: {e}")
                
                # Try alternate approach if it's a module
                try:
                    # Check if we need to use models.app.bsky.graph.list instead
                    if hasattr(models.app.bsky.graph, 'list'):
                        list_module = models.app.bsky.graph.list
                        if hasattr(list_module, 'create'):
                            logger.info("Found models.app.bsky.graph.list.create, trying that")
                            list_record = list_module.create(
                                purpose="app.bsky.graph.defs#modlist",
                                name="Test List",
                                description="Test Description",
                                created_at="2023-01-01T00:00:00Z"
                            )
                            logger.info("Successfully created list record via models.app.bsky.graph.list.create")
                except Exception as alt_e:
                    logger.error(f"Alternative approach also failed: {alt_e}")
                    
                # Check models.ids
                if hasattr(models, 'ids'):
                    logger.info(f"models.ids exists, type: {type(models.ids)}")
                    if hasattr(models.ids, 'AppBskyGraphList'):
                        logger.info(f"models.ids.AppBskyGraphList exists: {models.ids.AppBskyGraphList}")
    except Exception as e:
        logger.error(f"Error testing moderation list creation: {e}")

async def test_clearsky_api():
    """Test ClearSky API endpoints to ensure they work correctly."""
    logger.info("Starting ClearSky API test...")
    
    # Initialize HTTP client with a timeout
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        # Test 1: Get who is blocking the test DID using /single-blocklist endpoint
        try:
            url = f"{CLEARSKY_API_BASE_URL}/single-blocklist/{TEST_DIDS[0]}/1"
            logger.info(f"Testing endpoint: {url}")
            
            response = await http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Check the response structure
            if 'data' in data and 'blocklist' in data['data']:
                blocklist = data['data']['blocklist']
                logger.info(f"Successfully retrieved blocklist with {len(blocklist)} items from /single-blocklist endpoint")
                # Display first few entries if available
                if blocklist and len(blocklist) > 0:
                    logger.info(f"Sample blocklist entries: {blocklist[:3]}")
            else:
                logger.warning(f"Unexpected response format from /single-blocklist endpoint: {data}")
        except Exception as e:
            logger.error(f"Error testing /single-blocklist endpoint: {e}")
        
        # Test 2: Get who the test DID is blocking using /blocklist endpoint
        try:
            url = f"{CLEARSKY_API_BASE_URL}/blocklist/{TEST_DIDS[0]}/1"
            logger.info(f"Testing endpoint: {url}")
            
            response = await http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Check the response structure
            if 'data' in data and 'blocklist' in data['data']:
                blocklist = data['data']['blocklist']
                logger.info(f"Successfully retrieved blocklist with {len(blocklist)} items from /blocklist endpoint")
                # Display first few entries if available
                if blocklist and len(blocklist) > 0:
                    logger.info(f"Sample blocklist entries: {blocklist[:3]}")
            else:
                logger.warning(f"Unexpected response format from /blocklist endpoint: {data}")
        except Exception as e:
            logger.error(f"Error testing /blocklist endpoint: {e}")
            
    logger.info("ClearSky API test completed")

async def main():
    """Main function to run tests"""
    logger.info("Starting ClearSky API tests")
    
    # Test profile and handle resolution for one DID
    test_did = TEST_DIDS[0]  # gemini.is-a.bot
    await test_get_profile(test_did)
    await test_get_handle(test_did)
    
    # Test single-blocklist endpoint (who is blocking the given DID) for all DIDs
    for did in TEST_DIDS:
        await test_single_blocklist(did)
        await asyncio.sleep(0.3)  # Rate limiting
    
    # Test blocklist endpoint (who the given DID is blocking) for all DIDs
    for did in TEST_DIDS:
        await test_blocklist(did)
        await asyncio.sleep(0.3)  # Rate limiting
    
    # Test fun-facts endpoint
    await test_fun_facts()
    
    # Test moderation list issue
    await test_moderation_issue()
    
    # Test ClearSky API endpoints
    await test_clearsky_api()
    
    logger.info("ClearSky API tests completed")

if __name__ == "__main__":
    asyncio.run(main()) 