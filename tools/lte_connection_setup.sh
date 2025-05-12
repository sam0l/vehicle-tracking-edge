#!/bin/bash
# LTE connection setup script for vehicle tracking system
# This script helps set up PPP connection using the LTE modem

set -e  # Exit on error

# Config
PORT="/dev/ttyUSB2"
BAUDRATE="115200"
APN="internet"  # Change this to your carrier's APN

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== LTE Connection Setup ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Check for required tools
echo -e "${YELLOW}Checking for required tools...${NC}"
for tool in pppd chat; do
  if ! command -v $tool &> /dev/null; then
    echo -e "${RED}$tool not found. Installing ppp package...${NC}"
    apt-get update && apt-get install -y ppp
    break
  fi
done

# Create a more robust chat script
echo -e "${YELLOW}Creating chat script...${NC}"
CHAT_SCRIPT="/etc/ppp/chat-lte"
cat > $CHAT_SCRIPT << EOF
ABORT "BUSY"
ABORT "NO CARRIER"
ABORT "NO DIALTONE"
ABORT "ERROR"
ABORT "NO ANSWER"
TIMEOUT 45
'' AT
OK AT+CFUN=1
OK AT+CGATT=1
OK AT+CREG=1
OK 'AT+CGDCONT=1,"IP","$APN"'
OK ATD*99#
CONNECT ''
EOF

chmod 644 $CHAT_SCRIPT
echo -e "${GREEN}Chat script created at $CHAT_SCRIPT${NC}"

# Create a peer file for pppd
echo -e "${YELLOW}Creating PPP peer file...${NC}"
PEER_FILE="/etc/ppp/peers/lte"
cat > $PEER_FILE << EOF
# LTE modem connection settings
$PORT
$BAUDRATE
connect "/usr/sbin/chat -v -f $CHAT_SCRIPT"
noauth
defaultroute
usepeerdns
noipdefault
novj
novjccomp
noccp
nocrtscts
persist
holdoff 10
maxfail 0
debug
EOF

chmod 644 $PEER_FILE
echo -e "${GREEN}PPP peer file created at $PEER_FILE${NC}"

# Create connection script
echo -e "${YELLOW}Creating connection script...${NC}"
CONNECT_SCRIPT="/usr/local/bin/lte-connect"
cat > $CONNECT_SCRIPT << EOF
#!/bin/bash
# Script to connect LTE modem using PPP

echo "Starting LTE connection..."

# Kill any existing pppd instances
pkill -f "pppd.*/dev/ttyUSB2" || true

# Initialize modem first
echo "Initializing modem..."
stty -F $PORT $BAUDRATE
echo -e "AT\r" > $PORT
sleep 1
echo -e "AT+CFUN=1\r" > $PORT
sleep 2
echo -e "AT+CGDCONT=1,\"IP\",\"$APN\"\r" > $PORT
sleep 1

# Start pppd using peer file
echo "Starting PPP connection..."
/usr/sbin/pppd call lte

echo "PPP connection started. Check interface with 'ifconfig ppp0'"
EOF

chmod 755 $CONNECT_SCRIPT
echo -e "${GREEN}Connection script created at $CONNECT_SCRIPT${NC}"

# Create systemd service for auto-start
echo -e "${YELLOW}Creating systemd service...${NC}"
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

chmod 644 $SERVICE_FILE
echo -e "${GREEN}Systemd service created at $SERVICE_FILE${NC}"

# Create a direct connect script for manual testing
echo -e "${YELLOW}Creating direct connect script for testing...${NC}"
DIRECT_SCRIPT="/usr/local/bin/lte-direct-connect"
cat > $DIRECT_SCRIPT << EOF
#!/bin/bash
# Direct LTE connection for testing

stty -F $PORT $BAUDRATE
echo -e "AT\r" > $PORT
sleep 1
cat $PORT &
CAT_PID=\$!
sleep 1

echo "Sending initialization commands..."
echo -e "AT+CFUN=1\r" > $PORT
sleep 2
echo -e "AT+CGATT=1\r" > $PORT
sleep 2
echo -e "AT+CGDCONT=1,\"IP\",\"$APN\"\r" > $PORT
sleep 2
echo -e "AT+CGACT=1,1\r" > $PORT
sleep 5
echo -e "ATD*99#\r" > $PORT
sleep 2

echo "You should see 'CONNECT' in the output above. Press Enter to continue..."
read

# Kill the cat process
kill \$CAT_PID

# Now start pppd directly
echo "Starting PPP directly..."
sudo /usr/sbin/pppd $PORT $BAUDRATE noauth defaultroute usepeerdns noipdefault novj novjccomp noccp nocrtscts
EOF

chmod 755 $DIRECT_SCRIPT
echo -e "${GREEN}Direct connect script created at $DIRECT_SCRIPT${NC}"

# Reload systemd and enable service
echo -e "${YELLOW}Enabling service...${NC}"
systemctl daemon-reload
systemctl enable lte-connection.service

echo -e "${GREEN}LTE connection setup complete!${NC}"
echo -e "${YELLOW}Commands:${NC}"
echo -e "  Start connection: ${GREEN}sudo systemctl start lte-connection${NC}"
echo -e "  Stop connection:  ${GREEN}sudo systemctl stop lte-connection${NC}"
echo -e "  Check status:     ${GREEN}sudo systemctl status lte-connection${NC}"
echo -e "  Manual connect:   ${GREEN}sudo $CONNECT_SCRIPT${NC}"
echo -e "  Direct test:      ${GREEN}sudo $DIRECT_SCRIPT${NC}"
echo -e "  Check interface:  ${GREEN}ifconfig ppp0${NC}"

# Ask to test direct connection first
read -p "Try direct connection test first? (recommended) (y/n): " TEST_FIRST
if [[ $TEST_FIRST == "y" || $TEST_FIRST == "Y" ]]; then
  echo -e "${YELLOW}Starting direct connection test...${NC}"
  $DIRECT_SCRIPT
  exit 0
fi

# Ask to start service
read -p "Start LTE connection service? (y/n): " START_NOW
if [[ $START_NOW == "y" || $START_NOW == "Y" ]]; then
  echo -e "${YELLOW}Starting LTE connection...${NC}"
  systemctl start lte-connection
  echo -e "${YELLOW}Waiting for connection (15s)...${NC}"
  sleep 15
  if ifconfig ppp0 &>/dev/null; then
    echo -e "${GREEN}LTE connection established successfully!${NC}"
    echo -e "Interface details:"
    ifconfig ppp0
  else
    echo -e "${RED}LTE connection failed to establish.${NC}"
    echo -e "Check logs with: ${YELLOW}journalctl -u lte-connection -f${NC}"
    echo -e "Try the direct test script: ${GREEN}sudo $DIRECT_SCRIPT${NC}"
  fi
fi

exit 0 