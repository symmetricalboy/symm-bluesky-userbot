#!/usr/bin/env python3
"""
Verify Deployment Fixes

This script verifies that both fixes are working correctly:
1. Verify this.is-a.bot can authenticate using saved session
2. Verify all accounts have real DIDs (no placeholders)
3. Test ClearSky API calls with real DIDs

Usage:
    python verify_fixes.py
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
from database import Database
from account_agent import AccountAgent
import clearsky_helpers as cs

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_this_is_a_bot_session():
    """Test that this.is-a.bot can authenticate using saved session"""
    logger.info("🧪 Testing this.is-a.bot session authentication...")
    
    try:
        db = Database()
        agent = AccountAgent(
            handle='this.is-a.bot',
            password='dummy',  # Won't be used since we have a session
            is_primary=False,
            database=db
        )
        
        success = await agent.login()
        if success:
            logger.info(f"✅ this.is-a.bot session authentication successful! DID: {agent.did}")
            return True
        else:
            logger.error("❌ this.is-a.bot session authentication failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error testing this.is-a.bot session: {e}")
        return False

async def verify_no_placeholder_dids():
    """Verify all accounts have real DIDs (no placeholders)"""
    logger.info("🧪 Verifying all accounts have real DIDs...")
    
    try:
        db = Database()
        accounts_config = await db.get_account_configurations()
        accounts = accounts_config['accounts']
        
        placeholder_count = 0
        real_did_count = 0
        
        for account in accounts:
            if account['did'].startswith('placeholder_'):
                logger.error(f"❌ {account['handle']} still has placeholder DID: {account['did']}")
                placeholder_count += 1
            else:
                logger.info(f"✅ {account['handle']} has real DID: {account['did']}")
                real_did_count += 1
        
        logger.info(f"📊 Results: {real_did_count} real DIDs, {placeholder_count} placeholder DIDs")
        
        if placeholder_count == 0:
            logger.info("✅ All accounts have real DIDs!")
            return True
        else:
            logger.error(f"❌ {placeholder_count} accounts still have placeholder DIDs")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error verifying DIDs: {e}")
        return False

async def test_clearsky_api_calls():
    """Test ClearSky API calls with real DIDs"""
    logger.info("🧪 Testing ClearSky API calls with real DIDs...")
    
    try:
        db = Database()
        accounts_config = await db.get_account_configurations()
        accounts = accounts_config['accounts']
        
        # Test with the primary account
        primary_account = None
        for account in accounts:
            if account['is_primary']:
                primary_account = account
                break
        
        if not primary_account:
            logger.error("❌ No primary account found")
            return False
        
        did = primary_account['did']
        handle = primary_account['handle']
        
        logger.info(f"🔍 Testing ClearSky API call for {handle} (DID: {did})...")
        
        # Test fetching blocklist
        blocking_data = await cs.fetch_from_clearsky(f"/blocklist/{did}")
        
        if blocking_data:
            logger.info(f"✅ ClearSky API call successful for {handle}")
            if 'data' in blocking_data and 'blocklist' in blocking_data['data']:
                blocklist = blocking_data['data']['blocklist']
                if blocklist:
                    logger.info(f"📊 Found {len(blocklist)} blocks for {handle}")
                else:
                    logger.info(f"📊 No blocks found for {handle}")
            return True
        else:
            logger.warning(f"⚠️ ClearSky API returned no data for {handle}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error testing ClearSky API: {e}")
        return False

async def run_verification():
    """Run all verification tests"""
    logger.info("🚀 Starting verification tests...")
    
    # Test 1: this.is-a.bot session
    logger.info("\n" + "="*50)
    logger.info("TEST 1: this.is-a.bot session authentication")
    logger.info("="*50)
    session_test_passed = await test_this_is_a_bot_session()
    
    # Test 2: No placeholder DIDs
    logger.info("\n" + "="*50)
    logger.info("TEST 2: Verify no placeholder DIDs")
    logger.info("="*50)
    dids_test_passed = await verify_no_placeholder_dids()
    
    # Test 3: ClearSky API calls
    logger.info("\n" + "="*50)
    logger.info("TEST 3: ClearSky API calls with real DIDs")
    logger.info("="*50)
    clearsky_test_passed = await test_clearsky_api_calls()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("VERIFICATION SUMMARY")
    logger.info("="*50)
    
    total_tests = 3
    passed_tests = sum([session_test_passed, dids_test_passed, clearsky_test_passed])
    
    if session_test_passed:
        logger.info("✅ this.is-a.bot session: PASSED")
    else:
        logger.error("❌ this.is-a.bot session: FAILED")
    
    if dids_test_passed:
        logger.info("✅ No placeholder DIDs: PASSED")
    else:
        logger.error("❌ No placeholder DIDs: FAILED")
    
    if clearsky_test_passed:
        logger.info("✅ ClearSky API calls: PASSED")
    else:
        logger.error("❌ ClearSky API calls: FAILED")
    
    logger.info(f"\n📊 Overall result: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        logger.info("🎉 ALL VERIFICATION TESTS PASSED!")
        logger.info("✅ Your deployment fixes are working correctly!")
        return True
    else:
        logger.warning("⚠️ Some verification tests failed")
        logger.warning("Check the logs above for details on what needs attention")
        return False

if __name__ == "__main__":
    asyncio.run(run_verification()) 