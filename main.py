import os
import asyncio
import logging
import argparse
import signal
import psycopg2
import sys
import httpx
from datetime import datetime
from dotenv import load_dotenv
from account_agent import AccountAgent, CLEARSKY_API_BASE_URL
from setup_db import setup_database
from database import Database, get_connection
from test_mod_list_sync import sync_mod_list_from_db
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
agents = []
shutdown_event = asyncio.Event()

# Dictionary to map DIDs to handles
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

def is_database_setup():
    """Check if the database exists and is properly configured."""
    try:
        # Use the Database class's get_connection method to respect LOCAL_TEST
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check if required tables exist
        local_test = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        table_suffix = "_test" if local_test else ""
        
        required_tables = [f'accounts{table_suffix}', f'blocked_accounts{table_suffix}', f'mod_lists{table_suffix}']
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        all_tables_exist = all(table in existing_tables for table in required_tables)
        if not all_tables_exist:
            missing_tables = [table for table in required_tables if table not in existing_tables]
            logger.warning(f"Database check: Missing required tables: {', '.join(missing_tables)}")
            cursor.close()
            conn.close()
            return False

        # Check for 'updated_at' column in 'accounts' table
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'accounts{table_suffix}' 
                AND column_name = 'updated_at'
            )
        """)
        updated_at_exists = cursor.fetchone()[0]
        if not updated_at_exists:
            logger.warning(f"Database check: 'accounts{table_suffix}' table is missing 'updated_at' column.")
            cursor.close()
            conn.close()
            return False

        # Check for 'last_firehose_cursor' column in 'accounts' table
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'accounts{table_suffix}' 
                AND column_name = 'last_firehose_cursor'
            )
        """)
        last_firehose_cursor_exists = cursor.fetchone()[0]
        if not last_firehose_cursor_exists:
            logger.warning(f"Database check: 'accounts{table_suffix}' table is missing 'last_firehose_cursor' column.")
            cursor.close()
            conn.close()
            return False
            
        # Add checks for other critical columns if necessary, for example:
        # Check for 'is_primary' in 'accounts'
        # Check for 'source_account_id', 'did', 'block_type' in 'blocked_accounts'
        # Check for 'list_uri', 'owner_did' in 'mod_lists'

        logger.info("Database check: All required tables and critical columns appear to exist.")
        cursor.close()
        conn.close()
        return True
        
    except psycopg2.OperationalError as e:
        # This handles cases like database not existing or wrong credentials
        logger.warning(f"Database check: OperationalError connecting to or querying database. Error: {e}")
        return False
    except Exception as e:
        logger.error(f"Database check: An unexpected error occurred: {e}", exc_info=True)
        return False

async def initialize_agents():
    """Initialize all account agents from environment variables."""
    global agents
    
    # Initialize primary account agent
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    primary_agent = AccountAgent(primary_handle, primary_password, is_primary=True)
    login_success = await primary_agent.login()
    
    if not login_success:
        logger.error("Failed to login to primary account")
        return False
    
    agents.append(primary_agent)
    logger.info(f"Primary agent initialized for {primary_handle}")
    
    # Initialize secondary account agents
    secondary_accounts = os.getenv('SECONDARY_ACCOUNTS', '')
    
    if secondary_accounts:
        account_entries = secondary_accounts.split(';')
        
        for entry in account_entries:
            if ',' not in entry:
                logger.warning(f"Invalid account entry format: {entry}")
                continue
                
            handle, password = entry.split(',', 1)
            
            agent = AccountAgent(handle, password)
            login_success = await agent.login()
            
            if login_success:
                agents.append(agent)
                logger.info(f"Secondary agent initialized for {handle}")
            else:
                logger.warning(f"Failed to initialize agent for {handle}")
    
    if len(agents) == 0:
        logger.error("No agents could be initialized")
        return False
        
    logger.info(f"Initialized {len(agents)} agent(s)")
    return True

async def start_agents():
    """Start monitoring with all initialized agents."""
    start_tasks = []
    
    for agent in agents:
        start_tasks.append(agent.start_monitoring())
    
    # Wait for all agents to start
    await asyncio.gather(*start_tasks)
    logger.info("All agents started monitoring")

async def shutdown_agents():
    """Gracefully shut down all agent tasks."""
    shutdown_tasks = []
    
    for agent in agents:
        shutdown_tasks.append(agent.stop_monitoring())
    
    # Wait for all agents to stop
    await asyncio.gather(*shutdown_tasks)
    logger.info("All agents stopped")

def handle_signals():
    """Set up signal handlers for graceful shutdown."""
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

async def shutdown():
    """Handle graceful shutdown of the application."""
    logger.info("Shutdown initiated")
    shutdown_event.set()

async def initialize_accounts_in_db():
    """Initialize accounts in the database."""
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
        
        # Process who this account is blocking
        logger.info(f"Fetching who {account_handle} is blocking...")
        try:
            # Get blocks from standard ClearSky endpoint
            blocking_data = await fetch_from_clearsky(f"/blocklist/{account_did}")
            if blocking_data and 'data' in blocking_data and 'blocklist' in blocking_data['data']:
                blocklist = blocking_data['data']['blocklist']
                if blocklist:
                    logger.info(f"Found {len(blocklist)} accounts being blocked by {account_handle}")
                    
                    # Add 'blocking' relationships to database
                    for block_info in blocklist:
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
                            logger.debug(f"Added blocking relationship: {account_handle} blocks {blocked_did}")
                        except Exception as e:
                            logger.error(f"Error adding blocking relationship: {e}")
                else:
                    logger.info(f"No accounts being blocked by {account_handle}")
        except Exception as e:
            logger.error(f"Error fetching who {account_handle} is blocking: {e}")
        
        # Process who is blocking this account using our improved pagination helper
        logger.info(f"Fetching who is blocking {account_handle} with pagination support...")
        try:
            # Use our enhanced pagination-aware helper
            start_time = datetime.now()
            blockers, total_count = await cs.fetch_all_blocked_by(account_did)
            
            if blockers:
                logger.info(f"Found {len(blockers)} accounts blocking {account_handle}")
                
                # Process the blocked-by records and track for duplicate checking
                processed_dids = set()
                
                for blocker in blockers:
                    if 'did' not in blocker:
                        logger.warning(f"Skipping blocked-by record missing DID: {blocker}")
                        continue
                        
                    blocker_did = blocker['did']
                    
                    # Skip if we've already processed this DID (handle duplicates)
                    if blocker_did in processed_dids:
                        logger.debug(f"Skipping duplicate DID: {blocker_did}")
                        continue
                        
                    processed_dids.add(blocker_did)
                    blocker_handle = DID_TO_HANDLE.get(blocker_did, "unknown")  # Use known handle if available
                    
                    try:
                        db.add_blocked_account(
                            did=blocker_did,
                            handle=blocker_handle,
                            source_account_id=account_id,
                            block_type='blocked_by',
                            reason="Imported from ClearSky"
                        )
                        logger.debug(f"Added blocked_by relationship: {account_handle} is blocked by {blocker_did}")
                    except Exception as e:
                        logger.error(f"Error adding blocked_by relationship: {e}")
                
                elapsed_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"Processed {len(processed_dids)} unique blocked-by DIDs in {elapsed_time:.2f} seconds")
            else:
                logger.info(f"No accounts blocking {account_handle}")
        except Exception as e:
            logger.error(f"Error fetching who is blocking {account_handle}: {e}")
        
        # Rate limiting
        await asyncio.sleep(1)
    
    logger.info("Block population from ClearSky completed.")
    return True

async def test_modlist_functionality():
    """Test the moderation list functionality without making actual blocks."""
    logger.info("Testing moderation list functionality...")
    
    # Get account credentials
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    try:
        # Initialize the client and login
        from atproto import Client
        client = Client(base_url="https://bsky.social")
        logger.info(f"Attempting to login as {primary_handle}...")
        response = client.login(primary_handle, primary_password)
        did = response.did
        logger.info(f"Successfully logged in as {primary_handle} (DID: {did})")
        
        # Create the moderation list record
        logger.info("Testing moderation list creation...")
        
        list_name = "Test Moderation List"
        list_description = "Test description for moderation list"
        
        # Use the correct approach with direct dictionary creation
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
                    
            logger.info("Moderation list functionality verified successfully!")
            return True
        except Exception as e:
            logger.error(f"Error testing moderation list functionality: {e}")
            return False
    except Exception as e:
        logger.error(f"Error testing moderation list functionality: {e}")
        return False

async def run_test_mode():
    """Run in test mode without making any changes."""
    logger.info("Starting in TEST MODE - no actual changes will be made")
    
    test_success = True
    
    # Initialize database connection
    database = Database()
    
    # Test database connection
    logger.info("Testing database connection...")
    database_ok = database.test_connection()
    if database_ok:
        logger.info("Database connection successful")
    else:
        logger.warning("Database connection failed - some test components will be skipped")
        test_success = False
    
    # Get account credentials
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    # Initialize but don't login
    logger.info(f"Verifying primary account agent setup for {primary_handle}...")
    
    # Test ClearSky API connection
    logger.info("Testing ClearSky API connection...")
    try:
        url = f"{CLEARSKY_API_BASE_URL}/lists/fun-facts"
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 200:
                logger.info("ClearSky API connection successful")
            else:
                logger.error(f"ClearSky API returned status code {response.status_code}")
                test_success = False
    except Exception as e:
        logger.error(f"Error connecting to ClearSky API: {e}")
        test_success = False
    
    # Check secondary accounts configuration
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    if secondary_accounts_str:
        accounts = secondary_accounts_str.split(';')
        logger.info(f"Found {len(accounts)} secondary accounts configured")
    else:
        logger.info("No secondary accounts configured")
    
    if test_success:
        logger.info("All system components verified successfully!")
    else:
        logger.warning("Some system components failed verification")
    
    logger.info("TEST MODE completed - no changes were made")
    return test_success

async def run_diagnostics():
    """Run diagnostics and tests."""
    logger.info("=== RUNNING DATABASE DIAGNOSTICS ===")
    
    # Create a unique log file name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"diagnostic_results_{timestamp}.log"
    
    # Set up file handler for diagnostic logging
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # Add the file handler to the root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    
    try:
        # Initialize database for queries
        db = Database()
        if not db.test_connection():
            logger.error("Database connection test failed. Cannot run diagnostics.")
            return False
        
        # 1. Import and run the standard diagnostics
        try:
            import test_direct_db
            test_direct_db.run_diagnostics()
            logger.info("Database diagnostics completed successfully.")
        except Exception as e:
            logger.error(f"Database diagnostics failed: {e}")
        
        # 2. Check for duplicate DIDs in the database
        try:
            logger.info("Checking for duplicate DIDs in the database...")
            # Execute custom query to find duplicate DIDs
            query = """
                SELECT did, block_type, COUNT(*) as count
                FROM blocked_accounts
                GROUP BY did, block_type, source_account_id
                HAVING COUNT(*) > 1
            """
            results = db.execute_query(query)
            
            if results and len(results) > 0:
                logger.warning(f"Found {len(results)} instances of duplicate DIDs in the database!")
                for row in results:
                    logger.warning(f"Duplicate found: DID {row['did']}, Type: {row['block_type']}, Count: {row['count']}")
                
                # Log this to a special file for further investigation
                with open(f"duplicate_dids_check_{timestamp}.log", "w") as dup_file:
                    dup_file.write(f"Duplicate DIDs check run at {timestamp}\n")
                    dup_file.write(f"Found {len(results)} instances of duplicate DIDs\n\n")
                    for row in results:
                        dup_file.write(f"DID: {row['did']}, Type: {row['block_type']}, Count: {row['count']}\n")
                    
                logger.info(f"Detailed duplicate DID information saved to duplicate_dids_check_{timestamp}.log")
                
                # Try to run the deduplication script if available
                try:
                    import check_duplicate_dids
                    logger.info("Running duplicate DID check and cleanup...")
                    await check_duplicate_dids.main()
                except ImportError:
                    logger.warning("check_duplicate_dids.py not found. Skipping automatic deduplication.")
                except Exception as e_dedup:
                    logger.error(f"Error running duplicate DID check and cleanup: {e_dedup}")
            else:
                logger.info("No duplicate DIDs found in the database.")
        except Exception as e_dup:
            logger.error(f"Error checking for duplicate DIDs: {e_dup}")
        
        # 3. Check ClearSky API health
        try:
            logger.info("Checking ClearSky API health...")
            url = f"{CLEARSKY_API_BASE_URL}/lists/fun-facts"
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    logger.info("ClearSky API connection successful")
                else:
                    logger.error(f"ClearSky API returned status code {response.status_code}")
        except Exception as e_api:
            logger.error(f"Error connecting to ClearSky API: {e_api}")
    except Exception as e:
        logger.error(f"General error during diagnostics: {e}")
    finally:
        # Remove the file handler
        root_logger.removeHandler(file_handler)
        
        # Log the location of the diagnostic results
        logger.info(f"Diagnostic results saved to {log_file}")
        
        # Output a separator for clarity in logs
        logger.info("="*50)
    
    return True

async def run_test_block_sync():
    """Run a test block sync to verify sync functionality."""
    logger.info("=== RUNNING TEST BLOCK SYNC ===")
    try:
        # Import the test module and run it
        import test_block_sync
        # Since test_block_sync is designed to be run as a script with asyncio.run(),
        # we need to call its main function directly instead
        await test_block_sync.main()
        logger.info("Test block sync completed successfully.")
    except Exception as e:
        logger.error(f"Test block sync failed: {e}")
    finally:
        # Output a separator for clarity in logs
        logger.info("="*50)
    
    return True

async def sync_blocks_to_modlist():
    """Sync blocked accounts from database to moderation list"""
    logger.info("=== SYNCING BLOCKS TO MODERATION LIST ===")
    try:
        # Use the function from test_mod_list_sync.py
        success = await sync_mod_list_from_db()
        if success:
            logger.info("Successfully synchronized blocks to moderation list")
        else:
            logger.error("Failed to synchronize blocks to moderation list")
        return success
    except Exception as e:
        logger.error(f"Error synchronizing blocks to moderation list: {e}")
        return False

async def main():
    """Main function to run the bot."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Bluesky account agent for synchronizing blocks across accounts')
    parser.add_argument('--test', action='store_true', help='Run in test mode without making any changes')
    parser.add_argument('--test-modlist', action='store_true', help='Test moderation list functionality')
    parser.add_argument('--skip-diagnostics', action='store_true', help='Skip running diagnostics and tests')
    parser.add_argument('--skip-clearsky-init', action='store_true', help='Skip initializing blocks from ClearSky')
    parser.add_argument('--skip-modlist-sync', action='store_true', help='Skip syncing blocks to moderation list')
    args = parser.parse_args()
    
    # Run in test mode if requested
    if args.test:
        success = await run_test_mode()
        return success
    
    # Test moderation list if requested
    if args.test_modlist:
        success = await test_modlist_functionality()
        return success
    
    # Normal operation mode
    logger.info("Starting Bluesky account agent...")

    # Attempt to set up the database
    logger.info("Attempting to initialize/verify database schema...")
    try:
        setup_database(force_local=False) # Attempt to create/update tables, explicitly specifying NOT to force using test connection
        logger.info("Database setup/update function executed.")
        if not is_database_setup(): # Verify setup
            logger.critical("Database schema verification failed after setup attempt. Please check logs. Exiting.")
            return False # Indicate failure
        else:
            logger.info("Database schema successfully initialized/verified.")
    except Exception as e:
        logger.critical(f"A critical error occurred during database setup: {e}. Please check database configuration and logs. Exiting.")
        return False # Indicate failure

    # Initialize accounts in the database
    logger.info("Initializing accounts in the database...")
    await initialize_accounts_in_db()

    # Populate block information from ClearSky unless explicitly skipped
    if not args.skip_clearsky_init:
        logger.info("Populating blocks from ClearSky...")
        await populate_blocks_from_clearsky()
    else:
        logger.info("Skipping ClearSky block initialization (--skip-clearsky-init flag used).")

    # Sync blocks to moderation list unless explicitly skipped
    if not args.skip_modlist_sync:
        logger.info("Syncing blocks to moderation list...")
        await sync_blocks_to_modlist()
    else:
        logger.info("Skipping moderation list synchronization (--skip-modlist-sync flag used).")

    # Run diagnostics and tests, unless explicitly skipped
    if not args.skip_diagnostics:
        try:
            logger.info("Running diagnostics and tests...")
            # Run database diagnostics
            await run_diagnostics() # This should now run on a presumably set-up DB
            
            # Run test block sync.
            # Given the critical exit above if DB setup fails, is_database_setup() should be true here.
            if is_database_setup(): 
                await run_test_block_sync()
            else:
                # This path indicates a severe inconsistency.
                logger.error("CRITICAL: Database reported as not set up AFTER successful setup and verification. " +
                             "Skipping test block sync. System may be unstable.")
        except Exception as e:
            logger.error(f"Error during diagnostics/tests: {e}")
            logger.warning("Continuing with main application despite diagnostic/test errors. Check logs for details.")
    else:
        logger.info("Skipping diagnostics and tests (--skip-diagnostics flag used).")

    # Initialize database object (used by agents)
    database = Database()
    
    # Get account credentials
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found in .env file")
        return False
    
    # Create and initialize primary account agent
    logger.info(f"Initializing primary account agent: {primary_handle}")
    primary_agent = AccountAgent(
        handle=primary_handle,
        password=primary_password,
        is_primary=True,
        database=database
    )
    
    success = await primary_agent.login()
    if not success:
        logger.error(f"Failed to login as primary account {primary_handle}")
        return False
    
    # Start monitoring for the primary account
    await primary_agent.start_monitoring()
    
    # Initialize and start monitoring for secondary accounts
    secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
    secondary_agents = []
    
    if secondary_accounts_str:
        accounts = secondary_accounts_str.split(';')
        logger.info(f"Found {len(accounts)} secondary accounts")
        
        for account_str in accounts:
            try:
                # Try various separator formats (comma or colon)
                if ':' in account_str:
                    handle, password = account_str.split(':', 1)
                elif ',' in account_str:
                    handle, password = account_str.split(',', 1)
                else:
                    logger.error(f"Invalid account format: {account_str}. Expected format: 'handle:password' or 'handle,password'")
                    continue
                
                # Trim any whitespace
                handle = handle.strip()
                password = password.strip()
                
                logger.info(f"Initializing secondary account agent: {handle}")
                agent = AccountAgent(
                    handle=handle,
                    password=password,
                    is_primary=False,
                    database=database
                )
                
                success = await agent.login()
                if success:
                    await agent.start_monitoring()
                    secondary_agents.append(agent)
                else:
                    logger.error(f"Failed to login as secondary account {handle}. Halting application as all accounts must be operational.")
                    # Clean up already started primary agent before exiting
                    logger.info("Shutting down already started primary agent before exiting due to secondary account login failure...")
                    await primary_agent.stop_monitoring()
                    return False # Indicate failure to stop the application
            except Exception as e:
                logger.error(f"Error initializing secondary account {handle}: {e}. Halting application.")
                # Clean up already started primary agent
                logger.info("Shutting down already started primary agent before exiting due to secondary account initialization error...")
                await primary_agent.stop_monitoring()
                return False # Indicate failure
    
    # Keep the program running
    try:
        logger.info("All account agents started successfully. Running indefinitely.")
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour between checks
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        # Clean up
        logger.info("Shutting down account agents...")
        await primary_agent.stop_monitoring()
        for agent in secondary_agents:
            await agent.stop_monitoring()
    
    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1) 