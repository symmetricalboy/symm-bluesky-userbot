import os
import logging
import urllib.parse
import atexit
import asyncio
from typing import Dict, List, Optional, Any, Union
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# Import enhanced utilities
try:
    from utils import get_logger, async_retry, RetryConfig, get_performance_monitor
    logger = get_logger('database')
    performance_monitor = get_performance_monitor()
    use_enhanced_logging = True
except ImportError:
    # Fallback to basic logging if utils not available
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
    logger = logging.getLogger(__name__)
    performance_monitor = None
    use_enhanced_logging = False

# Global connection pool variable
connection_pool = None

async def get_connection_params():
    """Get database connection parameters, supporting both individual params and DATABASE_URL."""
    try:
        # Check if we're in local test mode
        local_test = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        
        if local_test:
            # In local test mode, use TEST_DATABASE_URL or modify database name
            test_database_url = os.getenv('TEST_DATABASE_URL')
            if test_database_url:
                logger.debug("Local test mode: Using TEST_DATABASE_URL")
                return {'dsn': test_database_url}
            else:
                # Fall back to using individual params with test database name
                DB_HOST = os.getenv('DB_HOST', 'localhost')
                DB_PORT = os.getenv('DB_PORT', '5432')
                DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
                DB_USER = os.getenv('DB_USER', 'postgres')
                DB_PASSWORD = os.getenv('DB_PASSWORD', '')
                
                # Use a separate test database
                test_db_name = f"{DB_NAME}_test"
                logger.debug(f"Local test mode: Using test database {test_db_name}")
                return {
                    'host': DB_HOST,
                    'port': int(DB_PORT),
                    'user': DB_USER,
                    'password': DB_PASSWORD,
                    'database': test_db_name
                }
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

@async_retry(RetryConfig(max_attempts=3, base_delay=2.0))
async def initialize_connection_pool():
    """Initialize the database connection pool with retry logic."""
    global connection_pool
    
    # Only initialize if not already initialized
    if connection_pool is not None:
        return
        
    connection_params = await get_connection_params()
    min_conn = int(os.getenv('DB_MIN_CONNECTIONS', '1'))
    max_conn = int(os.getenv('DB_MAX_CONNECTIONS', '10'))
    
    try:
        if performance_monitor:
            async with performance_monitor.measure('connection_pool_init'):
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
        else:
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
        
        if use_enhanced_logging:
            logger.success("Database connection pool initialized successfully")
        else:
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
        if use_enhanced_logging:
            logger.success("Database connection pool closed")

class Database:
    """Enhanced database class with comprehensive error handling and monitoring"""
    
    def __init__(self, test_mode=None):
        """Initialize the database with option for test mode.
        
        Args:
            test_mode (bool, optional): If provided, overrides the LOCAL_TEST env var.
        """
        if test_mode is None:
            self.test_mode = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        else:
            self.test_mode = test_mode
        
        if use_enhanced_logging:
            self.contextual_logger = logger.with_context(
                component='database',
                test_mode=self.test_mode
            )
        else:
            self.contextual_logger = logger
        
        self.contextual_logger.debug(f"Database initialized in {'test' if self.test_mode else 'production'} mode")
    
    async def ensure_pool(self):
        """Ensure the connection pool is initialized."""
        global connection_pool
        if connection_pool is None:
            await initialize_connection_pool()
    
    @async_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    async def test_connection(self) -> bool:
        """Test the database connection by executing a simple query."""
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_connection_test'):
                    async with connection_pool.acquire() as conn:
                        result = await conn.fetchval("SELECT 1")
                        success = result == 1
            else:
                async with connection_pool.acquire() as conn:
                    result = await conn.fetchval("SELECT 1")
                    success = result == 1
            
            if success:
                self.contextual_logger.debug("Database connection test passed")
            else:
                self.contextual_logger.error("Database connection test failed - unexpected result")
            
            return success
            
        except Exception as e:
            self.contextual_logger.error(f"Database connection test failed: {e}")
            return False
    
    @async_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    async def register_account(self, handle: str, did: str, is_primary: bool = False) -> int:
        """Register a managed account in the database."""
        contextual_logger = self.contextual_logger.with_context(
            operation='register_account',
            handle=handle,
            is_primary=is_primary
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_register_account'):
                    result = await self._execute_register_account(handle, did, is_primary, contextual_logger)
            else:
                result = await self._execute_register_account(handle, did, is_primary, contextual_logger)
            
            if use_enhanced_logging:
                contextual_logger.success(f"Account registered successfully with ID: {result}")
            else:
                contextual_logger.debug(f"Account registered successfully with ID: {result}")
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error registering account {handle}: {e}")
            raise
    
    async def _execute_register_account(self, handle: str, did: str, is_primary: bool, contextual_logger) -> int:
        """Execute the account registration logic"""
        async with connection_pool.acquire() as conn:
            async with conn.transaction():
                # Check if account already exists
                account_id = await conn.fetchval(
                    "SELECT id FROM accounts WHERE did = $1",
                    did
                )
                
                if account_id:
                    # Update existing account
                    await conn.execute(
                        "UPDATE accounts SET handle = $1, is_primary = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
                        handle, is_primary, account_id
                    )
                    contextual_logger.debug(f"Updated existing account with ID: {account_id}")
                else:
                    # Insert new account
                    account_id = await conn.fetchval(
                        "INSERT INTO accounts (handle, did, is_primary) VALUES ($1, $2, $3) RETURNING id",
                        handle, did, is_primary
                    )
                    contextual_logger.debug(f"Created new account with ID: {account_id}")
                
                return account_id
    
    async def get_account_by_did(self, did: str) -> Optional[Dict[str, Any]]:
        """Get account details by DID."""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_account_by_did',
            did=did
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_account_by_did'):
                    async with connection_pool.acquire() as conn:
                        record = await conn.fetchrow(
                            "SELECT * FROM accounts WHERE did = $1",
                            did
                        )
            else:
                async with connection_pool.acquire() as conn:
                    record = await conn.fetchrow(
                        "SELECT * FROM accounts WHERE did = $1",
                        did
                    )
            
            result = dict(record) if record else None
            if result:
                contextual_logger.debug(f"Found account: {result['handle']}")
            else:
                contextual_logger.debug("Account not found")
            
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting account {did}: {e}")
            raise
    
    async def get_primary_account(self) -> Optional[Dict[str, Any]]:
        """Get the primary account."""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_primary_account'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_primary_account'):
                    async with connection_pool.acquire() as conn:
                        record = await conn.fetchrow(
                            "SELECT * FROM accounts WHERE is_primary = TRUE LIMIT 1"
                        )
            else:
                async with connection_pool.acquire() as conn:
                    record = await conn.fetchrow(
                        "SELECT * FROM accounts WHERE is_primary = TRUE LIMIT 1"
                    )
            
            result = dict(record) if record else None
            if result:
                contextual_logger.debug(f"Found primary account: {result['handle']}")
            else:
                contextual_logger.warning("No primary account found")
            
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting primary account: {e}")
            raise
    
    async def get_secondary_accounts(self) -> List[Dict[str, Any]]:
        """Get all secondary (non-primary) accounts."""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_secondary_accounts'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_secondary_accounts'):
                    async with connection_pool.acquire() as conn:
                        records = await conn.fetch(
                            "SELECT * FROM accounts WHERE is_primary = FALSE ORDER BY id"
                        )
            else:
                async with connection_pool.acquire() as conn:
                    records = await conn.fetch(
                        "SELECT * FROM accounts WHERE is_primary = FALSE ORDER BY id"
                    )
            
            result = [dict(record) for record in records]
            contextual_logger.debug(f"Found {len(result)} secondary accounts")
            
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting secondary accounts: {e}")
            raise
    
    @async_retry(RetryConfig(max_attempts=2, base_delay=0.5))
    async def add_blocked_account(self, did: str, handle: Optional[str], source_account_id: int, 
                                block_type: str, reason: Optional[str] = None):
        """Add or update a blocked account in the database with comprehensive error handling."""
        contextual_logger = self.contextual_logger.with_context(
            operation='add_blocked_account',
            did=did,
            source_account_id=source_account_id,
            block_type=block_type
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_add_blocked_account'):
                    await self._execute_add_blocked_account(
                        did, handle, source_account_id, block_type, reason, contextual_logger
                    )
            else:
                await self._execute_add_blocked_account(
                    did, handle, source_account_id, block_type, reason, contextual_logger
                )
            
            contextual_logger.debug("Blocked account added/updated successfully")
            
        except Exception as e:
            contextual_logger.error(f"Error adding blocked account {did} for source_id {source_account_id}: {e}")
            raise
    
    async def _execute_add_blocked_account(self, did: str, handle: Optional[str], source_account_id: int,
                                         block_type: str, reason: Optional[str], contextual_logger):
        """Execute the add blocked account logic"""
        async with connection_pool.acquire() as conn:
            async with conn.transaction():
                # Get source account's primary status
                source_is_primary = await conn.fetchval(
                    "SELECT is_primary FROM accounts WHERE id = $1",
                    source_account_id
                )
                source_is_primary = source_is_primary if source_is_primary is not None else False
                
                # Check if record already exists
                existing_record = await conn.fetchrow(
                    "SELECT id, is_synced FROM blocked_accounts WHERE did = $1 AND source_account_id = $2 AND block_type = $3",
                    did, source_account_id, block_type
                )
                
                if existing_record:
                    existing_id = existing_record['id']
                    # Update existing record
                    update_query = "UPDATE blocked_accounts SET handle = $1, reason = $2, last_seen = CURRENT_TIMESTAMP"
                    params = [handle, reason, existing_id]
                    
                    # If the source is not primary, mark as unsynced for primary to re-check
                    if not source_is_primary:
                        update_query += ", is_synced = FALSE"
                        
                    update_query += " WHERE id = $3"
                    await conn.execute(update_query, *params)
                    contextual_logger.debug(f"Updated existing blocked account record ID: {existing_id}")
                else:
                    # New blocks from non-primary are unsynced by default
                    # New blocks from primary are considered synced with themselves by default
                    is_synced_for_new_block = True if source_is_primary else False
                    await conn.execute(
                        """INSERT INTO blocked_accounts 
                        (did, handle, reason, source_account_id, block_type, is_synced)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        did, handle, reason, source_account_id, block_type, is_synced_for_new_block
                    )
                    contextual_logger.debug("Created new blocked account record")
    
    async def execute_query(self, query: str, params: Optional[List[Any]] = None, commit: bool = False) -> Union[List[Dict[str, Any]], int]:
        """Execute a custom SQL query with enhanced error handling and monitoring."""
        contextual_logger = self.contextual_logger.with_context(
            operation='execute_query',
            query_type=query.split()[0].upper() if query else 'UNKNOWN'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_execute_query'):
                    result = await self._execute_custom_query(query, params, commit, contextual_logger)
            else:
                result = await self._execute_custom_query(query, params, commit, contextual_logger)
            
            if isinstance(result, list):
                contextual_logger.debug(f"Query returned {len(result)} rows")
            else:
                contextual_logger.debug(f"Query affected {result} rows")
            
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error executing query: {e}")
            raise
    
    async def _execute_custom_query(self, query: str, params: Optional[List[Any]], 
                                   commit: bool, contextual_logger) -> Union[List[Dict[str, Any]], int]:
        """Execute the custom query logic"""
        async with connection_pool.acquire() as conn:
            if commit:
                async with conn.transaction():
                    if params:
                        result = await conn.execute(query, *params)
                    else:
                        result = await conn.execute(query)
                    
                    # Return number of affected rows for non-SELECT queries
                    return int(result.split()[-1]) if result else 0
            else:
                if params:
                    records = await conn.fetch(query, *params)
                else:
                    records = await conn.fetch(query)
                
                return [dict(record) for record in records]
    
    async def initialize_default_accounts(self) -> bool:
        """Initialize default accounts from environment variables with enhanced error handling."""
        contextual_logger = self.contextual_logger.with_context(
            operation='initialize_default_accounts'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            contextual_logger.info("Initializing default accounts from environment variables")
            
            # Get primary account credentials
            primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
            primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
            
            if not primary_handle or not primary_password:
                contextual_logger.error("Primary account credentials not found in environment variables")
                return False
            
            # Initialize primary account (we'll need to get DID during login process)
            # For now, we'll create a placeholder that will be updated during agent initialization
            primary_account_id = await self.register_account(
                handle=primary_handle,
                did="placeholder_will_be_updated",
                is_primary=True
            )
            
            if use_enhanced_logging:
                contextual_logger.success(f"Primary account registered: {primary_handle}")
            else:
                contextual_logger.info(f"Primary account registered: {primary_handle}")
            
            # Initialize secondary accounts if configured
            secondary_accounts_str = os.getenv('SECONDARY_ACCOUNTS', '')
            secondary_count = 0
            
            if secondary_accounts_str:
                accounts = secondary_accounts_str.split(';')
                contextual_logger.info(f"Found {len(accounts)} secondary accounts to initialize")
                
                for account_str in accounts:
                    try:
                        if ':' in account_str:
                            handle, password = account_str.split(':', 1)
                        elif ',' in account_str:
                            handle, password = account_str.split(',', 1)
                        else:
                            contextual_logger.warning(f"Invalid account format: {account_str}")
                            continue
                        
                        handle = handle.strip()
                        password = password.strip()
                        
                        # Register secondary account (DID will be updated during login)
                        await self.register_account(
                            handle=handle,
                            did="placeholder_will_be_updated",
                            is_primary=False
                        )
                        
                        secondary_count += 1
                        if use_enhanced_logging:
                            contextual_logger.success(f"Secondary account registered: {handle}")
                        else:
                            contextual_logger.info(f"Secondary account registered: {handle}")
                        
                    except Exception as e:
                        contextual_logger.error(f"Error registering secondary account {account_str}: {e}")
                        continue
            
            total_accounts = 1 + secondary_count
            if use_enhanced_logging:
                contextual_logger.success(f"Account initialization completed. Total accounts: {total_accounts}")
            else:
                contextual_logger.info(f"Account initialization completed. Total accounts: {total_accounts}")
            
            return True
            
        except Exception as e:
            contextual_logger.error(f"Failed to initialize default accounts: {e}")
            return False
    
    async def get_account_configurations(self) -> Dict[str, Dict[str, Any]]:
        """Get all account configurations for management purposes."""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_account_configurations'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_account_configurations'):
                    async with connection_pool.acquire() as conn:
                        records = await conn.fetch(
                            "SELECT * FROM accounts ORDER BY is_primary DESC, id ASC"
                        )
            else:
                async with connection_pool.acquire() as conn:
                    records = await conn.fetch(
                        "SELECT * FROM accounts ORDER BY is_primary DESC, id ASC"
                    )
            
            accounts = [dict(record) for record in records]
            
            # Legacy format for backward compatibility
            did_to_handle = {}
            is_primary = {}
            
            for account in accounts:
                did = account['did']
                handle = account['handle'] 
                primary = account['is_primary']
                
                did_to_handle[did] = handle
                is_primary[did] = primary
            
            result = {
                'did_to_handle': did_to_handle,
                'is_primary': is_primary,
                'accounts': accounts
            }
            
            contextual_logger.debug(f"Retrieved {len(accounts)} account configurations")
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting account configurations: {e}")
            raise

    # Moderation List Management Functions
    @async_retry(RetryConfig(max_attempts=2, base_delay=0.5))
    async def register_mod_list(self, list_uri: str, list_cid: str, owner_did: str, name: str):
        """Register or update a moderation list in the database."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='register_mod_list',
            list_uri=list_uri,
            owner_did=owner_did
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_register_mod_list'):
                    await self._execute_register_mod_list(list_uri, list_cid, owner_did, name, table_suffix, contextual_logger)
            else:
                await self._execute_register_mod_list(list_uri, list_cid, owner_did, name, table_suffix, contextual_logger)
            
            contextual_logger.info(f"Moderation list registered: {list_uri}")
            
        except Exception as e:
            contextual_logger.error(f"Error registering moderation list: {e}")
            raise

    async def _execute_register_mod_list(self, list_uri: str, list_cid: str, owner_did: str, name: str, table_suffix: str, contextual_logger):
        """Execute the moderation list registration logic."""
        async with connection_pool.acquire() as conn:
            # Check if this list already exists
            existing = await conn.fetchrow(
                f"SELECT id FROM mod_lists{table_suffix} WHERE list_uri = $1",
                list_uri
            )
            
            if existing:
                # Update existing list
                await conn.execute(
                    f"""UPDATE mod_lists{table_suffix} 
                       SET list_cid = $1, name = $2, updated_at = CURRENT_TIMESTAMP 
                       WHERE list_uri = $3""",
                    list_cid, name, list_uri
                )
                contextual_logger.debug(f"Updated existing moderation list: {list_uri}")
            else:
                # Insert new list
                await conn.execute(
                    f"""INSERT INTO mod_lists{table_suffix} 
                       (list_uri, list_cid, owner_did, name) 
                       VALUES ($1, $2, $3, $4)""",
                    list_uri, list_cid, owner_did, name
                )
                contextual_logger.debug(f"Created new moderation list record: {list_uri}")

    async def get_mod_lists_by_owner(self, owner_did: str) -> List[Dict[str, Any]]:
        """Get all moderation lists owned by a specific DID."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_mod_lists_by_owner',
            owner_did=owner_did
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_mod_lists_by_owner'):
                    async with connection_pool.acquire() as conn:
                        records = await conn.fetch(
                            f"SELECT * FROM mod_lists{table_suffix} WHERE owner_did = $1 ORDER BY created_at DESC",
                            owner_did
                        )
            else:
                async with connection_pool.acquire() as conn:
                    records = await conn.fetch(
                        f"SELECT * FROM mod_lists{table_suffix} WHERE owner_did = $1 ORDER BY created_at DESC",
                        owner_did
                    )
            
            result = [dict(record) for record in records]
            contextual_logger.debug(f"Found {len(result)} moderation lists for owner {owner_did}")
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting moderation lists for owner {owner_did}: {e}")
            raise

    async def get_primary_mod_list(self) -> Optional[Dict[str, Any]]:
        """Get the primary account's moderation list."""
        try:
            primary_account = await self.get_primary_account()
            if not primary_account:
                return None
            
            mod_lists = await self.get_mod_lists_by_owner(primary_account['did'])
            return mod_lists[0] if mod_lists else None
            
        except Exception as e:
            self.contextual_logger.error(f"Error getting primary moderation list: {e}")
            return None

    async def get_all_blocked_accounts(self) -> List[Dict[str, Any]]:
        """Get all blocked accounts from the database."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_all_blocked_accounts'
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_all_blocked_accounts'):
                    async with connection_pool.acquire() as conn:
                        records = await conn.fetch(
                            f"SELECT * FROM blocked_accounts{table_suffix} ORDER BY first_seen DESC"
                        )
            else:
                async with connection_pool.acquire() as conn:
                    records = await conn.fetch(
                        f"SELECT * FROM blocked_accounts{table_suffix} ORDER BY first_seen DESC"
                    )
            
            result = [dict(record) for record in records]
            contextual_logger.debug(f"Retrieved {len(result)} blocked accounts")
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting all blocked accounts: {e}")
            raise

    async def get_all_dids_primary_should_list(self, primary_account_id: int) -> List[Dict[str, Any]]:
        """Get all DIDs that the primary account should include in its moderation list."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='get_all_dids_primary_should_list',
            primary_account_id=primary_account_id
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            if performance_monitor:
                async with performance_monitor.measure('db_get_all_dids_primary_should_list'):
                    async with connection_pool.acquire() as conn:
                        # Get all unique DIDs from blocked accounts (both blocking and blocked_by)
                        records = await conn.fetch(
                            f"SELECT DISTINCT did FROM blocked_accounts{table_suffix}"
                        )
            else:
                async with connection_pool.acquire() as conn:
                    records = await conn.fetch(
                        f"SELECT DISTINCT did FROM blocked_accounts{table_suffix}"
                    )
            
            result = [dict(record) for record in records]
            contextual_logger.debug(f"Found {len(result)} unique DIDs for primary moderation list")
            return result
            
        except Exception as e:
            contextual_logger.error(f"Error getting DIDs for primary moderation list: {e}")
            raise

    async def update_mod_list_name_description(self, list_uri: str, name: str, description: str = None):
        """Update the name and description of a moderation list (Note: This updates the database record, 
        the actual Bluesky list must be updated separately)."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='update_mod_list_name_description',
            list_uri=list_uri
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            async with connection_pool.acquire() as conn:
                await conn.execute(
                    f"""UPDATE mod_lists{table_suffix} 
                       SET name = $1, updated_at = CURRENT_TIMESTAMP 
                       WHERE list_uri = $2""",
                    name, list_uri
                )
            
            contextual_logger.info(f"Updated moderation list name to '{name}' for {list_uri}")
            
        except Exception as e:
            contextual_logger.error(f"Error updating moderation list name/description: {e}")
            raise

    async def save_last_firehose_cursor(self, did: str, cursor: int):
        """Save the last processed firehose cursor for an account."""
        table_suffix = "_test" if self.test_mode else ""
        contextual_logger = self.contextual_logger.with_context(
            operation='save_last_firehose_cursor',
            did=did,
            cursor=cursor
        ) if use_enhanced_logging else self.contextual_logger
        
        try:
            await self.ensure_pool()
            
            async with connection_pool.acquire() as conn:
                await conn.execute(
                    f"""UPDATE accounts{table_suffix} 
                       SET last_firehose_cursor = $1, updated_at = CURRENT_TIMESTAMP 
                       WHERE did = $2""",
                    cursor, did
                )
            
            contextual_logger.debug(f"Saved firehose cursor {cursor} for {did}")
            
        except Exception as e:
            contextual_logger.error(f"Error saving firehose cursor: {e}")
            raise

    async def get_last_firehose_cursor(self, did: str) -> Optional[int]:
        """Get the last processed firehose cursor for an account."""
        table_suffix = "_test" if self.test_mode else ""
        
        try:
            await self.ensure_pool()
            
            async with connection_pool.acquire() as conn:
                cursor = await conn.fetchval(
                    f"SELECT last_firehose_cursor FROM accounts{table_suffix} WHERE did = $1",
                    did
                )
            
            return cursor
            
        except Exception as e:
            self.contextual_logger.error(f"Error getting firehose cursor for {did}: {e}")
            return None

# Compatibility layer for synchronous code during transition
# These will be removed in the future when all code is async
def get_connection():
    """Get a database connection from the connection pool (compatibility function)."""
    raise NotImplementedError("Synchronous database connections are no longer supported. Use the async API instead.")

def release_connection(conn):
    """Return a connection to the pool (compatibility function)."""
    raise NotImplementedError("Synchronous database connections are no longer supported. Use the async API instead.") 