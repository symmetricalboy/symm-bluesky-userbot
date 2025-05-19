#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
import psycopg2
import urllib.parse

# Load environment variables
load_dotenv()

def test_connection():
    """Test the database connection, supporting both individual params and DATABASE_URL."""
    try:
        # Check for Railway-style DATABASE_URL
        database_url = os.getenv('DATABASE_URL')
        
        if database_url:
            print("Using DATABASE_URL for connection")
            parsed_url = urllib.parse.urlparse(database_url)
            db_name = parsed_url.path.lstrip('/')
            
            print(f"Testing connection to PostgreSQL database {db_name} via connection string...")
            conn = psycopg2.connect(database_url)
        else:
            # Use individual connection parameters
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_NAME = os.getenv('DB_NAME', 'symm_blocks')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            print(f"Testing connection to PostgreSQL database {DB_NAME}...")
            print(f"Host: {DB_HOST}, Port: {DB_PORT}, User: {DB_USER}")
            
            # Try to connect to the database
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname=DB_NAME
            )
            
        cursor = conn.cursor()
        
        # Check if the tables exist
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        tables = cursor.fetchall()
        
        print("Connection successful!")
        print(f"Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")
            
        # Close the connection
        cursor.close()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        
        if os.getenv('DATABASE_URL'):
            print("\nCould not connect using the DATABASE_URL.")
            print("Please check your connection string and ensure the database service is running.")
            return False
            
        # Try to connect to 'postgres' database if our database doesn't exist yet
        try:
            DB_HOST = os.getenv('DB_HOST', 'localhost')
            DB_PORT = os.getenv('DB_PORT', '5432')
            DB_USER = os.getenv('DB_USER', 'postgres')
            DB_PASSWORD = os.getenv('DB_PASSWORD', '')
            
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname='postgres'
            )
            conn.close()
            
            print("\nCould connect to 'postgres' database but not to your app database.")
            print("This likely means your app database hasn't been created yet.")
            print("Please run 'python setup_db.py' to create it.")
            
        except Exception as inner_e:
            print("\nCould not connect to the 'postgres' database either.")
            print("Please check your PostgreSQL server settings and credentials.")
            
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1) 