import os
import asyncio
import logging
import httpx
from dotenv import load_dotenv
from account_agent import AccountAgent

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a mock database class
class MockDatabase:
    def __init__(self):
        self.accounts = {}
        self.blocks = []
        self.mod_lists = {}
    
    def register_account(self, handle, did, is_primary=False):
        account_id = len(self.accounts) + 1
        self.accounts[account_id] = {
            'handle': handle,
            'did': did,
            'is_primary': is_primary
        }
        logger.info(f"Mock DB: Registered account {handle} with ID {account_id}")
        return account_id
    
    def register_mod_list(self, list_uri, list_cid, owner_did, name):
        logger.info(f"Mock DB: Registered mod list {list_uri} for {owner_did}")
        self.mod_lists[list_uri] = {
            'cid': list_cid,
            'owner_did': owner_did,
            'name': name
        }
        return True
    
    def add_blocked_account(self, did, handle, source_account_id, block_type):
        logger.info(f"Mock DB: Added blocked account {handle} ({did}) by account {source_account_id}, type {block_type}")
        self.blocks.append({
            'did': did,
            'handle': handle,
            'source_account_id': source_account_id,
            'block_type': block_type
        })
        return True
    
    def remove_stale_blocks(self, account_id, block_type, valid_dids):
        logger.info(f"Mock DB: Removed stale blocks for account {account_id}, type {block_type}")
        return True
    
    def get_all_blocked_accounts(self):
        # Return a few sample blocked accounts for testing
        return [
            {'did': 'did:plc:z4xsud6kzq5ve3cqkvaynwgy', 'handle': 'bsky.app'},
            {'did': 'did:plc:ragtjsm2j2vknwkz3zp4oxrd', 'handle': 'pfrazee.com'}
        ]
    
    def get_unsynced_blocks_for_primary(self, primary_account_id):
        # Return a sample unsynced block
        return [
            {'id': 1, 'did': 'did:plc:z4xsud6kzq5ve3cqkvaynwgy', 'handle': 'bsky.app'},
            {'id': 2, 'did': 'did:plc:ragtjsm2j2vknwkz3zp4oxrd', 'handle': 'pfrazee.com'}
        ]
    
    def mark_block_as_synced_by_primary(self, block_id, primary_account_id):
        logger.info(f"Mock DB: Marked block {block_id} as synced by primary account {primary_account_id}")
        return True
    
    def get_connection(self):
        # For compatibility with code that directly uses connections
        return None

async def test_account_agent():
    """Test the fixed AccountAgent class."""
    # Get credentials from environment variables
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return
    
    try:
        # Create a mock database
        mock_db = MockDatabase()
        
        # Create the account agent with the mock database
        logger.info(f"Creating account agent for {primary_handle} with mock database...")
        account_agent = AccountAgent(
            handle=primary_handle,
            password=primary_password,
            is_primary=True,
            database=mock_db
        )
        
        # Test login only (skip database operations)
        logger.info(f"Testing login for {primary_handle}...")
        try:
            response = account_agent.client.login(primary_handle, primary_password)
            account_agent.did = response.did
            logger.info(f"Successfully logged in as {primary_handle} (DID: {account_agent.did})")
            account_agent.account_id = mock_db.register_account(
                primary_handle, account_agent.did, is_primary=True
            )
        except Exception as e:
            logger.error(f"Failed to login as {primary_handle}: {e}")
            return
        
        # Test ClearSky API integration
        logger.info("Testing ClearSky API integration...")
        
        # Test single-blocklist endpoint (who is blocking this account)
        logger.info("Testing single-blocklist endpoint...")
        try:
            url = f"{account_agent.CLEARSKY_API_BASE_URL}/single-blocklist/{account_agent.did}/1"
            logger.info(f"Fetching from: {url}")
            
            async with account_agent.http_client as client:
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'data' in data and 'blocklist' in data['data']:
                        blocklist = data['data']['blocklist']
                        if blocklist is None:
                            logger.info(f"No accounts found blocking {account_agent.handle}")
                        else:
                            logger.info(f"Found {len(blocklist)} accounts blocking {account_agent.handle}")
                    else:
                        logger.warning(f"Unexpected response format: {data}")
                else:
                    logger.warning(f"Got status code {response.status_code} from ClearSky API")
        except Exception as e:
            logger.error(f"Error testing single-blocklist endpoint: {e}")
        
        # Clean up
        if account_agent.http_client and not account_agent.http_client.is_closed:
            await account_agent.http_client.aclose()
        
        logger.info("Test completed successfully")
        
    except Exception as e:
        logger.error(f"Error testing account agent: {e}")

async def test_moderation_list_only():
    """Test just the moderation list creation without any database dependencies."""
    from atproto import models, Client
    
    # Get credentials from environment variables
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return
    
    try:
        # Initialize the client and login
        client = Client(base_url="https://bsky.social")
        logger.info(f"Attempting to login as {primary_handle}...")
        response = client.login(primary_handle, primary_password)
        did = response.did
        logger.info(f"Successfully logged in as {primary_handle} (DID: {did})")
        
        # Create the moderation list record
        logger.info("Creating moderation list record...")
        
        list_name = "Test Moderation List"
        list_description = "Test description for moderation list"
        
        # Create a direct dictionary as this is the correct approach, not using models.AppBskyGraphList constructor
        list_record = {
            "$type": "app.bsky.graph.list",
            "purpose": "app.bsky.graph.defs#modlist",
            "name": list_name,
            "description": list_description,
            "createdAt": client.get_current_time_iso()
        }
        
        # First check for existing lists
        try:
            logger.info("Checking for existing lists...")
            lists_response = client.app.bsky.graph.get_lists(params={"actor": did})
            existing_lists = lists_response.lists
            existing_list = None
            
            for lst in existing_lists:
                logger.info(f"Found list: '{lst.name}' with purpose {lst.purpose}")
                if lst.name == list_name and lst.purpose == "app.bsky.graph.defs#modlist":
                    existing_list = lst
                    logger.info(f"Found existing matching moderation list: {lst.uri}")
                    break
        except Exception as e:
            logger.warning(f"Could not fetch existing lists: {e}")
            existing_list = None
        
        if existing_list:
            # Update existing list
            logger.info(f"Updating existing moderation list: {existing_list.uri}")
            response = client.com.atproto.repo.put_record(
                data={
                    "repo": did,
                    "collection": "app.bsky.graph.list",
                    "rkey": existing_list.uri.split('/')[-1],
                    "record": list_record
                }
            )
            list_uri = existing_list.uri
            logger.info(f"Successfully updated existing moderation list: {list_uri}")
        else:
            # Create new list
            logger.info("Creating new moderation list...")
            response = client.com.atproto.repo.create_record(
                data={
                    "repo": did,
                    "collection": "app.bsky.graph.list",
                    "record": list_record
                }
            )
            list_uri = response.uri
            logger.info(f"Successfully created new moderation list: {list_uri}")
        
        logger.info("Test completed successfully")
        
    except Exception as e:
        logger.error(f"Error testing moderation list creation: {e}")

async def test_clearsky_api_only():
    """Test only the ClearSky API endpoints without any database dependencies."""
    # ClearSky API base URL
    CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')
    
    # Get credentials from environment variables
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return
    
    try:
        # Initialize the client and login
        from atproto import Client
        client = Client(base_url="https://bsky.social")
        logger.info(f"Attempting to login as {primary_handle}...")
        response = client.login(primary_handle, primary_password)
        did = response.did
        logger.info(f"Successfully logged in as {primary_handle} (DID: {did})")
        
        # Test the /single-blocklist/{did} endpoint - who is blocking this account
        logger.info(f"Testing /single-blocklist/{did} endpoint...")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http_client:
            url = f"{CLEARSKY_API_BASE_URL}/single-blocklist/{did}/1"
            logger.info(f"Fetching from: {url}")
            
            response = await http_client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Response: {data}")
                
                if 'data' in data and 'blocklist' in data['data']:
                    blocklist = data['data']['blocklist']
                    if blocklist is None:
                        logger.info(f"No accounts found blocking {primary_handle}")
                    else:
                        logger.info(f"Found {len(blocklist)} accounts blocking {primary_handle}")
                        # Show a few samples
                        for i, entry in enumerate(blocklist[:5]):
                            logger.info(f"Blocker {i+1}: {entry}")
                else:
                    logger.warning(f"Unexpected response format for /single-blocklist endpoint: {data}")
            else:
                logger.warning(f"Got status code {response.status_code} from ClearSky API for /single-blocklist endpoint")
        
        # Test the /blocklist/{did} endpoint - who this account is blocking
        logger.info(f"Testing /blocklist/{did} endpoint...")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http_client:
            url = f"{CLEARSKY_API_BASE_URL}/blocklist/{did}/1"
            logger.info(f"Fetching from: {url}")
            
            response = await http_client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Response: {data}")
                
                if 'data' in data and 'blocklist' in data['data']:
                    blocklist = data['data']['blocklist']
                    if blocklist is None:
                        logger.info(f"No accounts found that {primary_handle} is blocking")
                    else:
                        logger.info(f"Found {len(blocklist)} accounts that {primary_handle} is blocking")
                        # Show a few samples
                        for i, entry in enumerate(blocklist[:5]):
                            logger.info(f"Blocked {i+1}: {entry}")
                else:
                    logger.warning(f"Unexpected response format for /blocklist endpoint: {data}")
            else:
                logger.warning(f"Got status code {response.status_code} from ClearSky API for /blocklist endpoint")
        
        logger.info("Test completed successfully")
        
    except Exception as e:
        logger.error(f"Error testing ClearSky API: {e}")

if __name__ == "__main__":
    asyncio.run(test_clearsky_api_only()) 