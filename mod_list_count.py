import os
import asyncio
from dotenv import load_dotenv
from atproto import AsyncClient

# Load environment variables
load_dotenv()

async def count_mod_list_items():
    try:
        # Login to Bluesky
        primary_handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
        primary_password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
        
        if not primary_handle or not primary_password:
            print("Missing account credentials in .env file")
            return
        
        print(f"Logging in as {primary_handle}...")
        client = AsyncClient()
        await client.login(primary_handle, primary_password)
        print(f"Login successful as {client.me.did}")
        
        # Get lists
        print("Getting lists...")
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
        
        # Count items
        print("Counting items in moderation list...")
        cursor = None
        page_count = 0
        total_items = 0
        
        while True:
            page_count += 1
            list_items_response = await client.app.bsky.graph.get_list({
                "list": mod_list.uri,
                "limit": 100,
                "cursor": cursor
            })
            
            if not hasattr(list_items_response, 'items') or not list_items_response.items:
                break
                
            items_this_page = len(list_items_response.items)
            total_items += items_this_page
            
            print(f"Page {page_count}: Retrieved {items_this_page} items. Total so far: {total_items}")
            
            cursor = list_items_response.cursor
            if not cursor:
                break
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
        
        print(f"Total items in list: {total_items}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(count_mod_list_items()) 