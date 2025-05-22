# Symmetrical Bluesky Userbot

A userbot for Bluesky that handles block synchronization between multiple accounts and manages a moderation list.

## Features

- Synchronizes blocks across multiple Bluesky accounts
- Creates and maintains a moderation list for the primary account
- Monitors real-time block events via Jetstream firehose
- Initializes block data from ClearSky API
- Persists block information in a PostgreSQL database

## Setup

1. Clone this repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - macOS/Linux: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and configure your credentials and settings
6. Run the bot: `python main.py`

## Configuration

Edit the `.env` file with your account credentials:

```
PRIMARY_BLUESKY_HANDLE="your.primary.handle"
PRIMARY_BLUESKY_PASSWORD="your-password"
SECONDARY_ACCOUNTS="secondary.handle1,password1;secondary.handle2,password2"
DATABASE_URL="postgresql://username:password@host:port/database"
```

## Usage

### Standard Operation

Run the bot in standard operation mode:

```
python main.py
```

This will:
1. Initialize the database schema
2. Register all accounts in the database
3. Import initial block data from ClearSky API
4. Start monitoring for new block events via Jetstream firehose
5. Synchronize blocks across all accounts
6. Maintain a moderation list on the primary account

### Command Line Options

- `--test`: Run in test mode without making any changes
- `--test-modlist`: Test moderation list functionality only
- `--skip-diagnostics`: Skip running diagnostics and tests
- `--skip-clearsky-init`: Skip initializing blocks from ClearSky API

### Diagnostics

Run the diagnostic script to check database status and block synchronization:

```
python run_diagnostic.py
```

This will:
1. Initialize accounts in the database
2. Populate block data from ClearSky API
3. Display detailed information about accounts and blocks

## Architecture

The bot uses:
- AtProto client library for Bluesky API communication
- Jetstream firehose for real-time block event monitoring
- ClearSky API for initial block data import
- PostgreSQL database for persistence

## Block Synchronization Flow

1. **Initial Setup**:
   - Accounts are registered in the database
   - Initial block data is imported from ClearSky API

2. **Ongoing Monitoring**:
   - Jetstream firehose is used to monitor real-time block events
   - New blocks are added to the database
   - Blocks are synchronized across all accounts
   - The primary account's moderation list is updated

## Troubleshooting

If you're experiencing issues, run the diagnostic script:

```
python run_diagnostic.py
```

Or check the database contents directly:

```
python debug_database.py
```

## License

[MIT License](LICENSE) 