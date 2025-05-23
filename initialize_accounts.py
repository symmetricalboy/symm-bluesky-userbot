import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

async def initialize_accounts():
    """Initialize the accounts in the database"""
    logger.info("Initializing accounts in the database...")
    
    db = Database()
    try:
        await db.test_connection()
        logger.info("Database connection test passed.")
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
    
    for did, handle in DID_TO_HANDLE.items():
        is_primary = IS_PRIMARY.get(did, False)
        try:
            account_id = await db.register_account(handle, did, is_primary)
            logger.info(f"Registered account {handle} (DID: {did}) as {'PRIMARY' if is_primary else 'secondary'} with ID: {account_id}")
        except Exception as e:
            logger.error(f"Failed to register account {handle} (DID: {did}): {e}")
    
    logger.info("Account initialization completed.")
    return True

if __name__ == "__main__":
    asyncio.run(initialize_accounts()) 