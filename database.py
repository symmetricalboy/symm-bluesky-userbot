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
    def register_account(self, handle, did, is_primary=False):
        """Register a managed account in the database."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Check if account already exists
            cursor.execute("SELECT id FROM accounts WHERE did = %s", (did,))
            result = cursor.fetchone()
            
            if result:
                # Update existing account
                account_id = result[0]
                cursor.execute(
                    "UPDATE accounts SET handle = %s, is_primary = %s WHERE id = %s",
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
        conn = get_connection()
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
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("SELECT * FROM accounts WHERE is_primary = TRUE")
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting primary account: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def add_blocked_account(self, did, handle, source_account_id, block_type, reason=None):
        """Add a blocked account to the database."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Check if record already exists
            cursor.execute(
                "SELECT id FROM blocked_accounts WHERE did = %s AND source_account_id = %s AND block_type = %s",
                (did, source_account_id, block_type)
            )
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                cursor.execute(
                    "UPDATE blocked_accounts SET handle = %s, reason = %s, last_seen = CURRENT_TIMESTAMP WHERE id = %s",
                    (handle, reason, result[0])
                )
            else:
                # Insert new record
                cursor.execute(
                    """
                    INSERT INTO blocked_accounts 
                    (did, handle, reason, source_account_id, block_type)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (did, handle, reason, source_account_id, block_type)
                )
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error adding blocked account {did}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def get_all_blocked_accounts(self, unsynced_only=False):
        """Get all blocked accounts from all sources."""
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = """
            SELECT DISTINCT did, handle 
            FROM blocked_accounts
            """
            
            if unsynced_only:
                query += " WHERE is_synced = FALSE"
                
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting blocked accounts: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def mark_accounts_as_synced(self, dids):
        """Mark multiple accounts as synced."""
        if not dids:
            return
            
        conn = get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ", ".join(["%s"] * len(dids))
            cursor.execute(
                f"UPDATE blocked_accounts SET is_synced = TRUE WHERE did IN ({placeholders})",
                dids
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error marking accounts as synced: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def register_mod_list(self, list_uri, list_cid, owner_did, name):
        """Register or update a moderation list."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Check if list already exists
            cursor.execute("SELECT id FROM mod_lists WHERE list_uri = %s", (list_uri,))
            result = cursor.fetchone()
            
            if result:
                # Update existing list
                cursor.execute(
                    "UPDATE mod_lists SET list_cid = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (list_cid, result[0])
                )
                list_id = result[0]
            else:
                # Insert new list
                cursor.execute(
                    """
                    INSERT INTO mod_lists (list_uri, list_cid, owner_did, name)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
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
        """Remove blocks that are no longer valid for an account."""
        if not current_dids:
            current_dids = []
            
        conn = get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ", ".join(["%s"] * len(current_dids)) if current_dids else "NULL"
            
            if current_dids:
                cursor.execute(
                    f"""
                    DELETE FROM blocked_accounts 
                    WHERE source_account_id = %s 
                    AND block_type = %s 
                    AND did NOT IN ({placeholders})
                    """,
                    [source_account_id, block_type] + current_dids
                )
            else:
                cursor.execute(
                    """
                    DELETE FROM blocked_accounts 
                    WHERE source_account_id = %s 
                    AND block_type = %s
                    """,
                    (source_account_id, block_type)
                )
                
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error removing stale blocks: {e}")
            raise
        finally:
            cursor.close()
            conn.close() 