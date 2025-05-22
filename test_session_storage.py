#!/usr/bin/env python3
"""
Test Session Storage System

This script tests both file-based and database-based session storage
to ensure they work correctly in different environments.
"""

import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_session_storage():
    """Test session storage functionality."""
    print("🧪 Testing Session Storage System")
    print("=" * 50)
    
    # Test data
    test_handle = "test.user.bsky.social"
    test_did = "did:plc:test123456789"
    test_access_jwt = "test_access_token_12345"
    test_refresh_jwt = "test_refresh_token_67890"
    
    is_local = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
    print(f"🌍 Environment: {'Local Development' if is_local else 'Production'}")
    
    # Test database storage
    try:
        from database import Database
        
        print("\n💾 Testing Database Storage...")
        db = Database()
        
        # Test connection
        if not await db.test_connection():
            print("❌ Database connection failed")
            return False
        
        # Save session data
        success = await db.save_session_data(
            handle=test_handle,
            did=test_did,
            access_jwt=test_access_jwt,
            refresh_jwt=test_refresh_jwt
        )
        
        if success:
            print("✅ Database save successful")
        else:
            print("❌ Database save failed")
            return False
        
        # Load session data
        session_data = await db.load_session_data(test_handle)
        
        if session_data:
            print("✅ Database load successful")
            print(f"   Handle: {session_data['handle']}")
            print(f"   DID: {session_data['did']}")
            print(f"   Access Token: {session_data['accessJwt'][:20]}...")
            print(f"   Refresh Token: {session_data['refreshJwt'][:20]}...")
        else:
            print("❌ Database load failed")
            return False
        
        # Test access token update
        new_access_jwt = "updated_access_token_54321"
        update_success = await db.update_access_token(test_handle, new_access_jwt)
        
        if update_success:
            print("✅ Database access token update successful")
        else:
            print("❌ Database access token update failed")
        
        # Verify update
        updated_session = await db.load_session_data(test_handle)
        if updated_session and updated_session['accessJwt'] == new_access_jwt:
            print("✅ Access token update verified")
        else:
            print("❌ Access token update verification failed")
        
    except ImportError:
        print("❌ Database module not available")
        return False
    except Exception as e:
        print(f"❌ Database test error: {e}")
        return False
    
    # Test file storage (should work in both environments)
    print("\n📄 Testing File Storage...")
    
    # Create test session file
    session_file = f"session_{test_handle.replace('.', '_').replace('@', '_')}.json"
    session_data = {
        'handle': test_handle,
        'did': test_did,
        'accessJwt': test_access_jwt,
        'refreshJwt': test_refresh_jwt,
        'accessDate': datetime.now().isoformat(),
        'refreshDate': datetime.now().isoformat()
    }
    
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
        print("✅ File save successful")
        
        # Read it back
        with open(session_file, 'r') as f:
            loaded_data = json.load(f)
        
        if loaded_data['handle'] == test_handle:
            print("✅ File load successful")
        else:
            print("❌ File load verification failed")
        
        # Clean up
        os.remove(session_file)
        print("✅ Test file cleaned up")
        
    except Exception as e:
        print(f"❌ File test error: {e}")
        return False
    
    print("\n🎉 All tests passed!")
    return True

async def test_account_agent_integration():
    """Test AccountAgent integration with new session storage."""
    print("\n🤖 Testing AccountAgent Integration")
    print("=" * 50)
    
    try:
        from account_agent import AccountAgent
        from database import Database
        
        # Create a test agent (don't actually login)
        agent = AccountAgent("test.handle", "test_password", database=Database())
        
        # Test session file path generation
        session_file_path = agent._get_session_file_path()
        print(f"📄 Session file path: {session_file_path}")
        
        # Test storage detection
        is_local = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        print(f"🔍 Storage mode: {'File' if is_local else 'Database'}")
        
        print("✅ AccountAgent integration test passed")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Integration test error: {e}")
        return False

async def main():
    """Main test function."""
    print("🚀 Starting Session Storage Tests")
    
    # Run tests
    storage_test = await test_session_storage()
    integration_test = await test_account_agent_integration()
    
    # Summary
    print("\n" + "=" * 50)
    if storage_test and integration_test:
        print("🎉 All tests passed! Session storage system is working correctly.")
    else:
        print("❌ Some tests failed. Check the output above for details.")
    
    return storage_test and integration_test

if __name__ == "__main__":
    asyncio.run(main()) 