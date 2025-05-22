import os
import asyncio
import logging
import httpx
from atproto import AsyncClient as ATProtoAsyncClient
from atproto import AsyncFirehoseSubscribeReposClient
from atproto_client.models.app.bsky.graph.list import Record as ListRecord
from atproto_client.models.app.bsky.graph.listitem import Record as ListItemRecord
from atproto_client.models.app.bsky.graph.block import Record as BlockRecord
from atproto_client.models.app.bsky.graph.get_blocks import Params as GetBlocksParams
from atproto_client.models.app.bsky.graph.get_list import Params as GetListParams
from atproto_client.models.com.atproto.repo.put_record import Data as PutRecordData
from atproto_client.models.com.atproto.repo.create_record import Data as CreateRecordData
from atproto_client.models.com.atproto.sync.subscribe_repos import Commit as FirehoseCommitModel

# Fix MessageFrame import
try:
    from atproto import MessageFrame
except ImportError:
    # If MessageFrame is not available, define a placeholder
    class MessageFrame:
        pass

from atproto_core.car import CAR
import cbor2
from database import Database
from test_mod_list_sync import sync_mod_list_from_db
import time
from datetime import datetime, timedelta
import clearsky_helpers as cs 

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

# Reduce verbosity of httpx and websockets library logger
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING) 

# API URLs
CLEARSKY_API_BASE_URL = os.getenv('CLEARSKY_API_URL', 'https://api.clearsky.services/api/v1/anon')
# BLUESKY_API_URL is not directly used by ATProtoAsyncClient if not passed to constructor, it defaults to bsky.social

# ClearSky Rate Limiting
CLEARSKY_REQUEST_DELAY = 1.0  # 1 request per second, down from 4 req/sec to avoid rate limiting

# Firehose constants
FIREHOSE_HOST = "bsky.network" # Updated to standard endpoint
FIREHOSE_PORT = 443 # Default HTTPS/WSS port
FIREHOSE_SSL = True

# Full synchronization schedule
FULL_SYNC_INTERVAL_HOURS = int(os.getenv('FULL_SYNC_INTERVAL_HOURS', '24'))

class AccountAgent:
    def __init__(self, handle, password, is_primary=False, database=None):
        self.handle = handle
        self.password = password
        self.is_primary = is_primary
        self.client = ATProtoAsyncClient() 
        self.database = database if database else Database()
        self.account_id = None
        self.did = None
        self.blocks_monitor_task = None
        self.firehose_monitor_task = None 
        self.http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        self.mod_list_uri = None
        self._firehose_stop_event = asyncio.Event()
        self._blocks_monitor_stop_event = asyncio.Event()
        logger.debug(f"AccountAgent initialized for {self.handle}")


    async def initialize(self):
        logger.info(f"Initializing AccountAgent for {self.handle}...")
        return await self.login()

    async def login(self):
        try:
            logger.info(f"Attempting login for {self.handle}...")
            profile = await self.client.login(self.handle, self.password)
            self.did = profile.did
            logger.info(f"Logged in as {self.handle} (DID: {self.did})")

            self.account_id = self.database.register_account(
                self.handle,
                self.did,
                is_primary=self.is_primary
            )
            logger.info(f"Account {self.handle} registered with ID {self.account_id}")

            if self.is_primary:
                try:
                    await self.create_or_update_moderation_list()
                except Exception as e:
                    logger.error(f"Error creating/updating moderation list for {self.handle}: {e}", exc_info=True)
            return True
        except Exception as e:
            logger.error(f"Failed to login as {self.handle}: {e}", exc_info=True)
            if "Unexpected server response" in str(e) or "Handshake failed" in str(e):
                logger.error("This might be a network issue or Bluesky server problem. Check connection and server status.")
            return False

    async def create_or_update_moderation_list(self):
        if not self.is_primary:
            logger.debug(f"Account {self.handle} is not primary, skipping moderation list creation.")
            return None

        list_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
        list_purpose = 'app.bsky.graph.defs#modlist'
        list_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by any of our managed accounts')
        
        try:
            logger.info(f"Creating or updating moderation list for primary account {self.handle}...")
            
            list_record_data = ListRecord(
                purpose=list_purpose,
                name=list_name,
                description=list_description,
                created_at=self.client.get_current_time_iso()
            )
            
            existing_list = None
            try:
                logger.debug(f"Fetching existing lists for {self.did}...")
                lists_response = await self.client.app.bsky.graph.get_lists(params={"actor": self.did})
                for lst in lists_response.lists:
                    if lst.name == list_name and lst.purpose == list_purpose:
                        existing_list = lst
                        logger.info(f"Found existing moderation list: {lst.uri}")
                        break
                if not existing_list:
                    logger.info(f"No existing moderation list found with name '{list_name}' for {self.did}.")
            except Exception as e:
                logger.warning(f"Could not fetch existing lists for {self.did}: {e}", exc_info=True)
            
            if existing_list:
                logger.info(f"Updating existing moderation list {existing_list.uri} for {self.handle}...")
                data = PutRecordData(
                    repo=self.did,
                    collection='app.bsky.graph.list',
                    rkey=existing_list.uri.split('/')[-1],
                    record=list_record_data.model_dump(exclude_none=True, by_alias=True)
                )
                response = await self.client.com.atproto.repo.put_record(data=data)
                list_uri = existing_list.uri
                list_cid = str(response.cid) 
                logger.info(f"Updated existing moderation list: {list_uri} (CID: {list_cid})")
            else:
                logger.info(f"Creating new moderation list for {self.handle}...")
                data = CreateRecordData(
                    repo=self.did,
                    collection='app.bsky.graph.list',
                    record=list_record_data.model_dump(exclude_none=True, by_alias=True)
                )
                response = await self.client.com.atproto.repo.create_record(data=data)
                list_uri = response.uri
                list_cid = str(response.cid)
                logger.info(f"Created new moderation list: {list_uri} (CID: {list_cid})")
            
            self.mod_list_uri = list_uri
            self.database.register_mod_list(
                list_uri=list_uri,
                list_cid=list_cid, 
                owner_did=self.did,
                name=list_name
            )
            logger.info(f"Moderation list {list_uri} registered in DB for {self.handle}.")
            return list_uri
        except Exception as e:
            logger.error(f"Error creating/updating moderation list for {self.handle}: {e}", exc_info=True)
            return None

    async def add_did_to_blocklist_and_mod_list(self, blocked_did: str, block_reason: str = "Blocked via firehose sync"):
        if not self.did or not self.account_id:
            logger.error(f"Account {self.handle} (DID: {self.did}, ID: {self.account_id}) not properly initialized to add DID {blocked_did} to blocklist.")
            return

        logger.info(f"Account {self.handle} (id: {self.account_id}) processing block for {blocked_did}. Reason: {block_reason}")
        try:
            self.database.add_blocked_account(
                did=blocked_did,
                handle=None, 
                source_account_id=self.account_id,
                block_type='blocking', 
                reason=block_reason
            )
            logger.info(f"Added {blocked_did} to local DB as 'blocking' for {self.handle} (id: {self.account_id}).")
        except Exception as e:
            logger.error(f"Error adding {blocked_did} to local DB for {self.handle}: {e}", exc_info=True)

        if self.is_primary and self.mod_list_uri:
            logger.info(f"Primary account {self.handle} attempting to add {blocked_did} to moderation list {self.mod_list_uri}")
            try:
                list_item_record = ListItemRecord(
                    subject=blocked_did,
                    list=self.mod_list_uri,
                    created_at=self.client.get_current_time_iso()
                )
                data = CreateRecordData(
                    repo=self.did, 
                    collection='app.bsky.graph.listitem',
                    record=list_item_record.model_dump(exclude_none=True, by_alias=True)
                )
                await self.client.com.atproto.repo.create_record(data=data)
                logger.info(f"Successfully added {blocked_did} to mod list {self.mod_list_uri} by {self.handle}.")
            except Exception as e:
                if "Conflict" in str(e) or "Record already exists" in str(e):
                    logger.debug(f"{blocked_did} may already be in moderation list {self.mod_list_uri}. Error: {e}")
                else:
                    logger.error(f"Error adding {blocked_did} to mod list {self.mod_list_uri} for {self.handle}: {e}", exc_info=True)
        elif self.is_primary and not self.mod_list_uri:
            logger.warning(f"Primary account {self.handle} has no moderation list URI to add {blocked_did}.")
        elif not self.is_primary:
            logger.debug(f"Account {self.handle} is not primary, not adding {blocked_did} to any mod list itself.")


    async def _firehose_message_handler(self, message) -> bool:
        if self._firehose_stop_event.is_set():
            logger.info(f"FIREHOSE_HANDLER ({self.did}): Stop event set, exiting message processing loop.")
            return True # Signal to stop

        current_seq = None
        try:
            if message.data and hasattr(message.data, 'seq'):
                current_seq = message.data.seq
            
            # INFO Log for any commit message received
            if message.type == '#commit':
                logger.info(f"FIREHOSE_HANDLER ({self.did}): Received a #commit message. Seq: {current_seq if current_seq else 'N/A'}, Repo: {message.data.repo if message.data and hasattr(message.data, 'repo') else 'Unknown Repo'}")

            logger.debug(f"FIREHOSE_HANDLER ({self.did}): Received message type '{message.type}', Seq: {current_seq if current_seq else 'N/A'}")

            if not message.data or message.type != '#commit':
                if message.type == '#info':
                    logger.info(f"FIREHOSE_HANDLER ({self.did}): Received info message: {message.data}")
                elif message.type == '#error':
                    logger.error(f"FIREHOSE_HANDLER ({self.did}): Received error message: {message.data}")
                else:
                    logger.debug(f"FIREHOSE_HANDLER ({self.did}): Skipping message type '{message.type}'.")
                
                if current_seq is not None: # Save cursor even for non-commit messages if they have a seq
                    logger.debug(f"FIREHOSE_HANDLER ({self.did}): Saving cursor {current_seq} after non-commit message.")
                    await self.database.save_last_firehose_cursor(self.did, current_seq)
                return False # Continue processing

            commit_data: FirehoseCommitModel = message.data
            current_seq = commit_data.seq # Ensure we use commit's seq, which should always exist for #commit

            # Add more detailed logging about the commit for debugging
            logger.info(f"FIREHOSE_HANDLER ({self.did}): Processing commit. Repo: {commit_data.repo}, Seq: {current_seq}")
            logger.info(f"FIREHOSE_HANDLER ({self.did}): Commit details - Ops: {len(commit_data.ops)}, Blocks Size: {len(commit_data.blocks) if commit_data.blocks else 0}")
            
            # Log operation details for debugging
            for op_idx, op in enumerate(commit_data.ops[:3]):  # Log first 3 operations
                logger.info(f"FIREHOSE_HANDLER ({self.did}): Operation {op_idx+1}: Action={op.action}, Path={op.path}, CID={op.cid}")

            if commit_data.repo != self.did:
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Commit repo {commit_data.repo} does not match self.did. Skipping. Saving cursor {current_seq}.")
                await self.database.save_last_firehose_cursor(self.did, current_seq)
                return False 
            
            logger.info(f"FIREHOSE_HANDLER ({self.did}): Processing relevant commit for self. Seq={current_seq}, Ops: {len(commit_data.ops)}")

            if not commit_data.blocks:
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Commit Seq {current_seq} has no 'blocks' (CAR file) data. Saving cursor {current_seq}.")
                await self.database.save_last_firehose_cursor(self.did, current_seq)
                return False

            try:
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Decoding CAR file for commit Seq {current_seq}...")
                car_file = CAR.decode(commit_data.blocks)
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): CAR file decoded. Root CIDs: {car_file.roots}, Num Blocks: {len(car_file.blocks)}")
            except Exception as e:
                logger.error(f"FIREHOSE_HANDLER ({self.did}): Error decoding CAR file for commit {current_seq} from {commit_data.repo}: {e}", exc_info=True)
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Saving cursor {current_seq} after CAR decode error.")
                await self.database.save_last_firehose_cursor(self.did, current_seq)
                return False

            for op_idx, op in enumerate(commit_data.ops):
                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Op {op_idx+1}/{len(commit_data.ops)} -> Action: {op.action}, Path: {op.path}, CID: {op.cid}")
                if op.action == 'create': 
                    collection = op.path.split('/')[0]
                    if collection == 'app.bsky.graph.block':
                        logger.info(f"FIREHOSE_HANDLER ({self.did}): Found 'app.bsky.graph.block' create operation. CID: {op.cid}, Path: {op.path}")
                        if op.cid is None:
                            logger.warning(f"FIREHOSE_HANDLER ({self.did}): Block create operation has no CID. Path: {op.path}. Skipping op.")
                            continue
                        
                        record_bytes = car_file.blocks.get(op.cid)
                        if not record_bytes:
                            logger.warning(f"FIREHOSE_HANDLER ({self.did}): Could not find record for CID {op.cid} in CAR file for commit {current_seq}. Skipping op.")
                            continue
                        
                        try:
                            logger.debug(f"FIREHOSE_HANDLER ({self.did}): Loading CBOR for block record CID {op.cid}...")
                            record_dict = cbor2.loads(record_bytes)
                            logger.debug(f"FIREHOSE_HANDLER ({self.did}): CBOR loaded for CID {op.cid}. Raw record: {record_dict}")
                            
                            if '$type' not in record_dict: 
                                record_dict['$type'] = 'app.bsky.graph.block'
                                logger.debug(f"FIREHOSE_HANDLER ({self.did}): Added '$type': 'app.bsky.graph.block' to record_dict for CID {op.cid}")
                            
                            block_record = BlockRecord.model_validate(record_dict)
                            blocked_did = block_record.subject
                            logger.info(f"FIREHOSE_HANDLER ({self.did}): Successfully parsed BlockRecord. Subject (blocked DID): {blocked_did}")
                            
                            logger.info(f"FIREHOSE_SYNC_EVENT: Account {self.handle} (DID: {self.did}) created block for {blocked_did} (Seq: {current_seq}, Op CID: {op.cid})")
                            await self.add_did_to_blocklist_and_mod_list(blocked_did, block_reason=f"Blocked via firehose seq {current_seq}, op_cid {op.cid}")
                        except Exception as e:
                            logger.error(f"FIREHOSE_HANDLER ({self.did}): Error processing block record CID {op.cid} in commit {current_seq}: {e}", exc_info=True)
            
            logger.debug(f"FIREHOSE_HANDLER ({self.did}): Finished processing ops for commit {current_seq}. Saving cursor {current_seq}.")
            await self.database.save_last_firehose_cursor(self.did, current_seq)
            return False # Continue processing
        
        except Exception as e: # Catch-all for unexpected errors in handler
            logger.error(f"FIREHOSE_HANDLER ({self.did}): Unexpected error in message handler (Seq: {current_seq if current_seq else 'N/A'}): {e}", exc_info=True)
            if current_seq is not None: # Try to save cursor if we know it
                try:
                    logger.error(f"FIREHOSE_HANDLER ({self.did}): Attempting to save cursor {current_seq} after unexpected handler error.")
                    await self.database.save_last_firehose_cursor(self.did, current_seq)
                except Exception as db_e:
                    logger.error(f"FIREHOSE_HANDLER ({self.did}): Failed to save cursor {current_seq} after handler error: {db_e}", exc_info=True)
            return False # Continue processing, but log the error heavily. Consider if True is safer.

    async def sync_blocks_with_firehose(self):
        if not self.did or not self.account_id:
            logger.error(f"FIREHOSE_SYNC ({self.handle}): Cannot start. Account not properly initialized (DID: {self.did}, ID: {self.account_id}).")
            return

        self._firehose_stop_event.clear()
        logger.info(f"FIREHOSE_SYNC ({self.handle}, DID: {self.did}): Starting...")

        cursor_val = await self.database.get_last_firehose_cursor(self.did)
        
        if cursor_val is None:
            logger.info(f"FIREHOSE_SYNC ({self.did}): No last cursor found. Starting from Jetstream's earliest available data (requesting cursor 0).")
            cursor_val = 0 
        else:
            logger.info(f"FIREHOSE_SYNC ({self.did}): Resuming from cursor: {cursor_val}")

        firehose_client = None # Initialize to ensure it's in scope for finally block
        try:
            logger.info(f"DEBUG_PROBE: sync_blocks_with_firehose - About to initialize AsyncFirehoseSubscribeReposClient for {self.handle}") # ADDED DEBUG PROBE
            logger.info(f"FIREHOSE_SYNC ({self.did}): Initializing AsyncFirehoseSubscribeReposClient. Cursor: {cursor_val}")
            
            # Create parameters with the cursor
            params = {"cursor": cursor_val} if cursor_val is not None else None
            
            firehose_client = AsyncFirehoseSubscribeReposClient(
                params=params,
                base_uri=f"wss://{FIREHOSE_HOST}/xrpc/com.atproto.sync.subscribeRepos"
            )
            
            logger.info(f"FIREHOSE_SYNC ({self.did}): Firehose client initialized. Attempting to connect and start listening...")
            logger.info(f"DEBUG_PROBE: sync_blocks_with_firehose - About to call firehose_client.start() for {self.handle}") # ADDED DEBUG PROBE
            # The start method blocks until an error or graceful stop
            await firehose_client.start(self._firehose_message_handler)
            
            logger.info(f"FIREHOSE_SYNC ({self.did}): firehose_client.start() returned. This means the stream ended or was stopped.")

        except asyncio.CancelledError:
            logger.info(f"FIREHOSE_SYNC ({self.did}): Task was cancelled.")
        except Exception as e:
            logger.error(f"FIREHOSE_SYNC ({self.did}): An error occurred: {e}", exc_info=True)
        finally:
            logger.info(f"FIREHOSE_SYNC ({self.did}): Entered finally block. Sync process is stopping/has stopped.")
            if firehose_client:
                logger.info(f"FIREHOSE_SYNC ({self.did}): Calling firehose_client.stop() to ensure connection is closed.")
                try:
                    await firehose_client.stop()
                    logger.info(f"FIREHOSE_SYNC ({self.did}): firehose_client.stop() completed.")
                except Exception as e_stop:
                    logger.error(f"FIREHOSE_SYNC ({self.did}): Error during firehose_client.stop(): {e_stop}", exc_info=True)
            else:
                logger.info(f"FIREHOSE_SYNC ({self.did}): firehose_client was not initialized, skipping stop().")
            logger.info(f"FIREHOSE_SYNC ({self.handle}, DID: {self.did}): Has fully stopped.")


    async def start_monitoring(self):
        if not self.did:
            logger.error(f"MONITORING ({self.handle}): Account not logged in. Cannot start monitoring.")
            return

        logger.info(f"MONITORING ({self.handle}, DID: {self.did}): Attempting to start all monitoring tasks...")
        await self.stop_monitoring() # Ensure clean state

        logger.info(f"MONITORING ({self.handle}): Starting legacy block monitor loop...")
        self._blocks_monitor_stop_event.clear()
        self.blocks_monitor_task = asyncio.create_task(self._blocks_monitor_loop())
        if self.blocks_monitor_task:
            logger.info(f"MONITORING ({self.handle}): Legacy block monitor task created and started.")
        else: # Should not happen with create_task
            logger.error(f"MONITORING ({self.handle}): Failed to create legacy block monitor task.")


        logger.info(f"MONITORING ({self.handle}): Starting firehose sync task...")
        self._firehose_stop_event.clear()
        self.firehose_monitor_task = asyncio.create_task(self.sync_blocks_with_firehose())
        if self.firehose_monitor_task:
            logger.info(f"MONITORING ({self.handle}): Firehose sync task created and started.")
        else: # Should not happen
            logger.error(f"MONITORING ({self.handle}): Failed to create firehose sync task.")
        
        logger.info(f"MONITORING ({self.handle}, DID: {self.did}): All monitoring tasks initiated.")


    async def stop_monitoring(self):
        logger.info(f"MONITORING ({self.handle}): Attempting to stop all monitoring tasks...")
        
        if self.firehose_monitor_task and not self.firehose_monitor_task.done():
            logger.info(f"MONITORING ({self.handle}): Stopping firehose sync task...")
            self._firehose_stop_event.set() 
            try:
                logger.debug(f"MONITORING ({self.handle}): Waiting for firehose task to stop gracefully (timeout 10s)...")
                await asyncio.wait_for(self.firehose_monitor_task, timeout=10.0)
                logger.info(f"MONITORING ({self.handle}): Firehose task stopped gracefully.")
            except asyncio.TimeoutError:
                logger.warning(f"MONITORING ({self.handle}): Firehose task did not stop gracefully within 10s, cancelling.")
                self.firehose_monitor_task.cancel()
                try:
                    await self.firehose_monitor_task
                except asyncio.CancelledError:
                    logger.info(f"MONITORING ({self.handle}): Firehose sync task cancelled successfully after timeout.")
            except asyncio.CancelledError: # If it was cancelled by something else while waiting
                 logger.info(f"MONITORING ({self.handle}): Firehose sync task was already cancelled during graceful stop wait.")
            except Exception as e:
                logger.error(f"MONITORING ({self.handle}): Exception while stopping firehose task: {e}", exc_info=True)
        else:
            logger.debug(f"MONITORING ({self.handle}): Firehose task was None or already done.")
        self.firehose_monitor_task = None

        if self.blocks_monitor_task and not self.blocks_monitor_task.done():
            logger.info(f"MONITORING ({self.handle}): Stopping legacy block monitor loop...")
            self._blocks_monitor_stop_event.set()
            try:
                logger.debug(f"MONITORING ({self.handle}): Waiting for legacy block monitor task to stop gracefully (timeout 5s)...")
                await asyncio.wait_for(self.blocks_monitor_task, timeout=5.0) 
                logger.info(f"MONITORING ({self.handle}): Legacy block monitor task stopped gracefully.")
            except asyncio.TimeoutError:
                logger.warning(f"MONITORING ({self.handle}): Legacy block monitor did not stop gracefully within 5s, cancelling.")
                self.blocks_monitor_task.cancel()
                try:
                    await self.blocks_monitor_task
                except asyncio.CancelledError:
                     logger.info(f"MONITORING ({self.handle}): Legacy block monitor loop cancelled successfully after timeout.")
            except asyncio.CancelledError:
                logger.info(f"MONITORING ({self.handle}): Legacy block monitor loop was already cancelled during graceful stop wait.")
            except Exception as e:
                logger.error(f"MONITORING ({self.handle}): Exception while stopping legacy block monitor loop: {e}", exc_info=True)
        else:
            logger.debug(f"MONITORING ({self.handle}): Legacy block monitor task was None or already done.")
        self.blocks_monitor_task = None
        logger.info(f"MONITORING ({self.handle}): All monitoring tasks stopped and cleared.")

    async def _fetch_paginated_clearsky_list(self, endpoint_template: str):
        """
        Fetch a paginated list from ClearSky API
        
        Args:
            endpoint_template: The API endpoint template with {did} placeholder
            
        Returns:
            List of DIDs from all pages
        """
        logger.debug(f"CLEARSKY_FETCH ({self.did}): Starting paginated fetch for endpoint template: {endpoint_template}")
        
        # Extract the endpoint type to determine which helper function to use
        if "/single-blocklist/" in endpoint_template:
            # Use the improved pagination handler for blocked-by lists
            logger.info(f"CLEARSKY_FETCH ({self.did}): Using enhanced pagination for blocked-by accounts")
            
            # Get the formatted endpoint
            formatted_endpoint = endpoint_template.replace("{did}", self.did)
            handle_or_did = self.did
            
            try:
                # First get the total count for logging purposes
                total_count = await cs.get_total_blocked_by_count(handle_or_did)
                if total_count is not None:
                    logger.info(f"CLEARSKY_FETCH ({self.did}): Found {total_count} total accounts in list")
                
                # Fetch all pages with our improved pagination handling
                blockers, fetched_count = await cs.fetch_all_blocked_by(handle_or_did)
                
                # Extract just the DIDs from the blocker records
                all_dids = [blocker['did'] for blocker in blockers if 'did' in blocker]
                
                logger.info(f"CLEARSKY_FETCH ({self.did}): Successfully fetched {len(all_dids)} DIDs using enhanced pagination")
                return all_dids
            except Exception as e:
                logger.error(f"CLEARSKY_FETCH ({self.did}): Error using enhanced pagination: {e}", exc_info=True)
                logger.warning(f"CLEARSKY_FETCH ({self.did}): Falling back to original pagination method")
                # Fall back to original implementation
        
        # Original implementation for other endpoints or as fallback
        all_dids = []
        page = 1
        max_pages = 500 
        while page <= max_pages:
            # Implement exponential backoff with retries for rate limiting
            retry_count = 0
            max_retries = 5
            retry_delay = CLEARSKY_REQUEST_DELAY
            
            while retry_count <= max_retries:
                try:
                    await asyncio.sleep(retry_delay)
                    formatted_endpoint = endpoint_template.replace("{did}", self.did)
                    url = f"{CLEARSKY_API_BASE_URL}{formatted_endpoint}/{page}"
                    logger.debug(f"CLEARSKY_FETCH ({self.did}): Fetching page {page} from {url} (retry: {retry_count})")
                    
                    response = await self.http_client.get(url)
                    if response.status_code == 404:
                        logger.debug(f"CLEARSKY_FETCH ({self.did}): Page {page} not found for {url} (404), assuming end of list.")
                        break 
                    
                    if response.status_code == 429:
                        retry_count += 1
                        if retry_count > max_retries:
                            logger.error(f"CLEARSKY_FETCH ({self.did}): Rate limit exceeded and max retries reached for {url}. Giving up.")
                            break
                        # Exponential backoff
                        retry_delay = min(60, retry_delay * 2)  # Cap at 60 seconds
                        logger.warning(f"CLEARSKY_FETCH ({self.did}): Rate limit hit (429) for {url}. Retrying in {retry_delay}s (retry {retry_count}/{max_retries})")
                        continue
                    
                    response.raise_for_status() # Raises for other 4xx/5xx responses
                    data = response.json()
                    
                    current_page_dids = []
                    blocklist_data = data.get('data', {}).get('blocklist')

                    if blocklist_data is None: 
                        logger.debug(f"CLEARSKY_FETCH ({self.did}): No 'blocklist' key or it's null/empty in response from {url}, page {page}. Assuming end.")
                        break
                    
                    current_page_dids = [item['did'] for item in blocklist_data if 'did' in item and isinstance(item['did'], str) and item['did'].startswith('did:')]
                    logger.debug(f"CLEARSKY_FETCH ({self.did}): Page {page} from {url} yielded {len(current_page_dids)} DIDs.")

                    if not current_page_dids and page > 1: 
                        logger.debug(f"CLEARSKY_FETCH ({self.did}): No DIDs found on page {page} for {url} (and not first page), assuming end of list.")
                        break
                    
                    all_dids.extend(current_page_dids)
                    if len(current_page_dids) < 100: 
                        logger.debug(f"CLEARSKY_FETCH ({self.did}): Fetched {len(current_page_dids)} DIDs on page {page} for {url}, <100, assuming last page.")
                        break
                    
                    # Success! Move to next page and reset retry logic
                    page += 1
                    break  # Exit retry loop on success
                    
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        retry_count += 1
                        if retry_count > max_retries:
                            logger.error(f"CLEARSKY_FETCH ({self.did}): Rate limit exceeded and max retries reached for {url}. Giving up.")
                            break
                        # Exponential backoff
                        retry_delay = min(60, retry_delay * 2)  # Cap at 60 seconds
                        logger.warning(f"CLEARSKY_FETCH ({self.did}): Rate limit hit (429) for {url}. Retrying in {retry_delay}s (retry {retry_count}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"CLEARSKY_FETCH ({self.did}): HTTP error fetching {url}: {e.response.status_code} - {e.response.text}", exc_info=True)
                        break
                except httpx.RequestError as e:
                    logger.error(f"CLEARSKY_FETCH ({self.did}): Request error fetching {url}: {e}", exc_info=True)
                    break
                except Exception as e: 
                    logger.error(f"CLEARSKY_FETCH ({self.did}): Unexpected error fetching or parsing {url}: {e}", exc_info=True)
                    break
            
            # If we've exhausted retries with rate limiting, break out of page loop
            if retry_count > max_retries:
                logger.error(f"CLEARSKY_FETCH ({self.did}): Giving up on pagination due to persistent rate limiting")
                break
                
        if page >= max_pages:
             logger.warning(f"CLEARSKY_FETCH ({self.did}): Reached max_pages ({max_pages}) for endpoint {endpoint_template}.")
        logger.debug(f"CLEARSKY_FETCH ({self.did}): Finished paginated fetch for {endpoint_template}. Total DIDs: {len(all_dids)}.")
        return all_dids

    async def fetch_who_is_blocking_me_from_clearsky(self):
        logger.info(f"CLEARSKY_SYNC ({self.handle}): Fetching who is blocking this account...")
        endpoint = "/single-blocklist/{did}"
        blocked_by_dids = await self._fetch_paginated_clearsky_list(endpoint)
        logger.info(f"CLEARSKY_SYNC ({self.handle}): Found {len(blocked_by_dids)} accounts blocking this account via ClearSky.")
        
        # Efficiently check DIDs already in DB to minimize writes for existing 'blocked_by'
        # This is a simplified approach; a more robust one might fetch existing 'blocked_by' DIDs first.
        for did in blocked_by_dids:
            try:
                # The add_blocked_account method in database.py should ideally handle "INSERT ... ON CONFLICT DO NOTHING"
                # or "UPDATE" if some fields might change (though for 'blocked_by' it's usually just presence).
                self.database.add_blocked_account(
                    did=did, handle=None, source_account_id=self.account_id, block_type='blocked_by' 
                )
                # logger.debug(f"CLEARSKY_SYNC ({self.handle}): Processed 'blocked_by' DID {did} into DB.") # Can be too verbose
            except Exception as e:
                logger.error(f"CLEARSKY_SYNC ({self.handle}): Error adding 'blocked_by' DID {did} from ClearSky to DB: {e}", exc_info=True)
        
        logger.debug(f"CLEARSKY_SYNC ({self.handle}): Removing stale 'blocked_by' entries from DB...")
        self.database.remove_stale_blocks(self.account_id, 'blocked_by', blocked_by_dids)
        logger.info(f"CLEARSKY_SYNC ({self.handle}): Finished fetching and processing who is blocking this account.")
        return blocked_by_dids

    async def fetch_bluesky_blocks(self):
        logger.info(f"DEBUG_PROBE_FETCH_ENTRY: fetch_bluesky_blocks ENTERED for {self.handle}") # MODIFIED DEBUG PROBE
        logger.info(f"DEBUG_PROBE: fetch_bluesky_blocks called for {self.handle}") 
        logger.info(f"BLUESKY_API_SYNC ({self.handle}): Fetching accounts this account is blocking (for initial sync)...")
        blocked_accounts_dids = []
        cursor = None
        max_attempts = 3
        attempt_delay = 1 # seconds
        blocks_found = 0  # Counter for debugging

        for attempt in range(max_attempts):
            try:
                logger.info(f"DEBUG_PROBE: fetch_bluesky_blocks - Entering attempt loop {attempt + 1} for {self.handle}") # ADDED DEBUG PROBE
                logger.debug(f"BLUESKY_API_SYNC ({self.handle}): get_blocks attempt {attempt + 1}/{max_attempts}. Cursor: {cursor}")
                params = GetBlocksParams(cursor=cursor, limit=100)
                response = await self.client.app.bsky.graph.get_blocks(params=params)
                
                if response and response.blocks:
                    blocks_count = len(response.blocks)
                    blocks_found += blocks_count
                    logger.info(f"BLUESKY_API_SYNC ({self.handle}): Fetched {blocks_count} blocks in this page.")
                    
                    # Log the first few blocks for debugging
                    for i, block_view in enumerate(response.blocks[:5]):  # Log only first 5 blocks for brevity
                        logger.info(f"BLUESKY_API_SYNC ({self.handle}): Block {i+1}: DID={block_view.did}, Handle={block_view.handle}")
                    
                    for block_view in response.blocks:
                        blocked_accounts_dids.append(block_view.did)
                        # This add_blocked_account should also be idempotent or handle conflicts
                        self.database.add_blocked_account(
                            did=block_view.did, handle=block_view.handle, 
                            source_account_id=self.account_id, block_type='blocking',
                            reason="Fetched via Bluesky API get_blocks" 
                        )
                else:
                    logger.debug(f"BLUESKY_API_SYNC ({self.handle}): No blocks in this page or empty response.")

                if not response or not response.cursor:
                    logger.info(f"BLUESKY_API_SYNC ({self.handle}): No more pages for Bluesky blocks.")
                    break 
                cursor = response.cursor
                logger.debug(f"BLUESKY_API_SYNC ({self.handle}): Next cursor for get_blocks: {cursor}")
                await asyncio.sleep(0.2) 
            except Exception as e:
                logger.error(f"BLUESKY_API_SYNC ({self.handle}): Error fetching Bluesky blocks (attempt {attempt + 1}/{max_attempts}): {e}", exc_info=True)
                if attempt + 1 >= max_attempts:
                    logger.error(f"BLUESKY_API_SYNC ({self.handle}): Max attempts reached fetching Bluesky blocks.")
                    break
                logger.info(f"BLUESKY_API_SYNC ({self.handle}): Retrying get_blocks in {attempt_delay}s...")
                await asyncio.sleep(attempt_delay)
                attempt_delay *= 2 # Exponential backoff
        
        logger.info(f"BLUESKY_API_SYNC ({self.handle}): Found {len(blocked_accounts_dids)} total accounts being blocked by this account via API ({blocks_found} blocks fetched across all pages).")
        
        if len(blocked_accounts_dids) > 0:
            logger.info(f"BLUESKY_API_SYNC ({self.handle}): Successfully fetched and stored {len(blocked_accounts_dids)} blocks for account {self.handle}")
        else:
            logger.warning(f"BLUESKY_API_SYNC ({self.handle}): No blocks found for account {self.handle}. This may be expected if the account has no blocks.")
            
        logger.debug(f"BLUESKY_API_SYNC ({self.handle}): Removing stale 'blocking' entries from DB (initial sync reconciliation)...")
        self.database.remove_stale_blocks(self.account_id, 'blocking', blocked_accounts_dids) # For initial sync, ensure DB reflects API state
        logger.info(f"BLUESKY_API_SYNC ({self.handle}): Finished fetching and processing blocks from Bluesky API.")
        return blocked_accounts_dids

    async def sync_blocks_from_others(self):
        if not self.is_primary or not self.mod_list_uri or not self.account_id:
            logger.debug(f"PRIMARY_SYNC ({self.handle}): Not primary, or mod_list_uri/account_id not set. Skipping sync_blocks_from_others.")
            return

        logger.info(f"PRIMARY_SYNC ({self.handle}): Syncing blocks from other managed (secondary) accounts to this primary account...")
        
        # Add debug logging to see if there are any blocked accounts in the database
        try:
            blocked_accounts = self.database.get_all_blocked_accounts()
            logger.info(f"PRIMARY_SYNC ({self.handle}): Database contains {len(blocked_accounts)} total blocked accounts records (including all accounts and types)")
            
            # Log sample of block records for debugging
            logger.info(f"PRIMARY_SYNC ({self.handle}): Sample of block records:")
            for idx, record in enumerate(blocked_accounts[:5]):  # Log just first 5 records
                logger.info(f"PRIMARY_SYNC ({self.handle}): Block record {idx+1}: "
                          f"DID={record.get('did', 'unknown')}, "
                          f"Type={record.get('block_type', 'unknown')}, "
                          f"Source={record.get('source_account_handle', 'unknown')}, "
                          f"Synced={record.get('is_synced', False)}")
            
            # Get the total number of blocked DIDs to help with debugging
            unique_dids = set(record['did'] for record in blocked_accounts if record.get('did'))
            logger.info(f"PRIMARY_SYNC ({self.handle}): Database contains {len(unique_dids)} unique DIDs being blocked by all accounts")
            
            # List secondary accounts for debugging
            secondary_accounts = self.database.get_secondary_accounts()
            if secondary_accounts:
                logger.info(f"PRIMARY_SYNC ({self.handle}): Found {len(secondary_accounts)} secondary accounts in database")
                for acct in secondary_accounts:
                    logger.info(f"PRIMARY_SYNC ({self.handle}): Secondary account: {acct.get('handle', 'unknown')} (DID: {acct.get('did', 'unknown')})")
            else:
                logger.warning(f"PRIMARY_SYNC ({self.handle}): No secondary accounts found in database!")
        except Exception as e:
            logger.error(f"PRIMARY_SYNC ({self.handle}): Error getting debug info: {e}", exc_info=True)
        
        # Continue with normal sync logic
        unsynced_entries = self.database.get_unsynced_blocks_for_primary(self.account_id)
        
        if not unsynced_entries:
            logger.info(f"PRIMARY_SYNC ({self.handle}): No new unsynced blocks from other accounts to process.")
            return

        logger.info(f"PRIMARY_SYNC ({self.handle}): Found {len(unsynced_entries)} unsynced block entries from other accounts.")

        for entry_idx, entry in enumerate(unsynced_entries):
            did_to_block = entry['did']
            original_block_db_id = entry['id'] 
            already_blocked_by_primary_in_db = entry['already_blocked_by_primary']
            source_secondary_handle = entry.get('source_account_handle', 'Unknown Secondary') # Assuming DB query provides this

            logger.info(f"PRIMARY_SYNC ({self.handle}): Processing entry {entry_idx+1}/{len(unsynced_entries)}. DID: {did_to_block}, From: {source_secondary_handle} (DB ID: {original_block_db_id}). Already blocked in DB by primary: {already_blocked_by_primary_in_db}")

            try:
                # Step 1: Ensure primary account blocks the DID on Bluesky if not already in DB as primary's block
                if not already_blocked_by_primary_in_db:
                    logger.info(f"PRIMARY_SYNC ({self.handle}): Attempting to create Bluesky block for {did_to_block} (as it's not in DB as primary's block).")
                    try:
                        block_record_data = BlockRecord(subject=did_to_block, created_at=self.client.get_current_time_iso())
                        data = CreateRecordData(
                            repo=self.did, 
                            collection='app.bsky.graph.block',
                            record=block_record_data.model_dump(exclude_none=True, by_alias=True)
                        )
                        await self.client.com.atproto.repo.create_record(data=data)
                        logger.info(f"PRIMARY_SYNC ({self.handle}): Successfully created Bluesky block for {did_to_block}.")
                        # Now, add this action to our DB for the primary account
                        self.database.add_blocked_account(
                            did=did_to_block, handle=entry.get('handle'), # Use handle from original block if available
                            source_account_id=self.account_id, block_type='blocking',
                            reason=f"Synced from {source_secondary_handle}'s block (db_id:{original_block_db_id})"
                        )
                        logger.info(f"PRIMARY_SYNC ({self.handle}): Added {did_to_block} to DB as primary's own block.")
                    except Exception as e_block_create:
                        if "Conflict" in str(e_block_create) or "Record already exists" in str(e_block_create):
                            logger.info(f"PRIMARY_SYNC ({self.handle}): Bluesky block for {did_to_block} already exists (Conflict). Assuming it's blocked. Adding to DB if missing.")
                            # Ensure it's in the DB as a primary block if the API says it exists
                            self.database.add_blocked_account(
                                did=did_to_block, handle=entry.get('handle'),
                                source_account_id=self.account_id, block_type='blocking',
                                reason=f"Synced from {source_secondary_handle} (API conflict indicated pre-existing)"
                            )
                        else:
                            logger.error(f"PRIMARY_SYNC ({self.handle}): Error creating Bluesky block for {did_to_block}: {e_block_create}", exc_info=True)
                            continue # Skip to next entry if we can't ensure block on Bluesky
                else:
                    logger.info(f"PRIMARY_SYNC ({self.handle}): Primary account {self.handle} already blocks {did_to_block} according to DB. No Bluesky block creation needed.")

                # Step 2: Add to moderation list (if not already there - create_record handles conflict)
                logger.info(f"PRIMARY_SYNC ({self.handle}): Attempting to add {did_to_block} to moderation list {self.mod_list_uri}")
                try:
                    list_item_record = ListItemRecord(
                        subject=did_to_block, list=self.mod_list_uri,
                        created_at=self.client.get_current_time_iso()
                    )
                    data = CreateRecordData(
                        repo=self.did, 
                        collection='app.bsky.graph.listitem',
                        record=list_item_record.model_dump(exclude_none=True, by_alias=True)
                    )
                    await self.client.com.atproto.repo.create_record(data=data)
                    logger.info(f"PRIMARY_SYNC ({self.handle}): Successfully added/ensured {did_to_block} is on mod list {self.mod_list_uri}.")
                except Exception as e_list_add:
                    if "Conflict" in str(e_list_add) or "Record already exists" in str(e_list_add):
                        logger.debug(f"PRIMARY_SYNC ({self.handle}): {did_to_block} already on mod list {self.mod_list_uri} (Conflict/Exists).")
                    else:
                        logger.error(f"PRIMARY_SYNC ({self.handle}): Error adding {did_to_block} to mod list {self.mod_list_uri}: {e_list_add}", exc_info=True)
                        # Continue even if list add fails, block is more critical
                
                # Step 3: Mark original secondary block as synced by primary
                self.database.mark_block_as_synced_by_primary(original_block_db_id, self.account_id)
                logger.info(f"PRIMARY_SYNC ({self.handle}): Marked original block (DB ID: {original_block_db_id}, DID: {did_to_block}) from {source_secondary_handle} as synced by primary.")
            
            except Exception as e_outer: # Catch-all for the entry processing
                logger.error(f"PRIMARY_SYNC ({self.handle}): Unexpected error processing unsynced entry for DID {did_to_block} (DB ID: {original_block_db_id}): {e_outer}", exc_info=True)
        
        logger.info(f"PRIMARY_SYNC ({self.handle}): Finished syncing blocks from other managed accounts.")


    async def update_moderation_list_items(self):
        if not self.is_primary or not self.mod_list_uri:
            logger.debug(f"MOD_LIST_SYNC ({self.handle}): Not primary or mod_list_uri not set. Skipping full moderation list update.")
            return

        logger.info(f"MOD_LIST_SYNC ({self.handle}): Performing full sync of moderation list {self.mod_list_uri} based on DB state...")
        try:
            all_intended_dids_on_list_records = self.database.get_all_dids_primary_should_list(self.account_id)
            intended_dids_on_list = {record['did'] for record in all_intended_dids_on_list_records}
            logger.info(f"MOD_LIST_SYNC ({self.handle}): DB indicates {len(intended_dids_on_list)} DIDs should be on the moderation list.")
        except Exception as e:
            logger.error(f"MOD_LIST_SYNC ({self.handle}): Could not fetch DIDs that should be on the moderation list from DB: {e}", exc_info=True)
            return

        current_dids_on_list = set()
        list_items_uris_by_did = {} 
        cursor = None
        logger.info(f"MOD_LIST_SYNC ({self.handle}): Fetching current items from moderation list {self.mod_list_uri} on Bluesky...")
        try:
            page_num = 0
            while True:
                page_num += 1
                logger.debug(f"MOD_LIST_SYNC ({self.handle}): Fetching page {page_num} of list items. Cursor: {cursor}")
                params = GetListParams(list=self.mod_list_uri, limit=100, cursor=cursor)
                response = await self.client.app.bsky.graph.get_list(params=params)
                
                if not response or not response.items:
                    logger.debug(f"MOD_LIST_SYNC ({self.handle}): No items in page {page_num} or empty response. End of list.")
                    break
                
                logger.debug(f"MOD_LIST_SYNC ({self.handle}): Page {page_num} has {len(response.items)} items.")
                for item_idx, item in enumerate(response.items):
                    if hasattr(item.subject, 'did'):
                        subject_did = item.subject.did
                        current_dids_on_list.add(subject_did)
                        list_items_uris_by_did[subject_did] = item.uri 
                        # logger.debug(f"MOD_LIST_SYNC ({self.handle}): Item {item_idx}: DID {subject_did}, URI {item.uri}")
                    else: 
                        logger.warning(f"MOD_LIST_SYNC ({self.handle}): List item {item.uri} in {self.mod_list_uri} has unexpected subject type: {type(item.subject)}. Data: {item.subject}")

                cursor = response.cursor
                if not cursor:
                    logger.debug(f"MOD_LIST_SYNC ({self.handle}): No more cursor from Bluesky. End of list.")
                    break
                await asyncio.sleep(0.1) 
            logger.info(f"MOD_LIST_SYNC ({self.handle}): Found {len(current_dids_on_list)} DIDs currently on moderation list {self.mod_list_uri} via Bluesky API.")
        except Exception as e:
            logger.error(f"MOD_LIST_SYNC ({self.handle}): Error fetching current items from moderation list {self.mod_list_uri}: {e}", exc_info=True)
            return

        dids_to_add = intended_dids_on_list - current_dids_on_list
        dids_to_remove = current_dids_on_list - intended_dids_on_list

        logger.info(f"MOD_LIST_SYNC ({self.handle}): Comparison complete. DIDs to add: {len(dids_to_add)}, DIDs to remove: {len(dids_to_remove)}")

        if dids_to_add:
            logger.info(f"MOD_LIST_SYNC ({self.handle}): Adding {len(dids_to_add)} DIDs to moderation list {self.mod_list_uri}...")
            for i, did_to_add in enumerate(list(dids_to_add)): 
                try:
                    logger.debug(f"MOD_LIST_SYNC ({self.handle}): Adding DID {did_to_add} ({i+1}/{len(dids_to_add)})...")
                    list_item_record = ListItemRecord(
                        subject=did_to_add, list=self.mod_list_uri,
                        created_at=self.client.get_current_time_iso()
                    )
                    data = CreateRecordData(
                        repo=self.did, 
                        collection='app.bsky.graph.listitem',
                        record=list_item_record.model_dump(exclude_none=True, by_alias=True)
                    )
                    await self.client.com.atproto.repo.create_record(data=data)
                    logger.info(f"MOD_LIST_SYNC ({self.handle}): Successfully added {did_to_add} to mod list.")
                    await asyncio.sleep(0.1) 
                except Exception as e:
                     if "Conflict" in str(e) or "Record already exists" in str(e):
                        logger.debug(f"MOD_LIST_SYNC ({self.handle}): Item {did_to_add} likely already added to mod list (Conflict/Exists). Error: {e}")
                     else:
                        logger.error(f"MOD_LIST_SYNC ({self.handle}): Error adding {did_to_add} to mod list {self.mod_list_uri}: {e}", exc_info=True)
        
        if dids_to_remove:
            logger.info(f"MOD_LIST_SYNC ({self.handle}): Removing {len(dids_to_remove)} DIDs from moderation list {self.mod_list_uri}...")
            for i, did_to_remove in enumerate(list(dids_to_remove)):
                list_item_uri = list_items_uris_by_did.get(did_to_remove)
                if not list_item_uri:
                    logger.warning(f"MOD_LIST_SYNC ({self.handle}): Could not find list item URI for DID {did_to_remove} to remove it. Skipping.")
                    continue
                try:
                    rkey = list_item_uri.split('/')[-1]
                    logger.debug(f"MOD_LIST_SYNC ({self.handle}): Removing DID {did_to_remove} (rkey: {rkey}) ({i+1}/{len(dids_to_remove)})...")
                    await self.client.com.atproto.repo.delete_record(
                        repo=self.did, collection='app.bsky.graph.listitem', rkey=rkey
                    )
                    logger.info(f"MOD_LIST_SYNC ({self.handle}): Successfully removed {did_to_remove} (rkey: {rkey}) from mod list.")
                    await asyncio.sleep(0.1) 
                except Exception as e:
                    logger.error(f"MOD_LIST_SYNC ({self.handle}): Error removing {did_to_remove} (rkey: {rkey}) from mod list {self.mod_list_uri}: {e}", exc_info=True)
        
        logger.info(f"MOD_LIST_SYNC ({self.handle}): Full moderation list sync completed.")

    async def sync_mod_list_with_database(self):
        """Sync moderation list with the database for primary account"""
        if not self.is_primary:
            logger.debug(f"MOD_LIST_SYNC ({self.handle}): Not a primary account, skipping moderation list sync")
            return False
        
        logger.info(f"MOD_LIST_SYNC ({self.handle}): Syncing moderation list with database...")
        try:
            # Use the function from test_mod_list_sync.py
            success = await sync_mod_list_from_db()
            if success:
                logger.info(f"MOD_LIST_SYNC ({self.handle}): Successfully synchronized blocks to moderation list")
            else:
                logger.error(f"MOD_LIST_SYNC ({self.handle}): Failed to synchronize blocks to moderation list")
            return success
        except Exception as e:
            logger.error(f"MOD_LIST_SYNC ({self.handle}): Error synchronizing blocks to moderation list: {e}", exc_info=True)
            return False

    async def sync_all_account_data(self, initial_sync=False):
        """
        Synchronize all data for this account
        
        Args:
            initial_sync: If True, perform a full sync including ClearSky data
        """
        if self._blocks_monitor_stop_event.is_set():
            logger.info(f"BLOCKS_MONITOR ({self.handle}): Stop event set, skipping full sync")
            return
            
        logger.info(f"BLOCKS_MONITOR ({self.handle}): Running {'full' if initial_sync else 'regular'} account data sync for {self.handle}...")
        
        try:
            # Always fetch blocks from Bluesky API
            logger.info(f"BLOCKS_MONITOR ({self.handle}): Fetching current blocks from Bluesky API...")
            await self.fetch_bluesky_blocks()
            
            # If this is an initial sync or full sync, fetch blocked-by accounts from ClearSky
            if initial_sync:
                logger.info(f"BLOCKS_MONITOR ({self.handle}): Fetching accounts that block this account from ClearSky...")
                try:
                    start_time = time.time()
                    
                    # Use our enhanced pagination-aware helper
                    logger.info(f"BLOCKS_MONITOR ({self.handle}): Using enhanced pagination for blocked-by accounts")
                    blockers, total_count = await cs.fetch_all_blocked_by(self.did)
                    
                    # Process the blocked-by records
                    logger.info(f"BLOCKS_MONITOR ({self.handle}): Processing {len(blockers)} blocked-by records from ClearSky")
                    processed_dids = set()  # To track DIDs we've already processed
                    
                    for blocker in blockers:
                        if 'did' not in blocker:
                            logger.warning(f"BLOCKS_MONITOR ({self.handle}): Skipping blocked-by record missing DID: {blocker}")
                            continue
                            
                        did = blocker['did']
                        
                        # Skip if we've already processed this DID (handle duplicates)
                        if did in processed_dids:
                            logger.debug(f"BLOCKS_MONITOR ({self.handle}): Skipping duplicate DID: {did}")
                            continue
                            
                        processed_dids.add(did)
                        
                        try:
                            # Add to database
                            self.database.add_blocked_account(
                                did=did, 
                                handle=None,  # Handle can be resolved later if needed
                                source_account_id=self.account_id, 
                                block_type='blocked_by'
                            )
                        except Exception as e:
                            logger.error(f"BLOCKS_MONITOR ({self.handle}): Error adding blocked-by DID {did} to DB: {e}", exc_info=True)
                    
                    # Remove stale entries
                    logger.info(f"BLOCKS_MONITOR ({self.handle}): Removing stale blocked-by entries from DB...")
                    self.database.remove_stale_blocks(self.account_id, 'blocked_by', list(processed_dids))
                    
                    elapsed_time = time.time() - start_time
                    logger.info(f"BLOCKS_MONITOR ({self.handle}): Processed {len(processed_dids)} unique blocked-by DIDs in {elapsed_time:.2f} seconds")
                    
                except Exception as e:
                    logger.error(f"BLOCKS_MONITOR ({self.handle}): Error fetching or processing blocked-by accounts: {e}", exc_info=True)
            
            # Only primary accounts do these operations
            if self.is_primary:
                # Ensure moderation list is created/updated
                if not self.mod_list_uri:
                    await self.create_or_update_moderation_list()
                
                # Sync blocks from other (secondary) accounts
                await self.sync_blocks_from_others()
                
                # Sync moderation list with the database (ensures all blocks are reflected in mod list)
                await self.sync_mod_list_with_database()
            
            logger.info(f"BLOCKS_MONITOR ({self.handle}): {'Full' if initial_sync else 'Regular'} account data sync completed for {self.handle}")
        except Exception as e:
            logger.error(f"BLOCKS_MONITOR ({self.handle}): Error during {'full' if initial_sync else 'regular'} account data sync: {e}", exc_info=True)

    async def _blocks_monitor_loop(self):
        sync_interval_primary_min = int(os.getenv('SYNC_INTERVAL_PRIMARY_MINUTES', 15))
        sync_interval_secondary_min = int(os.getenv('SYNC_INTERVAL_SECONDARY_MINUTES', 60))
        
        sync_interval_seconds = (sync_interval_primary_min if self.is_primary else sync_interval_secondary_min) * 60
        
        # Track when the last full ClearSky sync was performed
        last_full_clearsky_sync = datetime.now() - timedelta(hours=FULL_SYNC_INTERVAL_HOURS + 1)  # Force an initial full sync

        logger.info(f"LEGACY_MONITOR ({self.handle}): Performing initial data sync cycle as part of loop startup...")
        try:
            # Set initial_sync=True to perform a complete sync, including ClearSky data
            await self.sync_all_account_data(initial_sync=True) 
            last_full_clearsky_sync = datetime.now()  # Update after successful sync
            logger.info(f"LEGACY_MONITOR ({self.handle}): Initial full sync completed. Next full ClearSky sync scheduled for {last_full_clearsky_sync + timedelta(hours=FULL_SYNC_INTERVAL_HOURS)}")
        except Exception as e_initial_sync:
            logger.error(f"LEGACY_MONITOR ({self.handle}): Error during initial data sync in monitor loop: {e_initial_sync}", exc_info=True)
        
        logger.info(f"LEGACY_MONITOR ({self.handle}): Loop started. Will run regular sync every {sync_interval_seconds // 60} minutes, and full ClearSky sync every {FULL_SYNC_INTERVAL_HOURS} hours.")
        self._blocks_monitor_stop_event.clear()

        while not self._blocks_monitor_stop_event.is_set():
            try:
                logger.debug(f"LEGACY_MONITOR ({self.handle}): Waiting for {sync_interval_seconds}s or stop event...")
                await asyncio.wait_for(self._blocks_monitor_stop_event.wait(), timeout=sync_interval_seconds)
                
                # If wait_for didn't timeout, it means stop_event was set
                if self._blocks_monitor_stop_event.is_set():
                    logger.info(f"LEGACY_MONITOR ({self.handle}): Stop event received, exiting loop.")
                    break 
            except asyncio.TimeoutError:
                # Timeout means stop event was not set, time to sync
                now = datetime.now()
                time_since_full_sync = now - last_full_clearsky_sync
                needs_full_clearsky_sync = time_since_full_sync.total_seconds() >= FULL_SYNC_INTERVAL_HOURS * 3600
                
                if needs_full_clearsky_sync:
                    logger.info(f"LEGACY_MONITOR ({self.handle}): {FULL_SYNC_INTERVAL_HOURS} hours since last full sync. Performing full ClearSky data sync...")
                    try:
                        # Run a complete sync including ClearSky data
                        await self.sync_all_account_data(initial_sync=True)
                        last_full_clearsky_sync = now
                        logger.info(f"LEGACY_MONITOR ({self.handle}): Full ClearSky sync completed. Next full sync scheduled for {last_full_clearsky_sync + timedelta(hours=FULL_SYNC_INTERVAL_HOURS)}")
                    except Exception as e_full_sync:
                        logger.error(f"LEGACY_MONITOR ({self.handle}): Error during full ClearSky sync: {e_full_sync}", exc_info=True)
                else:
                    logger.info(f"LEGACY_MONITOR ({self.handle}): Performing regular sync cycle (next full ClearSky sync in {FULL_SYNC_INTERVAL_HOURS - (time_since_full_sync.total_seconds() / 3600):.1f} hours)...")
                    try:
                        # Run a regular sync without ClearSky data
                        await self.sync_all_account_data(initial_sync=False)
                    except Exception as e_regular_sync:
                        logger.error(f"LEGACY_MONITOR ({self.handle}): Error during regular sync: {e_regular_sync}", exc_info=True)
            except asyncio.CancelledError:
                logger.info(f"LEGACY_MONITOR ({self.handle}): Loop was cancelled.")
                break
            except Exception as e_loop: 
                logger.error(f"LEGACY_MONITOR ({self.handle}): Unexpected error in loop: {e_loop}", exc_info=True)
                logger.info(f"LEGACY_MONITOR ({self.handle}): Waiting 60s before trying loop logic again after unexpected error.")
                await asyncio.sleep(60) 
        logger.info(f"LEGACY_MONITOR ({self.handle}): Loop has finished.") 