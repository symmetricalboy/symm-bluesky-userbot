import os
import asyncio
import logging
from dotenv import load_dotenv
from atproto import Client
import httpx

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API URLs
BLUESKY_API_URL = os.getenv('BLUESKY_API_URL', 'https://bsky.social')
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')

# Test DIDs
TEST_DIDS = [
    "did:plc:33d7gnwiagm6cimpiepefp72",  # symm.social
    "did:plc:57na4nqoqohad5wk47jlu4rk",  # gemini.is-a.bot
    "did:plc:mbmd5aollpp5vkhc7fqff4cc",  # random DID from logs
]

async def resolve_handle_via_atproto(client, did):
    """Resolve a DID to a handle using atproto client."""
    try:
        logger.info(f"Attempting to resolve handle for DID: {did} via atproto")
        profile = client.com.atproto.repo.describe_repo(params={'repo': did})
        logger.info(f"Success! DID {did} resolved to handle: {profile.handle}")
        return profile.handle
    except Exception as e:
        logger.error(f"Failed to resolve handle for DID {did} via atproto: {e}")
        return None

async def resolve_handle_via_clearsky(did):
    """Resolve a DID to a handle using ClearSky API."""
    try:
        logger.info(f"Attempting to resolve handle for DID: {did} via ClearSky")
        url = f"{CLEARSKY_API_BASE_URL}/get-handle/{did}"
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            handle = data.get('data', {}).get('handle_identifier')
            
            if handle:
                logger.info(f"Success! DID {did} resolved to handle: {handle}")
                return handle
            else:
                logger.warning(f"ClearSky API returned no handle for DID: {did}")
                return None
    except Exception as e:
        logger.error(f"Failed to resolve handle for DID {did} via ClearSky: {e}")
        return None

async def main():
    """Main test function."""
    logger.info("Starting handle resolution test")
    
    # Initialize atproto client
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    client = Client(base_url=BLUESKY_API_URL)
    
    try:
        # Login
        logger.info(f"Logging in as {primary_handle}")
        client.login(primary_handle, primary_password)
        logger.info(f"Successfully logged in as {primary_handle}")
        
        # Test handle resolution for each DID
        for did in TEST_DIDS:
            # Try atproto first
            handle_from_atproto = await resolve_handle_via_atproto(client, did)
            
            # Then try ClearSky as fallback
            if not handle_from_atproto:
                handle_from_clearsky = await resolve_handle_via_clearsky(did)
                if handle_from_clearsky:
                    logger.info(f"Fallback successful: Resolved {did} to {handle_from_clearsky} via ClearSky")
                else:
                    logger.error(f"Failed to resolve {did} via both methods")
            
            # Small delay between tests
            await asyncio.sleep(1)
            
        logger.info("Handle resolution test completed")
        return True
        
    except Exception as e:
        logger.error(f"Unexpected error during test: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1) 