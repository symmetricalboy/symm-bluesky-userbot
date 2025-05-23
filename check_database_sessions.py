#!/usr/bin/env python3
"""
Check Database Sessions

Quick script to check which accounts have sessions stored in the database.
"""

import asyncio
from database import Database

async def check_sessions():
    db = Database()
    handles = ['symm.social', 'symm.app', 'symm.now', 'gemini.is-a.bot', 'this.is-a.bot']
    
    print('🔍 Checking sessions in database:')
    for handle in handles:
        try:
            session = await db.load_session_data(handle)
            if session:
                print(f'✅ {handle}: Session exists (DID: {session["did"]})')
            else:
                print(f'❌ {handle}: No session found')
        except Exception as e:
            print(f'❌ {handle}: Error - {e}')

if __name__ == "__main__":
    asyncio.run(check_sessions()) 