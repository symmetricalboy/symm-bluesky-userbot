import os
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
import websockets
from dotenv import load_dotenv
from account_agent import AccountAgent
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Jetstream server address
JETSTREAM_SERVER = "wss://jetstream.atproto.tools/subscribe"

async def connect_to_jetstream(server_addr):
    """Connect to the jetstream server and process events"""
    logger.info(f"Connecting to jetstream server at {server_addr}")
    
    # Calculate timestamp for 1 hour ago
    one_hour_ago = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000000)
    cursor_param = f"?cursor={one_hour_ago}"
    
    # Connect with cursor to get recent history
    async with websockets.connect(f"{server_addr}{cursor_param}") as websocket:
        logger.info("Connected to jetstream. Monitoring for block events...")
        
        block_events = {
            "blocks_created": [],
            "blocks_deleted": []
        }
        
        while True:
            try:
                # Receive message from websocket
                message = await websocket.recv()
                
                # Parse the JSON message
                try:
                    data = json.loads(message)
                    
                    # Process only commit events with block-related collections
                    if (data.get("commit") and 
                        data["commit"].get("collection") == "app.bsky.graph.block"):
                        
                        operation = data["commit"].get("operation")
                        did = data.get("did", "unknown")
                        timestamp = datetime.fromtimestamp(data.get("time_us", 0)/1000000).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Extract block information
                        if operation == "create":
                            if data["commit"].get("record"):
                                subject_did = data["commit"]["record"].get("subject", "unknown")
                                logger.info(f"BLOCK CREATED: {did} blocked {subject_did} at {timestamp}")
                                block_events["blocks_created"].append({
                                    "blocker_did": did,
                                    "blocked_did": subject_did,
                                    "timestamp": timestamp
                                })
                        
                        elif operation == "delete":
                            rkey = data["commit"].get("rkey", "unknown")
                            logger.info(f"BLOCK DELETED: {did} removed block {rkey} at {timestamp}")
                            block_events["blocks_deleted"].append({
                                "blocker_did": did,
                                "block_rkey": rkey,
                                "timestamp": timestamp
                            })
                            
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse message: {message[:100]}...")
                    continue
                
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed. Attempting to reconnect...")
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                continue
                
        return block_events

async def check_account_blocks_from_db():
    """Check blocks for all accounts from the database"""
    logger.info("Checking blocks from database...")
    
    # Initialize database
    db = Database()
    logger.info(f"Testing database connection: {db.test_connection()}")
    
    # Get primary account
    primary_account = db.get_primary_account()
    
    # Get secondary accounts
    secondary_accounts = db.get_secondary_accounts()
    
    accounts = []
    if primary_account:
        accounts.append(primary_account)
    if secondary_accounts:
        accounts.extend(secondary_accounts)
    
    if not accounts:
        logger.error("No accounts found in database")
        return
        
    logger.info(f"Found {len(accounts)} accounts in database")
    
    # Get all blocks from database
    all_blocks = db.get_all_blocked_accounts()
    logger.info(f"Found {len(all_blocks)} block records in database")
    
    # Organize blocks by account
    blocks_by_account = {}
    for account in accounts:
        handle = account.get('handle', 'unknown')
        account_id = account.get('id')
        did = account.get('did', 'unknown')
        
        blocks_by_account[handle] = {
            "did": did,
            "blocking": [],  # DIDs this account is blocking
            "blocked_by": []  # DIDs blocking this account
        }
    
    # Process each block
    for block in all_blocks:
        source_account_id = block.get('source_account_id')
        block_type = block.get('block_type')
        blocked_did = block.get('did')
        blocked_handle = block.get('handle')
        
        # Find which account this block belongs to
        for account in accounts:
            if account.get('id') == source_account_id:
                handle = account.get('handle', 'unknown')
                
                if block_type == 'blocking':
                    blocks_by_account[handle]["blocking"].append({
                        "did": blocked_did,
                        "handle": blocked_handle
                    })
                elif block_type == 'blocked_by':
                    blocks_by_account[handle]["blocked_by"].append({
                        "did": blocked_did,
                        "handle": blocked_handle
                    })
                break
    
    return blocks_by_account

async def main():
    # Check for blocks in the database
    logger.info("Retrieving current block information from database...")
    blocks_from_db = await check_account_blocks_from_db()
    
    if blocks_from_db:
        logger.info("\n=== BLOCKS FROM DATABASE ===")
        for handle, block_data in blocks_from_db.items():
            logger.info(f"\nAccount: {handle} (DID: {block_data['did']})")
            logger.info(f"  Blocking {len(block_data['blocking'])} accounts:")
            for block in block_data['blocking'][:10]:  # Show first 10
                logger.info(f"    - {block.get('handle', 'unknown')} ({block.get('did', 'unknown')})")
            if len(block_data['blocking']) > 10:
                logger.info(f"    ... and {len(block_data['blocking']) - 10} more")
                
            logger.info(f"  Blocked by {len(block_data['blocked_by'])} accounts:")
            for block in block_data['blocked_by'][:10]:  # Show first 10
                logger.info(f"    - {block.get('handle', 'unknown')} ({block.get('did', 'unknown')})")
            if len(block_data['blocked_by']) > 10:
                logger.info(f"    ... and {len(block_data['blocked_by']) - 10} more")
    
    # Monitor jetstream for new block events
    logger.info("\n=== CONNECTING TO JETSTREAM FOR LIVE BLOCK MONITORING ===")
    logger.info("Press Ctrl+C to stop monitoring")
    
    try:
        # Connect to jetstream and monitor for block events
        block_events = await connect_to_jetstream(JETSTREAM_SERVER)
        
        # Display summary of block events
        logger.info("\n=== JETSTREAM BLOCK EVENTS SUMMARY ===")
        logger.info(f"Blocks created: {len(block_events['blocks_created'])}")
        logger.info(f"Blocks deleted: {len(block_events['blocks_deleted'])}")
        
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    except Exception as e:
        logger.error(f"Error during jetstream monitoring: {e}", exc_info=True)
    
    logger.info("Test completed.")

if __name__ == "__main__":
    asyncio.run(main()) 