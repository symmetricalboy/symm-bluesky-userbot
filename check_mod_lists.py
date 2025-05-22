#!/usr/bin/env python3
import asyncio
from database import Database

async def check_mod_lists():
    db = Database()
    
    print("=== PRODUCTION MOD_LISTS TABLE ===")
    prod_lists = await db.execute_query('SELECT * FROM mod_lists ORDER BY created_at')
    for i, lst in enumerate(prod_lists, 1):
        print(f"{i}. URI: {lst['list_uri']}")
        print(f"   Name: {lst['name']}")
        print(f"   Created: {lst['created_at']}")
        print()
    
    print("=== TEST MOD_LISTS TABLE ===")
    try:
        test_lists = await db.execute_query('SELECT * FROM mod_lists_test ORDER BY created_at')
        for i, lst in enumerate(test_lists, 1):
            print(f"{i}. URI: {lst['list_uri']}")
            print(f"   Name: {lst['name']}")
            print(f"   Created: {lst['created_at']}")
            print()
    except Exception as e:
        print(f"Test table doesn't exist or error: {e}")

if __name__ == "__main__":
    asyncio.run(check_mod_lists()) 