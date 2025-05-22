import os
import logging
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def debug_database():
    """Debug database connection and query tables"""
    logger.info("Starting database debugging...")
    
    # Initialize database
    db = Database()
    connection_status = db.test_connection()
    logger.info(f"Database connection test: {connection_status}")
    
    # Get connection string (without password)
    conn_str = os.getenv('DATABASE_URL', 'Not found')
    if conn_str and '@' in conn_str:
        # Hide password
        parts = conn_str.split('@')
        prefix_parts = parts[0].split(':')
        sanitized_conn_str = f"{prefix_parts[0]}:***@{parts[1]}"
        logger.info(f"Using connection string: {sanitized_conn_str}")
    
    # Debug primary account retrieval
    try:
        primary = db.get_primary_account()
        if primary:
            logger.info(f"Primary account found: {primary.get('handle')} (DID: {primary.get('did')})")
        else:
            logger.warning("No primary account found in database")
    except Exception as e:
        logger.error(f"Error retrieving primary account: {e}")
    
    # Debug secondary accounts retrieval
    try:
        secondaries = db.get_secondary_accounts()
        if secondaries:
            logger.info(f"Found {len(secondaries)} secondary accounts:")
            for account in secondaries:
                logger.info(f"  - {account.get('handle')} (DID: {account.get('did')})")
        else:
            logger.warning("No secondary accounts found in database")
    except Exception as e:
        logger.error(f"Error retrieving secondary accounts: {e}")
    
    # Direct SQL queries to debug tables
    logger.info("\nDirect SQL queries for debugging:")
    
    # Check accounts table
    try:
        with db.conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM accounts")
            count = cursor.fetchone()[0]
            logger.info(f"accounts table has {count} rows")
            
            if count > 0:
                cursor.execute("SELECT id, did, handle FROM accounts")
                accounts = cursor.fetchall()
                logger.info("Sample accounts data:")
                for account in accounts[:5]:  # Show first 5
                    logger.info(f"  - ID: {account[0]}, Handle: {account[2]}, DID: {account[1]}")
    except Exception as e:
        logger.error(f"Error querying accounts table: {e}")
    
    # Check blocked_accounts table
    try:
        with db.conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM blocked_accounts")
            count = cursor.fetchone()[0]
            logger.info(f"blocked_accounts table has {count} rows")
            
            if count > 0:
                cursor.execute("""
                    SELECT ba.id, ba.source_account_id, a.handle, ba.did, ba.handle, ba.block_type 
                    FROM blocked_accounts ba
                    LEFT JOIN accounts a ON ba.source_account_id = a.id
                    LIMIT 5
                """)
                blocks = cursor.fetchall()
                logger.info("Sample blocked_accounts data:")
                for block in blocks:
                    logger.info(f"  - ID: {block[0]}, Source: {block[1]} ({block[2]}), Blocked: {block[4]} ({block[3]}), Type: {block[5]}")
    except Exception as e:
        logger.error(f"Error querying blocked_accounts table: {e}")
    
    # Check mod_lists table
    try:
        with db.conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM mod_lists")
            count = cursor.fetchone()[0]
            logger.info(f"mod_lists table has {count} rows")
    except Exception as e:
        logger.error(f"Error querying mod_lists table: {e}")
    
    logger.info("Database debugging completed")

if __name__ == "__main__":
    debug_database() 