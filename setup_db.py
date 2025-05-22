import os
import logging
import urllib.parse
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

async def setup_database(test_mode=None, force_local=True):
    """Set up database tables, supporting both individual connection params and DATABASE_URL.
    
    Args:
        test_mode (bool, optional): If provided, overrides the LOCAL_TEST env variable.
                                    Determines if we're creating test tables (_test suffix) or production tables.
        force_local (bool): Force using the TEST_DATABASE_URL connection even for production tables.
    """
    # Determine if we're in test mode (for table naming)
    if test_mode is None:
        local_test = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
    else:
        local_test = test_mode
    
    # Determine if we're using the test connection
    use_test_connection = force_local or os.getenv('LOCAL_TEST', 'False').lower() == 'true'
    
    database_url = os.getenv('DATABASE_URL')
    conn = None
    
    try:
        if use_test_connection:
            # Use TEST_DATABASE_URL for the connection
            test_database_url = os.getenv('TEST_DATABASE_URL')
            if not test_database_url:
                logger.error("TEST_DATABASE_URL environment variable not found")
                raise ValueError("TEST_DATABASE_URL not set")
                
            table_type = "test" if local_test else "production"
            logger.info(f"Using TEST_DATABASE_URL to set up {table_type} tables")
            parsed_url = urllib.parse.urlparse(test_database_url)
            db_name = parsed_url.path.lstrip('/')
            conn = await asyncpg.connect(test_database_url)
            logger.info(f"Connected to database '{db_name}' via TEST_DATABASE_URL")
        else:
            # In production mode, check DATABASE_URL first (for backwards compatibility)
            database_url = os.getenv('DATABASE_URL')
            if database_url:
                logger.info("Using DATABASE_URL for production database setup")
                parsed_url = urllib.parse.urlparse(database_url)
                db_name = parsed_url.path.lstrip('/')
                conn = await asyncpg.connect(database_url)
                logger.info(f"Connected to production database '{db_name}' via DATABASE_URL")
            else:
                DB_HOST = os.getenv('DB_HOST', 'localhost')
                DB_PORT = int(os.getenv('DB_PORT', '5432'))
                DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
                DB_USER = os.getenv('DB_USER', 'postgres')
                DB_PASSWORD = os.getenv('DB_PASSWORD', '')
                
                # First, check if the database exists
                try:
                    conn_pg = await asyncpg.connect(
                        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database='postgres'
                    )
                    # Check if database exists
                    exists = await conn_pg.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME)
                    
                    if not exists:
                        logger.info(f"Creating database '{DB_NAME}'...")
                        await conn_pg.execute(f'CREATE DATABASE "{DB_NAME}"')
                    else:
                        logger.info(f"Database '{DB_NAME}' already exists.")
                    
                    await conn_pg.close()
                except Exception as e:
                    logger.warning(f"Could not connect to 'postgres' database to check if '{DB_NAME}' exists: {e}")
                    logger.info(f"Attempting to connect directly to '{DB_NAME}'...")
                
                try:
                    conn = await asyncpg.connect(
                        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
                    )
                    logger.info(f"Connected to database '{DB_NAME}'")
                except Exception as e:
                    logger.error(f"Failed to connect to database '{DB_NAME}': {e}")
                    raise
        
        # Determine if we need to create test tables
        table_suffix = "_test" if local_test else ""
        logger.info(f"{'Test' if local_test else 'Production'} mode: Using table suffix '{table_suffix}'")
        
        logger.info("Creating/Altering tables if they don't exist or need changes...")
        
        # First, check if the accounts table exists
        accounts_table_exists = await conn.fetchval(f"""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'accounts{table_suffix}'
        )
        """)
        
        # Create accounts table if it doesn't exist
        if not accounts_table_exists:
            logger.info(f"Creating accounts{table_suffix} table...")
            await conn.execute(f"""
            CREATE TABLE accounts{table_suffix} (
                id SERIAL PRIMARY KEY,
                handle TEXT UNIQUE NOT NULL,
                did TEXT UNIQUE NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_firehose_cursor BIGINT DEFAULT NULL
            )
            """)
            logger.info(f"accounts{table_suffix} table created successfully!")
        else:
            # Check if updated_at column exists and add it if it doesn't
            updated_at_exists = await conn.fetchval(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'accounts{table_suffix}' 
                AND column_name = 'updated_at'
            )
            """)
            
            if not updated_at_exists:
                logger.info(f"Adding updated_at column to accounts{table_suffix} table...")
                await conn.execute(f"""
                ALTER TABLE accounts{table_suffix} 
                ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                """)
                logger.info(f"Added updated_at column to accounts{table_suffix} table")

            # Check if last_firehose_cursor column exists and add it if it doesn't
            last_firehose_cursor_exists = await conn.fetchval(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'accounts{table_suffix}' 
                AND column_name = 'last_firehose_cursor'
            )
            """)
            if not last_firehose_cursor_exists:
                logger.info(f"Adding last_firehose_cursor column to accounts{table_suffix} table...")
                await conn.execute(f"""
                ALTER TABLE accounts{table_suffix}
                ADD COLUMN last_firehose_cursor BIGINT DEFAULT NULL
                """)
                logger.info(f"Added last_firehose_cursor column to accounts{table_suffix} table")
        
        # Check for blocked_accounts table
        blocked_accounts_exists = await conn.fetchval(f"""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'blocked_accounts{table_suffix}'
        )
        """)
        
        # Create blocked_accounts table if it doesn't exist
        if not blocked_accounts_exists:
            logger.info(f"Creating blocked_accounts{table_suffix} table...")
            await conn.execute(f"""
            CREATE TABLE blocked_accounts{table_suffix} (
                id SERIAL PRIMARY KEY,
                did TEXT NOT NULL,
                handle TEXT,
                reason TEXT,
                source_account_id INTEGER REFERENCES accounts{table_suffix}(id) ON DELETE CASCADE,
                block_type TEXT NOT NULL,  -- 'blocking' or 'blocked_by'
                first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                is_synced BOOLEAN DEFAULT FALSE,
                UNIQUE(did, source_account_id, block_type)
            )
            """)
            logger.info(f"blocked_accounts{table_suffix} table created successfully!")
        
        # Check for mod_lists table
        mod_lists_exists = await conn.fetchval(f"""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'mod_lists{table_suffix}'
        )
        """)
        
        # Create mod_lists table if it doesn't exist
        if not mod_lists_exists:
            logger.info(f"Creating mod_lists{table_suffix} table...")
            await conn.execute(f"""
            CREATE TABLE mod_lists{table_suffix} (
                id SERIAL PRIMARY KEY,
                list_uri TEXT UNIQUE NOT NULL,
                list_cid TEXT NOT NULL,
                owner_did TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """)
            logger.info(f"mod_lists{table_suffix} table created successfully!")
        
        logger.info(f"{'Test' if local_test else 'Production'} database setup complete!")

    except Exception as e:
        logger.error(f"Database setup error: {e}")
        raise  # Re-raise the exception after logging
    finally:
        if conn:
            await conn.close()

if __name__ == "__main__":
    asyncio.run(setup_database()) 