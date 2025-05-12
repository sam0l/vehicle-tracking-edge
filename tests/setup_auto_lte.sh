#!/bin/bash
# LTE Auto-connect Setup Script
# This script sets up automatic LTE connection at system boot

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== LTE Auto-connect Setup ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Install required packages
echo -e "${YELLOW}Installing required packages...${NC}"
apt-get update && apt-get install -y ppp curl

# Find current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

# Run the connection setup script to create necessary files
echo -e "${YELLOW}Running connection setup script...${NC}"
bash ./lte_connection_setup.sh --auto

# Copy boot script to /usr/local/bin
echo -e "${YELLOW}Setting up boot script...${NC}"
cp ./lte_boot_connect.sh /usr/local/bin/lte-boot-connect
chmod +x /usr/local/bin/lte-boot-connect

# Add to rc.local for boot execution
RC_LOCAL="/etc/rc.local"
if [ -f "$RC_LOCAL" ]; then
  # Check if already in rc.local
  if grep -q "lte-boot-connect" "$RC_LOCAL"; then
    echo -e "${YELLOW}Boot script already in rc.local${NC}"
  else
    # Insert before exit 0
    sed -i '/^exit 0/i \/usr\/local\/bin\/lte-boot-connect &' "$RC_LOCAL"
    echo -e "${GREEN}Added boot script to rc.local${NC}"
  fi
else
  # Create rc.local if it doesn't exist
  echo -e "${YELLOW}Creating rc.local file...${NC}"
  cat > "$RC_LOCAL" << EOF
#!/bin/sh -e
#
# rc.local
#
# This script is executed at the end of each multiuser runlevel.
# Make sure that the script will "exit 0" on success or any other
# value on error.

/usr/local/bin/lte-boot-connect &

exit 0
EOF
  chmod +x "$RC_LOCAL"
  echo -e "${GREEN}Created rc.local with boot script${NC}"
fi

# Create systemd service as a backup method
echo -e "${YELLOW}Creating systemd service for boot script...${NC}"
cat > /etc/systemd/system/lte-boot.service << EOF
[Unit]
Description=LTE Boot Connection
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/lte-boot-connect
Restart=no

[Install]
WantedBy=multi-user.target
EOF

# Enable the service
systemctl daemon-reload
systemctl enable lte-boot.service

# Ensure the main service is enabled too
systemctl enable lte-connection.service

# Install diagnostic connection check script
echo -e "${YELLOW}Installing connection check script...${NC}"
cat > /usr/local/bin/check-lte << EOF
#!/bin/bash
# LTE connection diagnostics script

echo "=== LTE Connection Diagnostic ==="
echo "Current date: \$(date)"

echo -e "\n=== Network Interfaces ==="
ifconfig

echo -e "\n=== PPP Status ==="
if ifconfig ppp0 > /dev/null 2>&1; then
  echo "PPP interface found:"
  ifconfig ppp0
  echo -e "\nPPP route:"
  route -n | grep ppp0 || echo "No PPP routes"
else
  echo "PPP interface NOT found"
fi

echo -e "\n=== Connection Service Status ==="
systemctl status lte-connection.service | head -n 20

echo -e "\n=== Connection Test ==="
if ping -c 3 -W 5 8.8.8.8 > /dev/null 2>&1; then
  echo "Internet connectivity: ONLINE"
else
  echo "Internet connectivity: OFFLINE"
fi

echo -e "\n=== Last Boot Log ==="
tail -n 20 /var/log/lte-boot.log || echo "Boot log not found"

echo -e "\n=== Connection Troubleshooting ==="
if ! ifconfig ppp0 > /dev/null 2>&1; then
  echo "The PPP interface is not up. Try: sudo systemctl restart lte-connection"
  echo "Or for manual connection: sudo /usr/local/bin/lte-direct-connect"
else
  echo "If you're having issues, try:"
  echo "1. Restart connection: sudo systemctl restart lte-connection"
  echo "2. Manual reset: sudo /root/vehicle-tracking-edge/tests/qualcomm_reset.sh"
  echo "3. Check logs: journalctl -u lte-connection -f"
fi
EOF
chmod +x /usr/local/bin/check-lte

# After the setup is complete, add the nodetach option to the pppd config if it's missing
echo -e "${YELLOW}Adding persistence options to PPP config...${NC}"
PEER_FILE="/etc/ppp/peers/lte"
if ! grep -q "persist" "$PEER_FILE"; then
  echo "persist" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'persist' option to PPP config${NC}"
fi

if ! grep -q "maxfail 0" "$PEER_FILE"; then
  echo "maxfail 0" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'maxfail 0' option to PPP config${NC}"
fi

if ! grep -q "holdoff 10" "$PEER_FILE"; then
  echo "holdoff 10" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'holdoff 10' option to PPP config${NC}"
fi

# Fix pppd daemon mode
systemctl stop lte-connection
systemctl daemon-reload

echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo -e "${YELLOW}To manually start the connection:${NC}"
echo -e "  ${GREEN}sudo systemctl start lte-connection${NC}"
echo -e "${YELLOW}To check connection status:${NC}"
echo -e "  ${GREEN}sudo /usr/local/bin/check-lte${NC}"
echo -e "${YELLOW}The connection will automatically start at boot.${NC}"
echo -e "${YELLOW}Would you like to test the connection now? (y/n)${NC}"
read -r TEST_NOW

if [[ "$TEST_NOW" == "y" || "$TEST_NOW" == "Y" ]]; then
  echo -e "${YELLOW}Testing LTE connection...${NC}"
  systemctl restart lte-connection
  echo -e "${YELLOW}Waiting for connection (15s)...${NC}"
  sleep 15
  /usr/local/bin/check-lte
fi

exit 0 