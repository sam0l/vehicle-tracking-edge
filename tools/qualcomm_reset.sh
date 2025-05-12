#!/bin/bash
# Qualcomm A76XX Series LTE Module Reset Script
# Specifically designed for the detected modem (ID 1e0e:9011)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Qualcomm A76XX Series LTE Module Reset Tool ===${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root${NC}"
  exit 1
fi

# Stop any services that might be using the modem
echo -e "${YELLOW}Stopping services that might be using the modem...${NC}"
systemctl stop lte-connection.service 2>/dev/null || true
killall pppd 2>/dev/null || true
sleep 2

# Find the Qualcomm modem
echo -e "${YELLOW}Looking for Qualcomm A76XX modem...${NC}"
modem_info=$(lsusb | grep -i "1e0e:9011\|Qualcomm\|A76XX")

if [ -z "$modem_info" ]; then
  echo -e "${RED}Qualcomm modem not found. Checking all USB devices:${NC}"
  lsusb
  echo -e "${YELLOW}Please ensure the modem is connected.${NC}"
  exit 1
fi

echo -e "${GREEN}Found modem: $modem_info${NC}"

# Extract bus and device numbers
bus=$(echo "$modem_info" | awk '{print $2}')
device=$(echo "$modem_info" | awk '{print $4}' | sed 's/://')
echo -e "${YELLOW}Bus: $bus, Device: $device${NC}"

# Kill any processes using ttyUSB* devices
for tty in /dev/ttyUSB*; do
  if [ -e "$tty" ]; then
    echo -e "${YELLOW}Killing processes using $tty${NC}"
    fuser -k "$tty" 2>/dev/null || true
    sleep 1
  fi
done

# Try to find the correct sysfs path for the device
echo -e "${YELLOW}Searching for correct sysfs path...${NC}"

# Method 1: Try direct path
direct_path="/sys/bus/usb/devices/$bus-$device"
if [ -d "$direct_path" ]; then
  sysfs_path="$direct_path"
else
  # Method 2: Search by vendor and product ID
  for path in /sys/bus/usb/devices/*; do
    if [ -f "$path/idVendor" ] && [ -f "$path/idProduct" ]; then
      vendor=$(cat "$path/idVendor" 2>/dev/null || echo "")
      product=$(cat "$path/idProduct" 2>/dev/null || echo "")
      if [ "$vendor" = "1e0e" ] && [ "$product" = "9011" ]; then
        sysfs_path="$path"
        break
      fi
    fi
  done
fi

# Method 3: Try using the generic USB path format
if [ -z "$sysfs_path" ]; then
  # Try all possible path formats
  for format in "$bus-$device" "$bus-0:1.0" "usb$bus/$bus-$device" "$bus-0.$device"; do
    potential_path="/sys/bus/usb/devices/$format"
    if [ -d "$potential_path" ]; then
      sysfs_path="$potential_path"
      echo -e "${GREEN}Found device at $sysfs_path${NC}"
      break
    fi
  done
fi

# Method 4: Try common paths for this type of modem
if [ -z "$sysfs_path" ]; then
  for path in /sys/bus/usb/devices/*; do
    if [[ "$path" == *"-$bus."* ]] || [[ "$path" == *"$bus-"* ]]; then
      if [ -d "$path" ]; then
        # Check if this is a USB device (has descriptor file)
        if [ -f "$path/descriptors" ]; then
          sysfs_path="$path"
          echo -e "${GREEN}Found potential device at $sysfs_path${NC}"
          break
        fi
      fi
    fi
  done
fi

if [ -z "$sysfs_path" ]; then
  echo -e "${RED}Could not find sysfs path for modem. Manual method required.${NC}"
  # Use usb-devices to get more detailed information
  echo -e "${YELLOW}Gathering USB device information...${NC}"
  usb_devices_output=$(usb-devices)
  echo "$usb_devices_output"
  
  echo -e "${YELLOW}Looking for potential sysfs paths...${NC}"
  find /sys/bus/usb/devices -type d | grep -i "$bus" || true
  
  # Just try the USB bus reset as a last resort
  echo -e "${YELLOW}Attempting to reset USB bus $bus${NC}"
  echo "1" > "/sys/bus/usb/devices/usb$bus/bConfigurationValue" 2>/dev/null || true
  sleep 2
else
  echo -e "${GREEN}Found sysfs path: $sysfs_path${NC}"
  
  # Try various methods to reset the device
  echo -e "${YELLOW}Method 1: Unbinding and rebinding device${NC}"
  
  # Get the driver if available
  if [ -L "$sysfs_path/driver" ]; then
    driver_path=$(readlink -f "$sysfs_path/driver")
    driver_name=$(basename "$driver_path")
    echo -e "${YELLOW}Found driver: $driver_name${NC}"
    
    # Unbind
    echo -e "${YELLOW}Unbinding device from driver${NC}"
    device_name=$(basename "$sysfs_path")
    echo "$device_name" > "$driver_path/unbind" 2>/dev/null || echo -e "${RED}Failed to unbind${NC}"
    sleep 2
    
    # Rebind
    echo -e "${YELLOW}Rebinding device to driver${NC}"
    echo "$device_name" > "$driver_path/bind" 2>/dev/null || echo -e "${RED}Failed to rebind${NC}"
    sleep 2
  fi
  
  # Method 2: Power cycle using authorized flag
  echo -e "${YELLOW}Method 2: Cycling USB power state via authorized flag${NC}"
  if [ -f "$sysfs_path/authorized" ]; then
    echo "0" > "$sysfs_path/authorized" 2>/dev/null || echo -e "${RED}Failed to deauthorize${NC}"
    sleep 3
    echo "1" > "$sysfs_path/authorized" 2>/dev/null || echo -e "${RED}Failed to reauthorize${NC}"
    sleep 3
  else
    echo -e "${RED}No 'authorized' file found in sysfs path${NC}"
    # Try parent device if it exists
    parent_path=$(dirname "$sysfs_path")
    if [ -f "$parent_path/authorized" ]; then
      echo -e "${YELLOW}Trying parent device: $parent_path${NC}"
      echo "0" > "$parent_path/authorized" 2>/dev/null || echo -e "${RED}Failed to deauthorize parent${NC}"
      sleep 3
      echo "1" > "$parent_path/authorized" 2>/dev/null || echo -e "${RED}Failed to reauthorize parent${NC}"
      sleep 3
    fi
  fi
  
  # Method 3: Reset the USB device using usbreset utility
  echo -e "${YELLOW}Method 3: Using usbreset utility${NC}"
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
  
  # Try to reset the USB device
  usb_dev_path="/dev/bus/usb/$bus/$device"
  if [ -e "$usb_dev_path" ]; then
    echo -e "${YELLOW}Resetting USB device at $usb_dev_path${NC}"
    /tmp/usbreset "$usb_dev_path" 2>/dev/null || echo -e "${RED}Failed to reset USB device${NC}"
    sleep 3
  fi
fi

# Wait for modem to reappear
echo -e "${YELLOW}Waiting for modem devices to reappear (15 seconds)...${NC}"
sleep 15

# Check if ttyUSB devices reappeared
if ls /dev/ttyUSB* &>/dev/null; then
  echo -e "${GREEN}USB serial devices detected:${NC}"
  ls -la /dev/ttyUSB*
  
  # Try to communicate with the modem
  echo -e "${YELLOW}Testing modem communication...${NC}"
  # Try each ttyUSB device
  for tty in /dev/ttyUSB*; do
    echo -e "${YELLOW}Testing port $tty...${NC}"
    # Set correct baud rate
    stty -F $tty 115200
    
    # Send AT command and check response
    echo -e "AT\r" > $tty
    sleep 2
    response=$(head -n1 $tty 2>/dev/null || echo "No response")
    
    if [[ "$response" == *"OK"* ]]; then
      echo -e "${GREEN}Modem responded on $tty!${NC}"
      # Test more commands
      echo -e "ATI\r" > $tty
      sleep 1
      ati_response=$(head -n5 $tty 2>/dev/null || echo "")
      echo -e "${GREEN}Modem info: $ati_response${NC}"
      
      echo -e "${GREEN}===================================${NC}"
      echo -e "${GREEN}Modem reset successful on $tty!${NC}"
      echo -e "${GREEN}===================================${NC}"
      echo -e "You can now run the connection script:"
      echo -e "${YELLOW}sudo python3 tests/direct_lte_connect.py --port $tty --debug${NC}"
      exit 0
    else
      echo -e "${RED}No response from modem on $tty${NC}"
    fi
  done
else
  echo -e "${RED}No USB serial devices found after reset${NC}"
fi

# Last resort: Manually unload and reload USB modules
echo -e "${YELLOW}Attempting last resort: Reloading USB drivers...${NC}"
modprobe -r option
modprobe -r usb_wwan
modprobe -r usbserial
sleep 3
modprobe usbserial
modprobe usb_wwan
modprobe option
sleep 5

# Final check
if ls /dev/ttyUSB* &>/dev/null; then
  echo -e "${GREEN}USB serial devices reappeared after driver reload:${NC}"
  ls -la /dev/ttyUSB*
  echo -e "${YELLOW}Try running the connection script now:${NC}"
  echo -e "${YELLOW}sudo python3 tests/direct_lte_connect.py --debug${NC}"
else
  echo -e "${RED}===================================${NC}"
  echo -e "${RED}Modem reset failed. Try these steps:${NC}"
  echo -e "${RED}===================================${NC}"
  echo -e "1. Physically disconnect and reconnect the modem"
  echo -e "2. Reboot the system: ${YELLOW}sudo reboot${NC}"
  echo -e "3. Check dmesg for USB errors: ${YELLOW}dmesg | grep -i usb${NC}"
  echo -e "4. Check if modem is recognized: ${YELLOW}lsusb${NC}"
fi

exit 0 