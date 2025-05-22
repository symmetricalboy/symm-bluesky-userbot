#!/usr/bin/env python3
import asyncio
from database import Database

async def cleanup_db():
    db = Database()
    await db.execute_query(
        'DELETE FROM mod_lists WHERE list_uri = $1',
        ['at://did:plc:33d7gnwiagm6cimpiepefp72/app.bsky.graph.list/3lprp3u6tap2h'],
        commit=True
    )
    print('Cleaned up orphaned database record')

if __name__ == "__main__":
    asyncio.run(cleanup_db()) 