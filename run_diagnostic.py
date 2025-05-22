import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database
import debug_database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_diagnostics():
    logger.info("=== RUNNING BLOCK SYNCHRONIZATION DIAGNOSTICS ===")
    
    # Debug database setup
    logger.info("Checking database setup...")
    debug_database.debug_database()
    
    # Initialize accounts in the database using the ProductionOrchestrator
    logger.info("\n=== INITIALIZING ACCOUNTS ===")
    try:
        from main import ProductionOrchestrator
        orchestrator = ProductionOrchestrator()
        
        # Setup database first
        await orchestrator._setup_database()
        
        # Initialize accounts
        await orchestrator._initialize_accounts()
        logger.info("✅ Account initialization completed")
    except Exception as e:
        logger.error(f"❌ Account initialization failed: {e}")
    
    # Debug database again to see accounts
    logger.info("\n=== CHECKING ACCOUNTS AFTER INITIALIZATION ===")
    debug_database.debug_database()
    
    # Populate block information from ClearSky
    logger.info("\n=== POPULATING BLOCKS FROM CLEARSKY ===")
    try:
        await orchestrator._populate_clearsky_data()
        logger.info("✅ ClearSky population completed")
    except Exception as e:
        logger.error(f"❌ ClearSky population failed: {e}")
    
    # Debug database again to see blocks
    logger.info("\n=== CHECKING BLOCKS AFTER POPULATION ===")
    debug_database.debug_database()
    
    logger.info("\n=== DIAGNOSTIC RUN COMPLETED ===")

if __name__ == "__main__":
    asyncio.run(run_diagnostics()) 