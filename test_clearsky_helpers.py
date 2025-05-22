import asyncio
import logging
import os
from dotenv import load_dotenv
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test account for pagination testing
TEST_HANDLE = os.getenv('TEST_PAGINATION_BLUESKY_HANDLE', 'symm.social')

async def test_handle_resolution():
    """Test the handle and DID resolution functions"""
    logger.info("Testing handle/DID resolution...")
    
    # Test get_did_from_handle
    handle = "symm.social"
    did = await cs.get_did_from_handle(handle)
    logger.info(f"DID for {handle}: {did}")
    
    # Test get_handle_from_did
    if did:
        resolved_handle = await cs.get_handle_from_did(did)
        logger.info(f"Handle for {did}: {resolved_handle}")
        
        # Verify they match
        if handle.lower() == resolved_handle.lower():
            logger.info("✓ Handle resolution successful")
        else:
            logger.error(f"Handle resolution failed: {handle} != {resolved_handle}")
    
    return did

async def test_profile():
    """Test the profile fetching function"""
    logger.info("Testing profile fetching...")
    
    handle = "symm.social"
    profile = await cs.get_profile(handle)
    
    if profile:
        logger.info(f"Profile for {handle}:")
        logger.info(f"  Handle: {profile.get('handle')}")
        logger.info(f"  DID: {profile.get('did_identifier')}")
        logger.info(f"  Created: {profile.get('created_date')}")
        logger.info(f"  PDS: {profile.get('pds')}")
        return True
    else:
        logger.error(f"Failed to fetch profile for {handle}")
        return False

async def test_pagination(handle=None, max_pages=3):
    """Test the pagination functionality with a limited number of pages"""
    if not handle:
        handle = TEST_HANDLE
        
    logger.info(f"Testing pagination with {handle} (limited to {max_pages} pages)...")
    
    # Get total count
    total = await cs.get_total_blocked_by_count(handle)
    logger.info(f"Total accounts blocking {handle}: {total}")
    
    # Fetch a limited number of pages
    blockers, reported_total = await cs.fetch_all_blocked_by(handle, max_pages=max_pages)
    
    logger.info(f"Fetched {len(blockers)} blockers from {max_pages} pages (out of {reported_total} total)")
    
    # Display sample blockers
    if blockers:
        logger.info("Sample blocker records:")
        for blocker in blockers[:3]:
            logger.info(f"  DID: {blocker['did']}, Blocked date: {blocker['blocked_date']}")
    
    return blockers, reported_total

async def main():
    """Run all tests"""
    logger.info("Starting ClearSky helper tests")
    
    # Test handle resolution
    did = await test_handle_resolution()
    
    # Test profile fetching
    await test_profile()
    
    # Test pagination with limited pages
    await test_pagination(max_pages=3)
    
    logger.info("ClearSky helper tests completed")

if __name__ == "__main__":
    asyncio.run(main()) 