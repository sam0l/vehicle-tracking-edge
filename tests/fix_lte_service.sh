#!/bin/bash
# Quick fix for LTE service persistent connection

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== LTE Service Fix Script ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Stop the service first
echo -e "${YELLOW}Stopping LTE connection service...${NC}"
systemctl stop lte-connection.service

# Update the service file
echo -e "${YELLOW}Updating service configuration...${NC}"
SERVICE_FILE="/etc/systemd/system/lte-connection.service"
cat > $SERVICE_FILE << EOF
[Unit]
Description=LTE PPP Connection
After=network.target

[Service]
Type=forking
ExecStart=/usr/sbin/pppd call lte
Restart=always
RestartSec=30
TimeoutSec=120

[Install]
WantedBy=multi-user.target
EOF

# Update the pppd configuration
echo -e "${YELLOW}Updating PPP configuration...${NC}"
PEER_FILE="/etc/ppp/peers/lte"

# Make sure all required options are present
if ! grep -q "persist" "$PEER_FILE"; then
  echo "persist" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'persist' option${NC}"
fi

if ! grep -q "maxfail 0" "$PEER_FILE"; then
  echo "maxfail 0" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'maxfail 0' option${NC}"
fi

if ! grep -q "holdoff 10" "$PEER_FILE"; then
  echo "holdoff 10" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'holdoff 10' option${NC}"
fi

# Reload systemd
echo -e "${YELLOW}Reloading systemd daemon...${NC}"
systemctl daemon-reload

# Restart the service
echo -e "${YELLOW}Starting LTE connection service...${NC}"
systemctl restart lte-connection.service

echo -e "${GREEN}Fix applied. Checking service status...${NC}"
sleep 3
systemctl status lte-connection.service

echo -e "${YELLOW}Waiting 15 seconds to verify stability...${NC}"
sleep 15

echo -e "${YELLOW}Final service status:${NC}"
systemctl status lte-connection.service

# Check interface
echo -e "${YELLOW}Checking PPP interface:${NC}"
ifconfig ppp0 || echo -e "${RED}PPP interface not found${NC}"

# Check route
echo -e "${YELLOW}Checking routing:${NC}"
route -n | grep ppp0 || echo -e "${RED}No PPP routes found${NC}"

echo -e "${GREEN}=== Fix Completed ===${NC}"
echo -e "${YELLOW}If the service is still restarting, try rebooting the system${NC}"
echo -e "${YELLOW}After reboot, check status with: sudo systemctl status lte-connection${NC}" 