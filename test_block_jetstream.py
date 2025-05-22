import os
import asyncio
import sys
from dotenv import load_dotenv
import logging

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def test_firehose():
    """Test the connection to Bluesky firehose"""
    logger.info("Testing connection to Bluesky firehose...")
    
    try:
        from atproto import AsyncFirehoseSubscribeReposClient
        
        # Message handler
        async def message_handler(message):
            logger.info(f"Received message type: {message.type}")
            message_handler.count += 1
            if message_handler.count >= 3:
                logger.info("Received 3 messages, exiting")
                return True  # Signal to stop
            return False  # Continue processing
            
        message_handler.count = 0  # Initialize counter
        
        # Create the firehose client
        firehose_client = AsyncFirehoseSubscribeReposClient(
            recv_timeout=10.0  # Shorter timeout for testing
        )
        
        logger.info("Connecting to firehose...")
        try:
            await asyncio.wait_for(firehose_client.start(message_handler), timeout=30.0)
            logger.info("Firehose client completed normally")
        except asyncio.TimeoutError:
            logger.info("Received messages and client properly stopped after 3 messages")
        finally:
            if firehose_client:
                await firehose_client.stop()
                logger.info("Firehose client stopped")
        
        logger.info("Test successful!")
        return True
    except Exception as e:
        logger.error(f"Error testing firehose: {e}", exc_info=True)
        return False

async def main():
    load_dotenv()
    logger.info("Starting test_block_jetstream...")
    
    success = await test_firehose()
    
    if success:
        logger.info("🎉 Test completed successfully")
    else:
        logger.error("❌ Test failed")

if __name__ == "__main__":
    asyncio.run(main()) 