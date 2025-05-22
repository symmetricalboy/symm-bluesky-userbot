#!/usr/bin/env python3
"""
Session Status Checker

This script helps you understand the current state of your session files
and database session storage, providing guidance on rate limiting issues.
"""

import json
import os
import glob
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_session_file(session_file):
    """Check a single session file."""
    try:
        with open(session_file, 'r') as f:
            session_data = json.load(f)
        
        handle = session_data.get('handle', 'Unknown')
        did = session_data.get('did', 'Unknown')
        access_date = session_data.get('accessDate', 'Unknown')
        refresh_date = session_data.get('refreshDate', 'Unknown')
        
        print(f"\n📱 Account: {handle}")
        print(f"🆔 DID: {did}")
        print(f"📄 File: {session_file}")
        
        # Check token ages
        try:
            access_dt = datetime.fromisoformat(access_date)
            refresh_dt = datetime.fromisoformat(refresh_date)
            now = datetime.now()
            
            access_age = now - access_dt
            refresh_age = now - refresh_dt
            
            print(f"🕒 Access Token Age: {access_age}")
            print(f"🔄 Refresh Token Age: {refresh_age}")
            
            # Check if tokens need refresh
            if access_age > timedelta(hours=2):
                print("⚠️  Access token may need refresh (>2 hours old)")
            else:
                print("✅ Access token is fresh")
                
            if refresh_age > timedelta(days=60):
                print("❌ Refresh token is expired (>60 days old)")
            elif refresh_age > timedelta(days=55):
                print("⚠️  Refresh token will expire soon (>55 days old)")
            else:
                print("✅ Refresh token is valid")
                
        except Exception as e:
            print(f"❌ Error parsing dates: {e}")
            
        return True
        
    except Exception as e:
        print(f"❌ Error reading {session_file}: {e}")
        return False

async def check_database_sessions():
    """Check session data stored in database."""
    try:
        from database import Database
        
        db = Database()
        if not await db.test_connection():
            print("❌ Cannot connect to database")
            return 0
        
        # Get all accounts with session data
        table_suffix = "_test" if os.getenv('LOCAL_TEST', 'False').lower() == 'true' else ""
        query = f"""
            SELECT handle, did, access_jwt_date, refresh_jwt_date
            FROM accounts{table_suffix}
            WHERE access_jwt IS NOT NULL
        """
        
        await db.ensure_pool()
        from database import connection_pool
        
        async with connection_pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return 0
        
        print(f"\n💾 Database Session Storage:")
        print("=" * 40)
        
        valid_sessions = 0
        for row in rows:
            handle = row['handle']
            did = row['did']
            access_date = row['access_jwt_date']
            refresh_date = row['refresh_jwt_date']
            
            print(f"\n📱 Account: {handle}")
            print(f"🆔 DID: {did}")
            print(f"💾 Storage: Database")
            
            if access_date and refresh_date:
                now = datetime.now(access_date.tzinfo)  # Use timezone from DB
                access_age = now - access_date
                refresh_age = now - refresh_date
                
                print(f"🕒 Access Token Age: {access_age}")
                print(f"🔄 Refresh Token Age: {refresh_age}")
                
                # Check if tokens need refresh
                if access_age > timedelta(hours=2):
                    print("⚠️  Access token may need refresh (>2 hours old)")
                else:
                    print("✅ Access token is fresh")
                    
                if refresh_age > timedelta(days=60):
                    print("❌ Refresh token is expired (>60 days old)")
                elif refresh_age > timedelta(days=55):
                    print("⚠️  Refresh token will expire soon (>55 days old)")
                else:
                    print("✅ Refresh token is valid")
                
                valid_sessions += 1
            else:
                print("❌ Missing session dates")
            
            print("-" * 40)
        
        return valid_sessions
        
    except ImportError:
        print("⚠️  Database module not available - skipping database check")
        return 0
    except Exception as e:
        print(f"❌ Error checking database sessions: {e}")
        return 0

async def main():
    """Main function."""
    print("🔧 Bluesky Session Status Checker")
    print("=" * 50)
    
    is_local = os.getenv('LOCAL_TEST', 'False').lower() == 'true'
    
    # Check file sessions
    session_files = glob.glob("session_*.json")
    file_sessions = 0
    
    if session_files:
        print(f"\n📄 File Session Storage:")
        print("=" * 40)
        
        for session_file in sorted(session_files):
            if check_session_file(session_file):
                file_sessions += 1
            print("-" * 40)
    
    # Check database sessions
    db_sessions = await check_database_sessions()
    
    total_sessions = file_sessions + db_sessions
    
    if total_sessions == 0:
        print("\n❌ No session data found!")
        print("\n💡 If you're getting rate limit errors:")
        print("   1. Wait 24 hours for the limit to reset")
        print("   2. Create session files manually using create_manual_session.py")
        print("   3. Reduce the number of accounts logging in simultaneously")
        return
    
    print(f"\n📊 Summary:")
    print(f"   📄 File sessions: {file_sessions}")
    print(f"   💾 Database sessions: {db_sessions}")
    print(f"   📋 Total sessions: {total_sessions}")
    
    # Environment-specific guidance
    print(f"\n🌍 Environment: {'Local Development' if is_local else 'Production'}")
    if is_local:
        print("   💡 File sessions will be used automatically")
        print("   💡 Database sessions are available as backup")
    else:
        print("   💡 Database sessions will be used automatically")
        print("   💡 File sessions are ignored in production")
    
    # Rate limiting guidance
    print("\n💡 Rate Limiting Guidance:")
    print("   • Daily login limit: 10 per account per day")
    print("   • Session storage avoids the need for frequent logins")
    print("   • Access tokens refresh automatically every ~2 hours")
    print("   • Refresh tokens last ~60 days")
    print("   • If rate limited, wait 24 hours or create manual sessions")
    
    # Check for potential issues
    if total_sessions > 5:
        print(f"\n⚠️  Warning: You have {total_sessions} accounts configured.")
        print("   Consider staggering logins with delays to avoid rate limits.")

if __name__ == "__main__":
    asyncio.run(main()) 