import os
import logging
import sys
from database import Database

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("deduplicate_dids.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def deduplicate_dids():
    """Remove duplicate DIDs from the blocked_accounts table, keeping the most recent entry"""
    logger.info("Starting deduplication of DIDs in the database...")
    
    db = Database()
    if not db.test_connection():
        logger.error("Database connection test failed. Cannot deduplicate DIDs.")
        return False
    
    try:
        # Get all accounts (primary + secondary)
        accounts = []
        
        primary_account = db.get_primary_account()
        if primary_account:
            accounts.append(primary_account)
            logger.info(f"Found primary account: {primary_account['handle']}")
        
        secondary_accounts = db.get_secondary_accounts()
        if secondary_accounts:
            accounts.extend(secondary_accounts)
            logger.info(f"Found {len(secondary_accounts)} secondary accounts")
        
        if not accounts:
            logger.error("No accounts found in database.")
            return False
        
        logger.info(f"Found {len(accounts)} accounts in database")
        total_duplicates_removed = 0
        
        # For each account, deduplicate DIDs
        for account in accounts:
            account_id = account['id']
            handle = account['handle']
            
            for block_type in ['blocking', 'blocked_by']:
                # First identify duplicates
                duplicates = db.execute_query("""
                    SELECT did, COUNT(*) as count 
                    FROM blocked_accounts 
                    WHERE source_account_id = %s AND block_type = %s
                    GROUP BY did 
                    HAVING COUNT(*) > 1
                """, (account_id, block_type))
                
                if not duplicates:
                    logger.info(f"No duplicate DIDs found in '{block_type}' relationships for {handle}")
                    continue
                
                logger.warning(f"Found {len(duplicates)} DIDs with duplicates in '{block_type}' relationships for {handle}")
                
                # For each duplicate DID
                for dup in duplicates:
                    did = dup[0]
                    count = dup[1]
                    
                    # Get all entries for this DID
                    entries = db.execute_query("""
                        SELECT id, created_at 
                        FROM blocked_accounts 
                        WHERE source_account_id = %s AND block_type = %s AND did = %s
                        ORDER BY created_at DESC
                    """, (account_id, block_type, did))
                    
                    if len(entries) <= 1:
                        logger.warning(f"Expected duplicates for DID {did} but found only {len(entries)} entries")
                        continue
                    
                    # Keep the most recent entry, delete the rest
                    most_recent_id = entries[0][0]
                    to_delete_ids = [entry[0] for entry in entries[1:]]
                    
                    for delete_id in to_delete_ids:
                        db.execute_query("""
                            DELETE FROM blocked_accounts 
                            WHERE id = %s
                        """, (delete_id,), commit=True)
                    
                    logger.info(f"Kept entry {most_recent_id} and removed {len(to_delete_ids)} duplicates for DID {did} in '{block_type}' relationship for {handle}")
                    total_duplicates_removed += len(to_delete_ids)
        
        logger.info(f"Deduplication completed. Removed a total of {total_duplicates_removed} duplicate entries.")
        return True
    except Exception as e:
        logger.error(f"Error deduplicating DIDs: {e}")
        return False

if __name__ == "__main__":
    deduplicate_dids() 