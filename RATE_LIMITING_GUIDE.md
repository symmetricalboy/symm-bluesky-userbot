# Bluesky Userbot Rate Limiting Guide

## 🚨 **Critical Information: Account Lockout Prevention**

Your account lockouts are primarily caused by **excessive login attempts**, not content operations. This guide provides the solution.

## 📊 **Official Bluesky Rate Limits (2025)**

### **Session Creation (Login) Limits - MOST CRITICAL**
- **30 logins per 5 minutes (per account)**
- **300 logins per day (per account)**
- **Recent enforcement: Some users report as low as 10/day**

### **Content Write Operations**
- **5,000 points per hour (per account)**
- **35,000 points per day (per account)**
- Points: CREATE=3, UPDATE=2, DELETE=1
- **Max creates: 1,666/hour, 11,666/day**

### **API Request Limits**
- **3,000 requests per 5 minutes (per IP)**
- Various endpoint-specific limits

## 🛠️ **Solutions Implemented**

### **1. Session Management (PRIMARY FIX)**
The biggest improvement is **JWT token reuse** to avoid frequent logins:

- **Access tokens**: Valid for ~2 hours
- **Refresh tokens**: Valid for ~2 months  
- **Automatic refresh**: Tokens refresh before expiry
- **Persistent storage**: Sessions saved to `session_*.json` files

### **2. Conservative Rate Limiting**
Updated all scripts with much more conservative limits:

```python
# Old vs New Settings
BATCH_SIZE: 5 → 3 (sync_mod_list.py)
DELAY_BETWEEN_REQUESTS: 1.0s → 2.0s
DELAY_BETWEEN_BATCHES: 30s → 60s
DELAY_AFTER_RATE_LIMIT: 10min → 15min
MAX_ADDS_PER_SESSION: 100 → 50
```

### **3. Request Rate Limiting**
- **2 second minimum** between API requests
- **5-minute request windows** tracking
- **Automatic backoff** when approaching limits

## 🔧 **How Session Management Works**

### **Automatic Session Reuse**
The `AccountAgent` class now automatically:

1. **Checks for existing session** files
2. **Validates token expiry** dates
3. **Refreshes access tokens** when needed (every ~2 hours)
4. **Performs full login** only when refresh token expires (~2 months)

### **Session Files**
Located at: `session_[handle].json`
```json
{
  "handle": "your.handle",
  "did": "did:plc:...",
  "accessJwt": "eyJ0...",
  "refreshJwt": "eyJ0...",
  "accessDate": "2025-01-27T10:30:00",
  "refreshDate": "2025-01-27T10:30:00"
}
```

### **Manual Session Recovery**
If you're already rate-limited, you can manually create a session file:

1. **Login to Bluesky in browser**
2. **Open Developer Console** (F12)
3. **Go to Network tab**
4. **Find any `app.bsky.actor.getProfile` request**
5. **Extract from headers**:
   - `handle`: Your @handle
   - `did`: From response body
   - `accessJwt`: From Authorization header (remove "Bearer ")
   - `refreshJwt`: Use same as accessJwt (will auto-refresh)

## 📈 **Current Rate Limiting Settings**

### **account_agent.py** (Core Session Management)
```python
CLEARSKY_REQUEST_DELAY = 2.0  # 2 seconds between ClearSky requests
API_REQUESTS_PER_5MIN = 2500  # Conservative, under 3000 limit
REQUEST_INTERVAL_SECONDS = 0.12  # ~8 req/sec average
ACCESS_TOKEN_LIFETIME_MINUTES = 115  # Refresh before 2hr expiry
REFRESH_TOKEN_LIFETIME_DAYS = 55  # Refresh before 2mo expiry
```

### **sync_mod_list.py** (Moderation List Sync)
```python
BATCH_SIZE = 3  # Very conservative batching
DELAY_BETWEEN_REQUESTS = 2.0  # 2 seconds between requests
DELAY_BETWEEN_BATCHES = 60  # 1 minute between batches
DELAY_AFTER_RATE_LIMIT = 900  # 15 minutes after rate limit
```

### **add_dids_auto.py** (Adding DIDs)
```python
DELAY_BETWEEN_ADDS = 10.0  # 10 seconds between adds
DELAY_AFTER_ERROR = 30.0  # 30 seconds after errors
DELAY_AFTER_RATE_LIMIT = 1200.0  # 20 minutes after rate limit
MAX_ADDS_PER_SESSION = 50  # Maximum 50 adds per run
```

## 🔍 **Monitoring & Debugging**

### **Check Session Status**
```python
from account_agent import AccountAgent
agent = AccountAgent("your.handle", "password")
session_data = await agent._load_session_from_file()
if session_data:
    print(f"Session loaded: {session_data['accessDate']}")
```

### **Rate Limit Detection**
Watch for these log messages:
- `"Rate limit approaching"` - Automatic backoff
- `"Rate limited! Account may be temporarily locked"` - Need to wait
- `"Failed to use saved session"` - Session refresh needed

### **Performance Monitoring**
The system now logs:
- **Session reuse** vs **full logins**
- **Token refresh** operations
- **Rate limit** encounters
- **Request timing** and **batch progress**

## ⚡ **Best Practices**

### **1. Avoid Frequent Restarts**
- **Don't restart** the application frequently
- **Let sessions persist** between runs
- **Use checkpoints** to resume operations

### **2. Monitor Operations**
- **Track daily operations** to stay under limits
- **Use batch processing** for large operations
- **Implement progressive delays** when approaching limits

### **3. Error Handling**
- **Respect rate limit responses** (HTTP 429)
- **Implement exponential backoff** for retries
- **Log all rate limit encounters** for analysis

### **4. Production Deployment**
- **Use environment variables** for sensitive data
- **Rotate credentials** periodically
- **Monitor session files** for corruption
- **Implement health checks** for rate limit status

## 🚀 **Testing The Improvements**

### **Test Session Management**
```bash
# First run - should do full login and save session
python main.py

# Second run - should reuse session (no login)
python main.py

# Check session files created
ls session_*.json
```

### **Test Rate Limiting**
```bash
# Should be much slower but safer
python sync_mod_list.py

# Monitor logs for rate limiting messages
tail -f sync_mod_list_*.log
```

## 📞 **Emergency Recovery**

### **If Account is Locked**
1. **Stop all scripts** immediately
2. **Wait 24 hours** for daily limits to reset
3. **Manually create session file** (see above)
4. **Use session reuse** when resuming operations

### **If Sessions Corrupted**
```bash
# Remove all session files to force fresh login
rm session_*.json

# Run with extra logging
LOG_LEVEL=DEBUG python main.py
```

## 📝 **Summary**

The primary fix is **session management** to prevent frequent logins. Combined with **conservative rate limiting**, this should eliminate account lockouts while maintaining functionality.

**Key changes:**
- ✅ **Session reuse** - No more frequent logins
- ✅ **Token refresh** - Automatic before expiry  
- ✅ **Conservative batching** - Smaller, slower batches
- ✅ **Request rate limiting** - Built-in delays
- ✅ **Better error handling** - Graceful rate limit recovery

**Expected improvement:**
- **Logins**: From multiple/day → 1 every ~2 months
- **Rate limits**: Rare encounters vs frequent
- **Reliability**: Stable long-term operation 