import os
import asyncio
import logging
import argparse
import signal
import psycopg2
from dotenv import load_dotenv
from account_agent import AccountAgent, CLEARSKY_API_BASE_URL
from setup_db import setup_database
from database import Database
import httpx

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

def is_database_setup():
    """Check if the database exists and is properly configured."""
    try:
        # Check for Railway-style DATABASE_URL
        database_url = os.getenv('DATABASE_URL')
        
        if database_url:
            # Connect using the DATABASE_URL
            conn = psycopg2.connect(database_url)
        else:
            # Use individual connection parameters
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            # Try to connect to the application database
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname=DB_NAME
            )
            
        cursor = conn.cursor()
        
        # Check if required tables exist
        required_tables = ['accounts', 'blocked_accounts', 'mod_lists']
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        # If accounts table exists, check for updated_at column
        if 'accounts' in existing_tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = 'accounts' 
                    AND column_name = 'updated_at'
                )
            """)
            updated_at_exists = cursor.fetchone()[0]
            if not updated_at_exists:
                logger.info("accounts table exists but is missing updated_at column")
                cursor.close()
                conn.close()
                return False
        
        cursor.close()
        conn.close()
        
        # Check if all required tables exist
        all_tables_exist = all(table in existing_tables for table in required_tables)
        if not all_tables_exist:
            missing_tables = [table for table in required_tables if table not in existing_tables]
            logger.info(f"Missing required tables: {', '.join(missing_tables)}")
        return all_tables_exist
        
    except Exception as e:
        logger.info(f"Database check failed: {e}")
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
    """Run in test mode to verify components without making changes."""
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

async def main():
    """Main function to run the bot."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Bluesky account agent for synchronizing blocks across accounts')
    parser.add_argument('--test', action='store_true', help='Run in test mode without making any changes')
    parser.add_argument('--test-modlist', action='store_true', help='Test moderation list functionality')
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

    # Check and set up database
    logger.info("Checking database setup...")
    if not is_database_setup():
        logger.warning("Database is not set up correctly. Attempting to run setup...")
        try:
            setup_database()  # Call the imported setup function
            logger.info("Database setup function executed.")
            # Re-check database setup
            if not is_database_setup():
                logger.critical("Database setup failed after attempt. Please check database configuration and logs. Exiting.")
                return False # Indicate failure
            else:
                logger.info("Database is now correctly set up.")
        except Exception as e:
            logger.critical(f"An error occurred during database setup: {e}. Please check database configuration and logs. Exiting.")
            return False # Indicate failure
    else:
        logger.info("Database is correctly set up.")
    
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
                    logger.error(f"Failed to login as secondary account {handle}")
            except Exception as e:
                logger.error(f"Error initializing secondary account: {e}")
    
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