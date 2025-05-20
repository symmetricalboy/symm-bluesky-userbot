# Bluesky Account Agent

This is a userbot for Bluesky that synchronizes blocks across multiple accounts.

## Features

- Automatically synchronize blocks across multiple accounts
- Monitor for new blocks in real-time
- Create moderation lists for easy sharing of blocked accounts

## Setup

1. Create a `.env` file based on `.env.example` with your credentials
2. Install dependencies with `pip install -r requirements.txt`
3. Set up the database with `python setup_db.py`
4. Run the bot with `python main.py`

## Recent Fixes

- Fixed moderation list creation by using direct dictionary creation instead of trying to use `models.AppBskyGraphList` as a constructor
- Corrected ClearSky API endpoint usage, changing from `/blockedby/{did}` to `/single-blocklist/{did}`
- Updated HTTP client to automatically follow redirects when interacting with external APIs
- Fixed parameter naming in API calls from `record=` to `data=`
- Added support for properly handling HTTP redirects from the ClearSky API
- Added testing commands for comprehensive verification:
  - `python main.py --test`: Test all system components without making changes
  - `python main.py --test-modlist`: Test moderation list functionality specifically

## Requirements

- Python 3.8+
- Postgres database
- Bluesky account credentials

## Testing

You can verify functionality without making actual changes:

```bash
# Basic component testing
python main.py --test

# Specific functionality testing
python main.py --test-modlist

# API testing
python test_clearsky.py      # Test ClearSky API connection
python test_mod_list.py      # Test moderation list creation
python test_account_agent.py # Test account agent functionality
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
- HTTP client follows redirects automatically when interacting with the ClearSky API 