import os
import httpx
import asyncio
import logging
from dotenv import load_dotenv
import json
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ClearSky API base URL
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')

# Test DIDs - using the ones from test_clearsky.py
TEST_DIDS = [
    "did:plc:57na4nqoqohad5wk47jlu4rk",  # gemini.is-a.bot
    "did:plc:5eq355e2dkl6lkdvugveu4oc",  # this.is-a.bot
    "did:plc:33d7gnwiagm6cimpiepefp72",  # symm.social
    "did:plc:4y4wmofpqlwz7e5q5nzjpzdd",  # symm.app
    "did:plc:kkylvufgv5shv2kpd74lca6o",  # symm.now
]

# Dictionary to map DIDs to handles for better readability
DID_TO_HANDLE = {
    "did:plc:57na4nqoqohad5wk47jlu4rk": "gemini.is-a.bot",
    "did:plc:5eq355e2dkl6lkdvugveu4oc": "this.is-a.bot",
    "did:plc:33d7gnwiagm6cimpiepefp72": "symm.social",
    "did:plc:4y4wmofpqlwz7e5q5nzjpzdd": "symm.app",
    "did:plc:kkylvufgv5shv2kpd74lca6o": "symm.now",
}

# Specify which accounts are primary
IS_PRIMARY = {
    "did:plc:33d7gnwiagm6cimpiepefp72": True,  # symm.social is primary
    "did:plc:57na4nqoqohad5wk47jlu4rk": False,  # gemini.is-a.bot
    "did:plc:5eq355e2dkl6lkdvugveu4oc": False,  # this.is-a.bot
    "did:plc:4y4wmofpqlwz7e5q5nzjpzdd": False,  # symm.app
    "did:plc:kkylvufgv5shv2kpd74lca6o": False,  # symm.now
}

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

async def get_blocks_from_clearsky(did):
    """Get both blocking and blocked-by lists for a DID from ClearSky"""
    blocks_info = {
        "blocking": [],      # Who this DID is blocking
        "blocked_by": []     # Who is blocking this DID
    }
    
    # Get who this DID is blocking
    blocking_data = await fetch_from_clearsky(f"/blocklist/{did}")
    if blocking_data and 'data' in blocking_data and 'blocklist' in blocking_data['data']:
        blocklist = blocking_data['data']['blocklist']
        if blocklist:
            # Check if the API returned a list of DIDs or objects
            if isinstance(blocklist, list):
                for item in blocklist:
                    if isinstance(item, str):
                        # It's a simple DID string
                        blocks_info["blocking"].append({"did": item})
                    elif isinstance(item, dict) and 'did' in item:
                        # It's an object with a DID field
                        blocks_info["blocking"].append(item)
            else:
                logger.warning(f"Unexpected blocklist format: {type(blocklist)}")
    
    # Get who is blocking this DID
    blocked_by_data = await fetch_from_clearsky(f"/single-blocklist/{did}")
    if blocked_by_data and 'data' in blocked_by_data and 'blocklist' in blocked_by_data['data']:
        blocked_by_list = blocked_by_data['data']['blocklist']
        if blocked_by_list:
            # Check if the API returned a list of DIDs or objects
            if isinstance(blocked_by_list, list):
                for item in blocked_by_list:
                    if isinstance(item, str):
                        # It's a simple DID string
                        blocks_info["blocked_by"].append({"did": item})
                    elif isinstance(item, dict) and 'did' in item:
                        # It's an object with a DID field
                        blocks_info["blocked_by"].append(item)
            else:
                logger.warning(f"Unexpected blocked_by list format: {type(blocked_by_list)}")
    
    return blocks_info

def initialize_accounts_in_db():
    """Initialize the accounts in the database"""
    logger.info("Initializing accounts in the database...")
    
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed. Cannot initialize accounts.")
        return False
    
    for did, handle in DID_TO_HANDLE.items():
        is_primary = IS_PRIMARY.get(did, False)
        try:
            account_id = db.register_account(handle, did, is_primary)
            logger.info(f"Registered account {handle} (DID: {did}) as {'PRIMARY' if is_primary else 'secondary'} with ID: {account_id}")
        except Exception as e:
            logger.error(f"Failed to register account {handle} (DID: {did}): {e}")
    
    logger.info("Account initialization completed.")
    return True

async def main():
    logger.info("Starting block check for specified DIDs...")
    
    # Get blocks from ClearSky for each DID
    clearsky_blocks_by_did = {}
    for did in TEST_DIDS:
        handle = DID_TO_HANDLE.get(did, "unknown")
        logger.info(f"Getting blocks from ClearSky for {handle} ({did})...")
        
        # Get blocks from ClearSky
        blocks = await get_blocks_from_clearsky(did)
        clearsky_blocks_by_did[did] = blocks
        
        # Rate limiting
        await asyncio.sleep(1)
    
    # Display results
    logger.info("\n=== BLOCK INFORMATION FROM CLEARSKY ===")
    for did, blocks in clearsky_blocks_by_did.items():
        handle = DID_TO_HANDLE.get(did, "unknown")
        logger.info(f"\nAccount: {handle} ({did})")
        
        blocking = blocks["blocking"]
        blocked_by = blocks["blocked_by"]
        
        logger.info(f"  Blocking {len(blocking)} accounts:")
        for i, block_info in enumerate(blocking[:10]):  # Show first 10
            blocked_did = block_info.get("did", "unknown")
            blocked_handle = DID_TO_HANDLE.get(blocked_did, "unknown")
            logger.info(f"    {i+1}. {blocked_did} ({blocked_handle})")
        if len(blocking) > 10:
            logger.info(f"    ... and {len(blocking) - 10} more")
            
        logger.info(f"  Blocked by {len(blocked_by)} accounts:")
        for i, block_info in enumerate(blocked_by[:10]):  # Show first 10
            blocker_did = block_info.get("did", "unknown")
            blocker_handle = DID_TO_HANDLE.get(blocker_did, "unknown")
            logger.info(f"    {i+1}. {blocker_did} ({blocker_handle})")
        if len(blocked_by) > 10:
            logger.info(f"    ... and {len(blocked_by) - 10} more")
    
    # Look for any interesting patterns
    logger.info("\n=== BLOCK ANALYSIS ===")
    
    # Find common blockers (accounts that block multiple of our accounts)
    common_blockers = {}
    for did, blocks in clearsky_blocks_by_did.items():
        for block_info in blocks["blocked_by"]:
            blocker_did = block_info.get("did", "unknown")
            if blocker_did not in common_blockers:
                common_blockers[blocker_did] = []
            common_blockers[blocker_did].append(did)
    
    # Show accounts that block multiple of our accounts
    multiple_blockers = {k: v for k, v in common_blockers.items() if len(v) > 1}
    logger.info(f"Found {len(multiple_blockers)} accounts blocking multiple of our accounts:")
    for blocker_did, blocked_dids in sorted(multiple_blockers.items(), key=lambda x: len(x[1]), reverse=True)[:10]:  # Show top 10
        blocked_handles = [DID_TO_HANDLE.get(did, "unknown") for did in blocked_dids]
        logger.info(f"  {blocker_did} blocks {len(blocked_dids)} of our accounts: {', '.join(blocked_handles)}")
    
    logger.info("\nBlock check completed.")

if __name__ == "__main__":
    # Check if we should initialize accounts
    if os.getenv('INIT_ACCOUNTS', 'false').lower() == 'true':
        initialize_accounts_in_db()
    else:
        asyncio.run(main()) 