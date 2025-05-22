import test_direct_db
import sys
import logging
import os
from datetime import datetime

# Create a unique log file name with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"diagnostic_results_{timestamp}.log"

# Set up file logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info(f"Starting diagnostic run, logging to {log_file}")
    try:
        test_direct_db.run_diagnostics()
        logger.info("Diagnostic completed successfully.")
    except Exception as e:
        logger.error(f"Diagnostic failed with error: {e}")
    finally:
        logger.info(f"Diagnostic results saved to {log_file}")
        # Print the contents of the log file
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                print("\n" + "="*80)
                print(f"DIAGNOSTIC RESULTS FROM {log_file}:")
                print("="*80)
                print(f.read()) 