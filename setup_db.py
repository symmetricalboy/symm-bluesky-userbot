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
    # Check for Railway-style DATABASE_URL
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        logger.info("Using DATABASE_URL for database setup")
        
        # Parse the connection string to get database name
        parsed_url = urllib.parse.urlparse(database_url)
        db_name = parsed_url.path.lstrip('/')
        
        # Connect directly using the DATABASE_URL
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Database already exists as we're connected to it
        logger.info(f"Connected to database '{db_name}' via DATABASE_URL")
    else:
        # Use individual connection parameters
        DB_HOST = os.getenv('DB_HOST', 'localhost')
        DB_PORT = os.getenv('DB_PORT', '5432')
        DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
        DB_USER = os.getenv('DB_USER', 'postgres')
        DB_PASSWORD = os.getenv('DB_PASSWORD', '')
        
        # First connect to 'postgres' database to create our app database if it doesn't exist
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if cursor.fetchone() is None:
            logger.info(f"Creating database '{DB_NAME}'...")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
        else:
            logger.info(f"Database '{DB_NAME}' already exists.")
        
        cursor.close()
        conn.close()
        
        # Connect to the app database to create tables
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME
        )
        cursor = conn.cursor()
    
    # Create the necessary tables
    logger.info("Creating tables if they don't exist...")
    
    # Create accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        handle TEXT UNIQUE NOT NULL,
        did TEXT UNIQUE NOT NULL,
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Create blocked_accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blocked_accounts (
        id SERIAL PRIMARY KEY,
        did TEXT NOT NULL,
        handle TEXT,
        reason TEXT,
        source_account_id INTEGER REFERENCES accounts(id),
        block_type TEXT NOT NULL,  -- 'blocking' or 'blocked_by'
        first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        is_synced BOOLEAN DEFAULT FALSE,
        UNIQUE(did, source_account_id, block_type)
    )
    """)
    
    # Create mod_lists table
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
    
    conn.commit()
    cursor.close()
    conn.close()
    
    logger.info("Database setup complete!")

if __name__ == "__main__":
    setup_database() 