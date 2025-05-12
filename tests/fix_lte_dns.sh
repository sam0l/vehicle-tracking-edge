#!/bin/bash
# LTE DNS Resolution Fix Script

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== LTE DNS Resolution Fix ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Create DNS setup script
echo -e "${YELLOW}Creating DNS setup script...${NC}"
mkdir -p /etc/ppp/ip-up.d
cat > /etc/ppp/ip-up.d/01-setup-dns << 'EOF'
#!/bin/bash

# Set up proper DNS and routing for LTE
# This script runs when PPP connection is established

# Define Google DNS as backup
GOOGLE_DNS1="8.8.8.8"
GOOGLE_DNS2="8.8.4.4"

# Log to syslog and a specific file
log() {
  echo "$(date): $1" | tee -a /var/log/lte-dns.log
  logger -t "LTE-DNS" "$1"
}

# Log start
log "Running DNS setup for PPP connection"
log "Interface: $1, Device: $2, Speed: $3, Local IP: $4, Remote IP: $5, DNS1: $6, DNS2: $7"

# Ensure resolv.conf contains the provided DNS servers
if [ -n "$6" ]; then
  log "Adding carrier DNS servers to resolv.conf"
  # Add carrier's DNS servers
  echo "nameserver $6" > /etc/resolv.conf
  if [ -n "$7" ]; then
    echo "nameserver $7" >> /etc/resolv.conf
  fi
  # Add Google DNS as fallback
  echo "nameserver $GOOGLE_DNS1" >> /etc/resolv.conf
  echo "nameserver $GOOGLE_DNS2" >> /etc/resolv.conf
else
  # Use Google DNS if no carrier DNS provided
  log "No carrier DNS provided, using Google DNS"
  echo "nameserver $GOOGLE_DNS1" > /etc/resolv.conf
  echo "nameserver $GOOGLE_DNS2" >> /etc/resolv.conf
fi

# Add a specific route for the backend server
log "Adding route for backend server via PPP"
# Try to resolve and add route using Google DNS directly
host vehicle-tracking-backend-bwmz.onrender.com $GOOGLE_DNS1 > /tmp/dns_lookup 2>&1
IP=$(grep "has address" /tmp/dns_lookup | head -n1 | awk '{print $4}')

if [ -n "$IP" ]; then
  log "Backend resolved to $IP, adding specific route"
  route add -host $IP dev $1
else
  log "Could not resolve backend hostname"
  # Try to ping Google DNS to ensure connectivity
  ping -c 1 $GOOGLE_DNS1 > /dev/null 2>&1
  if [ $? -eq 0 ]; then
    log "Can ping Google DNS, network is functioning"
  else
    log "Cannot ping Google DNS, potential network issue"
  fi
fi

# Set PPP metric to prioritize it for certain traffic
log "Setting interface metrics to prioritize routing"
# Make PPP the default for Internet but not for local traffic
if ip route show | grep -q "default via.*dev wlan0"; then
  log "Found existing WiFi default route, adding PPP route with lower metric"
  # First delete any existing PPP default route
  ip route del default via $5 dev $1 2>/dev/null || true
  # Add PPP route with lower metric (higher priority than WiFi)
  ip route add default via $5 dev $1 metric 50
  # Make sure WiFi has higher metric
  WIFI_GW=$(ip route show | grep "default via.*dev wlan0" | awk '{print $3}')
  if [ -n "$WIFI_GW" ]; then
    ip route del default via $WIFI_GW dev wlan0 2>/dev/null || true
    ip route add default via $WIFI_GW dev wlan0 metric 100
  fi
  log "Route priorities set: PPP(50), WiFi(100)"
else
  # No default route yet, add primary via PPP
  log "No existing default route, setting PPP as primary"
  ip route add default via $5 dev $1 metric 50
fi

# Create a file that the application can check to verify DNS is working
echo "DNS setup completed at $(date)" > /tmp/lte_dns_ready

log "DNS and routing setup completed"
EOF

# Make script executable
chmod +x /etc/ppp/ip-up.d/01-setup-dns
echo -e "${GREEN}Created DNS setup script at /etc/ppp/ip-up.d/01-setup-dns${NC}"

# Update PPP peer configuration
echo -e "${YELLOW}Updating PPP configuration...${NC}"
PEER_FILE="/etc/ppp/peers/lte"

# Add DNS options if not present
if ! grep -q "usepeerdns" "$PEER_FILE"; then
  echo "usepeerdns" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'usepeerdns' option${NC}"
fi

if ! grep -q "replacedefaultroute" "$PEER_FILE"; then
  echo "replacedefaultroute" >> "$PEER_FILE"
  echo -e "${GREEN}Added 'replacedefaultroute' option${NC}"
fi

# Create a small test script
echo -e "${YELLOW}Creating DNS test script...${NC}"
cat > /usr/local/bin/test-lte-dns << 'EOF'
#!/bin/bash
# Test LTE DNS resolution

echo "=== LTE DNS Test ==="
echo "Current resolv.conf:"
cat /etc/resolv.conf

echo -e "\nTesting DNS resolution:"
echo -n "Google.com: "
host google.com || echo "Failed"

echo -n "Backend server: "
host vehicle-tracking-backend-bwmz.onrender.com || echo "Failed"

echo -e "\nTesting ping:"
echo -n "Google DNS: "
ping -c 1 8.8.8.8 > /dev/null && echo "Success" || echo "Failed"

echo -e "\nRouting table:"
ip route show

echo -e "\nPPP interface:"
ifconfig ppp0

echo -e "\nLast DNS setup log:"
tail -n 10 /var/log/lte-dns.log 2>/dev/null || echo "Log not found"
EOF

chmod +x /usr/local/bin/test-lte-dns
echo -e "${GREEN}Created DNS test script at /usr/local/bin/test-lte-dns${NC}"

# Restart the LTE connection
echo -e "${YELLOW}Restarting LTE connection...${NC}"
systemctl restart lte-connection

echo -e "${YELLOW}Waiting for connection to establish (15s)...${NC}"
sleep 15

# Test DNS resolution
echo -e "${YELLOW}Testing DNS resolution...${NC}"
/usr/local/bin/test-lte-dns

echo -e "${GREEN}=== DNS Fix Completed ===${NC}"
echo -e "${YELLOW}If you're still having DNS issues:${NC}"
echo -e "1. Try restarting the system: ${GREEN}sudo reboot${NC}"
echo -e "2. After reboot, check DNS: ${GREEN}sudo /usr/local/bin/test-lte-dns${NC}"
echo -e "3. Check the DNS setup log: ${GREEN}sudo cat /var/log/lte-dns.log${NC}" 