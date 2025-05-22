import os
import asyncio
import time
from datetime import datetime
from dotenv import load_dotenv
from atproto import AsyncClient

# Load environment variables
load_dotenv()

# Constants
DELAY_AFTER_SUCCESS = 2.0  # Seconds between successful adds
DELAY_AFTER_ERROR = 5.0    # Seconds to wait after an error
DELAY_AFTER_RATE_LIMIT = 600  # 10 minutes after rate limit
DIDS_FILE = "dids_to_add.txt"  # File containing DIDs to add

async def add_one_did():
    """
    Add a single DID to the moderation list and update the file.
    """
    print(f"Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if DIDs file exists
    if not os.path.exists(DIDS_FILE):
        print(f"DIDs file '{DIDS_FILE}' not found.")
        print("Please create this file with one DID per line.")
        return
    
    # Read all DIDs from file
    with open(DIDS_FILE, 'r') as f:
        all_dids = [line.strip() for line in f.readlines() if line.strip()]
    
    if not all_dids:
        print(f"No DIDs found in {DIDS_FILE}")
        return
        
    print(f"Found {len(all_dids)} DIDs to process")
    
    # Show first DID to process
    first_did = all_dids[0]
    print(f"Next DID to add: {first_did}")
    
    # Get confirmation
    choice = input("Add this DID? (y/n): ").lower()
    if choice != 'y':
        print("Operation canceled.")
        return
    
    # Login to Bluesky
    primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not primary_handle or not primary_password:
        print("Missing account credentials in .env file")
        return
    
    print(f"Logging in as {primary_handle}...")
    client = AsyncClient()
    try:
        await client.login(primary_handle, primary_password)
        print(f"Login successful as {client.me.did}")
    except Exception as e:
        print(f"Login failed: {e}")
        return
    
    # Get lists
    print("Getting moderation lists...")
    lists_response = await client.app.bsky.graph.get_lists(params={"actor": client.me.did})
    
    # Find moderation lists
    mod_lists = [lst for lst in lists_response.lists if lst.purpose == 'app.bsky.graph.defs#modlist']
    print(f"Found {len(mod_lists)} moderation lists")
    
    if not mod_lists:
        print("No moderation lists found")
        return
        
    # Use the first moderation list
    mod_list = mod_lists[0]
    print(f"Using list: '{mod_list.name}' ({mod_list.uri})")
    
    # Try to add the DID
    try:
        print(f"Adding DID: {first_did}")
        list_item_record = {
            "$type": "app.bsky.graph.listitem",
            "subject": first_did,
            "list": mod_list.uri,
            "createdAt": client.get_current_time_iso()
        }
        
        await client.com.atproto.repo.create_record({
            "repo": client.me.did,
            "collection": "app.bsky.graph.listitem",
            "record": list_item_record
        })
        
        print(f"Successfully added DID: {first_did}")
        
        # Update the file to remove the processed DID
        with open(DIDS_FILE, 'w') as f:
            for did in all_dids[1:]:
                f.write(f"{did}\n")
        
        print(f"Updated {DIDS_FILE} - {len(all_dids) - 1} DIDs remaining")
        print(f"Waiting {DELAY_AFTER_SUCCESS}s before next run...")
        
    except Exception as e:
        error_message = str(e).lower()
        
        if "already exists" in error_message or "conflict" in error_message:
            print(f"DID {first_did} already in list - removing from queue")
            # Update the file to remove the processed DID
            with open(DIDS_FILE, 'w') as f:
                for did in all_dids[1:]:
                    f.write(f"{did}\n")
            print(f"Updated {DIDS_FILE} - {len(all_dids) - 1} DIDs remaining")
            
        elif "rate limit" in error_message or "ratelimit" in error_message:
            print(f"Rate limit hit when adding DID {first_did}")
            minutes = DELAY_AFTER_RATE_LIMIT // 60
            print(f"You should wait about {minutes} minutes before trying again")
            
        else:
            print(f"Error adding DID {first_did}: {e}")
            print(f"You should wait about {DELAY_AFTER_ERROR} seconds before trying again")

if __name__ == "__main__":
    asyncio.run(add_one_did()) 