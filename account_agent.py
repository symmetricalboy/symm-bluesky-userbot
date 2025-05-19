import os
import asyncio
import logging
import httpx
from atproto import Client, FirehoseSubscribeReposClient, models
from database import Database

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

# API URLs
CLEARSKY_API_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')
BLUESKY_API_URL = os.getenv('BLUESKY_API_URL', 'https://bsky.social')

class AccountAgent:
    def __init__(self, handle, password, is_primary=False):
        self.handle = handle
        self.password = password
        self.is_primary = is_primary
        self.client = Client(base_url=BLUESKY_API_URL)
        self.database = Database()
        self.account_id = None
        self.did = None
        self.blocks_monitor_task = None
        self.firehose_monitor_task = None
        self.http_client = httpx.AsyncClient(timeout=30.0)
        
    async def login(self):
        """Login to the Bluesky account and register in the database."""
        try:
            response = self.client.login(self.handle, self.password)
            self.did = response.did
            logger.info(f"Logged in as {self.handle} (DID: {self.did})")
            
            # Register account in database
            self.account_id = self.database.register_account(
                self.handle, 
                self.did, 
                is_primary=self.is_primary
            )
            
            logger.info(f"Account {self.handle} registered with ID {self.account_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to login as {self.handle}: {e}")
            return False
    
    async def fetch_clearsky_blocks(self):
        """Fetch accounts blocking this account from ClearSky API."""
        try:
            # Try multiple ClearSky API endpoints to find one that works
            endpoints_to_try = [
                # Original endpoint
                f"{CLEARSKY_API_URL}/single-blocklist/detail/{self.did}",
                # Alternative endpoint
                f"{CLEARSKY_API_URL}/blockers/{self.did}",
                # Another possible format
                f"{CLEARSKY_API_URL}/blockers/detail/{self.did}",
                # Try with API v2 if v1 fails
                f"{CLEARSKY_API_URL.replace('/v1', '/v2')}/blockers/{self.did}",
                # Last resort - try the general blocklist API
                f"{CLEARSKY_API_URL}/lists/fun-facts"
            ]
            
            blockers = []
            success = False
            
            for endpoint in endpoints_to_try:
                logger.debug(f"Trying ClearSky endpoint: {endpoint}")
                try:
                    response = await self.http_client.get(endpoint)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extract blockers data based on the endpoint format
                    if "single-blocklist/detail" in endpoint:
                        blockers = data.get('data', {}).get('blockers', [])
                    elif "blockers/detail" in endpoint:
                        blockers = data.get('data', {}).get('blockers', [])
                    elif "blockers" in endpoint:
                        blockers = data.get('data', [])
                    elif "fun-facts" in endpoint:
                        # Extract relevant data from fun-facts endpoint
                        blocked_list = data.get('data', {}).get('blocked', [])
                        # Filter to find if our account is in the list
                        blockers = [b for b in blocked_list if b.get('did') == self.did]
                    
                    if blockers:
                        logger.info(f"Successfully fetched blockers from {endpoint}")
                        success = True
                        break
                    else:
                        logger.warning(f"No blockers found at endpoint: {endpoint}")
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch from {endpoint}: {e}")
                    continue
            
            if not success:
                logger.info(f"Could not fetch blockers for {self.handle} from any ClearSky endpoint")
                return []
                
            if not blockers:
                logger.info(f"No accounts found blocking {self.handle}")
                return []
                
            logger.info(f"Found {len(blockers)} accounts blocking {self.handle}")
            
            # Process each blocker
            for blocker in blockers:
                did = blocker.get('did')
                handle = blocker.get('handle', None)
                
                if not did:
                    continue
                    
                # If handle is not provided, try to resolve it
                if not handle:
                    handle = await self._resolve_handle(did)
                
                # Add to database
                self.database.add_blocked_account(
                    did=did,
                    handle=handle,
                    source_account_id=self.account_id,
                    block_type='blocked_by'
                )
            
            # Get all current blockers DIDs to remove stale ones
            current_blockers = [b.get('did') for b in blockers if b.get('did')]
            self.database.remove_stale_blocks(self.account_id, 'blocked_by', current_blockers)
            
            return blockers
        except Exception as e:
            logger.error(f"Error fetching ClearSky blocks for {self.handle}: {e}")
            return []
    
    async def fetch_bluesky_blocks(self):
        """Fetch accounts that this account is blocking from Bluesky API."""
        try:
            # Create a temporary list to collect all blocks
            blocking = []
            cursor = None
            
            # Paginate through all blocks
            while True:
                try:
                    # The correct way to call get_blocks - parameters need to be in the params dict
                    params = {}
                    if cursor:
                        params['cursor'] = cursor
                    
                    # Limit is also a parameter
                    params['limit'] = 100
                    
                    # Make the API call the correct way
                    response = self.client.app.bsky.graph.get_blocks(params=params)
                    
                    if not response.blocks:
                        break
                        
                    blocking.extend(response.blocks)
                    
                    if not response.cursor:
                        break
                        
                    cursor = response.cursor
                except Exception as api_error:
                    # More detailed error for debugging
                    logger.error(f"API error in get_blocks for {self.handle}: {api_error}")
                    # Try alternative approach
                    try:
                        logger.info(f"Trying alternative blocks fetch approach for {self.handle}")
                        # Some versions might expect a positional argument
                        if cursor:
                            response = self.client.app.bsky.graph.get_blocks(cursor=cursor, limit=100)
                        else:
                            response = self.client.app.bsky.graph.get_blocks(limit=100)
                            
                        if not response.blocks:
                            break
                            
                        blocking.extend(response.blocks)
                        
                        if not response.cursor:
                            break
                            
                        cursor = response.cursor
                    except Exception as alt_error:
                        logger.error(f"Alternative approach also failed: {alt_error}")
                        # No more options, break out of the loop
                        break
            
            logger.info(f"Found {len(blocking)} accounts being blocked by {self.handle}")
            
            # Process each blocked account
            for block in blocking:
                did = block.did
                handle = block.handle
                
                # Add to database
                self.database.add_blocked_account(
                    did=did,
                    handle=handle,
                    source_account_id=self.account_id,
                    block_type='blocking'
                )
            
            # Get all current blocked DIDs to remove stale ones
            current_blocked = [b.did for b in blocking]
            self.database.remove_stale_blocks(self.account_id, 'blocking', current_blocked)
            
            return blocking
        except Exception as e:
            logger.error(f"Error fetching Bluesky blocks for {self.handle}: {e}")
            return []
    
    async def _resolve_handle(self, did):
        """Resolve a DID to a handle."""
        try:
            url = f"{BLUESKY_API_URL}/xrpc/com.atproto.repo.describeRepo?repo={did}"
            response = await self.http_client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('handle', did[:15] + '...')
            
            return did[:15] + '...'
        except Exception as e:
            logger.error(f"Error resolving handle for {did}: {e}")
            return did[:15] + '...'
    
    async def sync_blocks_from_others(self):
        """If this is the primary account, sync all blocked accounts to a moderation list."""
        if not self.is_primary:
            logger.info(f"Account {self.handle} is not the primary account, skipping sync")
            return
            
        try:
            # Get all unsynced blocked accounts
            blocked_accounts = self.database.get_all_blocked_accounts(unsynced_only=True)
            
            if not blocked_accounts:
                logger.info("No new accounts to sync")
                return
                
            logger.info(f"Syncing {len(blocked_accounts)} new blocked accounts")
            
            # Get or create moderation list
            mod_list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
            mod_list_purpose = os.getenv('MOD_LIST_PURPOSE', 'Automatically synchronized blocks')
            
            try:
                # Check if we already have a list
                lists = self.client.app.bsky.graph.getLists()
                existing_list = None
                
                for lst in lists.lists:
                    if lst.name == mod_list_name:
                        existing_list = lst
                        break
                
                if existing_list:
                    list_uri = existing_list.uri
                    list_cid = None  # Will be updated after we update the list
                    logger.info(f"Using existing moderation list: {list_uri}")
                else:
                    # Create a new list
                    logger.info("Creating new moderation list")
                    purpose = models.AppBskyGraphDefs.ListPurpose.MODLIST
                    
                    create_response = self.client.app.bsky.graph.list.create(
                        purpose=purpose,
                        name=mod_list_name,
                        description=os.getenv('MOD_LIST_DESCRIPTION', 'Synchronized blocks')
                    )
                    
                    list_uri = create_response.uri
                    list_cid = create_response.cid
                    
                    logger.info(f"Created new moderation list: {list_uri}")
                    
                # Add all blocked accounts to the list
                dids_to_mark_synced = []
                chunk_size = 25  # Process in chunks to avoid rate limiting
                
                for i in range(0, len(blocked_accounts), chunk_size):
                    chunk = blocked_accounts[i:i+chunk_size]
                    
                    for account in chunk:
                        did = account['did']
                        try:
                            # Add to mute list
                            self.client.app.bsky.graph.block.create(
                                repo=self.did,
                                subject=did
                            )
                            logger.info(f"Blocked account {did}")
                            
                            dids_to_mark_synced.append(did)
                        except Exception as block_error:
                            if "duplicate" in str(block_error).lower():
                                # Already blocked, still mark as synced
                                dids_to_mark_synced.append(did)
                                logger.debug(f"Account {did} already blocked")
                            else:
                                logger.error(f"Error blocking account {did}: {block_error}")
                    
                    # Add a small delay between chunks
                    await asyncio.sleep(1)
                
                # Mark accounts as synced in the database
                if dids_to_mark_synced:
                    self.database.mark_accounts_as_synced(dids_to_mark_synced)
                    logger.info(f"Marked {len(dids_to_mark_synced)} accounts as synced")
                
                # Register/update the moderation list in the database
                self.database.register_mod_list(
                    list_uri=list_uri,
                    list_cid=list_cid or "unknown",  # CID might not be available for existing lists
                    owner_did=self.did,
                    name=mod_list_name
                )
                
                return True
            except Exception as e:
                logger.error(f"Error syncing blocks: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Error in sync_blocks_from_others: {e}")
            return False
    
    async def start_monitoring(self):
        """Start monitoring blocks for this account."""
        try:
            # Initial fetch of current blocks
            await self.fetch_clearsky_blocks()
            await self.fetch_bluesky_blocks()
            
            # Sync blocks if this is the primary account
            if self.is_primary:
                await self.sync_blocks_from_others()
                
            # Start continuous monitoring
            self.blocks_monitor_task = asyncio.create_task(self._blocks_monitor_loop())
            
            logger.info(f"Started monitoring blocks for {self.handle}")
            
        except Exception as e:
            logger.error(f"Error starting monitoring for {self.handle}: {e}")
    
    async def _blocks_monitor_loop(self):
        """Periodically check for new blocks."""
        polling_interval = int(os.getenv('POLLING_INTERVAL', '300'))  # Default: 5 minutes
        
        try:
            while True:
                logger.debug(f"Checking for new blocks for {self.handle}")
                
                await self.fetch_clearsky_blocks()
                await self.fetch_bluesky_blocks()
                
                # Sync blocks if this is the primary account
                if self.is_primary:
                    await self.sync_blocks_from_others()
                
                # Wait for the next check
                await asyncio.sleep(polling_interval)
                
        except asyncio.CancelledError:
            logger.info(f"Block monitoring for {self.handle} was cancelled")
        except Exception as e:
            logger.error(f"Error in blocks monitor loop for {self.handle}: {e}")
            
            # Restart the loop
            await asyncio.sleep(10)  # Wait a bit before restarting
            asyncio.create_task(self._blocks_monitor_loop())
    
    async def stop_monitoring(self):
        """Stop all monitoring tasks."""
        try:
            if self.blocks_monitor_task:
                self.blocks_monitor_task.cancel()
                try:
                    await self.blocks_monitor_task
                except asyncio.CancelledError:
                    pass
                
            logger.info(f"Stopped monitoring blocks for {self.handle}")
            
        except Exception as e:
            logger.error(f"Error stopping monitoring for {self.handle}: {e}")
            
        await self.http_client.aclose() 