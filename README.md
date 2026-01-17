# Home Assistant SMS Notification via Asterisk AMI DongleSendSMS/USSD
# Asterisk Integration for Home Assistant via Asterisk AMI. Send SMS/USSD, get USB Dongle statistic and network strength

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

This custom allows you to send SMS and USSD codes via your GSM dongle connected to Asterisk via 
[chan_dongle](https://github.com/bg111/asterisk-chan-dongle) driver. It uses Asterisk AMI api to send DongleSendSMS/USSD
command. It also allows you to monitor network signal on the USB stick.

## Installation

### HACS

[Guide](https://hacs.xyz/docs/faq/custom_repositories/)

### Manual

Copy `custom_components/asterisk_dongle/` contents from repo into `custom_components/asterisk_dongle/` 
   [directory](https://home-assistant.io/developers/component_loading/).

## Configuration

1. Configure Asterisk AMI by editing `/etc/asterisk/manager.conf`:
   
   ```ini
   [general]
   # enables AMI api
   enabled = yes
   # sets listen port
   port = 5038
   # listen interface
   bindaddr = 127.0.0.1
   
   # user name
   [smart-home]
   # user password
   secret=your_password
   # privileges, that's all we need for calling DongleSendSMS
   read=all
   write=all
   ```
   
   Restart Asterisk.
   
2. Add the integration Asterisk Dongle via Home Assistant UI. Provide AMI connectivity information (host, port, username and password) and scan_interval.

3. The integration creates devices and sensors for each dongle, connected to Asterisk (named sensor.cell_signal_<IMEI>) and 2 notification servives for SMS (notify.sms_<IMEI>) and USSD (notify.ussd_<IMEI>).
  
4. Add [automation](https://home-assistant.io/docs/automation/action/).

Written by Deepseek.
