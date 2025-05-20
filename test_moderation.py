import os
import asyncio
import logging
from dotenv import load_dotenv
from account_agent import AccountAgent
from database import Database

# Mock the database class methods we need
class MockDatabase(Database):
    def __init__(self):
        self.conn = None
        
    def get_all_blocked_accounts(self):
        # Return a mock list of blocked accounts
        return [
            {'did': 'did:plc:z4xsud6kzq5ve3cqkvaynwgy', 'handle': 'bsky.app'},  # Bluesky's DID
            {'did': 'did:plc:ragtjsm2j2vknwkz3zp4oxrd', 'handle': 'pfrazee.com'}  # Paul Frazee
        ]
    
    def register_mod_list(self, list_uri, list_cid, owner_did, name):
        # Just log it
        logging.info(f"Registered mod list: {list_uri}, {list_cid}, {owner_did}, {name}")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

async def test_moderation():
    # Get credentials from environment variables
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return
    
    # Create the mock database
    mock_db = MockDatabase()
    
    # Create and initialize account agent
    account_agent = AccountAgent(
        handle=primary_handle,
        password=primary_password,
        is_primary=True,
        database=mock_db
    )
    
    try:
        # Initialize the account agent
        await account_agent.initialize()
        
        # Create or update the moderation list
        mod_list_uri = await account_agent.create_or_update_moderation_list()
        
        if not mod_list_uri:
            logger.error("Failed to create or update moderation list")
            return
        
        # Update moderation list items
        await account_agent.update_moderation_list_items()
        
        logger.info("Moderation test completed successfully")
        
    except Exception as e:
        logger.error(f"Error in moderation test: {e}")
    finally:
        # Clean up
        if account_agent.client:
            account_agent.client.close()

if __name__ == "__main__":
    asyncio.run(test_moderation())