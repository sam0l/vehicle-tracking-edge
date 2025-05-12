#!/usr/bin/env python3
"""
Clear Data Utility for Vehicle Tracking System

This script can:
1. Clear the vehicle_tracker.log file
2. Clear the latest detections from the backend database
3. Archive logs before clearing

Usage:
python clear_data.py [--archive] [--logs-only] [--detections-only]

Options:
--archive: Archive logs before clearing
--logs-only: Only clear logs, not detections
--detections-only: Only clear detections, not logs
"""

import os
import sys
import time
import requests
import shutil
import argparse
import yaml
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("clear_data")

def load_config():
    """Load configuration from the config file."""
    try:
        config_path = "config/config.yaml"
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

def archive_logs(log_file, archive_dir="archive"):
    """Archive the log file before clearing."""
    try:
        # Create archive directory if it doesn't exist
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
            
        # Create timestamp for the archive filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_filename = f"{archive_dir}/vehicle_tracker_{timestamp}.log"
        
        # Copy the log file to archive
        if os.path.exists(log_file):
            shutil.copy2(log_file, archive_filename)
            logger.info(f"Log file archived to {archive_filename}")
            
            # Verify archive file exists and has content
            if os.path.exists(archive_filename) and os.path.getsize(archive_filename) > 0:
                logger.info(f"Archive verified: {os.path.getsize(archive_filename)} bytes")
                return archive_filename
            else:
                logger.error("Archive file is empty or not created properly")
                return None
        else:
            logger.warning(f"Log file {log_file} does not exist, nothing to archive")
            return None
    except Exception as e:
        logger.error(f"Failed to archive log file: {e}")
        return None

def clear_log_file(log_file):
    """Clear the vehicle_tracker.log file."""
    try:
        if os.path.exists(log_file):
            # Get original file size for reporting
            original_size = os.path.getsize(log_file)
            
            # Open file in write mode to truncate it
            with open(log_file, 'w') as f:
                f.write("")
            
            logger.info(f"Log file cleared (was {original_size} bytes)")
            return True
        else:
            logger.warning(f"Log file {log_file} does not exist, nothing to clear")
            return False
    except Exception as e:
        logger.error(f"Failed to clear log file: {e}")
        return False

def clear_detections(backend_url):
    """Clear the latest detections from the backend database."""
    try:
        # Try multiple possible health check endpoints
        health_endpoints = [
            "/health",           # Root health endpoint
            "/api/health",       # API health endpoint
            "/"                  # Root endpoint (often returns 200 OK)
        ]
        
        backend_reachable = False
        
        # Try each endpoint until we find one that works
        for endpoint in health_endpoints:
            health_check_url = f"{backend_url}{endpoint}"
            try:
                logger.info(f"Trying health check at {health_check_url}")
                response = requests.get(health_check_url, timeout=5)
                if response.status_code == 200:
                    logger.info(f"Health check succeeded at {health_check_url}")
                    backend_reachable = True
                    break
                else:
                    logger.warning(f"Health check at {health_check_url} returned status {response.status_code}")
            except requests.RequestException as e:
                logger.warning(f"Health check at {health_check_url} failed: {e}")
        
        if not backend_reachable:
            logger.error(f"Cannot connect to backend at {backend_url} using any known health endpoints")
            return False
        
        # Use the clear_detections endpoint
        clear_url = f"{backend_url}/api/clear_detections"
        
        logger.info(f"Attempting to clear detections from {clear_url}")
        response = requests.post(clear_url, timeout=10)
        
        if response.status_code == 200:
            logger.info("Detections cleared successfully")
            return True
        else:
            logger.error(f"Failed to clear detections: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error while clearing detections: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Clear logs and detections for the vehicle tracking system")
    parser.add_argument("--archive", action="store_true", help="Archive logs before clearing")
    parser.add_argument("--logs-only", action="store_true", help="Only clear logs, not detections")
    parser.add_argument("--detections-only", action="store_true", help="Only clear detections, not logs")
    parser.add_argument("--archive-dir", type=str, default="archive", help="Directory to store archived logs")
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config()
    log_file = config.get('logging', {}).get('file', 'vehicle_tracker.log')
    backend_url = config.get('backend', {}).get('url', 'https://vehicle-tracking-backend-bwmz.onrender.com')
    
    logger.info(f"Starting data clearing process")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Backend URL: {backend_url}")
    
    # Archive logs if requested
    if args.archive:
        archive_file = archive_logs(log_file, args.archive_dir)
        if archive_file:
            logger.info(f"Logs archived to {archive_file}")
        else:
            logger.warning("Log archiving failed or wasn't necessary")
    
    # Clear logs if not detections-only mode
    if not args.detections_only:
        if clear_log_file(log_file):
            logger.info("Logs cleared successfully")
        else:
            logger.warning("Log clearing failed or wasn't necessary")
    
    # Clear detections if not logs-only mode
    if not args.logs_only:
        if clear_detections(backend_url):
            logger.info("Detections cleared successfully")
        else:
            logger.error("Failed to clear detections")
    
    logger.info("Data clearing process completed")

if __name__ == "__main__":
    main() 