import os
import httpx
import asyncio
import logging
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ClearSky API base URL
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')

# Dictionary to map DIDs to handles
DID_TO_HANDLE = {
    "did:plc:57na4nqoqohad5wk47jlu4rk": "gemini.is-a.bot",
    "did:plc:5eq355e2dkl6lkdvugveu4oc": "this.is-a.bot",
    "did:plc:33d7gnwiagm6cimpiepefp72": "symm.social",
    "did:plc:4y4wmofpqlwz7e5q5nzjpzdd": "symm.app",
    "did:plc:kkylvufgv5shv2kpd74lca6o": "symm.now",
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

async def populate_blocks_from_clearsky():
    """Populate block information from ClearSky into our database"""
    logger.info("Starting to populate block information from ClearSky...")
    
    # Initialize database
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed. Cannot populate blocks.")
        return False
    
    # Get accounts from database to ensure they exist
    primary_account = db.get_primary_account()
    secondary_accounts = db.get_secondary_accounts() or []
    
    accounts = []
    if primary_account:
        accounts.append(primary_account)
    if secondary_accounts:
        accounts.extend(secondary_accounts)
    
    if not accounts:
        logger.error("No accounts found in database. Run initialize_accounts.py first.")
        return False
    
    logger.info(f"Found {len(accounts)} accounts in database")
    
    # For each account, get blocks from ClearSky and add to database
    for account in accounts:
        account_did = account['did']
        account_handle = account['handle']
        account_id = account['id']
        
        logger.info(f"Getting blocks for {account_handle} ({account_did})...")
        
        # Get blocks from ClearSky
        blocks = await get_blocks_from_clearsky(account_did)
        
        # Add 'blocking' relationships to database
        logger.info(f"Adding {len(blocks['blocking'])} 'blocking' relationships for {account_handle}...")
        for block_info in blocks['blocking']:
            blocked_did = block_info.get('did')
            blocked_handle = DID_TO_HANDLE.get(blocked_did, "unknown")  # Use known handle if available
            
            try:
                db.add_blocked_account(
                    did=blocked_did,
                    handle=blocked_handle,
                    source_account_id=account_id,
                    block_type='blocking',
                    reason="Imported from ClearSky"
                )
                logger.info(f"Added blocking relationship: {account_handle} blocks {blocked_did}")
            except Exception as e:
                logger.error(f"Error adding blocking relationship: {e}")
        
        # Add 'blocked_by' relationships to database
        logger.info(f"Adding {len(blocks['blocked_by'])} 'blocked_by' relationships for {account_handle}...")
        for block_info in blocks['blocked_by']:
            blocker_did = block_info.get('did')
            blocker_handle = DID_TO_HANDLE.get(blocker_did, "unknown")  # Use known handle if available
            
            try:
                db.add_blocked_account(
                    did=blocker_did,
                    handle=blocker_handle,
                    source_account_id=account_id,
                    block_type='blocked_by',
                    reason="Imported from ClearSky"
                )
                logger.info(f"Added blocked_by relationship: {account_handle} is blocked by {blocker_did}")
            except Exception as e:
                logger.error(f"Error adding blocked_by relationship: {e}")
        
        # Rate limiting
        await asyncio.sleep(1)
    
    logger.info("Block population completed.")
    return True

if __name__ == "__main__":
    asyncio.run(populate_blocks_from_clearsky()) 