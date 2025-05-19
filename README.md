# Symm Bluesky Userbot

A bot system that synchronizes blocks across multiple Bluesky accounts by collecting and aggregating block data.

## Features

- Monitors multiple Bluesky accounts for blocking and blocked-by data
- Uses both ATProto Jetstream and ClearSky API for comprehensive monitoring
- Centralizes blocking data in a PostgreSQL database
- Synchronizes blocks across all managed accounts through a primary account

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure the `.env` file with your account credentials and database information
   ```
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. Setup the PostgreSQL database:
   ```
   python setup_db.py
   ```

4. Run the bot:
   ```
   python main.py
   ```

## Deployment on Railway

This project is designed to be easily deployed on [Railway](https://railway.app/):

1. Create a new project in Railway
2. Add a PostgreSQL database service
3. Add a Python service pointing to your repository
4. Set the environment variables in the Railway dashboard:
   - `PRIMARY_BLUESKY_HANDLE` and `PRIMARY_BLUESKY_PASSWORD` for the primary account
   - `SECONDARY_ACCOUNTS` for other accounts
   - Database credentials will be automatically injected by Railway
   - Other configuration options as needed

The application will automatically check if the database is set up at startup, and if not, it will run the database setup process. This makes deployment seamless without manual database setup steps.

## Architecture

- Each account agent runs independently, collecting its own block data
- All data is centralized in a shared PostgreSQL database
- The primary account applies the aggregated block list to maintain synchronized blocking 