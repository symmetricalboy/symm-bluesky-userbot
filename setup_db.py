import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import logging
import urllib.parse

load_dotenv()

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

def setup_database():
    """Set up database tables, supporting both individual connection params and DATABASE_URL."""
    database_url = os.getenv('DATABASE_URL')
    conn = None
    cursor = None
    
    try:
        if database_url:
            logger.info("Using DATABASE_URL for database setup")
            parsed_url = urllib.parse.urlparse(database_url)
            db_name = parsed_url.path.lstrip('/')
            conn = psycopg2.connect(database_url)
            conn.autocommit = True # Set autocommit for operations like ADD COLUMN if needed outside a transaction
            cursor = conn.cursor()
            logger.info(f"Connected to database '{db_name}' via DATABASE_URL")
        else:
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            # First, check if the database exists, connect to 'postgres' database initially
            try:
                conn_pg = psycopg2.connect(
                    host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname='postgres'
                )
                conn_pg.autocommit = True
                cursor_pg = conn_pg.cursor()
                cursor_pg.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
                if cursor_pg.fetchone() is None:
                    logger.info(f"Creating database '{DB_NAME}'...")
                    cursor_pg.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
                else:
                    logger.info(f"Database '{DB_NAME}' already exists.")
                cursor_pg.close()
                conn_pg.close()
            except Exception as e:
                logger.warning(f"Could not connect to 'postgres' database to check if '{DB_NAME}' exists: {e}")
                logger.info(f"Attempting to connect directly to '{DB_NAME}'...")
            
            try:
                conn = psycopg2.connect(
                    host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
                )
                conn.autocommit = True
                cursor = conn.cursor()
                logger.info(f"Connected to database '{DB_NAME}'")
            except Exception as e:
                logger.error(f"Failed to connect to database '{DB_NAME}': {e}")
                raise
        
        logger.info("Creating/Altering tables if they don't exist or need changes...")
        
        # First, check if the accounts table exists
        cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'accounts'
        )
        """)
        
        accounts_table_exists = cursor.fetchone()[0]
        
        # Create accounts table if it doesn't exist
        if not accounts_table_exists:
            logger.info("Creating accounts table...")
            cursor.execute("""
            CREATE TABLE accounts (
                id SERIAL PRIMARY KEY,
                handle TEXT UNIQUE NOT NULL,
                did TEXT UNIQUE NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """)
            logger.info("Accounts table created successfully!")
        else:
            # Check if updated_at column exists and add it if it doesn't
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
                logger.info("Adding updated_at column to accounts table...")
                cursor.execute("""
                ALTER TABLE accounts 
                ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                """)
                logger.info("Added updated_at column to accounts table")

            # Check if last_firehose_cursor column exists and add it if it doesn't
            cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'accounts' 
                AND column_name = 'last_firehose_cursor'
            )
            """)
            last_firehose_cursor_exists = cursor.fetchone()[0]
            if not last_firehose_cursor_exists:
                logger.info("Adding last_firehose_cursor column to accounts table...")
                cursor.execute("""
                ALTER TABLE accounts
                ADD COLUMN last_firehose_cursor BIGINT DEFAULT NULL
                """)
                logger.info("Added last_firehose_cursor column to accounts table")
        
        # Check for blocked_accounts table
        cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'blocked_accounts'
        )
        """)
        
        blocked_accounts_exists = cursor.fetchone()[0]
        
        # Create blocked_accounts table if it doesn't exist
        if not blocked_accounts_exists:
            logger.info("Creating blocked_accounts table...")
            cursor.execute("""
            CREATE TABLE blocked_accounts (
                id SERIAL PRIMARY KEY,
                did TEXT NOT NULL,
                handle TEXT,
                reason TEXT,
                source_account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                block_type TEXT NOT NULL,  -- 'blocking' or 'blocked_by'
                first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                is_synced BOOLEAN DEFAULT FALSE,
                UNIQUE(did, source_account_id, block_type)
            )
            """)
            logger.info("blocked_accounts table created successfully!")
        
        # Check for mod_lists table
        cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'mod_lists'
        )
        """)
        
        mod_lists_exists = cursor.fetchone()[0]
        
        # Create mod_lists table if it doesn't exist
        if not mod_lists_exists:
            logger.info("Creating mod_lists table...")
            cursor.execute("""
            CREATE TABLE mod_lists (
                id SERIAL PRIMARY KEY,
                list_uri TEXT UNIQUE NOT NULL,
                list_cid TEXT NOT NULL,
                owner_did TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """)
            logger.info("mod_lists table created successfully!")
        
        logger.info("Database setup complete!")

    except Exception as e:
        logger.error(f"Database setup error: {e}")
        if conn and not conn.autocommit:
            conn.rollback()
        raise # Re-raise the exception after logging and potential rollback
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    setup_database() 