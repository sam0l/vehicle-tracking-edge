#!/bin/bash
# Persistent DNS Resolution Fix for LTE
# This script provides a more robust solution for maintaining DNS resolution

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Persistent LTE DNS Fix ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Create a more robust DNS setup script
echo -e "${YELLOW}Creating enhanced DNS setup script...${NC}"
mkdir -p /etc/ppp/ip-up.d
cat > /etc/ppp/ip-up.d/01-setup-dns << 'EOF'
#!/bin/bash

# Set up proper DNS and routing for LTE
# This script runs when PPP connection is established

# Define Google DNS as backup
GOOGLE_DNS1="8.8.8.8"
GOOGLE_DNS2="8.8.4.4"
CLOUDFLARE_DNS="1.1.1.1"

# Log to syslog and a specific file
log() {
  echo "$(date): $1" | tee -a /var/log/lte-dns.log
  logger -t "LTE-DNS" "$1"
}

# Log start
log "Running DNS setup for PPP connection"
log "Interface: $1, Device: $2, Speed: $3, Local IP: $4, Remote IP: $5, DNS1: $6, DNS2: $7"

# Create persistent DNS directory
mkdir -p /etc/resolv.conf.d

# Carrier DNS (if provided)
if [ -n "$6" ]; then
  log "Carrier DNS1: $6"
  echo "$6" > /etc/resolv.conf.d/carrier_dns1
  if [ -n "$7" ]; then
    log "Carrier DNS2: $7"
    echo "$7" > /etc/resolv.conf.d/carrier_dns2
  fi
fi

# Save other DNS for persistence
echo "$GOOGLE_DNS1" > /etc/resolv.conf.d/google_dns1
echo "$GOOGLE_DNS2" > /etc/resolv.conf.d/google_dns2
echo "$CLOUDFLARE_DNS" > /etc/resolv.conf.d/cloudflare_dns

# Build resolv.conf with all available DNS servers
log "Updating resolv.conf with multiple DNS servers"
{
  echo "# Created by LTE script on $(date)"
  echo "# Primary DNS servers"
  
  # Add carrier DNS if available
  if [ -n "$6" ]; then
    echo "nameserver $6"
    if [ -n "$7" ]; then
      echo "nameserver $7"
    fi
  fi
  
  # Add Google and Cloudflare DNS
  echo "nameserver $GOOGLE_DNS1"
  echo "nameserver $GOOGLE_DNS2"
  echo "nameserver $CLOUDFLARE_DNS"
  
  # Add search domains
  echo "search lan"
  echo "options timeout:2 attempts:3 rotate"
} > /etc/resolv.conf

# Make resolv.conf immutable to prevent NetworkManager from changing it
log "Setting resolv.conf as immutable"
chattr +i /etc/resolv.conf || log "Failed to set immutable flag (normal on some systems)"

# Set up routing for better connectivity
log "Setting up routing priorities"

# Add a specific route for the backend server
log "Adding route for backend server via PPP"
# Try to resolve and add route using Google DNS directly
for dns in $GOOGLE_DNS1 $CLOUDFLARE_DNS; do
  log "Trying to resolve backend via $dns"
  host vehicle-tracking-backend-bwmz.onrender.com $dns > /tmp/dns_lookup 2>&1
  IP=$(grep "has address" /tmp/dns_lookup | head -n1 | awk '{print $4}')
  
  if [ -n "$IP" ]; then
    log "Backend resolved to $IP, adding specific route"
    route add -host $IP dev $1
    # Also add a hosts entry for faster resolution
    if ! grep -q "vehicle-tracking-backend" /etc/hosts; then
      echo "$IP vehicle-tracking-backend-bwmz.onrender.com" >> /etc/hosts
      log "Added hosts entry for backend"
    fi
    break
  fi
done

if [ -z "$IP" ]; then
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

# Create a flag file to indicate DNS is set up
echo "DNS setup completed at $(date)" > /tmp/lte_dns_ready

# Install the DNS watchdog timer if it's not already there
if [ ! -f /etc/systemd/system/dns-watchdog.service ]; then
  log "Setting up DNS watchdog service"
  
  cat > /etc/systemd/system/dns-watchdog.service << 'WDEOF'
[Unit]
Description=DNS Resolver Watchdog
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/dns-watchdog.sh
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
WDEOF

  cat > /usr/local/bin/dns-watchdog.sh << 'WDSH'
#!/bin/bash

# Watchdog script to ensure DNS resolution keeps working
LOG_FILE="/var/log/dns-watchdog.log"

log() {
  echo "$(date): $1" >> "$LOG_FILE"
}

log "DNS watchdog started"

# Function to restore DNS settings
restore_dns() {
  log "Restoring DNS settings"
  
  if [ -f /etc/resolv.conf.d/carrier_dns1 ]; then
    CARRIER_DNS1=$(cat /etc/resolv.conf.d/carrier_dns1)
    if [ -f /etc/resolv.conf.d/carrier_dns2 ]; then
      CARRIER_DNS2=$(cat /etc/resolv.conf.d/carrier_dns2)
    fi
  fi
  
  GOOGLE_DNS1=$(cat /etc/resolv.conf.d/google_dns1)
  GOOGLE_DNS2=$(cat /etc/resolv.conf.d/google_dns2)
  CLOUDFLARE_DNS=$(cat /etc/resolv.conf.d/cloudflare_dns)
  
  # Remove immutable flag
  chattr -i /etc/resolv.conf 2>/dev/null
  
  # Recreate resolv.conf
  {
    echo "# Restored by watchdog on $(date)"
    echo "# Primary DNS servers"
    
    # Add carrier DNS if available
    if [ -n "$CARRIER_DNS1" ]; then
      echo "nameserver $CARRIER_DNS1"
      if [ -n "$CARRIER_DNS2" ]; then
        echo "nameserver $CARRIER_DNS2"
      fi
    fi
    
    # Add Google and Cloudflare DNS
    echo "nameserver $GOOGLE_DNS1"
    echo "nameserver $GOOGLE_DNS2"
    echo "nameserver $CLOUDFLARE_DNS"
    
    # Add search domains
    echo "search lan"
    echo "options timeout:2 attempts:3 rotate"
  } > /etc/resolv.conf
  
  # Make resolv.conf immutable again
  chattr +i /etc/resolv.conf 2>/dev/null
  
  log "DNS settings restored"
}

# Check and fix every 30 seconds
while true; do
  sleep 30
  
  # Check if we can resolve google.com
  host google.com > /dev/null 2>&1
  if [ $? -ne 0 ]; then
    log "DNS resolution failed, attempting to fix"
    restore_dns
    
    # Check if it's fixed
    host google.com > /dev/null 2>&1
    if [ $? -eq 0 ]; then
      log "DNS resolution fixed"
    else
      log "DNS resolution still failing after fix"
    fi
  fi
  
  # Check if we need to add backend server to hosts again
  if grep -q "vehicle-tracking-backend" /etc/hosts; then
    log "Backend server already in hosts file"
  else
    # Try to resolve and add to hosts
    for dns in 8.8.8.8 1.1.1.1; do
      host vehicle-tracking-backend-bwmz.onrender.com $dns > /tmp/dns_lookup 2>&1
      IP=$(grep "has address" /tmp/dns_lookup | head -n1 | awk '{print $4}')
      
      if [ -n "$IP" ]; then
        echo "$IP vehicle-tracking-backend-bwmz.onrender.com" >> /etc/hosts
        log "Added hosts entry for backend: $IP"
        break
      fi
    done
  fi
done
WDSH

  chmod +x /usr/local/bin/dns-watchdog.sh
  systemctl daemon-reload
  systemctl enable dns-watchdog.service
  systemctl start dns-watchdog.service
  log "DNS watchdog service installed and started"
fi

log "DNS and routing setup completed"
EOF

# Make script executable
chmod +x /etc/ppp/ip-up.d/01-setup-dns
echo -e "${GREEN}Created enhanced DNS setup script at /etc/ppp/ip-up.d/01-setup-dns${NC}"

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

# Install packages if needed
echo -e "${YELLOW}Installing required packages...${NC}"
apt update && apt install -y dnsutils net-tools

# Create a more advanced test script
echo -e "${YELLOW}Creating enhanced DNS test script...${NC}"
cat > /usr/local/bin/test-lte-dns << 'EOF'
#!/bin/bash
# Advanced LTE DNS resolution test

echo "=== LTE DNS Test ==="
echo "Current date: $(date)"

echo -e "\nCurrent resolv.conf:"
cat /etc/resolv.conf

echo -e "\nInternet connectivity check:"
ping -c 2 8.8.8.8 || echo "Cannot ping Google DNS!"
ping -c 2 1.1.1.1 || echo "Cannot ping Cloudflare DNS!"

echo -e "\nDNS resolution tests:"
echo "Google (via default DNS):"
host google.com || echo "Failed!"

echo -e "\nGoogle (via Google DNS):"
host google.com 8.8.8.8 || echo "Failed!"

echo -e "\nGoogle (via Cloudflare DNS):"
host google.com 1.1.1.1 || echo "Failed!"

echo -e "\nBackend server (via default DNS):"
host vehicle-tracking-backend-bwmz.onrender.com || echo "Failed!"

echo -e "\nBackend server (via Google DNS):"
host vehicle-tracking-backend-bwmz.onrender.com 8.8.8.8 || echo "Failed!"

echo -e "\nRouting table:"
ip route show

echo -e "\nHosts file entries:"
grep "vehicle-tracking-backend" /etc/hosts || echo "No backend entry in hosts file"

echo -e "\nPPP interface:"
ifconfig ppp0 || echo "No ppp0 interface found!"

echo -e "\nWatchdog service status:"
systemctl status dns-watchdog.service || echo "Watchdog service not running"

echo -e "\nLast DNS setup log:"
tail -n 10 /var/log/lte-dns.log 2>/dev/null || echo "Log not found"

echo -e "\nLast watchdog log:"
tail -n 10 /var/log/dns-watchdog.log 2>/dev/null || echo "Log not found"
EOF

chmod +x /usr/local/bin/test-lte-dns
echo -e "${GREEN}Created enhanced DNS test script at /usr/local/bin/test-lte-dns${NC}"

# Create application DNS helper
echo -e "${YELLOW}Creating application DNS helper...${NC}"
cat > /usr/local/bin/dns-precheck.py << 'EOF'
#!/usr/bin/env python3
"""
This helper script can be called by your application before making network requests.
It will ensure DNS is working and attempt to fix it if needed.
"""

import subprocess
import time
import sys
import socket
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/dns-precheck.log')
    ]
)

# Backend hostname to check
BACKEND_HOST = "vehicle-tracking-backend-bwmz.onrender.com"

def check_dns():
    """Check if DNS resolution is working."""
    try:
        # Try to resolve hostname
        socket.gethostbyname(BACKEND_HOST)
        logging.info(f"DNS resolution successful for {BACKEND_HOST}")
        return True
    except socket.gaierror:
        logging.warning(f"Cannot resolve {BACKEND_HOST}")
        return False

def fix_dns():
    """Attempt to fix DNS resolution."""
    logging.info("Attempting to fix DNS resolution")
    
    # Try to refresh DNS settings
    try:
        # Check if our backend is in hosts file
        with open('/etc/hosts', 'r') as f:
            if BACKEND_HOST not in f.read():
                # Try to resolve using Google DNS directly
                logging.info("Attempting to add backend to hosts file")
                result = subprocess.run(
                    ["host", BACKEND_HOST, "8.8.8.8"],
                    capture_output=True, text=True
                )
                
                # Extract IP address if resolved
                for line in result.stdout.splitlines():
                    if "has address" in line:
                        ip = line.split()[-1]
                        logging.info(f"Resolved {BACKEND_HOST} to {ip}")
                        
                        # Add to hosts file
                        with open('/etc/hosts', 'a') as hosts:
                            hosts.write(f"\n{ip} {BACKEND_HOST}\n")
                        
                        logging.info(f"Added {BACKEND_HOST} to hosts file")
                        return True
        
        # If we reach here, we couldn't resolve or it's already in hosts
        # Try to restore resolv.conf
        logging.info("Restoring resolv.conf from backup")
        subprocess.run(["chattr", "-i", "/etc/resolv.conf"], stderr=subprocess.DEVNULL)
        
        # Create a new resolv.conf with Google DNS
        with open('/etc/resolv.conf', 'w') as f:
            f.write("# Generated by dns-precheck.py\n")
            f.write("nameserver 8.8.8.8\n")
            f.write("nameserver 1.1.1.1\n")
            f.write("options timeout:1 attempts:2 rotate\n")
        
        logging.info("DNS settings restored")
        
        # Give it a moment to take effect
        time.sleep(1)
        
        # Check if it worked
        return check_dns()
        
    except Exception as e:
        logging.error(f"Error trying to fix DNS: {e}")
        return False

def main():
    """Main function."""
    if check_dns():
        # DNS is working, exit with success
        sys.exit(0)
    
    # Try to fix DNS
    if fix_dns():
        # Fixed successfully
        sys.exit(0)
    
    # Could not fix
    logging.error("Could not fix DNS resolution")
    sys.exit(1)

if __name__ == "__main__":
    main()
EOF

chmod +x /usr/local/bin/dns-precheck.py
echo -e "${GREEN}Created application DNS helper at /usr/local/bin/dns-precheck.py${NC}"

# Create application launcher wrapper
echo -e "${YELLOW}Creating application launcher with DNS check...${NC}"
cat > /usr/local/bin/run-with-dns-check << 'EOF'
#!/bin/bash
# Wrapper script to run application with DNS checking

# Log to file
LOGFILE="/var/log/dns-wrapper.log"
echo "$(date): Starting application with DNS check" >> $LOGFILE

# First run the DNS precheck
/usr/local/bin/dns-precheck.py
if [ $? -ne 0 ]; then
  echo "$(date): DNS precheck failed, restarting networking" >> $LOGFILE
  
  # Try more aggressive fixes
  chattr -i /etc/resolv.conf 2>/dev/null
  echo "nameserver 8.8.8.8" > /etc/resolv.conf
  echo "nameserver 1.1.1.1" >> /etc/resolv.conf

  # Restart networking
  systemctl restart lte-connection
  sleep 5
  
  # Run precheck again
  /usr/local/bin/dns-precheck.py
  if [ $? -ne 0 ]; then
    echo "$(date): DNS still not working after fixes" >> $LOGFILE
  else
    echo "$(date): DNS fixed after network restart" >> $LOGFILE
  fi
fi

# Run the application, passing all arguments to it
echo "$(date): Launching application: $@" >> $LOGFILE
exec "$@"
EOF

chmod +x /usr/local/bin/run-with-dns-check
echo -e "${GREEN}Created application launcher at /usr/local/bin/run-with-dns-check${NC}"

# Create an application service that uses the wrapper
echo -e "${YELLOW}Creating application service with DNS check...${NC}"
cat > /etc/systemd/system/vehicle-tracker-with-dns.service << EOF
[Unit]
Description=Vehicle Tracker with DNS Checks
After=network.target lte-connection.service

[Service]
Type=simple
ExecStart=/usr/local/bin/run-with-dns-check python3 $(pwd)/main.py
WorkingDirectory=$(pwd)
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo -e "${GREEN}Created application service at /etc/systemd/system/vehicle-tracker-with-dns.service${NC}"

# Restart the LTE connection to apply changes
echo -e "${YELLOW}Restarting LTE connection...${NC}"
systemctl restart lte-connection

echo -e "${YELLOW}Waiting for connection to establish (15s)...${NC}"
sleep 15

# Test DNS resolution
echo -e "${YELLOW}Testing DNS resolution...${NC}"
/usr/local/bin/test-lte-dns

echo -e "${GREEN}=== Persistent DNS Fix Completed ===${NC}"
echo -e "${YELLOW}This fix includes:${NC}"
echo -e "1. Enhanced DNS setup script"
echo -e "2. DNS watchdog service that continuously monitors and fixes DNS"
echo -e "3. Application helpers to check DNS before making requests"
echo -e "4. Custom application service with DNS checking"
echo -e "\n${YELLOW}To use the new application service:${NC}"
echo -e "${GREEN}sudo systemctl start vehicle-tracker-with-dns${NC}"
echo -e "\n${YELLOW}To check DNS status at any time:${NC}"
echo -e "${GREEN}sudo /usr/local/bin/test-lte-dns${NC}"
echo -e "\n${YELLOW}If still having issues after restart:${NC}"
echo -e "${GREEN}sudo systemctl status dns-watchdog${NC}" 