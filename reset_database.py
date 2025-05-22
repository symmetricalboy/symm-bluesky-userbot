import os
import sys
import logging
import argparse
from dotenv import load_dotenv

# Import our scripts
from drop_all_tables import drop_all_tables
from setup_db import setup_database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main function to reset the database completely."""
    parser = argparse.ArgumentParser(description='Reset database tables')
    parser.add_argument('--test-only', action='store_true', help='Reset only the test database')
    parser.add_argument('--prod-only', action='store_true', help='Reset only the production database')
    parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--no-force-local', action='store_true', help='Do not force using the test connection for production tables')
    args = parser.parse_args()
    
    # Determine which databases to reset
    reset_test = not args.prod_only
    reset_prod = not args.test_only
    force_local = not args.no_force_local
    
    print("\n===== DATABASE RESET =====")
    if reset_test and reset_prod:
        print("This script will reset BOTH test and production databases.")
    elif reset_test:
        print("This script will reset ONLY the test database.")
    elif reset_prod:
        print("This script will reset ONLY the production database.")
    
    if force_local:
        print("Using the TEST_DATABASE_URL connection for all operations.")
    
    print("This involves:")
    print("1. Dropping all existing tables")
    print("2. Recreating the database structure")
    print("Remember: The moderation list must be deleted manually as mentioned.")
    print("==========================\n")
    
    # Overall confirmation if not using --yes flag
    if not args.yes:
        confirmation = input("Do you want to continue? (yes/no): ")
        if confirmation.lower() not in ('yes', 'y'):
            print("Operation cancelled.")
            return
    
    try:
        # Step 1: Drop tables
        if reset_test:
            print("\n----- DROPPING TEST DATABASE TABLES -----")
            drop_all_tables(is_test_db=True, skip_confirmation=args.yes, force_local=force_local)
        
        if reset_prod:
            print("\n----- DROPPING PRODUCTION DATABASE TABLES -----")
            try:
                drop_all_tables(is_test_db=False, skip_confirmation=args.yes, force_local=force_local)
            except Exception as e:
                logger.error(f"Failed to reset production database: {e}")
                if not reset_test:
                    raise
                else:
                    print("\n⚠️ WARNING: Production database reset failed. Continuing with test database only.")
        
        # Step 2: Recreate tables
        if reset_test:
            print("\n----- RECREATING TEST DATABASE STRUCTURE -----")
            setup_database(test_mode=True, force_local=force_local)
        
        if reset_prod:
            print("\n----- RECREATING PRODUCTION DATABASE STRUCTURE -----")
            try:
                setup_database(test_mode=False, force_local=force_local)
            except Exception as e:
                logger.error(f"Failed to recreate production database structure: {e}")
                if not reset_test:
                    raise
                else:
                    print("\n⚠️ WARNING: Production database recreation failed. Test database has been reset successfully.")
        
        print("\n✅ Database reset and setup complete!")
        
    except Exception as e:
        logger.error(f"Database reset and setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 