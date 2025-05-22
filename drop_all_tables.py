import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import logging
import sys
import argparse

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_connection(is_test_tables=False, force_local=False):
    """Get a connection to the database.
    
    Args:
        is_test_tables (bool): Whether we're working with test tables (affects logging only)
        force_local (bool): Force using the test connection string even for production tables
    """
    try:
        # Always use the test connection string in local mode
        if force_local or os.getenv('LOCAL_TEST', 'False').lower() == 'true':
            test_database_url = os.getenv('TEST_DATABASE_URL')
            if not test_database_url:
                logger.error("TEST_DATABASE_URL environment variable not found")
                raise ValueError("TEST_DATABASE_URL not set")
            
            table_type = "test" if is_test_tables else "production"
            logger.info(f"Connecting to database for {table_type} tables using TEST_DATABASE_URL...")
            return psycopg2.connect(test_database_url)
        else:
            # This path is only taken when running in the actual production environment
            database_url = os.getenv('DATABASE_URL')
            if database_url:
                logger.info("Connecting to production database via DATABASE_URL...")
                return psycopg2.connect(database_url)
            else:
                # Fall back to individual connection parameters
                DB_HOST = os.getenv('DB_HOST', 'localhost')
                DB_PORT = os.getenv('DB_PORT', '5432')
                DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
                DB_USER = os.getenv('DB_USER', 'postgres')
                DB_PASSWORD = os.getenv('DB_PASSWORD', '')
                
                logger.info(f"Connecting to production database {DB_NAME} using individual parameters...")
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

def drop_all_tables(is_test_db=False, skip_confirmation=False, force_local=True):
    """Drop all tables from the database.
    
    Args:
        is_test_db (bool): Whether to drop test tables or production tables
        skip_confirmation (bool): Whether to skip confirmation prompts
        force_local (bool): Force using the test connection string even for production tables
    """
    conn = None
    cursor = None
    
    try:
        # Connect to the database
        conn = get_connection(is_test_tables=is_test_db, force_local=force_local)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Determine table suffix based on test mode
        table_suffix = "_test" if is_test_db else ""
        db_type = "TEST" if is_test_db else "PRODUCTION"
        
        logger.info(f"Preparing to drop all tables from {db_type} database...")
        
        # First, check if tables exist
        tables_to_drop = [
            f"blocked_accounts{table_suffix}",
            f"mod_lists{table_suffix}",
            f"accounts{table_suffix}"
        ]
        
        existing_tables = []
        for table in tables_to_drop:
            cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = '{table}'
            )
            """)
            if cursor.fetchone()[0]:
                existing_tables.append(table)
        
        if not existing_tables:
            logger.info(f"No tables found in {db_type} database.")
            return
        
        logger.info(f"Found {len(existing_tables)} tables in {db_type} database: {', '.join(existing_tables)}")
        
        # Prompt for confirmation before dropping tables (if not skipped)
        if not skip_confirmation:
            print(f"\n⚠️  WARNING: You are about to DROP ALL TABLES from the {db_type} database! ⚠️")
            print(f"Tables to be dropped: {', '.join(existing_tables)}")
            confirmation = input("\nType 'YES' to confirm: ")
            
            if confirmation.strip().upper() != "YES":
                logger.info("Operation canceled by user.")
                return
        else:
            logger.info(f"Skipping confirmation prompt as requested. Proceeding with table drops in {db_type} database.")
        
        # Drop tables in the correct order (to handle foreign key constraints)
        for table in existing_tables:
            logger.info(f"Dropping table {table}...")
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table)))
            logger.info(f"Table {table} dropped successfully!")
        
        logger.info(f"All tables dropped from {db_type} database.")
    
    except Exception as e:
        logger.error(f"Error dropping tables: {e}")
        if conn and not conn.autocommit:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def main():
    """Main function to drop all tables from both test and production databases."""
    parser = argparse.ArgumentParser(description='Drop all database tables')
    parser.add_argument('--test-only', action='store_true', help='Drop only test database tables')
    parser.add_argument('--prod-only', action='store_true', help='Drop only production database tables')
    parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--no-force-local', action='store_true', help='Do not force using the test connection for production tables')
    args = parser.parse_args()
    
    # Determine which databases to reset
    reset_test = not args.prod_only
    reset_prod = not args.test_only
    force_local = not args.no_force_local
    
    print("\n===== DATABASE TABLE DROP SCRIPT =====")
    if reset_test and reset_prod:
        print("This script will DROP ALL TABLES from both TEST and PRODUCTION databases.")
    elif reset_test:
        print("This script will DROP ALL TABLES from the TEST database only.")
    elif reset_prod:
        print("This script will DROP ALL TABLES from the PRODUCTION database only.")
    
    if force_local:
        print("Using the TEST_DATABASE_URL connection for all operations.")
    print("The moderation list must be deleted manually as mentioned.")
    print("===============================\n")
    
    try:
        # Drop tables from test database if needed
        if reset_test:
            print("\n----- TEST DATABASE -----")
            drop_all_tables(is_test_db=True, skip_confirmation=args.yes, force_local=force_local)
        
        # Drop tables from production database if needed
        if reset_prod:
            print("\n----- PRODUCTION DATABASE -----")
            drop_all_tables(is_test_db=False, skip_confirmation=args.yes, force_local=force_local)
        
        print("\n✅ Database table drop complete!")
        
    except Exception as e:
        logger.error(f"Database reset failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 