import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_connection():
    """Get a connection to the database, supporting both individual params and DATABASE_URL."""
    try:
        # First check for Railway-style DATABASE_URL
        database_url = os.getenv('DATABASE_URL')
        
        if database_url:
            logger.info(f"Connecting using DATABASE_URL: {database_url}")
            return psycopg2.connect(database_url)
        else:
            # Fall back to individual connection parameters
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            connection_string = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
            logger.info(f"Connecting using individual parameters: host={DB_HOST}, port={DB_PORT}, dbname={DB_NAME}, user={DB_USER}")
            return psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname=DB_NAME
            )
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def check_tables():
    """Check what tables exist in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        logger.info(f"Found {len(tables)} tables in the database:")
        for table in tables:
            logger.info(f"  - {table[0]}")
        return tables
    except Exception as e:
        logger.error(f"Error checking tables: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def check_columns(table_name):
    """Check what columns exist in a specific table."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = '{table_name}'
            ORDER BY ordinal_position;
        """)
        columns = cursor.fetchall()
        logger.info(f"Table '{table_name}' has {len(columns)} columns:")
        for col in columns:
            logger.info(f"  - {col[0]} ({col[1]})")
        return columns
    except Exception as e:
        logger.error(f"Error checking columns for table {table_name}: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def check_accounts():
    """Check accounts in the database."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM accounts ORDER BY id")
        accounts = cursor.fetchall()
        logger.info(f"Found {len(accounts)} accounts in the database:")
        for account in accounts:
            logger.info(f"  - ID: {account['id']}, Handle: {account['handle']}, DID: {account['did']}, Is Primary: {account['is_primary']}, Last Firehose Cursor: {account.get('last_firehose_cursor', 'N/A')}")
        return accounts
    except Exception as e:
        logger.error(f"Error checking accounts: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def check_mod_lists():
    """Check moderation lists in the database."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM mod_lists ORDER BY id")
        mod_lists = cursor.fetchall()
        logger.info(f"Found {len(mod_lists)} moderation lists in the database:")
        for mod_list in mod_lists:
            logger.info(f"  - ID: {mod_list['id']}, URI: {mod_list['list_uri']}, Owner DID: {mod_list['owner_did']}, Name: {mod_list['name']}")
        return mod_lists
    except Exception as e:
        logger.error(f"Error checking moderation lists: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def check_blocked_accounts():
    """Check blocked accounts in the database."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # First, count total blocks
        cursor.execute("SELECT COUNT(*) as count FROM blocked_accounts WHERE block_type = 'blocking'")
        count = cursor.fetchone()['count']
        logger.info(f"Found {count} 'blocking' entries in the database")
        
        # Count how many are from primary account
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM blocked_accounts ba
            JOIN accounts a ON ba.source_account_id = a.id
            WHERE a.is_primary = TRUE AND ba.block_type = 'blocking'
        """)
        primary_count = cursor.fetchone()['count']
        logger.info(f"  - {primary_count} blocks are from the primary account")
        
        # Count how many are from secondary accounts
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM blocked_accounts ba
            JOIN accounts a ON ba.source_account_id = a.id
            WHERE a.is_primary = FALSE AND ba.block_type = 'blocking'
        """)
        secondary_count = cursor.fetchone()['count']
        logger.info(f"  - {secondary_count} blocks are from secondary accounts")
        
        # Count how many secondary account blocks are unsynced
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM blocked_accounts ba
            JOIN accounts a ON ba.source_account_id = a.id
            WHERE a.is_primary = FALSE AND ba.block_type = 'blocking' AND ba.is_synced = FALSE
        """)
        unsynced_count = cursor.fetchone()['count']
        logger.info(f"  - {unsynced_count} blocks from secondary accounts are NOT synced to primary")
        
        # Get a sample of blocked accounts
        cursor.execute("""
            SELECT ba.id, ba.did, ba.handle, ba.block_type, ba.is_synced, 
                   ba.source_account_id, a.handle as source_account_handle,
                   ba.first_seen, ba.last_seen, ba.reason
            FROM blocked_accounts ba
            JOIN accounts a ON ba.source_account_id = a.id
            ORDER BY ba.first_seen DESC
            LIMIT 10
        """)
        recent_blocks = cursor.fetchall()
        logger.info(f"Sample of recent blocks (up to 10):")
        for block in recent_blocks:
            logger.info(f"  - ID: {block['id']}, DID: {block['did']}, Type: {block['block_type']}, Synced: {block['is_synced']}, Source: {block['source_account_handle']}")
        
        return {
            'total_count': count,
            'primary_count': primary_count,
            'secondary_count': secondary_count,
            'unsynced_count': unsynced_count,
            'recent_blocks': recent_blocks
        }
    except Exception as e:
        logger.error(f"Error checking blocked accounts: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def add_test_block():
    """Add a test block to the database for a secondary account."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Get a secondary account ID
        cursor.execute("SELECT id FROM accounts WHERE is_primary = FALSE LIMIT 1")
        result = cursor.fetchone()
        if not result:
            logger.error("No secondary account found")
            return False
        
        secondary_account_id = result[0]
        
        # Create a test DID
        import random
        test_did = f"did:plc:test{random.randint(10000, 99999)}"
        
        # Add block record
        cursor.execute(
            """INSERT INTO blocked_accounts 
            (did, handle, reason, source_account_id, block_type, is_synced)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (test_did, "test_handle", "Test block for diagnostics", secondary_account_id, 'blocking', False)
        )
        conn.commit()
        logger.info(f"Added test block for DID {test_did} to the database for secondary account ID {secondary_account_id}")
        return test_did
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding test block: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def run_diagnostics():
    """Run all diagnostics."""
    logger.info("Starting database diagnostics...")
    
    logger.info("\n=== CHECKING DATABASE TABLES ===")
    tables = check_tables()
    
    # If there are no tables, try to initialize the database
    if not tables:
        logger.warning("No tables found in the database. Attempting to initialize tables...")
        try:
            import setup_db
            setup_db.setup_database()
            logger.info("Database initialization completed. Checking tables again...")
            tables = check_tables()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
    
    if not tables:
        logger.error("Still no tables found after initialization attempt. Exiting.")
        return
    
    logger.info("\n=== CHECKING ACCOUNTS TABLE STRUCTURE ===")
    check_columns('accounts')
    
    logger.info("\n=== CHECKING BLOCKED_ACCOUNTS TABLE STRUCTURE ===")
    check_columns('blocked_accounts')
    
    logger.info("\n=== CHECKING MOD_LISTS TABLE STRUCTURE ===")
    check_columns('mod_lists')
    
    logger.info("\n=== CHECKING ACCOUNTS DATA ===")
    check_accounts()
    
    logger.info("\n=== CHECKING MODERATION LISTS DATA ===")
    check_mod_lists()
    
    logger.info("\n=== CHECKING BLOCKED ACCOUNTS DATA ===")
    check_blocked_accounts()
    
    logger.info("\n=== ADDING TEST BLOCK ===")
    test_did = add_test_block()
    
    logger.info("\n=== CHECKING BLOCKED ACCOUNTS AFTER ADDING TEST BLOCK ===")
    check_blocked_accounts()
    
    logger.info("\nDiagnostics complete!")
    logger.info(f"A test block with DID {test_did} has been added to the database.")
    logger.info("This should be picked up by the primary account's sync_blocks_from_others method.")
    logger.info("Check the logs to see if the sync occurs within the next sync interval.")

if __name__ == "__main__":
    run_diagnostics() 