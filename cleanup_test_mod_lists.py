#!/usr/bin/env python3
import asyncio
from database import Database

async def cleanup_test_tables():
    db = Database()
    
    print("=== CLEANING UP TEST MOD_LISTS TABLE ===")
    
    # Keep only the same list that's in production
    primary_uri = "at://did:plc:33d7gnwiagm6cimpiepefp72/app.bsky.graph.list/3lprokilplg25"
    
    # Delete all other records from test table
    deleted_count = await db.execute_query(
        'DELETE FROM mod_lists_test WHERE list_uri != $1',
        [primary_uri],
        commit=True
    )
    print(f"Deleted {deleted_count} duplicate records from test table")
    
    # Check final state
    print("\n=== FINAL STATE ===")
    
    print("Production table:")
    prod_lists = await db.execute_query('SELECT * FROM mod_lists ORDER BY created_at')
    for lst in prod_lists:
        print(f"  - {lst['list_uri']} ({lst['name']})")
    
    print("Test table:")
    test_lists = await db.execute_query('SELECT * FROM mod_lists_test ORDER BY created_at')
    for lst in test_lists:
        print(f"  - {lst['list_uri']} ({lst['name']})")

if __name__ == "__main__":
    asyncio.run(cleanup_test_tables()) 