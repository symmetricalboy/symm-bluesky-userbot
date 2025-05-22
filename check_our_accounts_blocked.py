#!/usr/bin/env python3
"""
Check if our own accounts are incorrectly in the blocked_accounts table
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_blocked_accounts():
    # Get database connection
    test_database_url = os.getenv('TEST_DATABASE_URL')
    if test_database_url:
        conn = await asyncpg.connect(test_database_url)
    else:
        host = os.getenv('DB_HOST', 'localhost')
        port = int(os.getenv('DB_PORT', '5432'))
        database = os.getenv('DB_NAME', 'symm_blocks')
        user = os.getenv('DB_USER', 'postgres')
        password = os.getenv('DB_PASSWORD', '')
        conn = await asyncpg.connect(host=host, port=port, database=database, user=user, password=password)
    
    try:
        # Get our account DIDs
        accounts = await conn.fetch('SELECT handle, did FROM accounts ORDER BY handle')
        our_dids = [acc['did'] for acc in accounts]
        
        print('=== OUR ACCOUNTS ===')
        for acc in accounts:
            print(f'{acc["handle"]}: {acc["did"]}')
        
        print('\n=== CHECKING IF OUR ACCOUNTS ARE IN BLOCKED_ACCOUNTS TABLE ===')
        
        # Check if any of our DIDs are in the blocked_accounts table
        any_problems = False
        for acc in accounts:
            did = acc['did']
            handle = acc['handle']
            blocked_entries = await conn.fetch('SELECT * FROM blocked_accounts WHERE did = $1', did)
            if blocked_entries:
                any_problems = True
                print(f'❌ PROBLEM: {handle} ({did}) found in blocked_accounts table:')
                for entry in blocked_entries:
                    source_account = await conn.fetchrow('SELECT handle FROM accounts WHERE id = $1', entry['source_account_id'])
                    source_handle = source_account['handle'] if source_account else f"ID:{entry['source_account_id']}"
                    print(f'   Block Type: {entry["block_type"]}, Source: {source_handle}, Reason: {entry["reason"]}')
            else:
                print(f'✅ GOOD: {handle} NOT in blocked_accounts table')
        
        if not any_problems:
            print('\n🎉 EXCELLENT: None of our accounts are in the blocked_accounts table!')
        else:
            print('\n⚠️  WARNING: Some of our accounts are in the blocked_accounts table - this needs to be fixed!')
            
        # Also check total blocked accounts count
        total_blocked = await conn.fetchval('SELECT COUNT(*) FROM blocked_accounts')
        print(f'\nTotal entries in blocked_accounts table: {total_blocked}')
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_blocked_accounts()) 