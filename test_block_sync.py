import os
import asyncio
import logging
import random
from dotenv import load_dotenv
from account_agent import AccountAgent
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test DID to block (this is a made-up DID for testing)
TEST_DID = f"did:plc:test{random.randint(10000, 99999)}"

async def main():
    # Initialize database
    db = Database()
    logger.info(f"Testing database connection: {db.test_connection()}")
    
    # Create a secondary account agent
    secondary_handle = os.getenv('SECONDARY_ACCOUNT')
    secondary_password = os.getenv('SECONDARY_PASSWORD')
    
    if not secondary_handle or not secondary_password:
        secondary_handle = "symm.app"  # Default to first secondary
        secondary_password = os.getenv('SYMM_APP_PASSWORD')
        
    logger.info(f"Using secondary account: {secondary_handle}")
    secondary_agent = AccountAgent(secondary_handle, secondary_password, is_primary=False, database=db)
    
    # Log in to secondary account
    logger.info(f"Logging in to secondary account: {secondary_handle}")
    success = await secondary_agent.initialize()
    if not success:
        logger.error(f"Failed to login as {secondary_handle}")
        return
    
    # Create a block on the secondary account
    logger.info(f"Creating test block on {secondary_handle} for DID: {TEST_DID}")
    try:
        # Create a block record
        from atproto_client.models.app.bsky.graph.block import Record as BlockRecord
        from atproto_client.models.com.atproto.repo.create_record import Data as CreateRecordData
        
        block_record = BlockRecord(subject=TEST_DID, created_at=secondary_agent.client.get_current_time_iso())
        data = CreateRecordData(
            repo=secondary_agent.did,
            collection='app.bsky.graph.block',
            record=block_record.model_dump(exclude_none=True, by_alias=True)
        )
        response = await secondary_agent.client.com.atproto.repo.create_record(data=data)
        logger.info(f"Block created successfully! URI: {response.uri}")
        
        # Add it to the database
        logger.info(f"Adding block to database...")
        secondary_agent.database.add_blocked_account(
            did=TEST_DID,
            handle=None,
            source_account_id=secondary_agent.account_id,
            block_type='blocking',
            reason="Test block for sync testing"
        )
        
        logger.info(f"Block added to database. Waiting for sync process to pick it up...")
        
        # Now, initialize primary account to test syncing
        primary_handle = os.getenv('PRIMARY_ACCOUNT', 'symm.social')
        primary_password = os.getenv('PRIMARY_PASSWORD', os.getenv('SYMM_SOCIAL_PASSWORD'))
        
        logger.info(f"Logging in to primary account: {primary_handle}")
        primary_agent = AccountAgent(primary_handle, primary_password, is_primary=True, database=db)
        success = await primary_agent.initialize()
        if not success:
            logger.error(f"Failed to login as {primary_handle}")
            return
        
        # Force a sync from primary account
        logger.info(f"Forcing sync_blocks_from_others on primary account...")
        await primary_agent.sync_blocks_from_others()
        
        # Also force a moderation list update
        logger.info(f"Forcing update_moderation_list_items on primary account...")
        await primary_agent.update_moderation_list_items()
        
        logger.info(f"Sync completed. Check logs to see if the block was synced.")
        
        # Cleanup - Delete the test block
        logger.info(f"Cleaning up test block...")
        rkey = response.uri.split('/')[-1]
        await secondary_agent.client.com.atproto.repo.delete_record(
            repo=secondary_agent.did,
            collection='app.bsky.graph.block',
            rkey=rkey
        )
        logger.info(f"Test block deleted.")
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
    
    logger.info("Test completed.")

if __name__ == "__main__":
    asyncio.run(main()) 