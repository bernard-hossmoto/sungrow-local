# Blocking the inverter from the cloud

[Deutsche Fassung](block-cloud.de.md)

With sungrow-local running, the inverter no longer needs the iSolarCloud to be useful to
you. You can cut the WiNet-S off from the internet and open it again only when you want a
firmware update. Modbus in your own network keeps working, because it never leaves the
house.

> On the tested system the dashboard runs, the block itself is prepared but not active yet.
> The steps below are the plan, not a long-term report. Feedback is welcome.

## Before you block

- **Grid operator.** In some countries the grid operator requires the plant to be remotely
  controllable or to limit its feed-in through the manufacturer's cloud. Check the
  conditions of your grid connection first.
- **Installer.** Tell your installer. Their remote access through the cloud stops working,
  and they should not search for a fault that is just your firewall.
- **What you lose:** the iSolarCloud app and web portal, remote support, automatic
  firmware updates and possibly time synchronisation of the inverter (see below).

## How to block

The idea is always the same: the WiNet-S may talk to your local network, but not to the
internet. Give it a fixed address first (DHCP reservation), then add a rule for that
address.

### Typical home router

Many routers have a "block internet access" switch per device, often under parental
controls or access profiles. Pick the WiNet-S there. The local network keeps working.

### OpenWrt (uci)

A named rule makes it easy to switch on and off later. Replace the address with the one of
your WiNet-S:

```sh
uci set firewall.sungrow_block=rule
uci set firewall.sungrow_block.name='Sungrow WiNet-S: no internet'
uci set firewall.sungrow_block.src='lan'
uci set firewall.sungrow_block.src_ip='192.168.1.100'
uci set firewall.sungrow_block.dest='wan'
uci set firewall.sungrow_block.proto='all'
uci set firewall.sungrow_block.target='REJECT'
uci commit firewall && /etc/init.d/firewall reload
```

Open it again for an update, and close it afterwards:

```sh
uci set firewall.sungrow_block.enabled='0' && uci commit firewall && /etc/init.d/firewall reload
uci set firewall.sungrow_block.enabled='1' && uci commit firewall && /etc/init.d/firewall reload
```

### OPNsense / pfSense

On the LAN interface add a **block** rule with source = the WiNet-S address and
destination = *not* LAN net, and place it above the default "allow LAN to any" rule. To
open it for an update, disable the rule.

## Firmware updates

1. Disable the block rule.
2. Wait until the app shows the plant online again, then run the update (or let it run).
3. Enable the rule again.

## Watch the clock

The daily counters (today's production, export and so on) reset at midnight **in the
inverter's clock**. We have not verified how the inverter sets its time without the cloud.
After blocking, check over a few days whether the daily values still start at 0 around
midnight. If they drift, open the internet for the WiNet-S now and then so it can resync,
or allow only time synchronisation (NTP, UDP port 123).

## Check that it works

- The router or firewall log shows rejected connections from the WiNet-S address.
- After a while the iSolarCloud app shows the plant offline.
- sungrow-local keeps showing live values.
