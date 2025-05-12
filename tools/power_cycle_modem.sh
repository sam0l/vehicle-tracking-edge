#!/bin/bash
# USB modem power cycle script
# This script attempts to power cycle a USB modem by disabling and re-enabling the USB port

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== USB Modem Power Cycle Tool ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Stop any services that might be using the modem
echo -e "${YELLOW}Stopping services that might be using the modem...${NC}"
systemctl stop lte-connection.service || true
killall pppd 2>/dev/null || true
sleep 2

# Find USB devices
echo -e "${YELLOW}Detecting USB modem devices...${NC}"
modem_bus_ids=$(lsusb | grep -iE 'modem|huawei|zte|quectel|sierra|telit|simcom|fibocom' | awk '{print $2 "/" $4}' | sed 's/://')

if [ -z "$modem_bus_ids" ]; then
  echo -e "${YELLOW}No specific modem device found by name. Listing all USB devices:${NC}"
  lsusb
  read -p "Enter the Bus/Device numbers (e.g., 001/002): " manual_bus_id
  modem_bus_ids=$manual_bus_id
fi

if [ -z "$modem_bus_ids" ]; then
  echo -e "${RED}No USB device selected. Exiting.${NC}"
  exit 1
fi

# Function to try to reset a USB device
reset_device() {
  local bus_id=$1
  local bus=$(echo $bus_id | cut -d/ -f1)
  local dev=$(echo $bus_id | cut -d/ -f2)
  
  echo -e "${YELLOW}Attempting to power cycle USB device at bus $bus, device $dev${NC}"
  
  # Get port and driver
  port_path=$(find /sys/bus/usb/devices -name "$bus-$dev" -o -name "$bus-$dev.*" | sort | head -1)
  if [ -z "$port_path" ]; then
    echo -e "${RED}Could not find sysfs path for device $bus_id${NC}"
    return 1
  fi
  
  echo -e "${YELLOW}Found device at: $port_path${NC}"
  
  # Unbind any active modems from their drivers
  tty_devices=$(ls -la /dev/ttyUSB* 2>/dev/null | grep -o "ttyUSB[0-9]*" || true)
  for tty in $tty_devices; do
    echo -e "${YELLOW}Killing processes using /dev/$tty${NC}"
    fuser -k /dev/$tty 2>/dev/null || true
    sleep 1
  done
  
  # Method 1: USB reset using sysfs
  echo -e "${YELLOW}Method 1: USB reset via sysfs...${NC}"
  echo 0 > "$port_path/authorized" 2>/dev/null || echo -e "${RED}Failed to deauthorize device${NC}"
  sleep 2
  echo 1 > "$port_path/authorized" 2>/dev/null || echo -e "${RED}Failed to reauthorize device${NC}"
  
  # Method 2: Use usbreset tool (create if not exists)
  echo -e "${YELLOW}Method 2: Using usbreset utility...${NC}"
  if ! command -v usbreset &> /dev/null; then
    echo -e "${YELLOW}Creating usbreset utility...${NC}"
    cat > /tmp/usbreset.c << 'EOF'
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <linux/usbdevice_fs.h>

int main(int argc, char **argv)
{
    const char *filename;
    int fd;
    int rc;

    if (argc != 2) {
        fprintf(stderr, "Usage: usbreset device-filename\n");
        return 1;
    }
    filename = argv[1];

    fd = open(filename, O_WRONLY);
    if (fd < 0) {
        perror("Error opening output file");
        return 1;
    }

    printf("Resetting USB device %s\n", filename);
    rc = ioctl(fd, USBDEVFS_RESET, 0);
    if (rc < 0) {
        perror("Error in ioctl");
        return 1;
    }
    printf("Reset successful\n");

    close(fd);
    return 0;
}
EOF
    gcc -o /tmp/usbreset /tmp/usbreset.c
    chmod +x /tmp/usbreset
  fi
  
  for dev_path in /dev/bus/usb/$bus/$dev; do
    if [ -e "$dev_path" ]; then
      /tmp/usbreset "$dev_path" || echo -e "${RED}Failed USB reset on $dev_path${NC}"
    fi
  done
  
  # Method 3: Use the uhubctl tool if available
  if command -v uhubctl &> /dev/null; then
    echo -e "${YELLOW}Method 3: Using uhubctl...${NC}"
    uhubctl -a cycle -l 1-1 || echo -e "${RED}Failed to cycle USB port with uhubctl${NC}"
  else
    echo -e "${YELLOW}uhubctl not available. Skipping method 3.${NC}"
  fi
  
  # Wait for devices to reappear
  echo -e "${YELLOW}Waiting for USB devices to reappear...${NC}"
  sleep 5
  
  # Check if modem devices reappeared
  if ls /dev/ttyUSB* &>/dev/null; then
    echo -e "${GREEN}USB serial devices detected after reset${NC}"
    ls -la /dev/ttyUSB*
    return 0
  else
    echo -e "${RED}No USB serial devices found after reset${NC}"
    return 1
  fi
}

# Process each modem device
for bus_id in $modem_bus_ids; do
  echo -e "${YELLOW}Processing device: $bus_id${NC}"
  reset_device $bus_id
  echo ""
done

# Wait for modem to settle
echo -e "${YELLOW}Waiting for modem to initialize (10 seconds)...${NC}"
sleep 10

# Test if modem is responsive
echo -e "${YELLOW}Testing modem responsiveness...${NC}"
for tty in $(ls /dev/ttyUSB* 2>/dev/null || echo ""); do
  echo -e "${YELLOW}Testing port: $tty${NC}"
  stty -F $tty 115200
  echo -e "AT\r" > $tty
  sleep 1
  response=$(head -n 1 $tty 2>/dev/null || echo "No response")
  
  if [[ "$response" == *"OK"* ]]; then
    echo -e "${GREEN}Modem is responding on $tty!${NC}"
    # Try more AT commands to verify functionality
    echo -e "ATI\r" > $tty
    sleep 1
    ati_response=$(head -n 5 $tty 2>/dev/null || echo "")
    echo -e "${GREEN}Modem information: $ati_response${NC}"
    success=true
    break
  else
    echo -e "${RED}No valid response from modem on $tty${NC}"
  fi
done

# Final check and next steps
if [[ "$success" == true ]]; then
  echo -e "${GREEN}===================================${NC}"
  echo -e "${GREEN}USB modem reset was successful!${NC}"
  echo -e "${GREEN}===================================${NC}"
  echo -e "You can now run the connection script:"
  echo -e "${YELLOW}sudo python3 tests/direct_lte_connect.py --debug${NC}"
else
  echo -e "${RED}===================================${NC}"
  echo -e "${RED}USB modem reset was not successful${NC}"
  echo -e "${RED}===================================${NC}"
  echo -e "Please try the following:"
  echo -e "1. Physically disconnect and reconnect the modem"
  echo -e "2. Restart the system"
  echo -e "3. Check if the modem is properly connected"
  echo -e "4. Check dmesg for USB errors: ${YELLOW}dmesg | grep -i usb${NC}"
fi

exit 0 