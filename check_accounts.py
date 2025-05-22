import asyncio
from database import Database

async def check_accounts():
    db = Database()
    accounts = await db.get_account_configurations()
    print('=== ACCOUNTS ===')
    for account in accounts['accounts']:
        print(f'ID: {account["id"]}, Handle: {account["handle"]}, DID: {account["did"]}, Primary: {account["is_primary"]}')
    
    print('\n=== MOD LISTS ===')
    mod_lists = await db.execute_query('SELECT * FROM mod_lists ORDER BY id')
    for mod_list in mod_lists:
        print(f'ID: {mod_list["id"]}, URI: {mod_list["list_uri"]}, Owner: {mod_list["owner_did"]}, Name: {mod_list["name"]}')

if __name__ == "__main__":
    asyncio.run(check_accounts()) 