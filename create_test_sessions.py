#!/usr/bin/env python3

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_mock_session_data(handle: str, did: str) -> dict:
    """Create mock session data for testing purposes."""
    now = datetime.now(timezone.utc)
    
    # Create mock JWT tokens (these won't work for real API calls but are valid for testing)
    mock_access_jwt = f"mock_access_jwt_for_{handle.replace('.', '_')}"
    mock_refresh_jwt = f"mock_refresh_jwt_for_{handle.replace('.', '_')}"
    
    return {
        'handle': handle,
        'did': did,
        'accessJwt': mock_access_jwt,
        'refreshJwt': mock_refresh_jwt,
        'accessDate': now.isoformat(),
        'refreshDate': now.isoformat()
    }

def get_session_file_path(handle: str) -> str:
    """Get session file path for a handle."""
    return f"session_{handle.replace('.', '_').replace('@', '_')}.json"

def create_session_file(handle: str, did: str):
    """Create a session file for the given handle."""
    session_data = create_mock_session_data(handle, did)
    session_file = get_session_file_path(handle)
    
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
        logger.info(f"✅ Created session file for {handle}: {session_file}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create session file for {handle}: {e}")
        return False

def main():
    """Create test session files for all configured accounts."""
    logger.info("🔧 Creating test session files...")
    
    # Account mappings
    accounts = [
        ("symm.social", "did:plc:33d7gnwiagm6cimpiepefp72"),
        ("symm.app", "did:plc:4y4wmofpqlwz7e5q5nzjpzdd"),
        ("symm.now", "did:plc:kkylvufgv5shv2kpd74lca6o"),
        ("this.is-a.bot", "did:plc:5eq355e2dkl6lkdvugveu4oc"),
        ("gemini.is-a.bot", "did:plc:57na4nqoqohad5wk47jlu4rk")
    ]
    
    # Check if we're in test mode
    is_test_mode = os.getenv('LOCAL_TEST', 'false').lower() == 'true'
    
    if not is_test_mode:
        logger.warning("⚠️  Not in test mode (LOCAL_TEST=true). This creates mock sessions for testing only!")
        response = input("Continue? (y/N): ").strip().lower()
        if response != 'y':
            logger.info("❌ Cancelled")
            return
    
    created_count = 0
    for handle, did in accounts:
        if create_session_file(handle, did):
            created_count += 1
    
    logger.info(f"🎉 Created {created_count}/{len(accounts)} session files")
    
    # Show what was created
    logger.info("\n📁 Session files created:")
    for handle, _ in accounts:
        session_file = get_session_file_path(handle)
        if os.path.exists(session_file):
            logger.info(f"  ✅ {session_file}")
        else:
            logger.info(f"  ❌ {session_file} (missing)")
    
    logger.info("\n💡 Note: These are mock sessions for testing only!")
    logger.info("   For production, use proper login procedures.")

if __name__ == "__main__":
    main() 