import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging
import urllib.parse

load_dotenv()

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

def get_connection():
    """Get a connection to the database, supporting both individual params and DATABASE_URL."""
    try:
        # Check if we're in local test mode
        local_test = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        
        if local_test:
            # In local test mode, use TEST_DATABASE_URL
            test_database_url = os.getenv('TEST_DATABASE_URL')
            if test_database_url:
                logger.info("Local test mode: Connecting using TEST_DATABASE_URL")
                return psycopg2.connect(test_database_url)
            else:
                logger.error("Local test mode enabled but TEST_DATABASE_URL not found")
                raise ValueError("LOCAL_TEST=True but TEST_DATABASE_URL not set")
        else:
            # In production mode, check DATABASE_URL first (for backwards compatibility)
            database_url = os.getenv('DATABASE_URL')
            
            if database_url:
                logger.info("Production mode: Connecting using DATABASE_URL")
                return psycopg2.connect(database_url)
            else:
                # Fall back to individual connection parameters
                DB_HOST = os.getenv('DB_HOST', 'localhost')
                DB_PORT = os.getenv('DB_PORT', '5432')
                DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
                DB_USER = os.getenv('DB_USER', 'postgres')
                DB_PASSWORD = os.getenv('DB_PASSWORD', '')
                
                logger.info(f"Production mode: Connecting using individual parameters to {DB_HOST}:{DB_PORT}/{DB_NAME}")
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

class Database:
    def __init__(self, test_mode=None):
        """Initialize the database connection with option for test mode.
        
        Args:
            test_mode (bool, optional): If provided, overrides the LOCAL_TEST env var.
        """
        if test_mode is None:
            self.test_mode = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        else:
            self.test_mode = test_mode
            
        self.table_suffix = "_test" if self.test_mode else ""
        logger.debug(f"Database initialized in {'test' if self.test_mode else 'production'} mode with table suffix '{self.table_suffix}'")

    def get_connection(self):
        """Get a database connection using the global connection function."""
        return get_connection()
    
    def test_connection(self):
        """Test the database connection by executing a simple query."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            return result[0] == 1
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def register_account(self, handle, did, is_primary=False):
        """Register a managed account in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Check if account already exists
            cursor.execute(f"SELECT id FROM accounts{self.table_suffix} WHERE did = %s", (did,))
            result = cursor.fetchone()
            
            if result:
                # Update existing account
                account_id = result[0]
                cursor.execute(
                    f"UPDATE accounts{self.table_suffix} SET handle = %s, is_primary = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (handle, is_primary, account_id)
                )
            else:
                # Insert new account
                cursor.execute(
                    f"INSERT INTO accounts{self.table_suffix} (handle, did, is_primary) VALUES (%s, %s, %s) RETURNING id",
                    (handle, did, is_primary)
                )
                account_id = cursor.fetchone()[0]
            
            conn.commit()
            return account_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error registering account {handle}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_account_by_did(self, did):
        """Get account details by DID."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(f"SELECT * FROM accounts{self.table_suffix} WHERE did = %s", (did,))
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting account {did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_primary_account(self):
        """Get the primary account."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(f"SELECT * FROM accounts{self.table_suffix} WHERE is_primary = TRUE LIMIT 1")
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting primary account: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_secondary_accounts(self):
        """Get all secondary (non-primary) accounts."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(f"SELECT * FROM accounts{self.table_suffix} WHERE is_primary = FALSE ORDER BY id")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting secondary accounts: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def add_blocked_account(self, did, handle, source_account_id, block_type, reason=None):
        """Add or update a blocked account in the database. Reset is_synced to FALSE on update if it's a non-primary block."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT is_primary FROM accounts{self.table_suffix} WHERE id = %s", (source_account_id,))
            source_is_primary = cursor.fetchone()
            source_is_primary = source_is_primary[0] if source_is_primary else False

            cursor.execute(
                f"SELECT id, is_synced FROM blocked_accounts{self.table_suffix} WHERE did = %s AND source_account_id = %s AND block_type = %s",
                (did, source_account_id, block_type)
            )
            result = cursor.fetchone()
            
            if result:
                existing_id = result[0]
                # For non-primary source accounts, if handle or reason changes, it might need re-syncing by primary.
                # However, simple last_seen update shouldn't reset is_synced.
                # Let's assume is_synced is only reset if the block was re-asserted by a non-primary.
                # For now, we will explicitly set is_synced to FALSE if the source_account_id is not primary
                # and this is an update to an existing block. This ensures it gets picked up by primary sync if not already processed.
                # This behavior might need refinement based on desired sync logic.
                update_query = f"UPDATE blocked_accounts{self.table_suffix} SET handle = %s, reason = %s, last_seen = CURRENT_TIMESTAMP" 
                params = [handle, reason]
                # If the source is not primary, and the block is updated, mark as unsynced for primary to re-check
                if not source_is_primary:
                    update_query += ", is_synced = FALSE"
                update_query += " WHERE id = %s"
                params.append(existing_id)
                cursor.execute(update_query, tuple(params))
            else:
                # New blocks from non-primary are unsynced by default (is_synced DEFAULT FALSE)
                # New blocks from primary are considered synced with themselves by default.
                is_synced_for_new_block = True if source_is_primary else False
                cursor.execute(
                    f"""INSERT INTO blocked_accounts{self.table_suffix} 
                    (did, handle, reason, source_account_id, block_type, is_synced)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (did, handle, reason, source_account_id, block_type, is_synced_for_new_block)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error adding blocked account {did} for source_id {source_account_id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_unsynced_blocks_for_primary(self, primary_account_id):
        """Get DIDs that were blocked by other managed accounts and need to be synced by the primary account."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # First, let's log how many total block entries we have for debugging
            cursor.execute(f"SELECT COUNT(*) as total_blocks FROM blocked_accounts{self.table_suffix} WHERE block_type = 'blocking'")
            total_blocks = cursor.fetchone()['total_blocks']
            logger.info(f"DB_SYNC: Found {total_blocks} total 'blocking' entries in the database")
            
            # Log raw data from blocked_accounts table for debugging
            logger.info(f"DB_SYNC: Fetching detailed block data for debugging...")
            cursor.execute(f"SELECT * FROM blocked_accounts{self.table_suffix} WHERE block_type = 'blocking' LIMIT 20")
            detailed_blocks = cursor.fetchall()
            for block in detailed_blocks:
                logger.info(f"DB_SYNC: Block record - DID: {block.get('did', 'unknown')}, " 
                          f"Account ID: {block.get('source_account_id', 'unknown')}, "
                          f"is_synced: {block.get('is_synced', 'unknown')}, "
                          f"First seen: {block.get('first_seen', 'unknown')}")
            
            # Log how many blocks are from non-primary accounts
            cursor.execute(f"""
                SELECT COUNT(*) as secondary_blocks 
                FROM blocked_accounts{self.table_suffix} ba
                JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
                WHERE a.is_primary = FALSE AND ba.block_type = 'blocking'
            """)
            secondary_blocks = cursor.fetchone()['secondary_blocks']
            logger.info(f"DB_SYNC: Found {secondary_blocks} 'blocking' entries from secondary accounts")
            
            # Log how many unsynced blocks we have
            cursor.execute(f"""
                SELECT COUNT(*) as unsynced_blocks 
                FROM blocked_accounts{self.table_suffix} ba
                JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
                WHERE a.is_primary = FALSE AND ba.block_type = 'blocking' AND ba.is_synced = FALSE
            """)
            unsynced_blocks = cursor.fetchone()['unsynced_blocks']
            logger.info(f"DB_SYNC: Found {unsynced_blocks} unsynced 'blocking' entries from secondary accounts")
            
            # Modified query that finds all blocks from non-primary accounts that should be synced
            # We want all blocks from secondary accounts where:
            # 1. The account is not the primary account
            # 2. The block type is 'blocking'
            # 3. This specific block entry hasn't been marked as synced
            # 4. We are NOT checking if primary already blocks this DID - we want to log that too
            query = f"""
            SELECT ba.id, ba.did, ba.handle, a.handle as source_account_handle,
                   EXISTS (
                       SELECT 1
                       FROM blocked_accounts{self.table_suffix} primary_blocks
                       WHERE primary_blocks.did = ba.did
                         AND primary_blocks.source_account_id = %s
                         AND primary_blocks.block_type = 'blocking'
                   ) as already_blocked_by_primary
            FROM blocked_accounts{self.table_suffix} ba
            JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
            WHERE a.is_primary = FALSE                    -- Block is from a non-primary account
              AND ba.block_type = 'blocking'              -- It's a block action by that non-primary account
              AND ba.is_synced = FALSE                    -- The primary account hasn't processed this specific entry yet
            ORDER BY ba.first_seen ASC; -- Process older blocks first
            """
            
            cursor.execute(query, (primary_account_id,))
            blocks_to_sync = cursor.fetchall()
            
            # Let's log what we found for debugging
            logger.info(f"DB_SYNC: Found {len(blocks_to_sync)} blocks that need to be synced by primary from non-primary accounts")
            for block in blocks_to_sync:
                already_blocked = "Already blocked by primary" if block['already_blocked_by_primary'] else "Not yet blocked by primary"
                logger.info(f"DB_SYNC: Need to sync block - DID: {block['did']}, Handle: {block['handle']}, "
                          f"Source Account: {block['source_account_handle']}, Status: {already_blocked}")
            
            return blocks_to_sync
        except Exception as e:
            logger.error(f"Error fetching unsynced blocks: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def mark_block_as_synced_by_primary(self, original_block_db_id, primary_account_id):
        """Mark a block as synced by the primary account."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Mark the original block entry as synced
            cursor.execute(
                f"UPDATE blocked_accounts{self.table_suffix} SET is_synced = TRUE WHERE id = %s",
                (original_block_db_id,)
            )
            conn.commit()
            logger.info(f"DB_SYNC: Marked block ID {original_block_db_id} as synced by primary account ID {primary_account_id}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Error marking block as synced: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_all_blocked_accounts(self, unsynced_only=False):
        """Get all blocked accounts."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = f"""
                SELECT 
                    ba.did, 
                    ba.handle, 
                    ba.block_type,
                    a.handle as source_account_handle,
                    ba.is_synced
                FROM blocked_accounts{self.table_suffix} ba
                JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
            """
            
            if unsynced_only:
                query += " WHERE ba.is_synced = FALSE"
                
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all blocked accounts: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def mark_accounts_as_synced(self, dids, specific_source_account_id=None):
        """Mark accounts as synced in the database."""
        if not dids:
            return
            
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if specific_source_account_id:
                # Mark specific accounts as synced from a specific source account
                # This is used when a secondary account tells us which accounts it's blocking
                placeholder_string = ','.join(['%s'] * len(dids))
                query = f"""
                    UPDATE blocked_accounts{self.table_suffix}
                    SET is_synced = TRUE
                    WHERE did IN ({placeholder_string})
                    AND source_account_id = %s
                """
                params = dids + [specific_source_account_id]
            else:
                # Mark accounts as synced for all source accounts
                # This is used when the primary account has synced blocks from secondary accounts
                placeholder_string = ','.join(['%s'] * len(dids))
                query = f"""
                    UPDATE blocked_accounts{self.table_suffix}
                    SET is_synced = TRUE
                    WHERE did IN ({placeholder_string})
                """
                params = dids
                
            cursor.execute(query, params)
            conn.commit()
            logger.info(f"Marked {cursor.rowcount} blocked accounts as synced")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error marking accounts as synced: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def register_mod_list(self, list_uri, list_cid, owner_did, name):
        """Register a moderation list in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Check if mod list already exists
            cursor.execute(f"SELECT id FROM mod_lists{self.table_suffix} WHERE list_uri = %s", (list_uri,))
            result = cursor.fetchone()
            
            if result:
                # Update existing mod list
                list_id = result[0]
                cursor.execute(
                    f"UPDATE mod_lists{self.table_suffix} SET list_cid = %s, owner_did = %s, name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (list_cid, owner_did, name, list_id)
                )
            else:
                # Insert new mod list
                cursor.execute(
                    f"INSERT INTO mod_lists{self.table_suffix} (list_uri, list_cid, owner_did, name) VALUES (%s, %s, %s, %s) RETURNING id",
                    (list_uri, list_cid, owner_did, name)
                )
                list_id = cursor.fetchone()[0]
            
            conn.commit()
            return list_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error registering mod list {list_uri}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def remove_stale_blocks(self, source_account_id, block_type, current_dids):
        """Remove blocks that are no longer valid."""
        if not current_dids:
            logger.warning(f"No current DIDs provided for account ID {source_account_id} and block type {block_type}")
            return
            
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Prepare the placeholder string for the IN clause
            placeholder_string = ','.join(['%s'] * len(current_dids))
            
            # Delete blocks that are not in the current list
            query = f"""
                DELETE FROM blocked_accounts{self.table_suffix}
                WHERE source_account_id = %s
                AND block_type = %s
                AND did NOT IN ({placeholder_string})
            """
            params = [source_account_id, block_type] + current_dids
            
            cursor.execute(query, params)
            deleted_count = cursor.rowcount
            conn.commit()
            
            logger.info(f"Removed {deleted_count} stale blocks for account ID {source_account_id} with block type {block_type}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error removing stale blocks for account ID {source_account_id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_last_firehose_cursor(self, account_did):
        """Get the last firehose cursor for an account."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT last_firehose_cursor FROM accounts{self.table_suffix} WHERE did = %s", (account_did,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting last firehose cursor for {account_did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def save_last_firehose_cursor(self, account_did, cursor_val):
        """Save the last firehose cursor for an account."""
        if not cursor_val:
            logger.warning(f"Attempted to save null cursor value for {account_did}")
            return
            
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE accounts{self.table_suffix} SET last_firehose_cursor = %s WHERE did = %s",
                (cursor_val, account_did)
            )
            conn.commit()
            logger.debug(f"Saved firehose cursor {cursor_val} for account {account_did}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving firehose cursor for {account_did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_all_dids_primary_should_list(self, primary_account_id):
        """Get all DIDs that the primary account should include in its mod list."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Get all unique DIDs from both blocking and blocked_by types from all accounts
            query = f"""
            SELECT DISTINCT did FROM blocked_accounts{self.table_suffix}
            WHERE 
                -- We want all blocks made by all accounts (primary and non-primary)
                (block_type = 'blocking')
                
                -- We also want accounts that are blocking any of our accounts
                OR (block_type = 'blocked_by')
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            # Extract DIDs from results
            dids = [row[0] for row in results]
            
            logger.info(f"Found {len(dids)} total unique DIDs that primary should include in mod list")
            
            return dids
        except Exception as e:
            logger.error(f"Error getting DIDs for primary mod list: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_mod_lists_by_owner(self, owner_did):
        """Get moderation lists by owner DID."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(f"SELECT * FROM mod_lists{self.table_suffix} WHERE owner_did = %s", (owner_did,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting mod lists for owner {owner_did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def execute_query(self, query, params=None, commit=False):
        """Execute a custom query and return results."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Replace table names with their test or production versions
            # This only handles explicitly named tables in the query
            if self.table_suffix:
                query = query.replace("accounts ", f"accounts{self.table_suffix} ")
                query = query.replace("blocked_accounts ", f"blocked_accounts{self.table_suffix} ")
                query = query.replace("mod_lists ", f"mod_lists{self.table_suffix} ")
                
                # Also handle table names at the end of the query
                query = query.replace("accounts;", f"accounts{self.table_suffix};")
                query = query.replace("blocked_accounts;", f"blocked_accounts{self.table_suffix};")
                query = query.replace("mod_lists;", f"mod_lists{self.table_suffix};")
            
            cursor.execute(query, params or ())
            
            if commit:
                conn.commit()
                return cursor.rowcount
            
            return cursor.fetchall()
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Error executing query: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
        finally:
            cursor.close()
            conn.close()  