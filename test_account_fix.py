#!/usr/bin/env python3

import asyncio
import os
from database import Database

async def test_account_registration():
    """Test the account registration fix"""
    try:
        # Initialize database
        db = Database()
        
        print("Testing account registration duplicate handling...")
        
        # Try to register the same account twice
        handle = "test.user"
        did1 = "did:plc:test123"
        did2 = "did:plc:test456"
        
        # First registration
        print("First registration...")
        account_id1 = await db.register_account(handle, did1, is_primary=False)
        print(f"✅ First registration successful, account ID: {account_id1}")
        
        # Second registration with same handle but different DID - should update
        print("Second registration with same handle...")
        account_id2 = await db.register_account(handle, did2, is_primary=False)
        print(f"✅ Second registration successful, account ID: {account_id2}")
        
        if account_id1 == account_id2:
            print("✅ SUCCESS: Same account ID returned, existing account was updated")
        else:
            print("❌ FAILED: Different account IDs, duplicate was created")
            return False
            
        # Third registration with placeholder DID (like during initialization)
        print("Third registration with placeholder DID...")
        account_id3 = await db.register_account(handle, f"placeholder_primary_{handle}", is_primary=True)
        print(f"✅ Third registration successful, account ID: {account_id3}")
        
        if account_id1 == account_id3:
            print("✅ SUCCESS: Account initialization scenario works correctly")
            return True
        else:
            print("❌ FAILED: Account initialization created duplicate")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    # Set test environment
    os.environ["TEST_MODE"] = "true"
    result = asyncio.run(test_account_registration())
    if result:
        print("\n🎉 All tests passed! Account registration fix works correctly.")
    else:
        print("\n💥 Tests failed! Need to investigate further.") 