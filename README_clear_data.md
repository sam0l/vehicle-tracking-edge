# Vehicle Tracking System - Data Clearing Utility

This utility script `clear_data.py` allows you to clear logs and detection data from the vehicle tracking system, with options to archive the data before clearing.

## Features

- Clear the local log file (`vehicle_tracker.log`)
- Clear detection records from the backend database
- Archive logs before clearing them
- Selectively clear only logs or only detections

## Prerequisites

Before running this script, ensure:

1. Python 3.6+ is installed
2. Required packages are installed:
   ```
   pip install requests pyyaml
   ```
3. The backend server is running and accessible
4. The backend has the `clear_detections` API endpoint installed (see Installation section)

## Installation

### On the Edge Device

1. Copy `clear_data.py` to your vehicle-tracking-edge directory
2. Make the script executable:
   ```
   chmod +x clear_data.py
   ```

### On the Backend Server

1. Copy `clear_detections.py` to your `vehicle-tracking-backend/app/api/` directory
2. Update the main.py file to include the new endpoint (as shown in the instructions)
3. Restart the backend server to apply changes

## Usage

```
python clear_data.py [--archive] [--logs-only] [--detections-only] [--archive-dir DIRECTORY]
```

### Arguments

- `--archive`: Archive logs before clearing them
- `--logs-only`: Only clear logs, not detections
- `--detections-only`: Only clear detections, not logs
- `--archive-dir DIRECTORY`: Specify a directory for archived logs (default: "archive")

### Examples

Clear both logs and detections:
```
python clear_data.py
```

Archive logs before clearing everything:
```
python clear_data.py --archive
```

Only clear logs and archive them first:
```
python clear_data.py --logs-only --archive
```

Only clear detections:
```
python clear_data.py --detections-only
```

Archive logs to a specific directory:
```
python clear_data.py --archive --archive-dir /path/to/backups
```

## How It Works

1. **Log Clearing**: The script truncates the vehicle_tracker.log file to zero bytes.

2. **Detection Clearing**: The script calls the backend API endpoint to clear detection records from the database.

3. **Log Archiving**: 
   - Creates an archive directory if it doesn't exist
   - Copies the log file with a timestamp in the filename
   - Verifies the archive was created successfully

## Troubleshooting

If you encounter issues:

1. **Cannot connect to backend**: 
   - Check that the backend URL in config.yaml is correct
   - Verify the backend server is running
   - Check network connectivity

2. **API endpoint not found**:
   - Verify that clear_detections.py was installed correctly
   - Ensure the backend's main.py was updated
   - Restart the backend server

3. **Permission issues**:
   - Make sure you have write permissions to the log file
   - Make sure you have write permissions to the archive directory

## Warning

⚠️ This script permanently deletes data. Use with caution, especially in production environments. Always use the --archive option when in doubt to keep a backup of your logs. 