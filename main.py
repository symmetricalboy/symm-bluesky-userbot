import os
import asyncio
import logging
import signal
import psycopg2
from dotenv import load_dotenv
from account_agent import AccountAgent
from setup_db import setup_database

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
        
        cursor.close()
        conn.close()
        
        # Check if all required tables exist
        all_tables_exist = all(table in existing_tables for table in required_tables)
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

async def main():
    """Main function to run the bot system."""
    try:
        # Check and set up the database if needed
        if not is_database_setup():
            logger.info("Database not set up properly. Running setup...")
            setup_database()
            logger.info("Database setup completed")
        else:
            logger.info("Database already configured properly")
            
        # Set up signal handlers
        handle_signals()
        
        # Initialize agents
        init_success = await initialize_agents()
        if not init_success:
            logger.error("Failed to initialize agents, exiting")
            return 1
        
        try:
            # Start monitoring
            await start_agents()
            
            # Run until shutdown signal
            logger.info("Bot system is running. Press CTRL+C to exit.")
            await shutdown_event.wait()
        except Exception as monitor_error:
            logger.error(f"Error during monitoring: {monitor_error}")
            # If there's an error during monitoring, we still want to try to shut down gracefully
        
        # Shutdown
        try:
            await shutdown_agents()
            logger.info("Bot system shutdown complete")
        except Exception as shutdown_error:
            logger.error(f"Error during shutdown: {shutdown_error}")
        
        return 0
    except Exception as e:
        logger.error(f"Unhandled error in main: {e}")
        # Print full traceback for easier debugging
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code) 