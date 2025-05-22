#!/usr/bin/env python3
"""
Enhanced Utilities for Symm Bluesky Userbot

This module provides production-ready utilities including:
- Beautiful, accessible logging with colors and cross-platform compatibility
- Intelligent retry mechanisms with error classification
- Performance monitoring and metrics collection
- Health checking for databases and APIs
- Contextual logging with structured data
"""

import asyncio
import functools
import json
import logging
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import psutil
from colorama import init, Fore, Back, Style

# Initialize colorama for cross-platform colors
init(autoreset=True)

def is_windows() -> bool:
    """Check if running on Windows"""
    return os.name == 'nt'

def emoji_supported() -> bool:
    """Check if the current environment supports emoji output"""
    # Disable emojis on Windows to avoid encoding issues
    if is_windows():
        return False
    
    # Check if we're in a terminal that supports UTF-8
    try:
        if sys.stdout.encoding and 'utf' in sys.stdout.encoding.lower():
            return True
    except:
        pass
    
    return False

class LogLevel(Enum):
    """Enhanced log levels with color and emoji mapping"""
    DEBUG = ("DEBUG", Fore.CYAN, "🔍", "[DEBUG]")
    INFO = ("INFO", Fore.GREEN, "ℹ️", "[INFO]")
    SUCCESS = ("SUCCESS", Fore.LIGHTGREEN_EX, "✅", "[SUCCESS]")
    WARNING = ("WARNING", Fore.YELLOW, "⚠️", "[WARNING]")
    ERROR = ("ERROR", Fore.RED, "❌", "[ERROR]")
    CRITICAL = ("CRITICAL", Fore.LIGHTRED_EX + Back.RED, "🔥", "[CRITICAL]")

class ColoredFormatter(logging.Formatter):
    """Enhanced formatter with colors and cross-platform emoji support"""
    
    # Custom level for SUCCESS
    SUCCESS_LEVEL = 25
    
    def __init__(self, use_colors=True, use_emojis=None, include_context=True):
        super().__init__()
        self.use_colors = use_colors and not os.getenv('NO_COLOR')
        self.use_emojis = emoji_supported() if use_emojis is None else (use_emojis and emoji_supported())
        self.include_context = include_context
        
        # Add SUCCESS level to logging
        logging.addLevelName(self.SUCCESS_LEVEL, "SUCCESS")
        
        # Create colors mapping
        self.COLORS = {
            logging.DEBUG: LogLevel.DEBUG.value,
            logging.INFO: LogLevel.INFO.value,
            logging.WARNING: LogLevel.WARNING.value,
            logging.ERROR: LogLevel.ERROR.value,
            logging.CRITICAL: LogLevel.CRITICAL.value,
            self.SUCCESS_LEVEL: LogLevel.SUCCESS.value,
        }
    
    def format(self, record):
        level_info = self.COLORS.get(record.levelno, ("UNKNOWN", Fore.WHITE, "❓", "[UNKNOWN]"))
        level_name, color, emoji, fallback = level_info
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        
        # Build message components
        components = []
        
        # Level indicator
        if self.use_colors and self.use_emojis:
            components.append(f"{color}{emoji} {level_name}{Style.RESET_ALL}")
        elif self.use_colors:
            components.append(f"{color}{level_name}{Style.RESET_ALL}")
        elif self.use_emojis:
            components.append(f"{emoji} {level_name}")
        else:
            components.append(fallback)
        
        components.append(f"[{timestamp}]")
        components.append(f"[{record.name}]")
        components.append(record.getMessage())
        
        return " ".join(components)

class StructuredLogger:
    """Enhanced logger with beautiful formatting and contextual information"""
    
    def __init__(self, name: str, level: str = "INFO", 
                 use_colors: bool = True, use_emojis: bool = None,
                 log_file: Optional[str] = None):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        
        # Clear existing handlers to avoid duplicates
        self.logger.handlers.clear()
        self.logger.propagate = False  # Prevent propagation to avoid duplicate messages
        
        # Console handler with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = ColoredFormatter(use_colors, use_emojis)
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler (optional)
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_formatter = ColoredFormatter(False, False)  # No colors in file
                file_handler.setFormatter(file_formatter)
                self.logger.addHandler(file_handler)
            except Exception:
                # If file logging fails, continue without it
                pass
    
    def success(self, message, *args, **kwargs):
        """Log a success message"""
        self.logger.log(ColoredFormatter.SUCCESS_LEVEL, message, *args, **kwargs)
    
    def with_context(self, **context) -> 'ContextualLogger':
        """Create a contextual logger with additional context"""
        return ContextualLogger(self, context)
    
    def __getattr__(self, name):
        return getattr(self.logger, name)

class ContextualLogger:
    """Logger wrapper that adds context to all log messages"""
    
    def __init__(self, logger: StructuredLogger, context: Dict[str, Any]):
        self.logger = logger
        self.context = context
    
    def _format_message(self, message: str) -> str:
        context_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
        return f"[{context_str}] {message}"
    
    def with_context(self, **additional_context) -> 'ContextualLogger':
        """Create a new contextual logger with additional context"""
        merged_context = {**self.context, **additional_context}
        return ContextualLogger(self.logger, merged_context)
    
    def debug(self, message, *args, **kwargs):
        self.logger.debug(self._format_message(message), *args, **kwargs)
    
    def info(self, message, *args, **kwargs):
        self.logger.info(self._format_message(message), *args, **kwargs)
    
    def success(self, message, *args, **kwargs):
        self.logger.success(self._format_message(message), *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        self.logger.warning(self._format_message(message), *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        self.logger.error(self._format_message(message), *args, **kwargs)
    
    def critical(self, message, *args, **kwargs):
        self.logger.critical(self._format_message(message), *args, **kwargs)

@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    backoff_strategy: str = "exponential"  # "exponential", "linear", "constant"

class ErrorClassifier:
    """Classify errors to determine retry behavior"""
    
    RETRYABLE_ERRORS = {
        # Network errors
        "ConnectionError", "TimeoutError", "httpx.ConnectTimeout", 
        "httpx.ReadTimeout", "httpx.ConnectError", "httpx.RemoteProtocolError",
        # Database errors
        "asyncpg.ConnectionDoesNotExistError", "asyncpg.ConnectionFailureError",
        "psycopg2.OperationalError", "psycopg2.InterfaceError",
        # API rate limiting
        "HTTPStatusError", "TooManyRequestsError", "RateLimitError",
        # Temporary service issues
        "ServiceUnavailableError", "BadGatewayError", "GatewayTimeoutError"
    }
    
    NON_RETRYABLE_ERRORS = {
        # Authentication errors
        "AuthenticationError", "UnauthorizedError", "ForbiddenError",
        # Client errors
        "ValidationError", "BadRequestError", "NotFoundError",
        # Programming errors
        "TypeError", "ValueError", "KeyError", "AttributeError"
    }
    
    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        """Determine if an error should trigger a retry"""
        error_type = type(error).__name__
        error_str = str(error).lower()
        
        # Check explicit non-retryable errors first
        if error_type in cls.NON_RETRYABLE_ERRORS:
            return False
        
        # Check explicit retryable errors
        if error_type in cls.RETRYABLE_ERRORS:
            return True
        
        # Check HTTP status codes
        if hasattr(error, 'response') and hasattr(error.response, 'status_code'):
            status = error.response.status_code
            if 400 <= status < 500 and status not in [408, 429, 502, 503, 504]:
                return False  # Client errors (except timeouts and rate limits)
            if 500 <= status < 600:
                return True   # Server errors
        
        # Check error message content
        if any(keyword in error_str for keyword in 
               ['timeout', 'connection', 'network', 'rate limit', 'temporary']):
            return True
        
        # Default to non-retryable for safety
        return False

def async_retry(config: Optional[RetryConfig] = None):
    """Enhanced async retry decorator with intelligent error handling"""
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger = get_logger(f"retry.{func.__module__}.{func.__name__}")
            
            last_exception = None
            for attempt in range(config.max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    
                    if attempt > 0:
                        logger.success(f"Function {func.__name__} succeeded on attempt {attempt + 1}")
                    
                    return result
                
                except Exception as e:
                    last_exception = e
                    
                    # Check if error is retryable
                    if not ErrorClassifier.is_retryable(e):
                        logger.error(f"Non-retryable error in {func.__name__}: {e}")
                        raise e
                    
                    if attempt < config.max_attempts - 1:
                        # Calculate delay
                        if config.backoff_strategy == "exponential":
                            delay = min(
                                config.base_delay * (config.exponential_base ** attempt),
                                config.max_delay
                            )
                        elif config.backoff_strategy == "linear":
                            delay = min(config.base_delay * (attempt + 1), config.max_delay)
                        else:  # constant
                            delay = config.base_delay
                        
                        # Add jitter
                        if config.jitter:
                            import random
                            delay = delay * (0.5 + random.random() * 0.5)
                        
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {config.max_attempts} attempts failed for {func.__name__}")
            
            # All attempts exhausted
            raise last_exception
        
        return wrapper
    return decorator

class HealthChecker:
    """System health monitoring"""
    
    def __init__(self):
        self.logger = get_logger("health_checker")
    
    async def check_database_health(self, database_func: Callable) -> Dict[str, Any]:
        """Check database connectivity and performance"""
        start_time = time.time()
        try:
            result = await database_func()
            duration = time.time() - start_time
            
            return {
                "status": "healthy" if result else "unhealthy",
                "response_time": duration,
                "error": None
            }
        except Exception as e:
            duration = time.time() - start_time
            return {
                "status": "unhealthy",
                "response_time": duration,
                "error": str(e)
            }
    
    async def check_api_health(self, url: str, timeout: float = 10.0) -> Dict[str, Any]:
        """Check external API health"""
        import httpx
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                duration = time.time() - start_time
                
                return {
                    "status": "healthy" if response.status_code < 400 else "degraded",
                    "status_code": response.status_code,
                    "response_time": duration,
                    "error": None
                }
        except Exception as e:
            duration = time.time() - start_time
            return {
                "status": "unhealthy",
                "status_code": None,
                "response_time": duration,
                "error": str(e)
            }
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)  # Faster check
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/' if not is_windows() else 'C:')
            
            return {
                "cpu_usage": cpu_percent,
                "memory_usage": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_usage": disk.percent,
                "disk_free_gb": disk.free / (1024**3),
                "status": "healthy"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

class PerformanceMonitor:
    """Performance monitoring and metrics collection"""
    
    def __init__(self):
        self.operation_times = {}
        self.counters = {}
    
    @asynccontextmanager
    async def measure(self, operation_name: str):
        """Context manager to measure operation duration"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            self.record_duration(operation_name, duration)
    
    def record_duration(self, operation_name: str, duration: float):
        """Record the duration of an operation"""
        if operation_name not in self.operation_times:
            self.operation_times[operation_name] = {
                'times': [],
                'total': 0,
                'count': 0,
                'min': float('inf'),
                'max': 0
            }
        
        stats = self.operation_times[operation_name]
        stats['times'].append(duration)
        stats['total'] += duration
        stats['count'] += 1
        stats['min'] = min(stats['min'], duration)
        stats['max'] = max(stats['max'], duration)
    
    def increment_counter(self, counter_name: str, value: int = 1):
        """Increment a counter"""
        self.counters[counter_name] = self.counters.get(counter_name, 0) + value
    
    def get_stats(self, operation_name: str) -> Dict[str, float]:
        """Get statistics for a specific operation"""
        if operation_name not in self.operation_times:
            return {}
        
        stats = self.operation_times[operation_name]
        return {
            'count': stats['count'],
            'total': stats['total'],
            'avg': stats['total'] / stats['count'] if stats['count'] > 0 else 0,
            'min': stats['min'] if stats['min'] != float('inf') else 0,
            'max': stats['max']
        }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get all performance statistics"""
        return {
            'operations': {name: self.get_stats(name) for name in self.operation_times},
            'counters': self.counters.copy()
        }

# Global instances
_logger_cache = {}
_performance_monitor = None

def get_logger(name: str, level: str = None, **kwargs) -> StructuredLogger:
    """Get or create a structured logger instance"""
    if level is None:
        level = os.getenv('LOG_LEVEL', 'INFO')
    
    cache_key = (name, level)
    if cache_key not in _logger_cache:
        _logger_cache[cache_key] = StructuredLogger(name, level, **kwargs)
    
    return _logger_cache[cache_key]

def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor

def format_error(error: Exception, include_traceback: bool = True) -> str:
    """Format an error for logging with optional traceback"""
    error_msg = f"{type(error).__name__}: {str(error)}"
    
    if include_traceback:
        tb = traceback.format_exc()
        error_msg += f"\n{tb}"
    
    return error_msg

def safe_json_serialize(obj: Any) -> str:
    """Safely serialize an object to JSON with fallbacks for complex types"""
    def default_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()
        elif hasattr(o, '__dict__'):
            return o.__dict__
        else:
            return str(o)
    
    try:
        return json.dumps(obj, default=default_serializer, indent=2)
    except Exception as e:
        return f"<Serialization failed: {e}>"

def create_timestamped_filename(base_name: str, extension: str = "log") -> str:
    """Create a filename with timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_{timestamp}.{extension}"

@asynccontextmanager
async def logged_operation(operation_name: str, logger: Optional[StructuredLogger] = None):
    """Context manager for logging operation start/end with timing"""
    if logger is None:
        logger = get_logger("operations")
    
    start_time = time.time()
    start_msg = f"Starting operation: {operation_name}"
    if emoji_supported():
        start_msg = f"🚀 {start_msg}"
    
    logger.info(start_msg)
    
    try:
        yield
        duration = time.time() - start_time
        success_msg = f"Operation completed: {operation_name} (took {duration:.2f}s)"
        if emoji_supported():
            success_msg = f"✅ {success_msg}"
        logger.success(success_msg)
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Operation failed: {operation_name} (took {duration:.2f}s) - {e}"
        if emoji_supported():
            error_msg = f"❌ {error_msg}"
        logger.error(error_msg)
        raise 