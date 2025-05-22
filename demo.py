#!/usr/bin/env python3
"""
Enhanced Symm Bluesky Userbot - Feature Demonstration

This demo showcases all the enhanced features:
- Beautiful, accessible logging with colors and emojis
- Intelligent error handling and retry mechanisms
- Health monitoring and performance tracking
- Interactive diagnostics and system information
- Production-ready orchestration capabilities
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Dict, Any

from colorama import init, Fore, Style

# Initialize colorama for cross-platform colors
init(autoreset=True)

# Import enhanced utilities
try:
    from utils import (
        get_logger, get_performance_monitor, async_retry, RetryConfig,
        HealthChecker, logged_operation, format_error, safe_json_serialize
    )
    from diagnostic_tools import SystemDiagnostics, run_interactive_diagnostics
    logger = get_logger('demo')
    performance_monitor = get_performance_monitor()
    use_enhanced_utils = True
except ImportError:
    # Fallback for basic functionality
    import logging
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
    logger = logging.getLogger('demo')
    performance_monitor = None
    use_enhanced_utils = False
    print(f"{Fore.YELLOW}⚠️  Enhanced utilities not available. Install dependencies first.{Style.RESET_ALL}")

class FeatureDemo:
    """Interactive demonstration of enhanced features"""
    
    def __init__(self):
        self.logger = get_logger('feature_demo') if use_enhanced_utils else logger
        self.performance_monitor = get_performance_monitor() if use_enhanced_utils else None
        
    def print_banner(self):
        """Print a beautiful banner"""
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}🚀 ENHANCED SYMM BLUESKY USERBOT - FEATURE DEMONSTRATION 🚀{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Welcome to the enhanced userbot demonstration!{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}This showcase highlights all the production-ready features.{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")
    
    def demo_beautiful_logging(self):
        """Demonstrate beautiful, accessible logging"""
        print(f"{Fore.BLUE}📝 BEAUTIFUL LOGGING DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ Enhanced logging not available{Style.RESET_ALL}")
            return
        
        # Get a contextual logger
        demo_logger = self.logger.with_context(
            feature='logging_demo',
            timestamp=datetime.now().strftime('%H:%M:%S')
        )
        
        print("Demonstrating different log levels with colors and emojis:")
        print()
        
        # Demonstrate all log levels
        demo_logger.debug("This is a debug message with context")
        demo_logger.info("This is an informational message")
        demo_logger.success("This is a success message - operation completed!")
        demo_logger.warning("This is a warning message - attention needed")
        demo_logger.error("This is an error message - something went wrong")
        
        # Demonstrate contextual logging
        operation_logger = demo_logger.with_context(
            operation='data_processing',
            batch_size=100,
            user_id='demo_user'
        )
        
        operation_logger.info("Processing data batch")
        operation_logger.success("Batch processing completed successfully")
        
        print(f"\n{Fore.GREEN}✅ Beautiful logging demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the colors, emojis, and structured context information.")
    
    async def demo_error_handling_retries(self):
        """Demonstrate intelligent error handling and retries"""
        print(f"\n{Fore.BLUE}🔄 ERROR HANDLING & RETRY DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ Enhanced error handling not available{Style.RESET_ALL}")
            return
        
        # Demonstrate successful retry after failures
        @async_retry(RetryConfig(max_attempts=3, base_delay=0.5, jitter=True))
        async def flaky_operation(attempt_counter: Dict[str, int]):
            """Simulates a flaky operation that fails first few times"""
            attempt_counter['count'] += 1
            
            if attempt_counter['count'] < 3:
                # Simulate different types of failures
                if attempt_counter['count'] == 1:
                    raise ConnectionError("Simulated network timeout")
                else:
                    raise Exception("Simulated temporary service unavailable")
            
            # Success on third attempt
            return f"Operation succeeded on attempt {attempt_counter['count']}"
        
        # Demonstrate non-retryable error
        @async_retry(RetryConfig(max_attempts=3, base_delay=0.3))
        async def non_retryable_operation():
            """Simulates a non-retryable error (authentication failure)"""
            raise ValueError("Invalid input data - non-retryable error")
        
        print("1. Testing retryable operation (will succeed after 2 failures):")
        try:
            attempt_counter = {'count': 0}
            result = await flaky_operation(attempt_counter)
            self.logger.success(f"Final result: {result}")
        except Exception as e:
            self.logger.error(f"Operation failed: {e}")
        
        print("\n2. Testing non-retryable operation (will fail immediately):")
        try:
            await non_retryable_operation()
        except Exception as e:
            self.logger.info(f"Non-retryable error handled correctly: {type(e).__name__}")
        
        print(f"\n{Fore.GREEN}✅ Error handling & retry demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the intelligent error classification and retry behavior.")
    
    async def demo_performance_monitoring(self):
        """Demonstrate performance monitoring capabilities"""
        print(f"\n{Fore.BLUE}📊 PERFORMANCE MONITORING DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not self.performance_monitor:
            print(f"{Fore.RED}❌ Performance monitoring not available{Style.RESET_ALL}")
            return
        
        # Simulate different operations with varying durations
        operations = [
            ("database_query", 0.1),
            ("api_request", 0.3),
            ("data_processing", 0.2),
            ("file_operation", 0.15)
        ]
        
        for operation_name, duration in operations:
            async with self.performance_monitor.measure(operation_name):
                self.logger.info(f"Executing {operation_name}...")
                await asyncio.sleep(duration)  # Simulate work
                self.performance_monitor.increment_counter(f"{operation_name}_count")
        
        # Get and display statistics
        stats = self.performance_monitor.get_all_stats()
        
        print(f"\n{Fore.YELLOW}📈 Performance Statistics:{Style.RESET_ALL}")
        
        if stats['operations']:
            print(f"  {Fore.CYAN}Operation Timings:{Style.RESET_ALL}")
            for operation, metrics in stats['operations'].items():
                avg_time = metrics.get('avg', 0)
                count = metrics.get('count', 0)
                print(f"    • {operation}: {count} calls, avg {avg_time:.3f}s")
        
        if stats['counters']:
            print(f"  {Fore.CYAN}Operation Counters:{Style.RESET_ALL}")
            for counter, value in stats['counters'].items():
                print(f"    • {counter}: {value}")
        
        print(f"\n{Fore.GREEN}✅ Performance monitoring demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the detailed timing and counting metrics.")
    
    async def demo_health_monitoring(self):
        """Demonstrate health monitoring capabilities"""
        print(f"\n{Fore.BLUE}💚 HEALTH MONITORING DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ Health monitoring not available{Style.RESET_ALL}")
            return
        
        health_checker = HealthChecker()
        
        # Simulate database health check
        async def mock_db_check():
            """Mock database health check"""
            await asyncio.sleep(0.1)  # Simulate query time
            return True
        
        print("Running system health checks...")
        
        # Check database health
        db_health = await health_checker.check_database_health(mock_db_check)
        status_color = Fore.GREEN if db_health['status'] == 'healthy' else Fore.RED
        print(f"  Database: {status_color}{db_health['status']}{Style.RESET_ALL} "
              f"(response time: {db_health['response_time']:.3f}s)")
        
        # Check API health
        api_health = await health_checker.check_api_health(
            "https://httpbin.org/status/200", timeout=5.0
        )
        status_color = Fore.GREEN if api_health['status'] == 'healthy' else Fore.RED
        print(f"  API Health: {status_color}{api_health['status']}{Style.RESET_ALL} "
              f"(status: {api_health.get('status_code', 'N/A')})")
        
        # Check system resources
        resource_health = health_checker.check_system_resources()
        status_color = Fore.GREEN if resource_health['status'] == 'healthy' else Fore.YELLOW
        print(f"  System Resources: {status_color}{resource_health['status']}{Style.RESET_ALL}")
        
        if resource_health['status'] == 'healthy':
            print(f"    • CPU Usage: {resource_health['cpu_usage']:.1f}%")
            print(f"    • Memory Usage: {resource_health['memory_usage']:.1f}%")
            print(f"    • Available Memory: {resource_health['memory_available_gb']:.1f} GB")
        
        print(f"\n{Fore.GREEN}✅ Health monitoring demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the real-time system health assessment.")
    
    async def demo_logged_operations(self):
        """Demonstrate logged operation context manager"""
        print(f"\n{Fore.BLUE}📋 LOGGED OPERATIONS DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ Logged operations not available{Style.RESET_ALL}")
            return
        
        # Demonstrate successful operation
        async with logged_operation("Data Synchronization", self.logger):
            self.logger.info("Fetching data from source...")
            await asyncio.sleep(0.2)
            self.logger.info("Processing data...")
            await asyncio.sleep(0.3)
            self.logger.info("Saving to database...")
            await asyncio.sleep(0.1)
        
        # Demonstrate failed operation
        try:
            async with logged_operation("Failed Operation Example", self.logger):
                self.logger.info("Starting operation...")
                await asyncio.sleep(0.1)
                raise Exception("Simulated operation failure")
        except Exception:
            pass  # Expected failure for demo
        
        print(f"\n{Fore.GREEN}✅ Logged operations demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the automatic timing and status logging.")
    
    def demo_data_serialization(self):
        """Demonstrate safe data serialization"""
        print(f"\n{Fore.BLUE}🔄 DATA SERIALIZATION DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ Enhanced serialization not available{Style.RESET_ALL}")
            return
        
        # Create complex data structure
        complex_data = {
            'timestamp': datetime.now(),
            'metrics': {
                'cpu_usage': 45.2,
                'memory_usage': 68.7,
                'operations': ['sync', 'monitor', 'health_check']
            },
            'config': {
                'retry_attempts': 3,
                'timeout': 30.0,
                'enabled_features': ['logging', 'monitoring', 'retries']
            }
        }
        
        # Demonstrate safe serialization
        serialized = safe_json_serialize(complex_data)
        
        print("Complex data structure serialized safely:")
        print(f"{Fore.CYAN}{serialized[:200]}...{Style.RESET_ALL}")
        
        print(f"\n{Fore.GREEN}✅ Data serialization demonstration complete!{Style.RESET_ALL}")
        print(f"Notice the safe handling of datetime and complex objects.")
    
    async def run_full_demo(self):
        """Run the complete feature demonstration"""
        self.print_banner()
        
        demos = [
            ("Beautiful Logging", self.demo_beautiful_logging),
            ("Error Handling & Retries", self.demo_error_handling_retries),
            ("Performance Monitoring", self.demo_performance_monitoring),
            ("Health Monitoring", self.demo_health_monitoring),
            ("Logged Operations", self.demo_logged_operations),
            ("Data Serialization", self.demo_data_serialization)
        ]
        
        for name, demo_func in demos:
            if asyncio.iscoroutinefunction(demo_func):
                await demo_func()
            else:
                demo_func()
            
            # Pause between demos
            await asyncio.sleep(1)
        
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}🎉 FEATURE DEMONSTRATION COMPLETE! 🎉{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}All enhanced features have been demonstrated.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}The system is ready for production use!{Style.RESET_ALL}")
        print()
    
    async def run_interactive_demo(self):
        """Run interactive demo with menu selection"""
        self.print_banner()
        
        demos = {
            '1': ("Beautiful Logging", self.demo_beautiful_logging),
            '2': ("Error Handling & Retries", self.demo_error_handling_retries),
            '3': ("Performance Monitoring", self.demo_performance_monitoring),
            '4': ("Health Monitoring", self.demo_health_monitoring),
            '5': ("Logged Operations", self.demo_logged_operations),
            '6': ("Data Serialization", self.demo_data_serialization),
            '7': ("System Diagnostics", self.run_system_diagnostics),
            '8': ("Run All Demos", self.run_full_demo)
        }
        
        while True:
            print(f"\n{Fore.BLUE}Available Demonstrations:{Style.RESET_ALL}")
            for key, (name, _) in demos.items():
                icon = "🔧" if "Diagnostics" in name else "🚀" if "All" in name else "✨"
                print(f"  {key}. {icon} {name}")
            print(f"  9. 🚪 Exit")
            
            try:
                choice = input(f"\n{Fore.GREEN}Select demo (1-9): {Style.RESET_ALL}").strip()
                
                if choice == '9':
                    print(f"\n{Fore.GREEN}👋 Thank you for trying the enhanced userbot!{Style.RESET_ALL}")
                    break
                elif choice in demos:
                    name, demo_func = demos[choice]
                    print(f"\n{Fore.YELLOW}🚀 Running: {name}{Style.RESET_ALL}")
                    
                    if asyncio.iscoroutinefunction(demo_func):
                        await demo_func()
                    else:
                        demo_func()
                        
                    input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}❌ Invalid choice. Please select 1-9.{Style.RESET_ALL}")
                    
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}🛑 Demo interrupted by user{Style.RESET_ALL}")
                break
            except Exception as e:
                print(f"{Fore.RED}❌ Error: {str(e)}{Style.RESET_ALL}")
    
    async def run_system_diagnostics(self):
        """Run system diagnostics demonstration"""
        print(f"\n{Fore.BLUE}🔍 SYSTEM DIAGNOSTICS DEMONSTRATION{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─' * 50}{Style.RESET_ALL}")
        
        if not use_enhanced_utils:
            print(f"{Fore.RED}❌ System diagnostics not available{Style.RESET_ALL}")
            return
        
        try:
            # Run lightweight diagnostics
            diagnostics = SystemDiagnostics()
            
            print("Running basic system checks...")
            
            # Environment check
            env_result = diagnostics.check_environment_variables()
            status_color = Fore.GREEN if env_result.status == 'pass' else Fore.YELLOW if env_result.status == 'warn' else Fore.RED
            print(f"  Environment: {status_color}{env_result.status.upper()}{Style.RESET_ALL} - {env_result.message}")
            
            # System resources check  
            resource_result = diagnostics.check_system_resources()
            status_color = Fore.GREEN if resource_result.status == 'pass' else Fore.YELLOW if resource_result.status == 'warn' else Fore.RED
            print(f"  Resources: {status_color}{resource_result.status.upper()}{Style.RESET_ALL} - {resource_result.message}")
            
            print(f"\n{Fore.YELLOW}💡 For comprehensive diagnostics, run:{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}python main.py --diagnostics{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}python main.py --interactive{Style.RESET_ALL}")
            
        except Exception as e:
            self.logger.error(f"Diagnostics demo failed: {e}")
            print(f"{Fore.RED}❌ Diagnostics demonstration failed: {e}{Style.RESET_ALL}")
        
        print(f"\n{Fore.GREEN}✅ System diagnostics demonstration complete!{Style.RESET_ALL}")

async def main():
    """Main demo function"""
    demo = FeatureDemo()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        await demo.run_interactive_demo()
    else:
        await demo.run_full_demo()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}👋 Demo interrupted. Goodbye!{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}💥 Demo failed: {e}{Style.RESET_ALL}")
        sys.exit(1) 