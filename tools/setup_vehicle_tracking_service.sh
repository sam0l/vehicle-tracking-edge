#!/bin/bash

# Script to set up the vehicle-tracking-edge main.py as a systemd service
# IMPORTANT: 
# 1. Run this script with sudo: sudo ./setup_vehicle_tracking_service.sh
# 2. Ensure the PROJECT_DIR variable below is set to the correct absolute path
#    of your vehicle-tracking-edge project on the target Linux machine.

# --- Configuration ---
SERVICE_NAME="vehicle-tracking"
SERVICE_DESCRIPTION="Vehicle Tracking Edge Application"
# !!! MODIFY THIS TO YOUR ACTUAL PROJECT DIRECTORY ON THE LINUX TARGET !!!
PROJECT_DIR="/root/vehicle-tracking-edge" # Example: /home/user/vehicle-tracking-edge
MAIN_SCRIPT="main.py"
SERVICE_USER="root" # User to run the service as. Change if needed.
SERVICE_GROUP="root" # Group to run the service as. Change if needed.

LOG_FILE="/var/log/${SERVICE_NAME}.log"
ERROR_LOG_FILE="/var/log/${SERVICE_NAME}_error.log"

# --- Script Logic ---

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root. Please use sudo." >&2
  exit 1
fi

# Find python3 executable
PYTHON_EXEC=$(which python3)
if [ -z "${PYTHON_EXEC}" ]; then
  echo "Error: python3 executable not found. Please install Python 3." >&2
  exit 1
fi

echo "Using Python 3 executable: ${PYTHON_EXEC}"

# Check if project directory exists
if [ ! -d "${PROJECT_DIR}" ]; then
  echo "Error: Project directory '${PROJECT_DIR}' not found." >&2
  echo "Please update the PROJECT_DIR variable in this script." >&2
  exit 1
fi

# Check if main script exists
if [ ! -f "${PROJECT_DIR}/${MAIN_SCRIPT}" ]; then
  echo "Error: Main script '${PROJECT_DIR}/${MAIN_SCRIPT}' not found." >&2
  exit 1
fi

SERVICE_FILE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Creating systemd service file at ${SERVICE_FILE_PATH}..."

# Create the service file content
cat << EOF > ${SERVICE_FILE_PATH}
[Unit]
Description=${SERVICE_DESCRIPTION}
After=network.target

[Service]
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${PROJECT_DIR}
ExecStart=/bin/bash -c 'source ~/bin/activate && python3 ${PROJECT_DIR}/${MAIN_SCRIPT}'
Restart=always
RestartSec=10
StandardOutput=append:${LOG_FILE}
StandardError=append:${ERROR_LOG_FILE}
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Set permissions for the service file
chmod 644 ${SERVICE_FILE_PATH}

echo "Service file created."

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling ${SERVICE_NAME} service to start on boot..."
systemctl enable ${SERVICE_NAME}.service

cat << EOF

Setup complete!

To start the service now, run:
  sudo systemctl start ${SERVICE_NAME}.service

To check the status of the service, run:
  sudo systemctl status ${SERVICE_NAME}.service

To see the logs, run:
  sudo tail -f ${LOG_FILE}
  sudo tail -f ${ERROR_LOG_FILE}

To stop the service, run:
  sudo systemctl stop ${SERVICE_NAME}.service

To disable the service from starting on boot, run:
  sudo systemctl disable ${SERVICE_NAME}.service
EOF

exit 0
