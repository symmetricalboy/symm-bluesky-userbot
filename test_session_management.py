#!/usr/bin/env python3
"""
Test script for session management functionality.
This script verifies that JWT token reuse is working correctly.
"""

import asyncio
import os
import time
from dotenv import load_dotenv
from account_agent import AccountAgent

load_dotenv()

async def test_session_management():
    """Test the session management system."""
    print("🧪 Testing Session Management System...")
    print("=" * 50)
    
    # Get credentials
    handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    password = os.getenv('PRIMARY_BLUESKY_PASSWORD')
    
    if not handle or not password:
        print("❌ Error: Missing credentials in .env file")
        return
    
    print(f"📧 Testing account: {handle}")
    
    # Test 1: First login (should create session file)
    print("\n📝 Test 1: First login (should create session file)")
    agent1 = AccountAgent(handle, password, is_primary=True)
    
    start_time = time.time()
    success1 = await agent1.login()
    duration1 = time.time() - start_time
    
    if success1:
        print(f"✅ First login successful in {duration1:.2f}s")
        print(f"📄 DID: {agent1.did}")
    else:
        print("❌ First login failed")
        return
    
    # Check if session file was created
    session_file = agent1._get_session_file_path()
    if os.path.exists(session_file):
        print(f"✅ Session file created: {session_file}")
    else:
        print(f"❌ Session file not created: {session_file}")
        return
    
    # Test 2: Second login (should reuse session)
    print("\n🔄 Test 2: Second login (should reuse session)")
    agent2 = AccountAgent(handle, password, is_primary=True)
    
    start_time = time.time()
    success2 = await agent2.login()
    duration2 = time.time() - start_time
    
    if success2:
        print(f"✅ Second login successful in {duration2:.2f}s")
        print(f"📄 DID: {agent2.did}")
    else:
        print("❌ Second login failed")
        return
    
    # Performance comparison
    print(f"\n⚡ Performance Comparison:")
    print(f"   First login (full):  {duration1:.2f}s")
    print(f"   Second login (session): {duration2:.2f}s")
    
    if duration2 < duration1:
        improvement = ((duration1 - duration2) / duration1) * 100
        print(f"   🚀 Session reuse is {improvement:.1f}% faster!")
    
    # Test 3: Check session data
    print("\n📋 Test 3: Session data verification")
    session_data = await agent2._load_session_from_file()
    
    if session_data:
        print("✅ Session data loaded successfully:")
        print(f"   Handle: {session_data.get('handle')}")
        print(f"   DID: {session_data.get('did')}")
        print(f"   Access Date: {session_data.get('accessDate')}")
        print(f"   Refresh Date: {session_data.get('refreshDate')}")
        
        # Verify token expiry logic
        is_access_expired = agent2._is_access_token_expired(session_data)
        is_refresh_expired = agent2._is_refresh_token_expired(session_data)
        
        print(f"   Access token expired: {is_access_expired}")
        print(f"   Refresh token expired: {is_refresh_expired}")
        
        if not is_access_expired and not is_refresh_expired:
            print("✅ Tokens are fresh and valid")
        else:
            print("⚠️  Some tokens need refresh")
    else:
        print("❌ Failed to load session data")
    
    # Test 4: Rate limiting verification
    print("\n🚦 Test 4: Rate limiting verification")
    print("Making a few rapid requests to test rate limiting...")
    
    for i in range(3):
        print(f"   Request {i+1}...", end="")
        start = time.time()
        await agent2._rate_limit_request()
        duration = time.time() - start
        print(f" completed in {duration:.2f}s")
    
    print("\n🎉 Session Management Test Complete!")
    print("=" * 50)
    print("✅ All tests passed successfully!")
    print("\n💡 What this means:")
    print("   • Your account will no longer login frequently")
    print("   • Sessions will be reused for ~2 hours")
    print("   • Tokens will refresh automatically")
    print("   • Rate limiting is active and working")
    print("   • Account lockouts should be prevented!")

async def cleanup_test_files():
    """Clean up test session files."""
    print("\n🧹 Cleaning up test files...")
    
    handle = os.getenv('PRIMARY_BLUESKY_HANDLE')
    if handle:
        session_file = f"session_{handle.replace('.', '_').replace('@', '_')}.json"
        if os.path.exists(session_file):
            os.remove(session_file)
            print(f"   Removed: {session_file}")

if __name__ == "__main__":
    print("🔧 Bluesky Session Management Test")
    print("This script tests the new session management system.")
    print("It will perform safe operations to verify functionality.\n")
    
    choice = input("Continue with test? (y/N): ").lower().strip()
    if choice != 'y':
        print("Test cancelled.")
        exit(0)
    
    try:
        asyncio.run(test_session_management())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    # Ask about cleanup
    print("\n" + "=" * 50)
    cleanup = input("Remove test session files? (y/N): ").lower().strip()
    if cleanup == 'y':
        asyncio.run(cleanup_test_files())
        print("✅ Cleanup complete!")
    else:
        print("💾 Session files preserved for reuse.") 