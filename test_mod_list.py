import os
import asyncio
import logging
from dotenv import load_dotenv
from atproto import Client, models

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Blue Sky API settings
BLUESKY_API_URL = os.getenv('BLUESKY_API_URL', 'https://bsky.social')

async def test_create_moderation_list():
    """Test creating a moderation list using the fixed code"""
    # Get credentials from environment variables
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return
    
    list_name = "Test Moderation List"
    list_description = "Test description for moderation list"
    
    try:
        # Initialize the client and login
        client = Client(base_url=BLUESKY_API_URL)
        logger.info(f"Attempting to login as {primary_handle}...")
        response = client.login(primary_handle, primary_password)
        did = response.did
        logger.info(f"Successfully logged in as {primary_handle} (DID: {did})")
        
        # Create a moderation list record with the proper fields
        logger.info("Creating moderation list record...")
        
        # Create a directly compatible dictionary instead of a Record
        list_record = {
            "$type": "app.bsky.graph.list",
            "purpose": "app.bsky.graph.defs#modlist",
            "name": list_name,
            "description": list_description,
            "createdAt": client.get_current_time_iso()
        }
        
        # First check if we already have lists
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
            list_cid = response.cid
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
            list_cid = response.cid
            logger.info(f"Successfully created new moderation list: {list_uri}")
        
        # Now, let's try to add an item to the list for testing
        # We'll use a well-known DID like Bluesky's own
        test_did = "did:plc:z4xsud6kzq5ve3cqkvaynwgy"  # bsky.app
        
        logger.info(f"Adding test DID {test_did} to moderation list...")
        
        try:
            # Get current list items by getting the list details
            try:
                list_details = client.app.bsky.graph.get_list(params={"list": list_uri})
                current_items = list_details.items
                current_item_subjects = [item.subject.did for item in current_items]
                logger.info(f"Found {len(current_items)} existing items in moderation list")
            except Exception as e:
                logger.warning(f"Could not fetch list items: {e}")
                current_item_subjects = []
            
            if test_did in current_item_subjects:
                logger.info(f"Test DID {test_did} is already in the list")
            else:
                # Create a directly compatible dictionary for the list item
                item_record = {
                    "$type": "app.bsky.graph.listitem",
                    "subject": test_did,
                    "list": list_uri,
                    "createdAt": client.get_current_time_iso()
                }
                
                response = client.com.atproto.repo.create_record(
                    data={
                        "repo": did,
                        "collection": "app.bsky.graph.listitem",
                        "record": item_record
                    }
                )
                
                logger.info(f"Successfully added test DID {test_did} to moderation list")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                logger.info(f"Test DID {test_did} already in list - skipping")
            else:
                logger.error(f"Error adding test DID {test_did} to moderation list: {e}")
        
        logger.info("Test completed successfully")
        
    except Exception as e:
        logger.error(f"Error testing moderation list creation: {e}")

if __name__ == "__main__":
    asyncio.run(test_create_moderation_list()) 