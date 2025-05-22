# Enhanced Symm Bluesky Userbot 🚀

A production-ready, intelligent Bluesky userbot with comprehensive error handling, beautiful logging, health monitoring, and robust retry mechanisms. This enhanced version provides enterprise-grade reliability with accessible, colorful diagnostics.

## ✨ Enhanced Features

### 🎨 Beautiful & Accessible Logging
- **Colorized output** with emojis and structured formatting
- **Multiple log levels** including custom SUCCESS level
- **Contextual logging** with operation tracking
- **File and console logging** with different formatters
- **Performance metrics** integrated into log output

### 🔄 Intelligent Error Handling & Retries
- **Automatic error classification** (retryable vs non-retryable)
- **Exponential backoff** with jitter for optimal retry timing
- **Configurable retry policies** per operation type
- **Graceful degradation** when services are unavailable
- **Circuit breaker patterns** for external API calls

### 💚 Comprehensive Health Monitoring
- **Real-time system health checks** (database, APIs, resources)
- **Performance monitoring** with operation timing and metrics
- **Automated diagnostics** with actionable recommendations
- **Interactive diagnostic tools** for troubleshooting
- **Health status reporting** with detailed system information

### 🛡️ Production-Ready Orchestration
- **Staged startup sequence** with validation at each step
- **Graceful shutdown** with proper cleanup
- **Signal handling** for container environments
- **Health monitoring loops** with automatic recovery
- **Resource usage tracking** and optimization

### 🔍 Advanced Diagnostics
- **Interactive diagnostic sessions** with menu-driven interface
- **Database integrity checks** with automated cleanup suggestions
- **API health validation** with response time monitoring
- **Environment validation** with security-conscious output
- **System resource monitoring** with threshold alerts

## 📋 Prerequisites

- **Python 3.8+** (tested with 3.9-3.11)
- **PostgreSQL 12+** database
- **Bluesky account(s)** with valid credentials
- **System requirements**: 1GB+ RAM, reliable internet connection

## 🚀 Installation

### 1. Clone and Setup
```bash
git clone <repository-url>
cd symm-bluesky-userbot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database Setup
```bash
# Create PostgreSQL database
createdb symm_blocks

# Or using SQL:
# CREATE DATABASE symm_blocks;
```

### 3. Environment Configuration
Copy the example environment file and configure:
```bash
cp .env.example .env
# Edit .env with your settings (see Configuration section)
```

## ⚙️ Configuration

### Required Environment Variables

```bash
# Primary Bluesky Account (Required)
PRIMARY_BLUESKY_HANDLE=your.handle.bsky.social
PRIMARY_BLUESKY_PASSWORD=your-app-password

# Database Configuration (Required)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=symm_blocks
DB_USER=postgres
DB_PASSWORD=your-db-password

# Alternative: Use DATABASE_URL instead of individual DB settings
# DATABASE_URL=postgresql://user:password@host:port/database
```

### Optional Environment Variables

```bash
# Secondary Accounts (Optional)
SECONDARY_ACCOUNTS=handle1:password1;handle2:password2

# API Configuration
CLEARSKY_API_URL=https://api.clearsky.services/api/v1/anon

# Moderation List Settings
MOD_LIST_NAME=Synchronized Blocks
MOD_LIST_DESCRIPTION=Automatically synchronized block list

# Logging & Monitoring
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
HEALTH_CHECK_INTERVAL=300  # Health check interval in seconds
MAX_CONSECUTIVE_FAILURES=3  # Max failures before marking unhealthy

# Database Pool Settings
DB_MIN_CONNECTIONS=1
DB_MAX_CONNECTIONS=10

# Testing
LOCAL_TEST=false  # Set to true for test mode
TEST_DATABASE_URL=postgresql://user:password@host:port/test_db
```

## 🎯 Usage

### Production Mode (Default)
```bash
# Full production startup with all features
python main.py

# Skip specific phases
python main.py --skip-clearsky     # Skip ClearSky data import
python main.py --skip-modlist-sync # Skip moderation list sync
python main.py --skip-diagnostics  # Skip pre-flight diagnostics
```

### Test & Diagnostic Modes
```bash
# Test mode - no persistent changes
python main.py --test

# Run diagnostics only
python main.py --diagnostics

# Interactive diagnostic session
python main.py --interactive
```

### Logging Options
```bash
# Set log level
python main.py --log-level DEBUG

# Log to file
python main.py --log-file app.log
```

## 🔍 Health Monitoring & Diagnostics

### System Health Checks
The system automatically monitors:
- **Database connectivity** and schema integrity
- **ClearSky API** health and response times
- **Account authentication** status
- **System resources** (CPU, memory, disk usage)
- **Environment configuration** completeness

### Interactive Diagnostics
Launch the interactive diagnostic session:
```bash
python main.py --interactive
```

Available options:
1. **Full System Diagnostics** - Comprehensive health check
2. **Database Analysis** - Table statistics and performance metrics
3. **Data Integrity Check** - Find and fix data inconsistencies
4. **Performance Metrics** - Operation timing and throughput stats
5. **Save Results** - Export diagnostic results to JSON

### Diagnostic Files
The system automatically creates diagnostic files:
- `diagnostic_results_TIMESTAMP.json` - Full diagnostic results
- `symm_userbot_YYYYMMDD.log` - Daily log files
- `duplicate_dids_check_TIMESTAMP.log` - Data integrity reports

## 🎨 Log Output Examples

### Successful Operation
```
✅ 2024-01-15 10:30:45 | enhanced_main        | SUCCESS  | Startup sequence completed successfully
ℹ️  2024-01-15 10:30:46 | orchestrator        | INFO     | 🤖 Starting agent monitoring...
✅ 2024-01-15 10:30:47 | orchestrator        | SUCCESS  | Started monitoring for 2 agents
```

### Health Check Status
```
💚 2024-01-15 10:35:00 | orchestrator        | INFO     | 📊 System Status Report:
   2024-01-15 10:35:00 | orchestrator        | INFO     |   🤖 Active Agents: 2
   2024-01-15 10:35:00 | orchestrator        | INFO     |   💚 System Health: Healthy
   2024-01-15 10:35:00 | orchestrator        | INFO     |   🔄 Health Checks: 12
```

### Error with Retry
```
⚠️  2024-01-15 10:31:23 | retry.main.setup    | WARNING  | Attempt 1 failed for setup_database: Connection refused. Retrying in 2.34s...
✅ 2024-01-15 10:31:26 | retry.main.setup    | SUCCESS  | Function setup_database succeeded on attempt 2
```

## 🗄️ Database Schema

The system uses three main tables:

### `accounts`
```sql
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(255) UNIQUE NOT NULL,
    did VARCHAR(255) UNIQUE NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    last_firehose_cursor BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `blocked_accounts`
```sql
CREATE TABLE blocked_accounts (
    id SERIAL PRIMARY KEY,
    did VARCHAR(255) NOT NULL,
    handle VARCHAR(255),
    reason TEXT,
    source_account_id INTEGER REFERENCES accounts(id),
    block_type VARCHAR(50) NOT NULL, -- 'blocking' or 'blocked_by'
    is_synced BOOLEAN DEFAULT FALSE,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `mod_lists`
```sql
CREATE TABLE mod_lists (
    id SERIAL PRIMARY KEY,
    list_uri VARCHAR(255) UNIQUE NOT NULL,
    list_cid VARCHAR(255),
    owner_did VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 🔧 Troubleshooting

### Common Issues

#### Database Connection Issues
```bash
# Check database status
sudo systemctl status postgresql

# Test connection manually
psql -h localhost -U postgres -d symm_blocks -c "SELECT 1;"

# Check logs
tail -f diagnostic_results_*.json
```

#### Authentication Problems
```bash
# Test credentials
python main.py --diagnostics

# Check Bluesky service status
curl -I https://bsky.social

# Verify app passwords are enabled
```

#### Performance Issues
```bash
# Run performance diagnostics
python main.py --interactive
# Select option 4: Performance Metrics

# Check system resources
python -c "import psutil; print(f'CPU: {psutil.cpu_percent()}%, Memory: {psutil.virtual_memory().percent}%')"
```

#### Rate Limiting
```bash
# Check for rate limiting errors in logs
grep -i "rate limit\|429\|too many" *.log

# Adjust delays in environment
export CLEARSKY_REQUEST_DELAY=3.0
```

### Error Message Guide

| Error Type | Common Causes | Solutions |
|------------|---------------|-----------|
| `Database connection failed` | PostgreSQL not running, wrong credentials | Check DB service, verify `.env` |
| `Account authentication failed` | Wrong credentials, disabled account | Check app passwords, account status |
| `ClearSky API timeout` | Network issues, API overload | Check connection, increase timeout |
| `High system resource usage` | Insufficient RAM/CPU | Upgrade hardware, optimize settings |
| `Missing environment variables` | Incomplete `.env` file | Copy from `.env.example`, fill all required |

### Recovery Procedures

#### Reset Database
```bash
# Drop and recreate tables
python drop_all_tables.py
python main.py --diagnostics
```

#### Clear Session Data
```bash
# Remove cached sessions
rm session_*.json
python main.py --test
```

#### Emergency Diagnostics
```bash
# Run basic health checks
python main.py --diagnostics --log-level DEBUG

# Generate comprehensive report
python main.py --interactive
# Select "1" for full diagnostics, then "5" to save results
```

## 📊 Performance Tuning

### Database Optimization
```bash
# Increase connection pool for high load
export DB_MAX_CONNECTIONS=20

# Enable connection pooling optimizations
export DB_POOL_TIMEOUT=30
```

### API Rate Limiting
```bash
# Adjust ClearSky API delays
export CLEARSKY_REQUEST_DELAY=2.0

# Reduce health check frequency
export HEALTH_CHECK_INTERVAL=600  # 10 minutes
```

### Memory Management
```bash
# Reduce log retention
export LOG_RETENTION_DAYS=7

# Optimize for memory-constrained environments
export DB_MIN_CONNECTIONS=1
export DB_MAX_CONNECTIONS=5
```

## 🐳 Docker Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### Docker Compose
```yaml
version: '3.8'
services:
  userbot:
    build: .
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/symm_blocks
      - PRIMARY_BLUESKY_HANDLE=your.handle.bsky.social
      - PRIMARY_BLUESKY_PASSWORD=your-password
    depends_on:
      - db
    restart: unless-stopped
    
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=symm_blocks
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

## 🔒 Security Considerations

### Credentials Management
- Use **app passwords** instead of main account passwords
- Store sensitive data in environment variables, not code
- Regularly rotate credentials
- Use **read-only database users** where possible

### Network Security
- Restrict database access to localhost/VPN
- Use **TLS connections** for database and APIs
- Implement **firewall rules** for production deployments
- Monitor for suspicious API usage patterns

### Operational Security
- Enable **audit logging** for database operations
- Monitor **resource usage** for anomalies
- Use **container isolation** in production
- Implement **backup and recovery** procedures

## 🤝 Contributing

### Development Setup
```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/

# Code formatting
black .
isort .

# Type checking
mypy .
```

### Code Standards
- **Type hints** for all function parameters and returns
- **Comprehensive error handling** with proper logging
- **Unit tests** for new functionality
- **Documentation** for complex operations

### Testing
```bash
# Run full test suite
python main.py --test

# Test specific components
python diagnostic_tools.py --interactive

# Database tests
python test_db_connection.py
```

## 📈 Monitoring & Alerts

### Health Endpoints
The system provides health information through:
- **Diagnostic files** with JSON health data
- **Log files** with structured health information  
- **Interactive diagnostics** for real-time status

### Key Metrics to Monitor
- **Database connection health** and response times
- **API success rates** and response times
- **Memory and CPU usage** trends
- **Error rates** and types
- **Agent uptime** and synchronization status

### Alert Thresholds
- Database response time > 5 seconds
- Memory usage > 85%
- Error rate > 5% over 10 minutes
- API failure rate > 10%
- Consecutive health check failures > 3

## 📚 API Reference

### Enhanced Utilities (`utils.py`)
```python
from utils import get_logger, async_retry, RetryConfig

# Get a contextual logger
logger = get_logger('my_component')
logger.info("Operation started")
logger.success("Operation completed")

# Add retry logic
@async_retry(RetryConfig(max_attempts=3, base_delay=2.0))
async def my_operation():
    # Your code here
    pass
```

### Diagnostic Tools (`diagnostic_tools.py`)
```python
from diagnostic_tools import SystemDiagnostics

# Run diagnostics programmatically
diagnostics = SystemDiagnostics()
results = await diagnostics.run_all_checks()

# Save results
filename = diagnostics.save_results()
```

### Enhanced Database (`database.py`)
```python
from database import Database

# Use enhanced database with retry logic
db = Database()
accounts = await db.get_account_configurations()
```

## 📞 Support

### Documentation
- **Setup Guide**: This README
- **API Reference**: Code docstrings and type hints
- **Troubleshooting**: See troubleshooting section above
- **Examples**: `demo.py` for feature demonstrations

### Getting Help
1. **Check diagnostic output**: `python main.py --diagnostics`
2. **Review log files**: Look for ERROR and WARNING messages
3. **Run interactive diagnostics**: `python main.py --interactive`
4. **Check system health**: Monitor resource usage and API connectivity

### Bug Reports
When reporting issues, please include:
- **Diagnostic output** from `--diagnostics` mode
- **Log files** with ERROR/WARNING messages
- **Environment details** (OS, Python version, resource limits)
- **Steps to reproduce** the issue
- **Expected vs actual behavior**

## 🏆 Production Checklist

Before deploying to production:

- [ ] **Database backup** strategy implemented
- [ ] **Environment variables** properly configured
- [ ] **Health monitoring** alerts set up
- [ ] **Log rotation** configured
- [ ] **Resource limits** appropriate for load
- [ ] **Network security** rules in place
- [ ] **Credential rotation** schedule established
- [ ] **Recovery procedures** tested
- [ ] **Performance benchmarks** established
- [ ] **Monitoring dashboards** configured

---

## 🎉 Success!

You now have a production-ready Bluesky userbot with enterprise-grade reliability, beautiful diagnostics, and comprehensive monitoring. The system will automatically handle errors gracefully, provide detailed health information, and maintain optimal performance.

For questions or issues, refer to the troubleshooting section or run the interactive diagnostics for detailed system analysis.

**Happy botting! 🤖✨** 