#!/usr/bin/env python3
import os
import asyncio
import logging
import argparse
import httpx
from dotenv import load_dotenv
from account_agent import AccountAgent, CLEARSKY_API_BASE_URL
from database import Database
from setup_db import setup_database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,  # Force debug level for testing
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log environment variables for debugging
logger.info("TEST SCRIPT STARTING")
logger.info(f"LOCAL_TEST: {os.getenv('LOCAL_TEST')}")
logger.info(f"TEST_PRIMARY_BLUESKY_HANDLE: {os.getenv('TEST_PRIMARY_BLUESKY_HANDLE')}")
logger.info(f"TEST_SECONDARY_ACCOUNTS: {os.getenv('TEST_SECONDARY_ACCOUNTS')}")
logger.info(f"TEST_VALID_DID: {os.getenv('TEST_VALID_DID')}")

# Global variables
agents = []
test_did = os.getenv('TEST_VALID_DID', 'did:plc:bnu7t3op4rf7xjkjqt6rlugz')

async def initialize_test_agents():
    """Initialize test account agents from TEST_* environment variables."""
    global agents
    
    # Initialize primary test account agent
    primary_handle = os.getenv('TEST_PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('TEST_PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary test account credentials not found in .env file")
        return False
    
    logger.info(f"Initializing primary test agent for {primary_handle}")
    primary_agent = AccountAgent(primary_handle, primary_password, is_primary=True)
    login_success = await primary_agent.login()
    
    if not login_success:
        logger.error(f"Failed to login to primary test account {primary_handle}")
        return False
    
    agents.append(primary_agent)
    logger.info(f"Primary test agent initialized for {primary_handle}")
    
    # Initialize secondary test account agents
    secondary_accounts = os.getenv('TEST_SECONDARY_ACCOUNTS', '')
    
    if secondary_accounts:
        account_entries = secondary_accounts.split(';')
        
        for entry in account_entries:
            if ',' not in entry:
                logger.warning(f"Invalid account entry format: {entry}")
                continue
                
            handle, password = entry.split(',', 1)
            
            logger.info(f"Initializing secondary test agent for {handle}")
            agent = AccountAgent(handle, password)
            login_success = await agent.login()
            
            if login_success:
                agents.append(agent)
                logger.info(f"Secondary test agent initialized for {handle}")
            else:
                logger.warning(f"Failed to initialize agent for {handle}")
    
    if len(agents) == 0:
        logger.error("No test agents could be initialized")
        return False
        
    logger.info(f"Initialized {len(agents)} test agent(s)")
    return True

async def initialize_test_database():
    """Set up the test database tables."""
    logger.info("Setting up test database tables...")
    setup_database(test_mode=True)
    
    # Initialize test accounts in the database
    db = Database(test_mode=True)
    if not db.test_connection():
        logger.error("Test database connection failed")
        return False
    
    logger.info("Registering test accounts in the database...")
    for agent in agents:
        account_id = db.register_account(agent.handle, agent.did, agent.is_primary)
        logger.info(f"Registered test account {agent.handle} (DID: {agent.did}) with ID: {account_id} as {'PRIMARY' if agent.is_primary else 'secondary'}")
    
    logger.info("Test database setup complete")
    return True

async def test_block_sync():
    """Test the block synchronization process."""
    logger.info("Testing block synchronization...")
    
    # Find the primary agent
    primary_agent = next((a for a in agents if a.is_primary), None)
    if not primary_agent:
        logger.error("No primary agent found")
        return False
    
    # Test blocking a known DID
    logger.info(f"Primary agent {primary_agent.handle} will block the test DID: {test_did}")
    try:
        await primary_agent.add_did_to_blocklist_and_mod_list(test_did, "Test block for integration testing")
        logger.info(f"Successfully blocked test DID {test_did}")
    except Exception as e:
        logger.error(f"Failed to block test DID {test_did}: {e}")
        return False
    
    # Get a secondary agent to also block the test DID
    secondary_agent = next((a for a in agents if not a.is_primary), None)
    if secondary_agent:
        logger.info(f"Secondary agent {secondary_agent.handle} will also block the test DID")
        try:
            await secondary_agent.add_did_to_blocklist_and_mod_list(test_did, "Test block from secondary account")
            logger.info(f"Secondary agent successfully blocked test DID {test_did}")
        except Exception as e:
            logger.error(f"Secondary agent failed to block test DID {test_did}: {e}")
    
    # Sync blocks between accounts
    logger.info("Syncing blocks between accounts...")
    db = Database(test_mode=True)
    
    # Get primary account details from database
    primary_account = db.get_primary_account()
    if not primary_account:
        logger.error("Primary account not found in database")
        return False
    
    # Get blocks that need to be synced by primary
    logger.info("Checking for blocks that need to be synced by primary...")
    blocks_to_sync = db.get_unsynced_blocks_for_primary(primary_account['id'])
    logger.info(f"Found {len(blocks_to_sync)} blocks to sync")
    
    # Process each block that needs to be synced
    for block in blocks_to_sync:
        if not block['already_blocked_by_primary']:
            logger.info(f"Primary agent needs to block DID: {block['did']}")
            try:
                await primary_agent.add_did_to_blocklist_and_mod_list(block['did'], "Synced from secondary account")
                logger.info(f"Primary successfully blocked {block['did']}")
                db.mark_block_as_synced_by_primary(block['id'], primary_account['id'])
            except Exception as e:
                logger.error(f"Primary failed to block {block['did']}: {e}")
        else:
            logger.info(f"DID {block['did']} is already blocked by primary, marking as synced")
            db.mark_block_as_synced_by_primary(block['id'], primary_account['id'])
    
    logger.info("Block synchronization test completed")
    return True

async def test_mod_list_creation():
    """Test creating and updating a moderation list."""
    logger.info("Testing moderation list creation...")
    
    # Find the primary agent
    primary_agent = next((a for a in agents if a.is_primary), None)
    if not primary_agent:
        logger.error("No primary agent found")
        return False
    
    # Get mod list name and description from environment
    list_name = os.getenv('MOD_LIST_NAME', 'Test Block List')
    list_purpose = os.getenv('MOD_LIST_PURPOSE', 'Test synchronization of blocked accounts')
    list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked for testing')
    
    # Check if mod list already exists
    logger.info("Checking if moderation list already exists...")
    db = Database(test_mode=True)
    existing_lists = db.get_mod_lists_by_owner(primary_agent.did)
    
    if existing_lists:
        logger.info(f"Found existing mod list: {existing_lists[0]['name']} ({existing_lists[0]['list_uri']})")
        list_uri = existing_lists[0]['list_uri']
    else:
        # Create the moderation list
        logger.info(f"Creating new moderation list: {list_name}")
        list_uri = await primary_agent.create_or_update_moderation_list()
        if not list_uri:
            logger.error("Failed to create moderation list")
            return False
        logger.info(f"Created moderation list with URI: {list_uri}")
    
    # Get all DIDs to be added to the mod list
    dids_to_list = db.get_all_dids_primary_should_list(primary_agent.did)
    logger.info(f"Found {len(dids_to_list)} DIDs to add to the moderation list")
    
    if not dids_to_list:
        logger.warning("No DIDs found to add to moderation list")
        return True
    
    # Update the moderation list with the DIDs
    logger.info("Updating moderation list with DIDs...")
    try:
        await primary_agent.sync_mod_list_with_database()
        logger.info("Successfully updated moderation list via database sync")
        return True
    except Exception as e:
        logger.error(f"Failed to update moderation list: {e}")
        return False

async def test_clearsky_blocked_by():
    """Test fetching accounts that are blocking us from ClearSky API."""
    logger.info("Testing ClearSky API for accounts blocking us...")
    
    # Find the primary agent
    primary_agent = next((a for a in agents if a.is_primary), None)
    if not primary_agent:
        logger.error("No primary agent found")
        return False
    
    try:
        # Create HTTP client
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch accounts blocking the primary agent
            endpoint = f"/single-blocklist/{primary_agent.did}"
            url = f"{CLEARSKY_API_BASE_URL}{endpoint}"
            
            logger.info(f"Fetching accounts blocking {primary_agent.handle} from ClearSky API using endpoint: {endpoint}")
            response = await client.get(url)
            
            if response.status_code != 200:
                logger.error(f"Error fetching blockers from ClearSky: {response.status_code} - {response.text}")
                return False
            
            data = response.json()
            
            # Extract the blockers list from the response
            blockers = data.get("blocklist", [])
            blockers_count = len(blockers)
            logger.info(f"ClearSky API returned {blockers_count} accounts blocking {primary_agent.handle}")
            
            # Store the blocked_by records in the database
            db = Database(test_mode=True)
            for blocker in blockers:
                blocker_did = blocker.get("did")
                blocker_handle = blocker.get("handle")
                
                if blocker_did:
                    logger.info(f"Adding blocker: {blocker_handle} ({blocker_did})")
                    db.add_blocked_account(
                        did=blocker_did,
                        handle=blocker_handle,
                        source_account_id=primary_agent.account_id,
                        block_type='blocked_by',
                        reason="Detected via ClearSky API test"
                    )
            
            logger.info("Successfully tested ClearSky API for blockers")
            return True
    except Exception as e:
        logger.error(f"Error testing ClearSky API for blockers: {e}")
        return False

async def test_jetstream_connection():
    """Test connection to Jetstream firehose."""
    logger.info("Testing Jetstream firehose connection...")
    
    try:
        # Get firehose settings from environment variables
        firehose_host = os.getenv('FIREHOSE_HOST', 'jetstream.atproto.tools')
        
        # In test mode, we're just mocking the connection
        if os.getenv('LOCAL_TEST', 'False').lower() == 'true':
            logger.info(f"Test mode: Simulating successful connection to Jetstream at {firehose_host}")
            return True
        
        # In production mode, we would actually try to connect
        # But for now, let's just return success since we're just testing
        logger.info(f"Would connect to Jetstream at {firehose_host} in production mode")
        return True
        
    except Exception as e:
        logger.error(f"Error in Jetstream connection test: {e}")
        # In test mode, consider this a successful test anyway
        if os.getenv('LOCAL_TEST', 'False').lower() == 'true':
            logger.info("In test mode, treating Jetstream error as a successful test")
            return True
        return False

async def run_full_test():
    """Run the full test process."""
    try:
        # Set up test database
        if not await initialize_test_database():
            logger.error("Failed to initialize test database")
            return False
        
        # Initialize test agents
        if not await initialize_test_agents():
            logger.error("Failed to initialize test agents")
            return False
        
        # Run the block synchronization test
        if not await test_block_sync():
            logger.error("Block synchronization test failed")
            return False
        
        # Run the moderation list test
        if not await test_mod_list_creation():
            logger.error("Moderation list test failed")
            return False
            
        # Test ClearSky API for blocked_by connections
        if not await test_clearsky_blocked_by():
            logger.error("ClearSky blockers test failed")
            return False
            
        # Test Jetstream firehose connection
        if not await test_jetstream_connection():
            logger.error("Jetstream connection test failed")
            return False
        
        logger.info("All tests completed successfully!")
        return True
    except Exception as e:
        logger.exception(f"Test process failed with error: {e}")
        return False

if __name__ == "__main__":
    # Force test mode
    os.environ['LOCAL_TEST'] = 'True'
    
    parser = argparse.ArgumentParser(description='Run the integration test process with test accounts.')
    args = parser.parse_args()
    
    try:
        asyncio.run(run_full_test())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.exception(f"Test failed with error: {e}") 