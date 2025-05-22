#!/usr/bin/env python3
"""
Cleanup script for duplicate moderation lists

This script will:
1. Find all moderation lists in the database 
2. Find all moderation lists on Bluesky for the primary account
3. Identify duplicates and inconsistencies  
4. Consolidate to a single list with updated name/description from environment
5. Remove orphaned database records and extra Bluesky lists
"""

import asyncio
import os
import logging
from typing import List, Dict, Any
from atproto import AsyncClient as ATProtoAsyncClient
from database import Database

# Set up logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

async def get_bluesky_mod_lists(client: ATProtoAsyncClient, did: str) -> List[Dict[str, Any]]:
    """Get all moderation lists owned by a DID from Bluesky API."""
    mod_lists = []
    try:
        lists_response = await client.app.bsky.graph.get_lists(params={"actor": did})
        for lst in lists_response.lists:
            if lst.purpose == 'app.bsky.graph.defs#modlist':
                mod_lists.append({
                    'uri': lst.uri,
                    'cid': str(lst.cid) if hasattr(lst, 'cid') else 'unknown',
                    'name': lst.name,
                    'description': getattr(lst, 'description', ''),
                    'indexed_at': lst.indexed_at
                })
    except Exception as e:
        logger.error(f"Error fetching moderation lists from Bluesky: {e}")
    
    return mod_lists

async def delete_bluesky_list(client: ATProtoAsyncClient, list_uri: str) -> bool:
    """Delete a moderation list from Bluesky."""
    try:
        rkey = list_uri.split('/')[-1]
        from atproto_client.models.com.atproto.repo.delete_record import Data as DeleteRecordData
        
        data = DeleteRecordData(
            repo=client.me.did,
            collection='app.bsky.graph.list',
            rkey=rkey
        )
        
        await client.com.atproto.repo.delete_record(data=data)
        logger.info(f"Deleted Bluesky moderation list: {list_uri}")
        return True
    except Exception as e:
        logger.error(f"Error deleting Bluesky list {list_uri}: {e}")
        return False

async def cleanup_duplicate_mod_lists():
    """Main cleanup function."""
    logger.info("=== MODERATION LIST CLEANUP STARTING ===")
    
    # Initialize database
    db = Database()
    
    if not await db.test_connection():
        logger.error("Database connection failed")
        return False
    
    # Get primary account credentials  
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        logger.error("Primary account credentials not found")
        return False
    
    # Login to Bluesky
    client = ATProtoAsyncClient()
    try:
        profile = await client.login(primary_handle, primary_password)
        primary_did = profile.did
        logger.info(f"Logged in as: {primary_handle} (DID: {primary_did})")
    except Exception as e:
        logger.error(f"Failed to login: {e}")
        return False
    
    # Get desired list configuration from environment
    target_name = os.getenv('MOD_LIST_NAME', 'Synchronized Blocks')
    target_description = os.getenv('MOD_LIST_DESCRIPTION', 'This list contains accounts that are blocked by any of our managed accounts')
    
    logger.info(f"Target list configuration:")
    logger.info(f"  Name: {target_name}")
    logger.info(f"  Description: {target_description}")
    
    # Step 1: Get moderation lists from database
    logger.info("\n=== STEP 1: DATABASE INSPECTION ===")
    db_mod_lists = await db.get_mod_lists_by_owner(primary_did)
    logger.info(f"Found {len(db_mod_lists)} moderation lists in database:")
    for idx, db_list in enumerate(db_mod_lists, 1):
        logger.info(f"  {idx}. URI: {db_list['list_uri']}")
        logger.info(f"     Name: {db_list['name']}")
        logger.info(f"     Created: {db_list['created_at']}")
    
    # Step 2: Get moderation lists from Bluesky
    logger.info("\n=== STEP 2: BLUESKY INSPECTION ===") 
    bluesky_mod_lists = await get_bluesky_mod_lists(client, primary_did)
    logger.info(f"Found {len(bluesky_mod_lists)} moderation lists on Bluesky:")
    for idx, bs_list in enumerate(bluesky_mod_lists, 1):
        logger.info(f"  {idx}. URI: {bs_list['uri']}")
        logger.info(f"     Name: {bs_list['name']}")
        logger.info(f"     Description: {bs_list['description']}")
    
    # Step 3: Identify inconsistencies
    logger.info("\n=== STEP 3: INCONSISTENCY ANALYSIS ===")
    
    # Check for orphaned database records (not on Bluesky)
    bluesky_uris = {lst['uri'] for lst in bluesky_mod_lists}
    orphaned_db_records = [lst for lst in db_mod_lists if lst['list_uri'] not in bluesky_uris]
    
    if orphaned_db_records:
        logger.warning(f"Found {len(orphaned_db_records)} orphaned database records:")
        for record in orphaned_db_records:
            logger.warning(f"  - {record['list_uri']} (name: {record['name']})")
    
    # Check for unregistered Bluesky lists (not in database)
    db_uris = {lst['list_uri'] for lst in db_mod_lists}
    unregistered_bluesky_lists = [lst for lst in bluesky_mod_lists if lst['uri'] not in db_uris]
    
    if unregistered_bluesky_lists:
        logger.warning(f"Found {len(unregistered_bluesky_lists)} unregistered Bluesky lists:")
        for bs_list in unregistered_bluesky_lists:
            logger.warning(f"  - {bs_list['uri']} (name: {bs_list['name']})")
    
    # Step 4: Determine cleanup strategy
    logger.info("\n=== STEP 4: CLEANUP STRATEGY ===")
    
    if len(bluesky_mod_lists) == 0:
        logger.info("No moderation lists found. Will create a new one.")
        primary_list_uri = None
    elif len(bluesky_mod_lists) == 1:
        primary_list_uri = bluesky_mod_lists[0]['uri']
        logger.info(f"Single moderation list found, will keep: {primary_list_uri}")
    else:
        # Multiple lists found - need to consolidate
        logger.warning(f"Multiple moderation lists found ({len(bluesky_mod_lists)}), need to consolidate")
        
        # Choose the oldest one as primary (most likely the original)
        primary_list = min(bluesky_mod_lists, key=lambda x: x['indexed_at'])
        primary_list_uri = primary_list['uri']
        logger.info(f"Selected primary list (oldest): {primary_list_uri}")
        
        # Mark others for deletion
        lists_to_delete = [lst for lst in bluesky_mod_lists if lst['uri'] != primary_list_uri]
        logger.info(f"Will delete {len(lists_to_delete)} duplicate lists:")
        for lst in lists_to_delete:
            logger.info(f"  - {lst['uri']} (name: {lst['name']})")
    
    # Step 5: Execute cleanup
    logger.info("\n=== STEP 5: EXECUTING CLEANUP ===")
    
    # Clean up orphaned database records
    for orphaned_record in orphaned_db_records:
        try:
            await db.execute_query(
                "DELETE FROM mod_lists WHERE list_uri = $1",
                [orphaned_record['list_uri']], 
                commit=True
            )
            logger.info(f"Deleted orphaned database record: {orphaned_record['list_uri']}")
        except Exception as e:
            logger.error(f"Error deleting orphaned database record {orphaned_record['list_uri']}: {e}")
    
    # Delete duplicate Bluesky lists if we have multiple
    if len(bluesky_mod_lists) > 1:
        for lst in lists_to_delete:
            success = await delete_bluesky_list(client, lst['uri'])
            if success:
                # Also remove from database if it exists
                try:
                    await db.execute_query(
                        "DELETE FROM mod_lists WHERE list_uri = $1",
                        [lst['uri']], 
                        commit=True
                    )
                    logger.info(f"Deleted database record for deleted list: {lst['uri']}")
                except Exception as e:
                    logger.error(f"Error deleting database record for {lst['uri']}: {e}")
    
    # Step 6: Ensure primary list exists and is properly configured
    logger.info("\n=== STEP 6: ENSURING PRIMARY LIST ===")
    
    if not primary_list_uri:
        # Create new list
        logger.info("Creating new moderation list...")
        from atproto_client.models.app.bsky.graph.list import Record as ListRecord
        from atproto_client.models.com.atproto.repo.create_record import Data as CreateRecordData
        
        list_record_data = ListRecord(
            purpose='app.bsky.graph.defs#modlist',
            name=target_name,
            description=target_description,
            created_at=client.get_current_time_iso()
        )
        
        data = CreateRecordData(
            repo=primary_did,
            collection='app.bsky.graph.list',
            record=list_record_data.model_dump(exclude_none=True, by_alias=True)
        )
        
        response = await client.com.atproto.repo.create_record(data=data)
        primary_list_uri = response.uri
        list_cid = str(response.cid)
        
        logger.info(f"Created new moderation list: {primary_list_uri}")
        
        # Register in database
        await db.register_mod_list(
            list_uri=primary_list_uri,
            list_cid=list_cid,
            owner_did=primary_did,
            name=target_name
        )
        logger.info("Registered new moderation list in database")
    
    else:
        # Update existing list if needed
        logger.info(f"Checking if primary list needs updates: {primary_list_uri}")
        
        # Get current list details
        current_list = next((lst for lst in bluesky_mod_lists if lst['uri'] == primary_list_uri), None)
        if current_list:
            needs_update = (current_list['name'] != target_name or 
                          current_list['description'] != target_description)
            
            if needs_update:
                logger.info("Updating list name/description...")
                from atproto_client.models.app.bsky.graph.list import Record as ListRecord
                from atproto_client.models.com.atproto.repo.put_record import Data as PutRecordData
                
                list_record_data = ListRecord(
                    purpose='app.bsky.graph.defs#modlist',
                    name=target_name,
                    description=target_description,
                    created_at=current_list['indexed_at']
                )
                
                data = PutRecordData(
                    repo=primary_did,
                    collection='app.bsky.graph.list',
                    rkey=primary_list_uri.split('/')[-1],
                    record=list_record_data.model_dump(exclude_none=True, by_alias=True)
                )
                
                response = await client.com.atproto.repo.put_record(data=data)
                logger.info(f"Updated moderation list name/description")
                
                # Update database record
                await db.update_mod_list_name_description(primary_list_uri, target_name, target_description)
                logger.info("Updated database record")
            else:
                logger.info("List name/description already correct")
        
        # Ensure it's registered in database
        current_db_record = next((lst for lst in db_mod_lists if lst['list_uri'] == primary_list_uri), None)
        if not current_db_record:
            logger.info("Registering existing list in database...")
            await db.register_mod_list(
                list_uri=primary_list_uri,
                list_cid=current_list['cid'] if current_list else 'unknown',
                owner_did=primary_did,
                name=target_name
            )
            logger.info("Registered existing list in database")
    
    # Step 7: Final verification
    logger.info("\n=== STEP 7: FINAL VERIFICATION ===")
    
    # Re-check database
    final_db_lists = await db.get_mod_lists_by_owner(primary_did)
    logger.info(f"Final database state: {len(final_db_lists)} moderation lists")
    for lst in final_db_lists:
        logger.info(f"  - {lst['list_uri']} (name: {lst['name']})")
    
    # Re-check Bluesky
    final_bluesky_lists = await get_bluesky_mod_lists(client, primary_did)
    logger.info(f"Final Bluesky state: {len(final_bluesky_lists)} moderation lists")
    for lst in final_bluesky_lists:
        logger.info(f"  - {lst['uri']} (name: {lst['name']})")
    
    if len(final_db_lists) == 1 and len(final_bluesky_lists) == 1:
        if final_db_lists[0]['list_uri'] == final_bluesky_lists[0]['uri']:
            logger.info("✅ SUCCESS: Single consistent moderation list found!")
            logger.info(f"   URI: {final_db_lists[0]['list_uri']}")
            logger.info(f"   Name: {final_db_lists[0]['name']}")
            return True
    
    logger.error("❌ INCONSISTENT STATE: Cleanup did not result in single consistent list")
    return False

if __name__ == "__main__":
    asyncio.run(cleanup_duplicate_mod_lists()) 