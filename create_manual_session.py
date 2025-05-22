#!/usr/bin/env python3
"""
Manual Session File Creator

This script helps you create session files for accounts that are rate-limited.
You can extract the necessary information from browser developer tools.

Instructions:
1. Login to the account in your browser
2. Open Developer Tools (F12)
3. Go to Network tab
4. Find any API request to bsky.social 
5. Look for Authorization header (contains the JWT token)
6. Run this script with the extracted information
"""

import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def create_session_file(handle, did, access_jwt, refresh_jwt=None):
    """Create a session file for manual use."""
    
    # Use access_jwt as refresh_jwt if not provided (will auto-refresh)
    if not refresh_jwt:
        refresh_jwt = access_jwt
    
    # Clean handle for filename
    safe_handle = handle.replace('.', '_').replace('@', '_')
    session_file = f"session_{safe_handle}.json"
    
    session_data = {
        'handle': handle,
        'did': did,
        'accessJwt': access_jwt,
        'refreshJwt': refresh_jwt,
        'accessDate': datetime.now().isoformat(),
        'refreshDate': datetime.now().isoformat()
    }
    
    try:
        # Always create file (useful for local development)
        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
        
        print(f"✅ Session file created: {session_file}")
        
        # Also save to database if not in local test mode
        is_local = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
        if not is_local:
            try:
                import asyncio
                from database import Database
                
                async def save_to_db():
                    db = Database()
                    success = await db.save_session_data(handle, did, access_jwt, refresh_jwt)
                    return success
                
                success = asyncio.run(save_to_db())
                if success:
                    print(f"✅ Session data saved to database")
                else:
                    print(f"⚠️  Warning: Failed to save session to database")
            except Exception as e:
                print(f"⚠️  Warning: Could not save to database: {e}")
                print(f"💡 Session file created successfully for local use")
        
        print(f"📋 Handle: {handle}")
        print(f"🆔 DID: {did}")
        print(f"📅 Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if is_local:
            print(f"💡 Local mode: Session file will be used automatically by the bot.")
        else:
            print(f"💡 Production mode: Session data saved to database for bot use.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating session file: {e}")
        return False

def extract_from_browser():
    """Interactive session to extract info from browser."""
    print("\n🔧 Manual Session File Creator")
    print("=" * 50)
    print("\nStep 1: Login to your account in a browser")
    print("Step 2: Open Developer Tools (F12)")
    print("Step 3: Go to Network tab")
    print("Step 4: Find any request to bsky.social")
    print("Step 5: Look for 'Authorization: Bearer <token>' in headers")
    print("Step 6: Copy the token (everything after 'Bearer ')")
    print("\n" + "=" * 50)
    
    # Get account info
    handle = input("\n🏷️  Enter account handle (e.g., username.bsky.social): ").strip()
    if not handle:
        print("❌ Handle is required")
        return False
    
    did = input("🆔 Enter DID (starts with did:plc:): ").strip()
    if not did or not did.startswith('did:'):
        print("❌ Valid DID is required")
        return False
    
    access_jwt = input("🔑 Paste JWT token (from Authorization header): ").strip()
    if not access_jwt:
        print("❌ JWT token is required")
        return False
    
    # Remove "Bearer " prefix if accidentally included
    if access_jwt.startswith('Bearer '):
        access_jwt = access_jwt[7:]
    
    print(f"\n📋 Creating session for: {handle}")
    print(f"🆔 DID: {did}")
    
    confirm = input("\n✅ Create session file? (y/n): ").strip().lower()
    if confirm == 'y':
        return create_session_file(handle, did, access_jwt)
    else:
        print("❌ Session creation cancelled")
        return False

def main():
    """Main function."""
    print("🔧 Bluesky Manual Session Creator")
    
    if len(sys.argv) == 4:
        # Command line mode
        handle, did, access_jwt = sys.argv[1:4]
        create_session_file(handle, did, access_jwt)
    else:
        # Interactive mode
        extract_from_browser()

if __name__ == "__main__":
    main() 