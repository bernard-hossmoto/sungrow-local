# Blocking the inverter from the cloud

[Deutsche Fassung](block-cloud.de.md)

With sungrow-local running, the inverter no longer needs the iSolarCloud to be useful to
you. You can cut the WiNet-S off from the internet and open it again only when you want a
firmware update. Modbus in your own network keeps working, because it never leaves the
house.

Blocking the cloud is only half of it. The Modbus port that sungrow-local needs has no
login, so the dongle should also be shielded from the rest of your home network. Both
are described below.

> On the tested system the dashboard runs, the block itself is prepared but not active yet.
> The steps below are the plan, not a long-term report. Feedback is welcome.

## Before you block

- **Update the firmware first.** WiNet-S firmware up to `WINET-SV200.001.00.P027` has
  published vulnerabilities (hard-coded credentials, missing firmware integrity check,
  buffer overflows; for example
  [CVE-2024-50692](https://en.sungrowpower.com/security-notice-detail-2/6136)). A dongle
  that is blocked before it is updated stays vulnerable to anyone in your network. Check
  the firmware version in the app and let it update while it still has internet.
- **Change the admin password** of the dongle's local web interface (see
  [setup-winet.md](setup-winet.md), way B). That interface stays reachable from your network.
- **Grid operator.** In some countries the grid operator requires the plant to be remotely
  controllable or to limit its feed-in through the manufacturer's cloud. Check the
  conditions of your grid connection first.
- **Installer.** Tell your installer. Their remote access through the cloud stops working,
  and they should not search for a fault that is just your firewall.
- **What you lose:** the iSolarCloud app and web portal, remote support, automatic
  firmware updates and possibly time synchronisation of the inverter (see below).

## Lock down the WiNet-S

**Port 502 is unauthenticated.** Everything that can reach it can read the inverter, and
you should assume it can also write settings: Sungrow SH inverters accept battery mode,
forced charging and discharging, export limit and start/stop over the same interface.
That is how evcc and the Home Assistant integration control the battery. sungrow-local
only reads, but it cannot protect the port. A compromised phone, TV, smart plug or a
guest's laptop in the same network can talk to the inverter directly.

The goal is exactly one allowed flow, **sungrow-local host → WiNet-S, TCP 502**, and
nothing else to or from the dongle: no internet, no access to its web interface (TCP 80
and 443) from other devices, no forwarding anywhere.

### Recommended: a network segment of its own

Put the WiNet-S into its own network: a VLAN, a separate "IoT" network or a firewall zone
of its own. Then the router sees every packet to and from the dongle and can filter it.

**OpenWrt.** Assuming the dongle is in its own network called `sungrow` (a VLAN, a
separate port or SSID), with the dashboard host at `192.168.1.10` and the dongle at
`192.168.20.2`:

```sh
# zone for the dongle: it may not reach the router, the internet or any other zone
uci set firewall.sungrow=zone
uci set firewall.sungrow.name='sungrow'
uci set firewall.sungrow.network='sungrow'
uci set firewall.sungrow.input='REJECT'
uci set firewall.sungrow.output='ACCEPT'
uci set firewall.sungrow.forward='REJECT'

# the dongle still needs DHCP from the router
uci set firewall.sungrow_dhcp=rule
uci set firewall.sungrow_dhcp.name='Sungrow WiNet-S: DHCP'
uci set firewall.sungrow_dhcp.src='sungrow'
uci set firewall.sungrow_dhcp.proto='udp'
uci set firewall.sungrow_dhcp.dest_port='67-68'
uci set firewall.sungrow_dhcp.target='ACCEPT'

# only the dashboard host may reach Modbus
uci set firewall.sungrow_modbus=rule
uci set firewall.sungrow_modbus.name='sungrow-local to WiNet-S Modbus'
uci set firewall.sungrow_modbus.src='lan'
uci set firewall.sungrow_modbus.src_ip='192.168.1.10'
uci set firewall.sungrow_modbus.dest='sungrow'
uci set firewall.sungrow_modbus.dest_ip='192.168.20.2'
uci set firewall.sungrow_modbus.proto='tcp'
uci set firewall.sungrow_modbus.dest_port='502'
uci set firewall.sungrow_modbus.target='ACCEPT'

uci commit firewall && /etc/init.d/firewall reload
```

Do not add a `forwarding` from `sungrow` to `wan` or from `lan` to `sungrow`. Since the
dongle may not use the router's DNS either, it has no slow side channel through name
lookups. For a firmware update, temporarily add a forwarding `sungrow → wan` and remove
it again afterwards (and allow DNS, UDP and TCP 53, from `sungrow` for that time).

**OPNsense / pfSense.** On the interface of the dongle's VLAN: a **block** rule with source
= the dongle and destination = any. On the LAN interface: a **pass** rule with source = the
dashboard host, destination = the dongle, TCP port 502, and below it a **block** rule with
destination = the dongle's network. For a firmware update, put a temporary pass rule from
the dongle to the internet above the block rule.

### Without VLANs

In a flat home network, traffic between two devices goes through the switch, not through
the router's firewall. The router can then block the dongle from the **internet**, but it
cannot stop other devices in your network from reaching port 502. What still helps:

- Block internet access for the dongle (next section).
- Wi-Fi client isolation, if the dongle and your other devices are on Wi-Fi and the router
  offers it.
- Be honest about the limit: in a flat network every device in the house can reach the
  inverter. If that matters to you, a separate network for the dongle is the fix.

## Blocking only the internet

The idea is always the same: the WiNet-S may talk to your local network, but not to the
internet. Give it a fixed address first (DHCP reservation), then add a rule for it.

### Typical home router

Many routers have a "block internet access" switch per device, often under parental
controls or access profiles. Pick the WiNet-S there. The local network keeps working.

### OpenWrt (uci)

Match the dongle by its **MAC address**, not by its IP: a device that changes its own
address or gets a new lease would otherwise no longer be covered. Replace the MAC with the
one of your WiNet-S:

```sh
uci set firewall.sungrow_block=rule
uci set firewall.sungrow_block.name='Sungrow WiNet-S: no internet'
uci set firewall.sungrow_block.src='lan'
uci set firewall.sungrow_block.src_mac='AC:19:9F:00:00:00'
uci set firewall.sungrow_block.dest='wan'
uci set firewall.sungrow_block.proto='all'
uci set firewall.sungrow_block.target='REJECT'
uci commit firewall && /etc/init.d/firewall reload
```

A MAC address can be changed by the device too. If you treat the dongle's firmware as
untrusted, the separate network above is the only rule that does not depend on the
dongle's cooperation. The dongle can also still ask the router's DNS resolver; to stop
that, add a rule that rejects UDP and TCP port 53 from the dongle to the router (`src
lan`, `src_mac` as above, no `dest`, `dest_port 53`, `target REJECT`).

Open it again for an update, and close it afterwards:

```sh
uci set firewall.sungrow_block.enabled='0' && uci commit firewall && /etc/init.d/firewall reload
uci set firewall.sungrow_block.enabled='1' && uci commit firewall && /etc/init.d/firewall reload
```

### OPNsense / pfSense

On the LAN interface add a **block** rule with source = the WiNet-S address (or an alias
with its MAC) and destination = *not* LAN net, and place it above the default "allow LAN to
any" rule. To open it for an update, disable the rule.

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

- The router or firewall log shows rejected connections from the WiNet-S.
- After a while the iSolarCloud app shows the plant offline.
- sungrow-local keeps showing live values.
- From **another** device in your network (not the dashboard host),
  `nc -z -w 3 <winet-ip> 502` must fail. If it succeeds, other devices can still reach
  the Modbus port.
