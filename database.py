import os
import logging
import urllib.parse
import atexit
import asyncio
from typing import Dict, List, Optional, Any, Union
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

# Global connection pool variable
connection_pool = None

async def get_connection_params():
    """Get database connection parameters, supporting both individual params and DATABASE_URL."""
    try:
        # Check if we're in local test mode
        local_test = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        
        if local_test:
            # In local test mode, use TEST_DATABASE_URL
            test_database_url = os.getenv('TEST_DATABASE_URL')
            if test_database_url:
                logger.debug("Local test mode: Using TEST_DATABASE_URL")
                return {'dsn': test_database_url}
            else:
                logger.error("Local test mode enabled but TEST_DATABASE_URL not found")
                raise ValueError("LOCAL_TEST=True but TEST_DATABASE_URL not set")
        else:
            # In production mode, check DATABASE_URL first (for backwards compatibility)
            database_url = os.getenv('DATABASE_URL')
            
            if database_url:
                logger.debug("Production mode: Using DATABASE_URL")
                return {'dsn': database_url}
            else:
                # Fall back to individual connection parameters
                DB_HOST = os.getenv('DB_HOST', 'localhost')
                DB_PORT = os.getenv('DB_PORT', '5432')
                DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
                DB_USER = os.getenv('DB_USER', 'postgres')
                DB_PASSWORD = os.getenv('DB_PASSWORD', '')
                
                logger.debug(f"Production mode: Using connection pool with {DB_HOST}:{DB_PORT}/{DB_NAME}")
                return {
                    'host': DB_HOST,
                    'port': int(DB_PORT),
                    'user': DB_USER,
                    'password': DB_PASSWORD,
                    'database': DB_NAME
                }
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

async def initialize_connection_pool():
    """Initialize the database connection pool."""
    global connection_pool
    
    # Only initialize if not already initialized
    if connection_pool is not None:
        return
        
    connection_params = await get_connection_params()
    min_conn = int(os.getenv('DB_MIN_CONNECTIONS', '1'))
    max_conn = int(os.getenv('DB_MAX_CONNECTIONS', '10'))
    
    try:
        if 'dsn' in connection_params:
            connection_pool = await asyncpg.create_pool(
                connection_params['dsn'],
                min_size=min_conn,
                max_size=max_conn
            )
        else:
            connection_pool = await asyncpg.create_pool(
                min_size=min_conn,
                max_size=max_conn,
                **connection_params
            )
        logger.debug("Database connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to create connection pool: {e}")
        raise
        
async def close_connection_pool():
    """Close the database connection pool."""
    global connection_pool
    if connection_pool is not None:
        logger.debug("Closing database connection pool")
        await connection_pool.close()
        connection_pool = None

# Register the close_connection_pool function to run at exit
# Note: For asyncio, we need a different approach than atexit
# We'll handle this in main.py instead

# We'll initialize the pool when it's needed, not at import time

class Database:
    def __init__(self, test_mode=None):
        """Initialize the database with option for test mode.
        
        Args:
            test_mode (bool, optional): If provided, overrides the LOCAL_TEST env var.
        """
        if test_mode is None:
            self.test_mode = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        else:
            self.test_mode = test_mode
            
        self.table_suffix = "_test" if self.test_mode else ""
        logger.debug(f"Database initialized in {'test' if self.test_mode else 'production'} mode with table suffix '{self.table_suffix}'")
    
    async def ensure_pool(self):
        """Ensure the connection pool is initialized."""
        global connection_pool
        if connection_pool is None:
            await initialize_connection_pool()
    
    async def test_connection(self) -> bool:
        """Test the database connection by executing a simple query."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    async def register_account(self, handle: str, did: str, is_primary: bool = False) -> int:
        """Register a managed account in the database."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Check if account already exists
                    account_id = await conn.fetchval(
                        f"SELECT id FROM accounts{self.table_suffix} WHERE did = $1",
                        did
                    )
                    
                    if account_id:
                        # Update existing account
                        await conn.execute(
                            f"UPDATE accounts{self.table_suffix} SET handle = $1, is_primary = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
                            handle, is_primary, account_id
                        )
                    else:
                        # Insert new account
                        account_id = await conn.fetchval(
                            f"INSERT INTO accounts{self.table_suffix} (handle, did, is_primary) VALUES ($1, $2, $3) RETURNING id",
                            handle, did, is_primary
                        )
                    
                    return account_id
        except Exception as e:
            logger.error(f"Error registering account {handle}: {e}")
            raise
    
    async def get_account_by_did(self, did: str) -> Optional[Dict[str, Any]]:
        """Get account details by DID."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                record = await conn.fetchrow(
                    f"SELECT * FROM accounts{self.table_suffix} WHERE did = $1",
                    did
                )
                return dict(record) if record else None
        except Exception as e:
            logger.error(f"Error getting account {did}: {e}")
            raise
    
    async def get_primary_account(self) -> Optional[Dict[str, Any]]:
        """Get the primary account."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                record = await conn.fetchrow(
                    f"SELECT * FROM accounts{self.table_suffix} WHERE is_primary = TRUE LIMIT 1"
                )
                return dict(record) if record else None
        except Exception as e:
            logger.error(f"Error getting primary account: {e}")
            raise
    
    async def get_secondary_accounts(self) -> List[Dict[str, Any]]:
        """Get all secondary (non-primary) accounts."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                records = await conn.fetch(
                    f"SELECT * FROM accounts{self.table_suffix} WHERE is_primary = FALSE ORDER BY id"
                )
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error getting secondary accounts: {e}")
            raise
    
    async def add_blocked_account(self, did: str, handle: Optional[str], source_account_id: int, block_type: str, reason: Optional[str] = None):
        """Add or update a blocked account in the database. Reset is_synced to FALSE on update if it's a non-primary block."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Get source account's primary status
                    source_is_primary = await conn.fetchval(
                        f"SELECT is_primary FROM accounts{self.table_suffix} WHERE id = $1",
                        source_account_id
                    )
                    source_is_primary = source_is_primary if source_is_primary is not None else False
                    
                    # Check if record already exists
                    existing_record = await conn.fetchrow(
                        f"SELECT id, is_synced FROM blocked_accounts{self.table_suffix} WHERE did = $1 AND source_account_id = $2 AND block_type = $3",
                        did, source_account_id, block_type
                    )
                    
                    if existing_record:
                        existing_id = existing_record['id']
                        # Update existing record
                        update_query = f"UPDATE blocked_accounts{self.table_suffix} SET handle = $1, reason = $2, last_seen = CURRENT_TIMESTAMP"
                        params = [handle, reason, existing_id]
                        
                        # If the source is not primary, mark as unsynced for primary to re-check
                        if not source_is_primary:
                            update_query += ", is_synced = FALSE"
                            
                        update_query += " WHERE id = $3"
                        await conn.execute(update_query, *params)
                    else:
                        # New blocks from non-primary are unsynced by default
                        # New blocks from primary are considered synced with themselves by default
                        is_synced_for_new_block = True if source_is_primary else False
                        await conn.execute(
                            f"""INSERT INTO blocked_accounts{self.table_suffix} 
                            (did, handle, reason, source_account_id, block_type, is_synced)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            did, handle, reason, source_account_id, block_type, is_synced_for_new_block
                        )
        except Exception as e:
            logger.error(f"Error adding blocked account {did} for source_id {source_account_id}: {e}")
            raise
    
    async def get_unsynced_blocks_for_primary(self, primary_account_id: int) -> List[Dict[str, Any]]:
        """Get DIDs that were blocked by other managed accounts and need to be synced by the primary account."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                # First, log how many total block entries we have for debugging
                total_blocks = await conn.fetchval(
                    f"SELECT COUNT(*) as total_blocks FROM blocked_accounts{self.table_suffix} WHERE block_type = 'blocking'"
                )
                logger.info(f"DB_SYNC: Found {total_blocks} total 'blocking' entries in the database")
                
                # Log raw data from blocked_accounts table for debugging
                logger.info(f"DB_SYNC: Fetching detailed block data for debugging...")
                detailed_blocks = await conn.fetch(
                    f"SELECT * FROM blocked_accounts{self.table_suffix} WHERE block_type = 'blocking' LIMIT 20"
                )
                for block in detailed_blocks:
                    block_dict = dict(block)
                    logger.info(f"DB_SYNC: Block record - DID: {block_dict.get('did', 'unknown')}, " 
                              f"Account ID: {block_dict.get('source_account_id', 'unknown')}, "
                              f"is_synced: {block_dict.get('is_synced', 'unknown')}, "
                              f"First seen: {block_dict.get('first_seen', 'unknown')}")
                
                # Log how many blocks are from non-primary accounts
                secondary_blocks = await conn.fetchval(f"""
                    SELECT COUNT(*) as secondary_blocks 
                    FROM blocked_accounts{self.table_suffix} ba
                    JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
                    WHERE a.is_primary = FALSE AND ba.block_type = 'blocking'
                """)
                logger.info(f"DB_SYNC: Found {secondary_blocks} 'blocking' entries from secondary accounts")
                
                # Log how many unsynced blocks we have
                unsynced_blocks = await conn.fetchval(f"""
                    SELECT COUNT(*) as unsynced_blocks 
                    FROM blocked_accounts{self.table_suffix} ba
                    JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
                    WHERE a.is_primary = FALSE AND ba.block_type = 'blocking' AND ba.is_synced = FALSE
                """)
                logger.info(f"DB_SYNC: Found {unsynced_blocks} unsynced 'blocking' entries from secondary accounts")
                
                # Now get the actual blocks that need to be synced
                blocks_to_sync = await conn.fetch(f"""
                    SELECT 
                        ba.did, 
                        ba.handle, 
                        ba.reason, 
                        ba.id as original_block_id,
                        a.handle as source_account_handle,
                        EXISTS (
                            SELECT 1 FROM blocked_accounts{self.table_suffix} 
                            WHERE did = ba.did 
                            AND source_account_id = $1 
                            AND block_type = 'blocking'
                        ) as already_blocked_by_primary
                    FROM blocked_accounts{self.table_suffix} ba
                    JOIN accounts{self.table_suffix} a ON ba.source_account_id = a.id
                    WHERE a.is_primary = FALSE 
                    AND ba.block_type = 'blocking'
                    AND ba.is_synced = FALSE
                    ORDER BY ba.first_seen ASC
                    LIMIT 100  -- Process in batches to avoid overwhelming the primary account
                """, primary_account_id)
                
                logger.info(f"DB_SYNC: Returning {len(blocks_to_sync)} blocks to be synced by primary account")
                return [dict(block) for block in blocks_to_sync]
        except Exception as e:
            logger.error(f"Error getting unsynced blocks for primary: {e}")
            raise
    
    async def mark_block_as_synced_by_primary(self, original_block_db_id: int, primary_account_id: int) -> bool:
        """Mark a block as synced by the primary account."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                await conn.execute(
                    f"UPDATE blocked_accounts{self.table_suffix} SET is_synced = TRUE WHERE id = $1",
                    original_block_db_id
                )
                logger.info(f"DB_SYNC: Marked block ID {original_block_db_id} as synced by primary account ID {primary_account_id}")
                return True
        except Exception as e:
            logger.error(f"Error marking block as synced: {e}")
            raise
    
    async def get_all_blocked_accounts(self, unsynced_only: bool = False) -> List[Dict[str, Any]]:
        """Get all blocked accounts."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
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
                    
                records = await conn.fetch(query)
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error getting all blocked accounts: {e}")
            raise
    
    async def mark_accounts_as_synced(self, dids: List[str], specific_source_account_id: Optional[int] = None):
        """Mark accounts as synced in the database."""
        if not dids:
            return
            
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                if specific_source_account_id:
                    # Mark specific accounts as synced from a specific source account
                    # This is used when a secondary account tells us which accounts it's blocking
                    query = f"""
                        UPDATE blocked_accounts{self.table_suffix}
                        SET is_synced = TRUE
                        WHERE did = ANY($1::text[])
                        AND source_account_id = $2
                    """
                    await conn.execute(query, dids, specific_source_account_id)
                else:
                    # Mark accounts as synced for all source accounts
                    # This is used when the primary account has synced blocks from secondary accounts
                    query = f"""
                        UPDATE blocked_accounts{self.table_suffix}
                        SET is_synced = TRUE
                        WHERE did = ANY($1::text[])
                    """
                    await conn.execute(query, dids)
                
                # Get the number of rows affected
                rowcount = await conn.execute(f"""
                    SELECT COUNT(*) FROM blocked_accounts{self.table_suffix}
                    WHERE did = ANY($1::text[])
                    AND is_synced = TRUE
                """, dids)
                logger.info(f"Marked {rowcount} blocked accounts as synced")
        except Exception as e:
            logger.error(f"Error marking accounts as synced: {e}")
            raise
    
    async def register_mod_list(self, list_uri: str, list_cid: str, owner_did: str, name: str) -> int:
        """Register a moderation list in the database."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Check if mod list already exists
                    list_id = await conn.fetchval(
                        f"SELECT id FROM mod_lists{self.table_suffix} WHERE list_uri = $1",
                        list_uri
                    )
                    
                    if list_id:
                        # Update existing mod list
                        await conn.execute(
                            f"UPDATE mod_lists{self.table_suffix} SET list_cid = $1, owner_did = $2, name = $3, updated_at = CURRENT_TIMESTAMP WHERE id = $4",
                            list_cid, owner_did, name, list_id
                        )
                    else:
                        # Insert new mod list
                        list_id = await conn.fetchval(
                            f"INSERT INTO mod_lists{self.table_suffix} (list_uri, list_cid, owner_did, name) VALUES ($1, $2, $3, $4) RETURNING id",
                            list_uri, list_cid, owner_did, name
                        )
                    
                    return list_id
        except Exception as e:
            logger.error(f"Error registering mod list {list_uri}: {e}")
            raise
    
    async def remove_stale_blocks(self, source_account_id: int, block_type: str, current_dids: List[str]):
        """Remove blocks that are no longer valid."""
        if not current_dids:
            logger.warning(f"No current DIDs provided for account ID {source_account_id} and block type {block_type}")
            return
            
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                # Delete blocks that are not in the current list
                deleted_count = await conn.execute(
                    f"""
                    DELETE FROM blocked_accounts{self.table_suffix}
                    WHERE source_account_id = $1
                    AND block_type = $2
                    AND did != ALL($3::text[])
                    """,
                    source_account_id, block_type, current_dids
                )
                
                logger.info(f"Removed {deleted_count} stale blocks for account ID {source_account_id} with block type {block_type}")
        except Exception as e:
            logger.error(f"Error removing stale blocks for account ID {source_account_id}: {e}")
            raise
    
    async def get_last_firehose_cursor(self, account_did: str) -> Optional[int]:
        """Get the last firehose cursor for an account."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                cursor_val = await conn.fetchval(
                    f"SELECT last_firehose_cursor FROM accounts{self.table_suffix} WHERE did = $1",
                    account_did
                )
                return cursor_val
        except Exception as e:
            logger.error(f"Error getting last firehose cursor for {account_did}: {e}")
            raise
    
    async def save_last_firehose_cursor(self, account_did: str, cursor_val: int):
        """Save the last firehose cursor for an account."""
        if not cursor_val:
            logger.warning(f"Attempted to save null cursor value for {account_did}")
            return
            
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                await conn.execute(
                    f"UPDATE accounts{self.table_suffix} SET last_firehose_cursor = $1 WHERE did = $2",
                    cursor_val, account_did
                )
                logger.debug(f"Saved firehose cursor {cursor_val} for account {account_did}")
        except Exception as e:
            logger.error(f"Error saving firehose cursor for {account_did}: {e}")
            raise
    
    async def get_all_dids_primary_should_list(self, primary_account_id: int) -> List[Dict[str, str]]:
        """Get all DIDs that the primary account should include in its mod list."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                # Get all unique DIDs from both blocking and blocked_by types from all accounts
                query = f"""
                SELECT DISTINCT did FROM blocked_accounts{self.table_suffix}
                WHERE 
                    -- We want all blocks made by all accounts (primary and non-primary)
                    (block_type = 'blocking')
                    
                    -- We also want accounts that are blocking any of our accounts
                    OR (block_type = 'blocked_by')
                """
                
                records = await conn.fetch(query)
                dids = [{'did': record['did']} for record in records]
                
                logger.info(f"Found {len(dids)} total unique DIDs that primary should include in mod list")
                
                return dids
        except Exception as e:
            logger.error(f"Error getting DIDs for primary mod list: {e}")
            raise
    
    async def get_mod_lists_by_owner(self, owner_did: str) -> List[Dict[str, Any]]:
        """Get moderation lists by owner DID."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
                records = await conn.fetch(
                    f"SELECT * FROM mod_lists{self.table_suffix} WHERE owner_did = $1",
                    owner_did
                )
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error getting mod lists for owner {owner_did}: {e}")
            raise
    
    async def execute_query(self, query: str, params: Optional[List[Any]] = None, commit: bool = False) -> Union[List[Dict[str, Any]], int]:
        """Execute a custom query and return results."""
        try:
            await self.ensure_pool()
            async with connection_pool.acquire() as conn:
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
                
                if commit:
                    result = await conn.execute(query, *(params or []))
                    return result
                else:
                    records = await conn.fetch(query, *(params or []))
                    return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise

# Compatibility layer for synchronous code during transition
# This allows existing code to work without immediate refactoring
# These will be removed in the future when all code is async
def get_connection():
    """Get a database connection from the connection pool (compatibility function)."""
    raise NotImplementedError("Synchronous database connections are no longer supported. Use the async API instead.")

def release_connection(conn):
    """Return a connection to the pool (compatibility function)."""
    raise NotImplementedError("Synchronous database connections are no longer supported. Use the async API instead.")  