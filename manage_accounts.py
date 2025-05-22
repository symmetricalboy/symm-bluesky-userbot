#!/usr/bin/env python3
"""
Account Management Script

This script allows you to manage Bluesky account configurations stored in the database.
No more hardcoded account lists - everything is stored in the database and can be
updated dynamically.

Usage:
    python manage_accounts.py list                                    # List all accounts
    python manage_accounts.py add <handle> <did> [--primary]          # Add account
    python manage_accounts.py remove <did>                            # Remove account
    python manage_accounts.py set-primary <did>                       # Set as primary
    python manage_accounts.py init                                    # Initialize defaults
"""

import asyncio
import argparse
import sys
from database import Database
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def list_accounts():
    """List all managed accounts."""
    db = Database()
    
    try:
        accounts = await db.get_all_managed_accounts()
        
        if not accounts:
            print("No accounts found in database.")
            return
        
        print(f"\n📋 Managed Accounts ({len(accounts)} total):")
        print("=" * 60)
        
        for account in accounts:
            status = "🔸 PRIMARY" if account['is_primary'] else "🔹 Secondary"
            print(f"{status} {account['handle']}")
            print(f"   DID: {account['did']}")
            print(f"   ID: {account['id']}")
            if account['updated_at']:
                print(f"   Updated: {account['updated_at']}")
            print()
            
    except Exception as e:
        print(f"❌ Error listing accounts: {e}")
        return False
    
    return True

async def add_account(handle: str, did: str, is_primary: bool = False):
    """Add a new managed account."""
    db = Database()
    
    try:
        account_id = await db.add_managed_account(handle, did, is_primary)
        
        status = "PRIMARY" if is_primary else "secondary"
        print(f"✅ Added {status} account: {handle} (DID: {did}) with ID: {account_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error adding account: {e}")
        return False

async def remove_account(did: str):
    """Remove a managed account."""
    db = Database()
    
    try:
        # Get account info first for confirmation
        account = await db.get_account_by_did(did)
        if not account:
            print(f"❌ Account with DID {did} not found.")
            return False
        
        print(f"⚠️  About to remove: {account['handle']} (DID: {did})")
        if account['is_primary']:
            print("   This is a PRIMARY account!")
        
        confirm = input("Are you sure? (yes/no): ").lower()
        if confirm != 'yes':
            print("❌ Operation cancelled.")
            return False
        
        success = await db.remove_managed_account(did)
        
        if success:
            print(f"✅ Removed account: {account['handle']} (DID: {did})")
            return True
        else:
            print(f"❌ Failed to remove account.")
            return False
            
    except Exception as e:
        print(f"❌ Error removing account: {e}")
        return False

async def set_primary(did: str):
    """Set an account as primary."""
    db = Database()
    
    try:
        # Get account info first
        account = await db.get_account_by_did(did)
        if not account:
            print(f"❌ Account with DID {did} not found.")
            return False
        
        if account['is_primary']:
            print(f"ℹ️  {account['handle']} is already the primary account.")
            return True
        
        success = await db.set_primary_account(did)
        
        if success:
            print(f"✅ Set {account['handle']} (DID: {did}) as primary account")
            return True
        else:
            print(f"❌ Failed to set primary account.")
            return False
            
    except Exception as e:
        print(f"❌ Error setting primary account: {e}")
        return False

async def initialize_defaults():
    """Initialize default accounts."""
    db = Database()
    
    try:
        success = await db.initialize_default_accounts()
        
        if success:
            print("✅ Default accounts initialized successfully")
            # Show the accounts that were created
            await list_accounts()
            return True
        else:
            print("❌ Failed to initialize default accounts")
            return False
            
    except Exception as e:
        print(f"❌ Error initializing defaults: {e}")
        return False

async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage Bluesky account configurations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manage_accounts.py list
  python manage_accounts.py add symm.social did:plc:33d7gnwiagm6cimpiepefp72 --primary
  python manage_accounts.py add this.is-a.bot did:plc:5eq355e2dkl6lkdvugveu4oc
  python manage_accounts.py remove did:plc:5eq355e2dkl6lkdvugveu4oc
  python manage_accounts.py set-primary did:plc:33d7gnwiagm6cimpiepefp72
  python manage_accounts.py init
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    subparsers.add_parser('list', help='List all managed accounts')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new managed account')
    add_parser.add_argument('handle', help='Account handle (e.g., symm.social)')
    add_parser.add_argument('did', help='Account DID (e.g., did:plc:...)')
    add_parser.add_argument('--primary', action='store_true', help='Set as primary account')
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a managed account')
    remove_parser.add_argument('did', help='Account DID to remove')
    
    # Set primary command
    primary_parser = subparsers.add_parser('set-primary', help='Set an account as primary')
    primary_parser.add_argument('did', help='Account DID to set as primary')
    
    # Initialize command
    subparsers.add_parser('init', help='Initialize default accounts')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Test database connection
    db = Database()
    if not await db.test_connection():
        print("❌ Database connection failed. Please check your configuration.")
        sys.exit(1)
    
    # Execute the requested command
    success = False
    
    if args.command == 'list':
        success = await list_accounts()
    elif args.command == 'add':
        success = await add_account(args.handle, args.did, args.primary)
    elif args.command == 'remove':
        success = await remove_account(args.did)
    elif args.command == 'set-primary':
        success = await set_primary(args.did)
    elif args.command == 'init':
        success = await initialize_defaults()
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 