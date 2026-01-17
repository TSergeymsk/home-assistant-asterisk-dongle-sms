Вот обновлённый `README.md`, отражающий все изменения в интеграции:

```markdown
# Asterisk Dongle Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

This custom integration allows you to connect to Asterisk AMI and manage GSM dongles via the [chan_dongle](https://github.com/bg111/asterisk-chan-dongle) driver. It provides device monitoring, signal strength tracking, and SMS/USSD messaging capabilities.

## Features

- **Device Discovery**: Automatically detects connected dongles via Asterisk AMI
- **Signal Monitoring**: Real-time cell signal strength tracking (in dBm)
- **Device Information**: Manufacturer, model, firmware, IMEI, IMSI, and provider details
- **Unified Messaging**: Single notification service per dongle that automatically handles SMS and USSD
- **Dynamic Updates**: Devices and services are automatically created/removed as dongles are connected/disconnected

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant
2. Go to "Integrations"
3. Click "+ Explore & Download Repositories"
4. Search for "Asterisk Dongle" and add this repository
5. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `asterisk_dongle` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

### 1. Configure Asterisk AMI

Edit `/etc/asterisk/manager.conf`:

```ini
[general]
enabled = yes
port = 5038
bindaddr = 0.0.0.0  # Or your Home Assistant IP

[homeassistant]
secret = your_password
read = system,call,log,verbose,command,reporting,cdr
write = system,call,command,originate,message
```

Restart Asterisk after making changes:
```bash
sudo systemctl restart asterisk
```

### 2. Install and Configure chan_dongle

Ensure the `chan_dongle` module is installed and configured in Asterisk:

1. Install `chan_dongle` for your Asterisk version
2. Configure `/etc/asterisk/dongle.conf` for your GSM dongles
3. Load the module in Asterisk CLI: `module load chan_dongle.so`

### 3. Add Integration in Home Assistant

1. Go to **Settings** → **Devices & Services** → **Integrations**
2. Click **+ Add Integration**
3. Search for "Asterisk Dongle"
4. Enter your AMI connection details:
   - **Host**: IP address of your Asterisk server
   - **Port**: AMI port (default: 5038)
   - **Username**: AMI username (from manager.conf)
   - **Password**: AMI password
   - **Scan Interval**: How often to check for devices (default: 60 seconds)

## Created Entities

For each detected dongle, the integration creates:

### Device
- **Name**: `Dongle <IMEI>` (e.g., `Dongle 123456788935456`)
- **Manufacturer**: Detected from dongle (e.g., Huawei, ZTE)
- **Model**: Dongle model (e.g., E173)
- **Firmware**: Device firmware version

### Sensor
- **Entity ID**: `sensor.dongle_<IMEI>_cell_signal`
- **Name**: `Cell Signal <IMEI>`
- **Attributes**:
  - Signal strength (dBm)
  - Signal quality (Excellent/Good/Fair/Poor)
  - Provider name
  - Network mode
  - Registration status
  - LAC and Cell ID

### Notification Service
- **Service**: `notify.asterisk_<IMEI>`
- **Fields**:
  - `target`: Phone number (for SMS) or USSD code (e.g., `*100#`)
  - `message`: SMS text content (ignored for USSD)

## Usage Examples

### Send SMS
```yaml
service: notify.asterisk_123456788935456
data:
  target: "+79123456789"
  message: "Temperature is {{ states('sensor.living_room_temp') }}°C"
```

### Check Balance via USSD
```yaml
service: notify.asterisk_123456788935456
data:
  target: "*100#"
  message: "ignored"  # Any value - this field is ignored for USSD
```

### Automation Example
```yaml
automation:
  - alias: "Alert on high temperature"
    trigger:
      platform: numeric_state
      entity_id: sensor.temperature
      above: 30
    action:
      - service: notify.asterisk_123456788935456
        data:
          target: "+79123456789"
          message: "⚠️ High temperature alert: {{ states('sensor.temperature') }}°C"
```

### Script Example
```yaml
check_balance:
  alias: "Check mobile balance"
  sequence:
    - service: notify.asterisk_123456788935456
      data:
        target: "*100#"
        message: "Balance check"
```

## How It Works

### SMS/USSD Detection
The integration automatically detects whether to send SMS or USSD based on the `target` field format:

- **USSD**: If `target` starts with `*` and ends with `#` (e.g., `*100#`, `*102#`, `*111*1#`)
- **SMS**: All other formats are treated as phone numbers

### Device Discovery
The integration periodically polls Asterisk AMI for connected dongles using the command:
```
dongle show devices
```

### Signal Monitoring
For each dongle, the integration runs:
```
dongle show device state dongleX
```
to extract signal strength and other device information.

## Troubleshooting

### Common Issues

1. **"Cannot connect" error during setup**:
   - Verify Asterisk is running: `systemctl status asterisk`
   - Check AMI port is open: `telnet <asterisk_ip> 5038`
   - Verify AMI credentials in `manager.conf`

2. **No devices discovered**:
   - Check `chan_dongle` is loaded in Asterisk: `module show like chan_dongle`
   - Test directly in Asterisk CLI: `dongle show devices`
   - Verify dongles are properly connected to the server

3. **SMS/USSD not working**:
   - Check AMI user has `write = command` permissions
   - Test in Asterisk CLI: `dongle sms dongle0 +79123456789 "test"`
   - Verify cellular network connectivity on the dongle

### Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.asterisk_dongle: debug
```

## Changelog

### v2.0.0
- Complete rewrite with improved AMI client
- Unified notification service (auto-detects SMS/USSD)
- Proper device naming (`Dongle <IMEI>`)
- Manufacturer detection from dongle data
- Dynamic device/service management

## Support

For issues and feature requests, please visit the GitHub repository.

The README now accurately represents the current state of the integration and provides comprehensive documentation for users.