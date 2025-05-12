#!/bin/bash
# LTE auto-connect script for system startup
# Place this in /etc/rc.local to run at boot time

# Set strict error handling
set -e

# Log file
LOGFILE="/var/log/lte-boot.log"

echo "$(date) - Starting LTE boot connection script" | tee -a $LOGFILE

# Function to check if PPP is already up
check_ppp() {
  ifconfig ppp0 >/dev/null 2>&1
  return $?
}

# Function to check if connection is active
check_connectivity() {
  ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1
  return $?
}

# Wait a bit for other services to start
echo "Waiting for system to settle..." | tee -a $LOGFILE
sleep 20

# Check if PPP is already running
if check_ppp; then
  echo "PPP already running" | tee -a $LOGFILE
  
  # Check if it has connectivity
  if check_connectivity; then
    echo "Connectivity test passed, no action needed" | tee -a $LOGFILE
    exit 0
  else
    echo "PPP interface exists but no connectivity. Restarting service..." | tee -a $LOGFILE
    systemctl restart lte-connection.service
  fi
else
  echo "No PPP interface found. Starting LTE connection service..." | tee -a $LOGFILE
  
  # Ensure the service is enabled and started
  systemctl enable lte-connection.service
  systemctl restart lte-connection.service
fi

# Wait for connection to establish
echo "Waiting for PPP interface..." | tee -a $LOGFILE
for i in {1..12}; do
  if check_ppp; then
    echo "PPP interface detected" | tee -a $LOGFILE
    break
  fi
  echo "Waiting for PPP interface (attempt $i/12)..." | tee -a $LOGFILE
  sleep 5
done

# Check if we have connectivity
if check_connectivity; then
  echo "Internet connectivity established successfully!" | tee -a $LOGFILE
  
  # Get and log interface details
  IFCONFIG=$(ifconfig ppp0)
  echo "PPP interface details:" | tee -a $LOGFILE
  echo "$IFCONFIG" | tee -a $LOGFILE
  
  echo "LTE connection setup complete!" | tee -a $LOGFILE
  exit 0
else
  echo "No internet connectivity after bringing up PPP interface." | tee -a $LOGFILE
  echo "Running diagnostic reset and reconnect..." | tee -a $LOGFILE
  
  # Try direct connect as fallback
  echo "Trying direct connection script..." | tee -a $LOGFILE
  if [ -f /usr/local/bin/lte-direct-connect ]; then
    /usr/local/bin/lte-direct-connect --auto | tee -a $LOGFILE
  elif [ -f /usr/local/bin/lte-connect ]; then
    /usr/local/bin/lte-connect | tee -a $LOGFILE
  else
    echo "Direct connection scripts not found. Attempting manual reset..." | tee -a $LOGFILE
    # Try to find and run the reset script
    if [ -f /root/vehicle-tracking-edge/tests/qualcomm_reset.sh ]; then
      /root/vehicle-tracking-edge/tests/qualcomm_reset.sh | tee -a $LOGFILE
      sleep 10
      systemctl restart lte-connection.service
    fi
  fi
fi

# Final connectivity check
sleep 10
if check_connectivity; then
  echo "Connection established after recovery attempts!" | tee -a $LOGFILE
  exit 0
else
  echo "Failed to establish connection after recovery attempts." | tee -a $LOGFILE
  echo "Manual intervention may be required." | tee -a $LOGFILE
  exit 1
fi 