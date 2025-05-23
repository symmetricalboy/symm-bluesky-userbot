#!/usr/bin/env python3
"""
Upload Local Session Files to Database

This script reads all local session_*.json files and uploads them to the database
so the production environment can use them.

Usage:
    python upload_sessions_to_database.py
"""

import asyncio
import os
import logging
import json
import glob
from dotenv import load_dotenv
from database import Database

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def find_session_files():
    """Find all session files in the current directory"""
    session_files = glob.glob("session_*.json")
    logger.info(f"Found {len(session_files)} session files: {session_files}")
    return session_files

async def validate_session_data(session_data, filename):
    """Validate that session data has all required fields and real tokens"""
    required_fields = ['handle', 'did', 'accessJwt', 'refreshJwt', 'accessDate', 'refreshDate']
    
    # Check all required fields are present
    missing_fields = [field for field in required_fields if field not in session_data]
    if missing_fields:
        logger.error(f"❌ {filename}: Missing required fields: {missing_fields}")
        return False
    
    # Check if tokens are real (not mock)
    if session_data['accessJwt'].startswith('mock_'):
        logger.warning(f"⚠️ {filename}: Contains mock access token, skipping")
        return False
    
    if session_data['refreshJwt'].startswith('mock_'):
        logger.warning(f"⚠️ {filename}: Contains mock refresh token, skipping")
        return False
    
    # Check if DID is real (not placeholder)
    if session_data['did'].startswith('placeholder_'):
        logger.warning(f"⚠️ {filename}: Contains placeholder DID, skipping")
        return False
    
    logger.info(f"✅ {filename}: Valid session data for {session_data['handle']}")
    return True

async def upload_session_to_database(session_data, db):
    """Upload a single session to the database"""
    try:
        success = await db.save_session_data(
            handle=session_data['handle'],
            did=session_data['did'],
            access_jwt=session_data['accessJwt'],
            refresh_jwt=session_data['refreshJwt']
        )
        
        if success:
            logger.info(f"✅ Uploaded session for {session_data['handle']} to database")
            return True
        else:
            logger.error(f"❌ Failed to upload session for {session_data['handle']} to database")
            return False
    
    except Exception as e:
        logger.error(f"❌ Error uploading session for {session_data['handle']}: {e}")
        return False

async def verify_session_in_database(handle, db):
    """Verify that a session was correctly saved to the database"""
    try:
        session_data = await db.load_session_data(handle)
        if session_data:
            logger.info(f"✅ Verified: {handle} session exists in database")
            return True
        else:
            logger.error(f"❌ Verification failed: {handle} session not found in database")
            return False
    except Exception as e:
        logger.error(f"❌ Error verifying session for {handle}: {e}")
        return False

async def main():
    """Main function to upload all session files to database"""
    logger.info("🚀 Starting session upload to database...")
    
    # Find all session files
    session_files = await find_session_files()
    
    if not session_files:
        logger.warning("⚠️ No session files found to upload")
        return
    
    # Initialize database connection
    try:
        db = Database()
        logger.info("✅ Database connection established")
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        return
    
    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    
    # Process each session file
    for filename in session_files:
        logger.info(f"\n📁 Processing {filename}...")
        
        try:
            # Read session file
            with open(filename, 'r') as f:
                session_data = json.load(f)
            
            # Validate session data
            if not await validate_session_data(session_data, filename):
                skipped_count += 1
                continue
            
            # Upload to database
            if await upload_session_to_database(session_data, db):
                # Verify upload was successful
                if await verify_session_in_database(session_data['handle'], db):
                    uploaded_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ {filename}: Invalid JSON format: {e}")
            failed_count += 1
        except Exception as e:
            logger.error(f"❌ {filename}: Error processing file: {e}")
            failed_count += 1
    
    # Summary
    total_files = len(session_files)
    logger.info(f"\n" + "="*60)
    logger.info("UPLOAD SUMMARY")
    logger.info("="*60)
    logger.info(f"📊 Total session files found: {total_files}")
    logger.info(f"✅ Successfully uploaded: {uploaded_count}")
    logger.info(f"⚠️ Skipped (invalid/mock): {skipped_count}")
    logger.info(f"❌ Failed to upload: {failed_count}")
    
    if uploaded_count > 0:
        logger.info(f"\n🎉 Successfully uploaded {uploaded_count} sessions to database!")
        logger.info("💡 Production environment can now use these sessions.")
    
    if failed_count > 0:
        logger.warning(f"\n⚠️ {failed_count} sessions failed to upload. Check logs above for details.")
    
    if skipped_count > 0:
        logger.info(f"\n📝 {skipped_count} sessions were skipped (mock tokens or invalid data).")
    
    # List what's now available in database
    if uploaded_count > 0:
        logger.info(f"\n📋 Sessions now available in production database:")
        for filename in session_files:
            try:
                with open(filename, 'r') as f:
                    session_data = json.load(f)
                if (not session_data['accessJwt'].startswith('mock_') and 
                    not session_data['did'].startswith('placeholder_')):
                    logger.info(f"  🔐 {session_data['handle']} (DID: {session_data['did']})")
            except:
                continue

if __name__ == "__main__":
    asyncio.run(main()) 