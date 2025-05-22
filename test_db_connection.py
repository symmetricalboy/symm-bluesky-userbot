#!/usr/bin/env python3
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging to see all INFO messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get test database URL from environment
TEST_DATABASE_URL = os.getenv('TEST_DATABASE_URL')

def main():
    logger.info("Testing direct database connection pooling...")
    
    if not TEST_DATABASE_URL:
        logger.error("TEST_DATABASE_URL not found in environment variables")
        return
    
    # Create a connection pool
    connection_pool = None
    try:
        min_conn = 1
        max_conn = 5
        connection_pool = pool.ThreadedConnectionPool(min_conn, max_conn, dsn=TEST_DATABASE_URL)
        logger.info("Connection pool created successfully")
        
        # Test multiple operations using the pool
        for i in range(3):
            logger.info(f"Operation {i+1}: Getting a connection from the pool")
            conn = connection_pool.getconn()
            
            # Execute a simple query
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            logger.info(f"Query result: {result}")
            
            # Return the connection to the pool
            cursor.close()
            connection_pool.putconn(conn)
            logger.info(f"Operation {i+1}: Connection returned to the pool")
        
        logger.info("All operations completed successfully")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if connection_pool:
            connection_pool.closeall()
            logger.info("Connection pool closed")

if __name__ == "__main__":
    main() 