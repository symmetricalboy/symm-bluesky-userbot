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
        # First check for Railway-style DATABASE_URL
        database_url = os.getenv('DATABASE_URL')
        
        if database_url:
            logger.debug("Connecting using DATABASE_URL")
            return psycopg2.connect(database_url)
        else:
            # Fall back to individual connection parameters
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            logger.debug(f"Connecting using individual parameters to {DB_HOST}:{DB_PORT}/{DB_NAME}")
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
            cursor.execute("SELECT id FROM accounts WHERE did = %s", (did,))
            result = cursor.fetchone()
            
            if result:
                # Update existing account
                account_id = result[0]
                cursor.execute(
                    "UPDATE accounts SET handle = %s, is_primary = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (handle, is_primary, account_id)
                )
            else:
                # Insert new account
                cursor.execute(
                    "INSERT INTO accounts (handle, did, is_primary) VALUES (%s, %s, %s) RETURNING id",
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
            cursor.execute("SELECT * FROM accounts WHERE did = %s", (did,))
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
            cursor.execute("SELECT * FROM accounts WHERE is_primary = TRUE LIMIT 1")
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
            cursor.execute("SELECT * FROM accounts WHERE is_primary = FALSE ORDER BY id")
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
            cursor.execute("SELECT is_primary FROM accounts WHERE id = %s", (source_account_id,))
            source_is_primary = cursor.fetchone()
            source_is_primary = source_is_primary[0] if source_is_primary else False

            cursor.execute(
                "SELECT id, is_synced FROM blocked_accounts WHERE did = %s AND source_account_id = %s AND block_type = %s",
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
                update_query = "UPDATE blocked_accounts SET handle = %s, reason = %s, last_seen = CURRENT_TIMESTAMP" 
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
                    """INSERT INTO blocked_accounts 
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
            cursor.execute("SELECT COUNT(*) as total_blocks FROM blocked_accounts WHERE block_type = 'blocking'")
            total_blocks = cursor.fetchone()['total_blocks']
            logger.info(f"DB_SYNC: Found {total_blocks} total 'blocking' entries in the database")
            
            # Log raw data from blocked_accounts table for debugging
            logger.info(f"DB_SYNC: Fetching detailed block data for debugging...")
            cursor.execute("SELECT * FROM blocked_accounts WHERE block_type = 'blocking' LIMIT 20")
            detailed_blocks = cursor.fetchall()
            for block in detailed_blocks:
                logger.info(f"DB_SYNC: Block record - DID: {block.get('did', 'unknown')}, " 
                          f"Account ID: {block.get('source_account_id', 'unknown')}, "
                          f"is_synced: {block.get('is_synced', 'unknown')}, "
                          f"First seen: {block.get('first_seen', 'unknown')}")
            
            # Log how many blocks are from non-primary accounts
            cursor.execute("""
                SELECT COUNT(*) as secondary_blocks 
                FROM blocked_accounts ba
                JOIN accounts a ON ba.source_account_id = a.id
                WHERE a.is_primary = FALSE AND ba.block_type = 'blocking'
            """)
            secondary_blocks = cursor.fetchone()['secondary_blocks']
            logger.info(f"DB_SYNC: Found {secondary_blocks} 'blocking' entries from secondary accounts")
            
            # Log how many unsynced blocks we have
            cursor.execute("""
                SELECT COUNT(*) as unsynced_blocks 
                FROM blocked_accounts ba
                JOIN accounts a ON ba.source_account_id = a.id
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
            query = """
            SELECT ba.id, ba.did, ba.handle, a.handle as source_account_handle,
                   EXISTS (
                       SELECT 1
                       FROM blocked_accounts primary_blocks
                       WHERE primary_blocks.did = ba.did
                         AND primary_blocks.source_account_id = %s
                         AND primary_blocks.block_type = 'blocking'
                   ) as already_blocked_by_primary
            FROM blocked_accounts ba
            JOIN accounts a ON ba.source_account_id = a.id
            WHERE a.is_primary = FALSE                    -- Block is from a non-primary account
              AND ba.block_type = 'blocking'              -- It's a block action by that non-primary account
              AND ba.is_synced = FALSE                    -- The primary account hasn't processed this specific entry yet
            ORDER BY ba.first_seen ASC; -- Process older blocks first
            """
            cursor.execute(query, (primary_account_id,))
            results = cursor.fetchall()
            
            # Log detailed info about what's being synced
            if results:
                for r in results:
                    if r['already_blocked_by_primary']:
                        logger.info(f"DB_SYNC: Found block for {r['handle']} ({r['did']}) that is already blocked by primary - will mark as synced")
                    else:
                        logger.info(f"DB_SYNC: Found block for {r['handle']} ({r['did']}) that needs to be blocked by primary")
            else:
                logger.info(f"DB_SYNC: No blocks from secondary accounts that need syncing")
                
            # Return only the ones not already blocked by primary
            return [r for r in results if not r['already_blocked_by_primary']]
        except Exception as e:
            logger.error(f"Error getting unsynced blocks for primary {primary_account_id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def mark_block_as_synced_by_primary(self, original_block_db_id, primary_account_id):
        """Mark an original block (from a non-primary account) as synced by the primary account.
           This sets the is_synced flag on the original block_accounts record to TRUE.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # We also need to ensure that the primary account has indeed now blocked this DID.
            # This function is called *after* the primary attempts the block.
            # So, we just update the flag on the original record.
            cursor.execute(
                "UPDATE blocked_accounts SET is_synced = TRUE WHERE id = %s",
                (original_block_db_id,)
            )
            conn.commit()
            logger.debug(f"Marked original block ID {original_block_db_id} as synced by primary {primary_account_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error marking block ID {original_block_db_id} as synced by primary {primary_account_id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def get_all_blocked_accounts(self, unsynced_only=False):
        """Get all unique DIDs and handles that are blocked by any managed account.
           If unsynced_only is True, it returns those DIDs that have at least one 
           'blocking' record by a non-primary account marked as is_synced = FALSE.
           This method is more for general reporting or if other types of sync processes need it.
        """
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            if unsynced_only:
                # This will fetch DIDs that are marked as blocking by a non-primary account and are not yet synced.
                # It's similar to get_unsynced_blocks_for_primary but doesn't exclude DIDs primary already blocks.
                # It just indicates a DID needs *some* sync attention from primary for at least one of its non-primary block entries.
                query = """
                SELECT DISTINCT ba.did, ba.handle, a.handle as source_account_handle, a.id as source_account_id,
                       ba.block_type, ba.is_synced, ba.reason, ba.first_seen, ba.last_seen 
                FROM blocked_accounts ba
                JOIN accounts a ON ba.source_account_id = a.id
                WHERE a.is_primary = FALSE 
                  AND ba.block_type = 'blocking' 
                  AND ba.is_synced = FALSE;
                """
            else:
                query = """
                SELECT ba.did, ba.handle, a.handle as source_account_handle, a.id as source_account_id,
                       ba.block_type, ba.is_synced, ba.reason, ba.first_seen, ba.last_seen
                FROM blocked_accounts ba
                JOIN accounts a ON ba.source_account_id = a.id
                ORDER BY ba.first_seen DESC;
                """
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all blocked accounts (unsynced_only={unsynced_only}): {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def mark_accounts_as_synced(self, dids, specific_source_account_id=None):
        """Mark multiple accounts (by DID) as synced. 
           If specific_source_account_id is provided, only marks records from that source as synced.
           Otherwise, marks all 'blocking' records for these DIDs from non-primary accounts as synced.
           This is a broad sync operation.
        """
        if not dids:
            return
            
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ", ".join(["%s"] * len(dids))
            query_base = f"UPDATE blocked_accounts SET is_synced = TRUE WHERE did IN ({placeholders}) AND block_type = 'blocking'"
            params = list(dids)

            if specific_source_account_id:
                query_base += " AND source_account_id = %s"
                params.append(specific_source_account_id)
            else:
                # If no specific source, mark as synced for all non-primary accounts that reported this block
                query_base += " AND source_account_id IN (SELECT id FROM accounts WHERE is_primary = FALSE)"
            
            cursor.execute(query_base, tuple(params))
            conn.commit()
            logger.info(f"Marked DIDs {dids} as synced (source_id: {specific_source_account_id if specific_source_account_id else 'all non-primary'}). Affected rows: {cursor.rowcount}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error marking accounts {dids} as synced: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def register_mod_list(self, list_uri, list_cid, owner_did, name):
        """Register or update a moderation list."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Check if list already exists
            cursor.execute("SELECT id FROM mod_lists WHERE list_uri = %s", (list_uri,))
            result = cursor.fetchone()
            
            if result:
                # Update existing list
                cursor.execute(
                    "UPDATE mod_lists SET list_cid = %s, owner_did=%s, name=%s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (list_cid, owner_did, name, result[0])
                )
                list_id = result[0]
            else:
                # Insert new list
                cursor.execute(
                    "INSERT INTO mod_lists (list_uri, list_cid, owner_did, name) VALUES (%s, %s, %s, %s) RETURNING id",
                    (list_uri, list_cid, owner_did, name)
                )
                list_id = cursor.fetchone()[0]
            
            conn.commit()
            return list_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error registering moderation list {list_uri}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
            
    def remove_stale_blocks(self, source_account_id, block_type, current_dids):
        """Remove blocks from the database that are no longer present in the current_dids list for a specific account and block_type."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if not current_dids: # If current_dids is empty, delete all for this source/type
                logger.debug(f"current_dids is empty for source {source_account_id}, type {block_type}. Deleting all entries.")
                cursor.execute(
                    "DELETE FROM blocked_accounts WHERE source_account_id = %s AND block_type = %s",
                    (source_account_id, block_type)
                )
            else:
                placeholders = ", ".join(["%s"] * len(current_dids))
                cursor.execute(
                    f"DELETE FROM blocked_accounts WHERE source_account_id = %s AND block_type = %s AND did NOT IN ({placeholders})",
                    [source_account_id, block_type] + current_dids # Parameters must be a list or tuple
                )
            conn.commit()
            logger.debug(f"Removed stale blocks for source_account_id {source_account_id}, block_type {block_type}. Affected rows: {cursor.rowcount}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error removing stale blocks for source_id {source_account_id}, type {block_type}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def get_last_firehose_cursor(self, account_did):
        """Get the last processed firehose cursor for an account."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("SELECT last_firehose_cursor FROM accounts WHERE did = %s", (account_did,))
            result = cursor.fetchone()
            return result['last_firehose_cursor'] if result else None
        except Exception as e:
            logger.error(f"Error getting last firehose cursor for {account_did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def save_last_firehose_cursor(self, account_did, cursor_val):
        """Save the last processed firehose cursor for an account."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE accounts SET last_firehose_cursor = %s, updated_at = CURRENT_TIMESTAMP WHERE did = %s",
                (cursor_val, account_did)
            )
            conn.commit()
            logger.debug(f"Saved last firehose cursor {cursor_val} for {account_did}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving last firehose cursor for {account_did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def get_all_dids_primary_should_list(self, primary_account_id):
        """
        Get all unique DIDs that the primary account should have on its moderation list.
        This includes:
        1. DIDs directly blocked by the primary account itself ('blocking' type).
        2. DIDs blocked by any secondary managed account ('blocking' type), 
           which are not yet marked as handled/synced by the primary for list purposes.
           Effectively, any 'blocking' record in the DB should be on the list.
        """
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # This query aims to get all unique DIDs that are currently marked as 'blocking'
            # by ANY of the managed accounts. The moderation list should reflect all such DIDs.
            query = """
            SELECT DISTINCT ba.did
            FROM blocked_accounts ba
            WHERE ba.block_type = 'blocking';
            """
            # We don't strictly need primary_account_id for this version of the query,
            # as the goal is to list *all* DIDs that *any* of our accounts are actively blocking.
            # The primary account's list should be comprehensive.
            cursor.execute(query)
            results = cursor.fetchall()
            return results # Returns a list of RealDictRow objects, e.g., [{'did': 'did:plc:...'}]
        except Exception as e:
            logger.error(f"Error getting all DIDs primary should list: {e}")
            raise
        finally:
            cursor.close()
            conn.close() 