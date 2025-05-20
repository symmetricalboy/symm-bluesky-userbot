import os
import asyncio
import logging
import httpx
from atproto import Client, FirehoseSubscribeReposClient, models
from database import Database
import time # Added for rate limiting delay
import psycopg2
import psycopg2.extras

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

# Reduce verbosity of httpx library logger
logging.getLogger("httpx").setLevel(logging.WARNING)

# API URLs
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')
BLUESKY_API_URL = os.getenv('BLUESKY_API_URL', 'https://bsky.social')

# ClearSky Rate Limiting
CLEARSKY_REQUEST_DELAY = 0.25 # 4 requests per second, just under 5 req/sec limit

class AccountAgent:
    def __init__(self, handle, password, is_primary=False, database=None):
        self.handle = handle
        self.password = password
        self.is_primary = is_primary
        self.client = Client(base_url=BLUESKY_API_URL)
        self.database = database if database else Database()
        self.account_id = None
        self.did = None
        self.blocks_monitor_task = None
        self.firehose_monitor_task = None
        # Increased timeout for HTTP client and enable redirect following
        self.http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        self.mod_list_uri = None
    
    async def initialize(self):
        """Initialize the account agent by logging in and registering in the database."""
        return await self.login()
        
    async def login(self):
        """Login to the Bluesky account and register in the database."""
        try:
            # Attempt to login with longer timeout for the initial connection
            async with httpx.AsyncClient(timeout=60.0) as temp_client:
                # The login method of atproto.Client is synchronous,
                # but if it involves network calls that can be configured,
                # those would be an issue. For now, assume atproto.Client handles its own timeouts.
                # However, the error might be in initial DID resolution or server handshake
                # which might not be directly using self.client's http_client yet.
                # For now, let's assume the library handles its own login timeouts.
                pass # Placeholder if we need to adjust client settings before login

            logger.info(f"Attempting login for {self.handle}...")
            response = self.client.login(self.handle, self.password)
            self.did = response.did
            logger.info(f"Logged in as {self.handle} (DID: {self.did})")
            
            self.account_id = self.database.register_account(
                self.handle, 
                self.did, 
                is_primary=self.is_primary
            )
            
            logger.info(f"Account {self.handle} registered with ID {self.account_id}")
            
            # If this is primary account, create the moderation list
            if self.is_primary:
                try:
                    await self.create_or_update_moderation_list()
                except Exception as e:
                    logger.error(f"Error creating/updating moderation list for {self.handle}: {e}")
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to login as {self.handle}: {e}")
            if "Unexpected server response" in str(e) or "Handshake failed" in str(e):
                logger.error("This might be a network issue or Bluesky server problem. Check connection and server status.")
            return False
    
    async def create_or_update_moderation_list(self):
        """Create or update a moderation list for the primary account."""
        if not self.is_primary:
            logger.debug(f"Account {self.handle} is not primary, skipping moderation list creation.")
            return None
        
        list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
        list_purpose = os.getenv('MOD_LIST_PURPOSE', 'Automatically synchronized blocks across multiple accounts')
        list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by or blocking any of our managed accounts')
        
        try:
            logger.info(f"Creating or updating moderation list for primary account {self.handle}...")
            
            # Create the moderation list record as a direct dictionary
            # This is correct - we should NOT use models.AppBskyGraphList as a constructor
            list_record = {
                "$type": "app.bsky.graph.list",
                "purpose": "app.bsky.graph.defs#modlist",
                "name": list_name,
                "description": list_description,
                "createdAt": self.client.get_current_time_iso()
            }
            
            # First try to get existing lists to see if we already have one
            try:
                lists_response = self.client.app.bsky.graph.get_lists(params={"actor": self.did})
                existing_lists = lists_response.lists
                existing_list = None
                
                for lst in existing_lists:
                    if lst.name == list_name and lst.purpose == "app.bsky.graph.defs#modlist":
                        existing_list = lst
                        logger.info(f"Found existing moderation list: {lst.uri}")
                        break
            except Exception as e:
                logger.warning(f"Could not fetch existing lists: {e}")
                existing_list = None
            
            if existing_list:
                # Update existing list
                response = self.client.com.atproto.repo.put_record(
                    data={
                        "repo": self.did,
                        "collection": "app.bsky.graph.list",
                        "rkey": existing_list.uri.split('/')[-1],
                        "record": list_record
                    }
                )
                list_uri = existing_list.uri
                list_cid = response.cid
                logger.info(f"Updated existing moderation list: {list_uri}")
            else:
                # Create new list
                response = self.client.com.atproto.repo.create_record(
                    data={
                        "repo": self.did,
                        "collection": "app.bsky.graph.list",
                        "record": list_record
                    }
                )
                list_uri = response.uri
                list_cid = response.cid
                logger.info(f"Created new moderation list: {list_uri}")
            
            # Store the list URI for later reference
            self.mod_list_uri = list_uri
            
            # Register the list in our database
            self.database.register_mod_list(
                list_uri=list_uri,
                list_cid=list_cid,
                owner_did=self.did,
                name=list_name
            )
            
            logger.info(f"Moderation list registered: {list_uri}")
            return list_uri
            
        except Exception as e:
            logger.error(f"Error creating/updating moderation list for {self.handle}: {e}")
            return None
    
    async def _fetch_paginated_clearsky_list(self, endpoint_template: str):
        """Helper to fetch all DIDs from a paginated ClearSky endpoint."""
        all_dids = []
        page = 1
        while True:
            await asyncio.sleep(CLEARSKY_REQUEST_DELAY) # Rate limit before each request
            # Ensure the DID is correctly inserted into the URL template
            formatted_endpoint = endpoint_template.replace("{did}", self.did)
            url = f"{CLEARSKY_API_BASE_URL}{formatted_endpoint}/{page}"
            logger.debug(f"Fetching from ClearSky: {url}")
            try:
                response = await self.http_client.get(url)
                if response.status_code == 404:
                    logger.debug(f"Page {page} not found for {url}, assuming end of list.")
                    break 
                response.raise_for_status()
                data = response.json()
                
                current_page_dids = []
                
                # Handle both single-blocklist and blocklist endpoints
                if endpoint_template.startswith("/single-blocklist"):
                    # Who is blocking this account
                    blocklist = data.get('data', {}).get('blocklist', [])
                    if blocklist is None:
                        logger.debug(f"No DIDs found on single-blocklist endpoint for {url}")
                        break
                    current_page_dids = [item['did'] for item in blocklist]
                elif endpoint_template.startswith("/blocklist"): 
                    # Who this account is blocking
                    blocklist = data.get('data', {}).get('blocklist', [])
                    if blocklist is None:
                        logger.debug(f"No DIDs found on blocklist endpoint for {url}")
                        break
                    current_page_dids = [item['did'] for item in blocklist]
                else:
                    logger.warning(f"Unknown endpoint template structure for pagination: {endpoint_template}")
                    break

                if not current_page_dids:
                    logger.debug(f"No DIDs found on page {page} for {url}, assuming end of list.")
                    break
                
                all_dids.extend(current_page_dids)
                
                if len(current_page_dids) < 100:
                    logger.debug(f"Fetched {len(current_page_dids)} DIDs, assuming last page for {url}.")
                    break
                
                page += 1
                if page > 500: 
                    logger.warning(f"Reached 500 pages for {url}, stopping pagination.")
                    break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404: 
                    logger.debug(f"Reached end of list (404) for {url} on page {page}.")
                elif e.response.status_code == 429:
                    logger.warning(f"Rate limited by ClearSky for {url}.")
                else:
                    logger.error(f"HTTP error fetching {url}: {e}")
                break 
            except Exception as e:
                logger.error(f"Error fetching or parsing {url}: {e}")
                break 
        return all_dids

    async def fetch_who_is_blocking_me_from_clearsky(self):
        """Fetch DIDs of accounts blocking this account from ClearSky API."""
        logger.info(f"Fetching who is blocking {self.handle} from ClearSky...")
        # Use the correct endpoint /single-blocklist/{did} instead of /blockedby/{did}
        blocking_me_dids = await self._fetch_paginated_clearsky_list("/single-blocklist/{did}")
        
        if blocking_me_dids:
            logger.info(f"Found {len(blocking_me_dids)} accounts blocking {self.handle} via ClearSky.")
            valid_dids_found = []
            for did_blocker in blocking_me_dids:
                if not isinstance(did_blocker, str) or not did_blocker.startswith("did:"):
                    logger.warning(f"Skipping invalid DID received from ClearSky /single-blocklist: {did_blocker}")
                    continue
                valid_dids_found.append(did_blocker)
                handle_blocker = await self._resolve_handle(did_blocker)
                self.database.add_blocked_account(
                    did=did_blocker,
                    handle=handle_blocker,
                    source_account_id=self.account_id,
                    block_type='blocked_by'
                )
            self.database.remove_stale_blocks(self.account_id, 'blocked_by', valid_dids_found)
        else:
            logger.info(f"No accounts found blocking {self.handle} via ClearSky /single-blocklist endpoint.")
            await asyncio.sleep(CLEARSKY_REQUEST_DELAY * 2) 
            try:
                fun_facts_url = f"{CLEARSKY_API_BASE_URL}/lists/fun-facts"
                logger.debug(f"Trying fallback API: {fun_facts_url}")
                # Check if self.http_client is closed
                if self.http_client.is_closed:
                    self.http_client = httpx.AsyncClient(timeout=60.0) # Reinitialize if closed

                response = await self.http_client.get(fun_facts_url)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Fun-facts API contacted as fallback, but its data cannot determine who blocks {self.handle}.")
                self.database.remove_stale_blocks(self.account_id, 'blocked_by', [])

            except Exception as fun_facts_error:
                logger.warning(f"Fun-facts API fallback also failed for {self.handle}: {fun_facts_error}")
                self.database.remove_stale_blocks(self.account_id, 'blocked_by', [])

        return blocking_me_dids

    async def fetch_who_i_am_blocking_from_clearsky(self):
        """Fetch DIDs of accounts this account is blocking via ClearSky API blocklist."""
        logger.info(f"Fetching who {self.handle} is blocking from ClearSky...")
        i_am_blocking_dids = await self._fetch_paginated_clearsky_list("/blocklist/{did}")

        if i_am_blocking_dids:
            logger.info(f"Found {len(i_am_blocking_dids)} accounts {self.handle} is blocking via ClearSky.")
            valid_dids_found = []
            for did_blocked in i_am_blocking_dids:
                if not isinstance(did_blocked, str) or not did_blocked.startswith("did:"):
                    logger.warning(f"Skipping invalid DID received from ClearSky /blocklist: {did_blocked}")
                    continue
                valid_dids_found.append(did_blocked)
                handle_blocked = await self._resolve_handle(did_blocked)
                self.database.add_blocked_account(
                    did=did_blocked,
                    handle=handle_blocked, 
                    source_account_id=self.account_id,
                    block_type='blocking' 
                )
            self.database.remove_stale_blocks(self.account_id, 'blocking', valid_dids_found)
        else:
            logger.info(f"No accounts found that {self.handle} is blocking via ClearSky /blocklist endpoint.")
            self.database.remove_stale_blocks(self.account_id, 'blocking', [])
            
        return i_am_blocking_dids
    
    async def fetch_bluesky_blocks(self):
        """Fetch accounts that this account is blocking from Bluesky API."""
        try:
            blocking = []
            cursor = None
            while True:
                try:
                    # Create params dictionary correctly
                    params = {'limit': 100}
                    if cursor:
                        params['cursor'] = cursor
                    
                    # Correct way to call get_blocks - params dict is passed to params parameter
                    response = self.client.app.bsky.graph.get_blocks(params=params)
                    
                    if not response.blocks:
                        break
                    blocking.extend(response.blocks)
                    if not response.cursor:
                        break
                    cursor = response.cursor
                except Exception as api_error:
                    logger.error(f"API error in get_blocks for {self.handle}: {api_error}. Trying alternative.")
                    # Alternative attempt with different API approach
                    try:
                        # Try a different approach without specifying actor
                        response = self.client.app.bsky.graph.get_blocks(limit=100, cursor=cursor)

                        if not response.blocks: break
                        blocking.extend(response.blocks)
                        if not response.cursor: break
                        cursor = response.cursor
                    except Exception as alt_error:
                        logger.error(f"Alternative get_blocks approach also failed for {self.handle}: {alt_error}")
                        break
            
            logger.info(f"Found {len(blocking)} accounts being blocked by {self.handle} via Bluesky API.")
            
            processed_dids = []
            for block_record in blocking: # Iterate over BlockView objects
                did = block_record.did
                handle = block_record.handle # BlockView has .did and .handle
                processed_dids.append(did)
                
                self.database.add_blocked_account(
                    did=did,
                    handle=handle,
                    source_account_id=self.account_id,
                    block_type='blocking'
                )
            
            self.database.remove_stale_blocks(self.account_id, 'blocking', processed_dids)
            return blocking
        except Exception as e:
            logger.error(f"Error fetching Bluesky blocks for {self.handle}: {e}")
            return []
    
    async def _resolve_handle(self, did):
        """Resolve a DID to a handle."""
        await asyncio.sleep(CLEARSKY_REQUEST_DELAY / 2) 
        try:
            profile = self.client.com.atproto.repo.describe_repo(repo=did)
            return profile.handle
        except Exception as e:
            logger.warning(f"Could not resolve handle for DID {did} via describe_repo: {e}. Falling back to ClearSky.")
            try:
                await asyncio.sleep(CLEARSKY_REQUEST_DELAY) 
                # Ensure client is not closed
                if self.http_client.is_closed:
                    self.http_client = httpx.AsyncClient(timeout=60.0)

                url = f"{CLEARSKY_API_BASE_URL}/get-handle/{did}"
                response = await self.http_client.get(url)
                response.raise_for_status()
                data = response.json()
                return data.get('data', {}).get('handle_identifier', did[:15] + '...')
            except Exception as cs_e:
                logger.error(f"Error resolving handle for {did} via ClearSky as well: {cs_e}")
                return did[:15] + '...'
    
    async def sync_blocks_from_others(self):
        """If this is the primary account, sync blocks from other managed accounts to its own blocklist."""
        if not self.is_primary:
            logger.debug(f"Account {self.handle} is not primary, skipping sync_blocks_from_others.")
            return

        logger.info(f"Primary account {self.handle} starting sync of blocks from other managed accounts.")
        try:
            # Get all DIDs that other managed accounts are blocking but are not yet synced by this primary account
            accounts_to_block_info = self.database.get_unsynced_blocks_for_primary(self.account_id)
            
            # Also mark any blocks already being blocked by the primary account as synced
            already_blocked_dids = []
            try:
                # Get all blocks from non-primary accounts that need syncing including those already blocked
                conn = self.database.get_connection()
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                query = """
                SELECT ba.id, ba.did, ba.handle, 
                       EXISTS (
                           SELECT 1
                           FROM blocked_accounts primary_blocks
                           WHERE primary_blocks.did = ba.did
                             AND primary_blocks.source_account_id = %s
                             AND primary_blocks.block_type = 'blocking'
                       ) as already_blocked_by_primary
                FROM blocked_accounts ba
                JOIN accounts a ON ba.source_account_id = a.id
                WHERE a.is_primary = FALSE                    
                  AND ba.block_type = 'blocking'              
                  AND ba.is_synced = FALSE                    
                """
                cursor.execute(query, (self.account_id,))
                all_pending_blocks = cursor.fetchall()
                
                # Process those already blocked
                for block in all_pending_blocks:
                    if block['already_blocked_by_primary']:
                        already_blocked_dids.append(block['did'])
                        self.database.mark_block_as_synced_by_primary(block['id'], self.account_id)
                        logger.info(f"Found block for {block['handle']} ({block['did']}) that is already blocked by primary - will mark as synced")
                
                cursor.close()
                conn.close()
            except Exception as e:
                logger.error(f"Error processing already blocked DIDs: {e}")
            
            # Add the blocks to the moderation list if we have one and there are new blocks
            if self.mod_list_uri and (accounts_to_block_info or already_blocked_dids):
                await self.update_moderation_list_items()
            
            if not accounts_to_block_info:
                logger.info(f"No new accounts to sync for primary account {self.handle}.")
                return
                
            logger.info(f"Primary account {self.handle} found {len(accounts_to_block_info)} new DIDs to block.")
            
            successfully_blocked_dids_in_session = []
            chunk_size = 10 # Reduced chunk size for block creation
            
            for i in range(0, len(accounts_to_block_info), chunk_size):
                chunk = accounts_to_block_info[i:i+chunk_size]
                logger.info(f"Processing chunk {i//chunk_size + 1}/{(len(accounts_to_block_info) + chunk_size - 1)//chunk_size} for {self.handle}")

                for acc_info in chunk:
                    blocked_did_to_sync = acc_info['did'] # This is the DID to be blocked
                    original_block_db_id = acc_info['id'] # This is the ID from the blocked_accounts table

                    logger.debug(f"Primary account {self.handle} attempting to block DID: {blocked_did_to_sync}")
                    try:
                        # Create a block record as a direct dictionary
                        record_data = {
                            "$type": "app.bsky.graph.block",
                            "subject": blocked_did_to_sync,
                            "createdAt": self.client.get_current_time_iso()
                        }
                        
                        # Use the standard client method for creating a record.
                        # Pass data to the data parameter, not as a mixture of params and record
                        response = self.client.com.atproto.repo.create_record(
                            data={
                                "repo": self.did,
                                "collection": "app.bsky.graph.block",
                                "record": record_data
                            }
                        )
                        logger.info(f"Primary account {self.handle} successfully blocked {blocked_did_to_sync}. URI: {response.uri}")
                        # Mark this specific block instance as synced by this primary account
                        self.database.mark_block_as_synced_by_primary(original_block_db_id, self.account_id)
                        successfully_blocked_dids_in_session.append(blocked_did_to_sync)
                    
                    except Exception as e:
                        # Check for the specific Pydantic validation error
                        if "validation error for Params" in str(e) and "actor" in str(e) and "Field required" in str(e):
                            logger.critical(f"CRITICAL: Pydantic 'actor' field validation error for {self.handle} blocking {blocked_did_to_sync}. Params: {getattr(e, 'input_value', 'N/A')}. Error: {e}")
                        elif "already exists" in str(e).lower() or "duplicate record" in str(e).lower():
                            logger.info(f"Block for {blocked_did_to_sync} already exists for {self.handle}. Marking as synced.")
                            self.database.mark_block_as_synced_by_primary(original_block_db_id, self.account_id)
                            successfully_blocked_dids_in_session.append(blocked_did_to_sync)
                        else:
                            logger.error(f"Error creating block record for {blocked_did_to_sync} by {self.handle}: {e}")
                
                if len(accounts_to_block_info) > chunk_size:
                     logger.info(f"Finished processing chunk for {self.handle}. Sleeping for 1 second before next chunk.")
                     await asyncio.sleep(1) # Delay between chunks

            if successfully_blocked_dids_in_session:
                logger.info(f"Primary account {self.handle} successfully blocked {len(successfully_blocked_dids_in_session)} new DIDs in this session.")
                
                # Update the moderation list with the new blocks
                if self.mod_list_uri:
                    await self.update_moderation_list_items()
            
        except Exception as e:
            # This is the outer catch block where the user's log showed the Pydantic error
            logger.error(f"General error in sync_blocks_from_others for primary account {self.handle}: {e}")
            if "1 validation error for Params" in str(e) and "actor" in str(e) and "Field required" in str(e):
                 logger.critical(f"CRITICAL HIT IN OUTER EXCEPTION: Pydantic Validation Error in sync_blocks_from_others for {self.handle}: {e}")
        
        logger.info(f"Sync of blocks from others completed for primary account {self.handle}.")
        
    async def update_moderation_list_items(self):
        """Update the moderation list with all blocked accounts."""
        if not self.is_primary or not self.mod_list_uri:
            return
            
        try:
            logger.info(f"Updating moderation list items for {self.handle}...")
            
            # Get all accounts that are blocked by any managed account
            blocked_accounts = self.database.get_all_blocked_accounts()
            
            if not blocked_accounts:
                logger.info("No blocked accounts to add to moderation list")
                return
                
            logger.info(f"Adding {len(blocked_accounts)} accounts to moderation list")
            
            # Get the current list items
            try:
                list_details = self.client.app.bsky.graph.get_list(params={"list": self.mod_list_uri})
                current_items = list_details.items
                current_item_subjects = [item.subject.did for item in current_items]
                logger.info(f"Found {len(current_items)} existing items in moderation list")
            except Exception as e:
                logger.warning(f"Could not fetch current list items: {e}")
                current_item_subjects = []
            
            # Add all blocked accounts to the list
            for account in blocked_accounts:
                # Skip if this DID is already in the list
                if account['did'] in current_item_subjects:
                    continue
                    
                try:
                    # Add the account to the moderation list
                    item_record = {
                        "$type": "app.bsky.graph.listitem",
                        "subject": account['did'],
                        "list": self.mod_list_uri,
                        "createdAt": self.client.get_current_time_iso()
                    }
                    
                    response = self.client.com.atproto.repo.create_record(
                        data={
                            "repo": self.did,
                            "collection": "app.bsky.graph.listitem",
                            "record": item_record
                        }
                    )
                    
                    logger.info(f"Added {account['handle'] or account['did']} to moderation list")
                except Exception as e:
                    if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                        logger.info(f"Account {account['handle'] or account['did']} already in list - skipping")
                    else:
                        logger.error(f"Error adding {account['handle'] or account['did']} to moderation list: {e}")
            
            logger.info(f"Finished updating moderation list")
        except Exception as e:
            logger.error(f"Error updating moderation list: {e}")
            return
    
    async def sync_all_account_data(self):
        """Fetch all relevant data for this account (blocks, blocked by, etc.)."""
        if not self.did:
            logger.warning(f"Cannot sync data for {self.handle}, DID not resolved.")
            return

        logger.info(f"Starting data sync for {self.handle} (DID: {self.did})...")
        
        await self.fetch_who_is_blocking_me_from_clearsky()
        await self.fetch_bluesky_blocks()
        # await self.fetch_who_i_am_blocking_from_clearsky() # Optional

        if self.is_primary:
            await self.sync_blocks_from_others()
            
        logger.info(f"Data sync completed for {self.handle}")
    
    async def start_monitoring(self):
        """Start monitoring blocks for this account."""
        try:
            await self.sync_all_account_data() # Initial full sync
                
            self.blocks_monitor_task = asyncio.create_task(self._blocks_monitor_loop())
            logger.info(f"Started monitoring blocks for {self.handle}")
        except Exception as e:
            logger.error(f"Error starting monitoring for {self.handle}: {e}")
    
    async def _blocks_monitor_loop(self):
        """Periodically check for new blocks."""
        polling_interval = int(os.getenv('POLLING_INTERVAL', '300'))
        
        try:
            while True:
                await asyncio.sleep(polling_interval) # Wait first
                logger.debug(f"Periodic check for new blocks for {self.handle}")
                await self.sync_all_account_data()
        except asyncio.CancelledError:
            logger.info(f"Block monitoring for {self.handle} was cancelled")
        except Exception as e:
            logger.error(f"Error in blocks monitor loop for {self.handle}: {e}. Restarting loop.")
            await asyncio.sleep(10) 
            # Ensure the task is recreated if it exits due to an unhandled error
            if not (self.blocks_monitor_task and not self.blocks_monitor_task.done()):
                 self.blocks_monitor_task = asyncio.create_task(self._blocks_monitor_loop())
    
    async def stop_monitoring(self):
        """Stop all monitoring tasks."""
        try:
            if self.blocks_monitor_task and not self.blocks_monitor_task.done():
                self.blocks_monitor_task.cancel()
                try:
                    await self.blocks_monitor_task
                except asyncio.CancelledError:
                    logger.info(f"Block monitoring task for {self.handle} successfully cancelled.")
                except Exception as e: # Catch any other exceptions during cancellation
                    logger.warning(f"Exception during cancellation of block monitoring for {self.handle}: {e}")
                
            logger.info(f"Stopped monitoring blocks for {self.handle}")
            
        except Exception as e:
            logger.error(f"Error stopping monitoring for {self.handle}: {e}")
        finally: # Ensure http_client is closed
            if self.http_client and not self.http_client.is_closed:
                 await self.http_client.aclose()
                 logger.info(f"HTTP client closed for {self.handle}") 