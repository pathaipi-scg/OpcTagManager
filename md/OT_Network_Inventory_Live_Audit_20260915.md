# OT Network Inventory live MAC audit - 2026-09-15

Observed at: 2026-09-15T15:06:35.616806+00:00

## Findings

- Read-only SQL audit: DEFAULT_OT is NetworkId 1, range 172.28.231.1-254. Latest stored scan is 2026-09-15 14:55 UTC.
- Latest scan: 254 IPs, 144 MACs, 144 stored vendors; 110 rows have neither MAC nor vendor. 109 of those had no ICMP reply; 172.28.231.251 replied but had no captured MAC. No Unknown row has a captured MAC with an unmatched OUI.
- The current workstation ARP cache has no configured-subnet entries. Running the actual collector here returns zero target MACs, consistent with arp -a. This is not a contemporaneous capture from the production scanner host. Production ARP interface provenance was not previously stored, so it cannot be recovered from old SQL history.
- No new scan, SQL mutation, or restart was performed for this audit.

## Sample-MAC provenance

The exact sample MAC 00:11:22:33:44:55 is present in 508 legacy history rows (254 in each run below), all with NetworkId NULL. No scoped history row has that exact sample MAC. The old records have Vendor NULL; the CSV fix resolves their stored prefix to CIMSYS Inc at display time. They predate the September 15 offline lookup verification. The original source/injection mechanism is not provable from the stored metadata alone.

| Run | UTC started | Trigger | Rows |
|---|---|---|---|
| 824D94B2-0662-4B96-9678-04ED862741F3 | 2026-09-08 16:32:07.451000 | live-verification:Kepware-IP-normalization | 254 |
| CAB8DCFE-F4EA-447D-972A-368F22D7AC89 | 2026-09-09 17:15:05.642000 | client:127.0.0.1 | 254 |

The fix withholds this exact placeholder from new captured/persisted MAC/vendor evidence and derived current views. Other MACs under the same OUI are not blocked. Raw append-only history and Candidate Free evidence are retained. Pure offline OUI diagnostics still perform lookup only, and do not persist or seed scan state.

## Current workstation arp -a (verbatim)

```text
Interface: 10.56.7.81 --- 0x4
  Internet Address      Physical Address      Type
  10.28.255.115         00-11-22-33-44-55     dynamic
  10.100.10.20          00-11-22-33-44-55     dynamic
  172.30.1.25           00-11-22-33-44-55     dynamic
  172.30.1.26           00-11-22-33-44-55     dynamic
  172.30.53.91          00-11-22-33-44-55     dynamic
  172.30.53.92          00-11-22-33-44-55     dynamic
  224.0.0.22            01-00-5e-00-00-16     static
  224.0.0.251           01-00-5e-00-00-fb     static
  239.255.255.250       01-00-5e-7f-ff-fa     static

Interface: 10.89.19.86 --- 0x17
  Internet Address      Physical Address      Type
  10.89.19.173          56-fa-5c-28-ec-1d     dynamic
  10.89.19.255          ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
  224.0.0.251           01-00-5e-00-00-fb     static
  224.0.0.252           01-00-5e-00-00-fc     static
  239.255.255.250       01-00-5e-7f-ff-fa     static
  255.255.255.255       ff-ff-ff-ff-ff-ff     static
```

All listed unicast IPs are outside DEFAULT_OT. The repeated 00-11-22-33-44-55 is observed cache output, not proof of physical device identity. Multicast/broadcast entries are not usable device MAC evidence.

## Per-IP comparison

The table distinguishes the latest production scan history from this workstation cache snapshot. The current collector captures none of these IPs because none appear in the local cache. Interface/source for the current snapshot is therefore none / Windows arp -a for every row. Previous production interface is unavailable, not inferred.

| NetworkId | IP | Stored scan MAC | Prefix | Stored vendor / Unknown reason | Current local capture |
|---|---|---|---|---|---|
| 1 | 172.28.231.1 | E8:ED:D6:0C:64:97 | E8:ED:D6 | Fortinet, Inc. | none |
| 1 | 172.28.231.2 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.3 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.4 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.5 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.6 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.7 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.8 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.9 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.10 | 00:E0:4C:50:CB:38 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.11 | 00:E0:4C:24:EE:BD | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.12 | 00:E0:4C:24:ED:77 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.13 | 00:E0:4C:24:EF:67 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.14 | 00:E0:4C:24:F6:03 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.15 | 00:E0:4C:24:ED:08 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.16 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.17 | 04:03:12:5B:71:B3 | 04:03:12 | Hangzhou Hikvision Digital Technology Co.,Ltd. | none |
| 1 | 172.28.231.18 | 04:EE:E8:14:62:1D | 04:EE:E8 | IEEE Registration Authority | none |
| 1 | 172.28.231.19 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.20 | 00:30:DE:4B:70:14 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.21 | 00:30:DE:05:FA:5D | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.22 | 00:30:DE:06:A7:5E | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.23 | 00:50:C2:CE:AE:47 | 00:50:C2 | IEEE Registration Authority | none |
| 1 | 172.28.231.24 | 00:30:DE:4A:5F:8E | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.25 | 00:30:DE:06:97:E3 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.26 | 00:30:DE:05:F9:A5 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.27 | 00:30:DE:05:D9:11 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.28 | 00:30:DE:06:97:CC | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.29 | 00:30:DE:06:98:3D | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.30 | 00:30:DE:07:3B:E7 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.31 | 00:30:DE:05:F9:CD | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.32 | 00:E0:4C:24:EE:16 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.33 | 00:E0:4C:24:ED:9A | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.34 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.35 | 00:E0:4C:24:F7:BA | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.36 | 00:E0:4C:24:F7:99 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.37 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.38 | 30:B8:51:9A:56:99 | 30:B8:51 | Siemens AG | none |
| 1 | 172.28.231.39 | 00:00:54:8A:3D:27 | 00:00:54 | Schneider Electric | none |
| 1 | 172.28.231.40 | 00:04:A3:05:00:D3 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.41 | 00:04:A3:05:01:E4 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.42 | 00:04:A3:06:01:DC | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.43 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.44 | 00:04:A3:05:00:05 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.45 | 00:04:A3:05:00:91 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.46 | 00:04:03:05:00:00 | 00:04:03 | Nexsi Corporation | none |
| 1 | 172.28.231.47 | 00:04:A3:05:00:90 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.48 | 00:04:A3:05:00:8F | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.49 | 00:04:A3:05:00:7E | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.50 | 00:30:DE:06:97:E6 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.51 | 00:04:A3:05:00:D9 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.52 | 00:04:A3:05:00:D8 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.53 | 00:04:A3:05:00:D4 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.54 | 00:04:A3:06:01:DA | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.55 | 00:04:A3:05:00:78 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.56 | 00:04:A3:05:00:93 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.57 | 00:04:A3:05:00:D7 | 00:04:A3 | Microchip Technology Inc. | none |
| 1 | 172.28.231.58 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.59 | 00:30:DE:05:BC:4B | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.60 | 00:30:DE:46:AB:AF | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.61 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.62 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.63 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.64 | 00:30:DE:45:BA:B4 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.65 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.66 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.67 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.68 | 00:30:DE:20:79:62 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.69 | 00:30:DE:45:B9:B4 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.70 | 00:30:DE:08:C7:A2 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.71 | 00:01:23:2A:EF:AD | 00:01:23 | Schneider Electric Japan Holdings Ltd. | none |
| 1 | 172.28.231.72 | 00:30:DE:02:7C:3F | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.73 | 00:01:23:2B:7B:D3 | 00:01:23 | Schneider Electric Japan Holdings Ltd. | none |
| 1 | 172.28.231.74 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.75 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.76 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.77 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.78 | 00:30:DE:46:EB:59 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.79 | 00:01:23:30:3D:FE | 00:01:23 | Schneider Electric Japan Holdings Ltd. | none |
| 1 | 172.28.231.80 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.81 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.82 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.83 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.84 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.85 | 00:30:DE:45:BA:BA | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.86 | 00:30:DE:07:3D:75 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.87 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.88 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.89 | 00:30:DE:02:98:36 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.90 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.91 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.92 | E0:DC:A0:D5:FF:E4 | E0:DC:A0 | Siemens Industrial Automation Products Ltd., Chengdu | none |
| 1 | 172.28.231.93 | 00:30:DE:47:0A:56 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.94 | 00:30:11:37:AA:DD | 00:30:11 | HMS Industrial Networks | none |
| 1 | 172.28.231.95 | 00:01:23:30:DD:61 | 00:01:23 | Schneider Electric Japan Holdings Ltd. | none |
| 1 | 172.28.231.96 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.97 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.98 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.99 | 00:30:64:61:4D:FB | 00:30:64 | ADLINK TECHNOLOGY, INC. | none |
| 1 | 172.28.231.100 | 74:FE:48:73:5A:7D | 74:FE:48 | ADVANTECH CO., LTD. | none |
| 1 | 172.28.231.101 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.102 | 30:B8:51:35:C5:7C | 30:B8:51 | Siemens AG | none |
| 1 | 172.28.231.103 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.104 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.105 | 00:1B:1B:26:B4:BE | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.106 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.107 | 8C:F3:E7:25:67:D0 | 8C:F3:E7 | solidotech | none |
| 1 | 172.28.231.108 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.109 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.110 | 00:1B:1B:2A:9A:DE | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.111 | 00:1B:1B:2A:40:5D | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.112 | 00:1B:1B:2B:0D:57 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.113 | 00:1B:1B:2A:3F:DC | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.114 | 00:1B:1B:2D:D8:02 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.115 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.116 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.117 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.118 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.119 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.120 | 00:30:DE:5A:EC:19 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.121 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.122 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.123 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.124 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.125 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.126 | 00:1B:1B:2A:3F:C7 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.127 | 00:1B:1B:2C:4A:D4 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.128 | 00:1B:1B:2A:3F:DF | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.129 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.130 | 00:1B:1B:2A:3F:F1 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.131 | 00:1B:1B:2A:3F:BE | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.132 | 00:1B:1B:1F:0C:63 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.133 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.134 | 00:1B:1B:2A:3F:C4 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.135 | 00:30:DE:51:97:CF | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.136 | 00:1B:1B:2A:3F:D3 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.137 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.138 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.139 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.140 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.141 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.142 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.143 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.144 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.145 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.146 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.147 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.148 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.149 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.150 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.151 | 00:0F:69:07:01:B5 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.152 | 00:0F:69:07:01:B8 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.153 | 00:0F:69:07:01:AF | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.154 | 00:0F:69:07:0E:EA | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.155 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.156 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.157 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.158 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.159 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.160 | 00:0F:69:07:02:4B | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.161 | 00:1B:1B:28:22:96 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.162 | 00:0F:69:07:01:A3 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.163 | 00:0F:69:07:0E:E1 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.164 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.165 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.166 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.167 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.168 | 00:0F:69:05:84:1C | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.169 | 00:1B:1B:2B:04:92 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.170 | 00:1B:1B:28:84:60 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.171 | 00:1B:1B:28:F1:3F | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.172 | 00:0F:69:5E:2C:FD | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.173 | 00:0F:69:05:84:01 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.174 | 00:1B:1B:28:F0:B1 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.175 | 00:0F:69:06:ED:06 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.176 | 00:0F:69:06:ED:03 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.177 | 00:1B:1B:28:F1:3C | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.178 | 00:0F:69:06:C5:FA | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.179 | 00:0F:69:06:FA:77 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.180 | 00:0F:69:06:21:96 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.181 | 00:1B:1B:28:84:9C | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.182 | 00:1B:1B:28:84:87 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.183 | 00:1B:1B:28:79:EE | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.184 | 00:1B:1B:28:7A:65 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.185 | 00:1B:1B:28:7A:41 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.186 | 00:1B:1B:1F:12:AB | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.187 | 00:1B:1B:28:84:99 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.188 | 00:1B:1B:28:79:26 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.189 | 00:1B:1B:2A:3F:5E | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.190 | 00:1B:1B:2A:3F:91 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.191 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.192 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.193 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.194 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.195 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.196 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.197 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.198 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.199 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.200 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.201 | C0:64:E4:F7:1C:76 | C0:64:E4 | Cisco Systems, Inc | none |
| 1 | 172.28.231.202 | C0:64:E4:F7:1D:33 | C0:64:E4 | Cisco Systems, Inc | none |
| 1 | 172.28.231.203 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.204 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.205 | 00:1B:1B:2D:3A:6A | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.206 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.207 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.208 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.209 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.210 | 00:1B:1B:2B:43:9C | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.211 | 00:1B:1B:2A:40:03 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.212 | 00:1B:1B:2A:3F:C1 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.213 | 00:1B:1B:2A:3F:BB | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.214 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.215 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.216 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.217 | 00:E0:4C:1C:62:70 | 00:E0:4C | REALTEK SEMICONDUCTOR CORP. | none |
| 1 | 172.28.231.218 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.219 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.220 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.221 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.222 | 00:1B:1B:2A:3F:61 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.223 | 00:1B:1B:2A:40:00 | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.224 | 00:1B:1B:2B:0D:5B | 00:1B:1B | Siemens AG, | none |
| 1 | 172.28.231.225 | 8C:F3:19:8F:A3:0A | 8C:F3:19 | Siemens Industrial Automation Products Ltd., Chengdu | none |
| 1 | 172.28.231.226 | 00:30:DE:58:85:CD | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.227 | 00:01:23:31:D2:5D | 00:01:23 | Schneider Electric Japan Holdings Ltd. | none |
| 1 | 172.28.231.228 | 00:30:11:55:EE:63 | 00:30:11 | HMS Industrial Networks | none |
| 1 | 172.28.231.229 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.230 | 00:0F:69:61:81:5C | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.231 | 00:0F:69:07:15:3B | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.232 | 00:0F:69:07:0E:F0 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.233 | 00:0F:69:07:14:C3 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.234 | 00:0F:69:07:0E:E4 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.235 | 00:0F:69:09:8C:8A | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.236 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.237 | 20:BB:C6:10:2A:AE | 20:BB:C6 | Jabil Circuit Hungary Ltd. | none |
| 1 | 172.28.231.238 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.239 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.240 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.241 | 00:0F:69:07:01:C1 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.242 | 00:0F:69:07:14:E7 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.243 | 00:0F:69:07:01:B2 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.244 | 00:0F:69:60:D4:07 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.245 | 00:0F:69:07:15:35 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.246 | 00:0F:69:07:15:38 | 00:0F:69 | SEW Eurodrive GmbH & Co. KG | none |
| 1 | 172.28.231.247 | BC:FC:E7:3F:3B:44 | BC:FC:E7 | ASUSTek COMPUTER INC. | none |
| 1 | 172.28.231.248 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.249 | 00:30:DE:4C:57:3D | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.250 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.251 | none | none | Unknown: ICMP reply, no MAC captured | none |
| 1 | 172.28.231.252 | 00:30:DE:47:A1:26 | 00:30:DE | WAGO Kontakttechnik GmbH | none |
| 1 | 172.28.231.253 | none | none | Unknown: no ICMP reply and no MAC captured | none |
| 1 | 172.28.231.254 | none | none | Unknown: no ICMP reply and no MAC captured | none |
