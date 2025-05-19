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
            
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
            )
            # For schema changes, autocommit can be helpful or manage transactions explicitly
            # conn.autocommit = True 
            cursor = conn.cursor()
        
        logger.info("Creating/Altering tables if they don't exist or need changes...")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            handle TEXT UNIQUE NOT NULL,
            did TEXT UNIQUE NOT NULL,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Add updated_at column to accounts if it doesn't exist
        cursor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='accounts' AND column_name='updated_at'
            ) THEN
                ALTER TABLE accounts ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
            END IF;
        END$$;
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocked_accounts (
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
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mod_lists (
            id SERIAL PRIMARY KEY,
            list_uri TEXT UNIQUE NOT NULL,
            list_cid TEXT NOT NULL,
            owner_did TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        if not conn.autocommit: # Only commit if autocommit is not enabled for the main connection
            conn.commit()
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