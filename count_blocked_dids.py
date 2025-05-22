import asyncio
from database import Database

async def count_database_blocked_dids():
    try:
        print("Connecting to production database...")
        db = Database(test_mode=False)
        
        if not await db.test_connection():
            print("Database connection failed")
            return
            
        # Get primary account for reference
        primary_account = await db.get_primary_account()
        if not primary_account:
            print("No primary account found in database")
            return
            
        print(f"Primary account: {primary_account['did']}")
        
        # Count all DIDs in the database
        print("Counting all DIDs in database...")
        query_all = "SELECT COUNT(DISTINCT did) FROM blocked_accounts"
        result_all = await db.execute_query(query_all)
        unique_dids_count = result_all[0]['count']
        print(f"Total unique DIDs in database: {unique_dids_count}")
        
        # Count DIDs for moderation list
        print("Counting DIDs that should be in moderation list...")
        all_dids_to_list = await db.get_all_dids_primary_should_list(primary_account['id'])
        blocked_dids = set()
        for did_record in all_dids_to_list:
            blocked_dids.add(did_record['did'])
        
        print(f"DIDs that should be in moderation list: {len(blocked_dids)}")
        
        # Get some sample DIDs if there are any
        if blocked_dids:
            sample_count = min(5, len(blocked_dids))
            samples = list(blocked_dids)[:sample_count]
            print(f"Sample DIDs: {samples}")
            
        print("=== SUMMARY ===")
        print(f"Total unique DIDs in database: {unique_dids_count}")
        print(f"DIDs that should be in moderation list: {len(blocked_dids)}")
        print(f"DIDs that need to be added: {len(blocked_dids) - 681}")  # 681 is from our previous count
        print("===============")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(count_database_blocked_dids()) 