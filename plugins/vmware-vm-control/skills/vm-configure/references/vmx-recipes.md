# .vmx recipes (all VMware Workstation / Player versions)

Use `vm_settings` (`action: set` / `remove`) with the VM powered off. Values are strings; `TRUE`/`FALSE` are upper-case. Read the current keys first with `prefix`.

## CPU and memory
| Goal | Keys |
|---|---|
| Memory 4 GB | `memsize = "4096"` (MB; XP 32-bit uses at most ~3.5 GB) |
| 2 virtual CPUs | `numvcpus = "2"`; cores per socket: `cpuid.coresPerSocket = "2"` |

## Serial port (COM) - e.g. download to an HMI or PLC
| Goal | Keys |
|---|---|
| Host COM3 -> guest COM1 | `serial0.present = "TRUE"`, `serial0.fileType = "device"`, `serial0.fileName = "COM3"`, `serial0.startConnected = "TRUE"` |
| Named pipe | `serial0.fileType = "pipe"`, `serial0.fileName = "\\.\pipe\com_1"`, `serial0.pipe.endPoint = "server"` |
| Output to a file | `serial0.fileType = "file"`, `serial0.fileName = "C:\path\serial.log"` |
| Yield CPU on poll (Windows guests) | `serial0.tryNoRxLoss = "FALSE"`, `serial0.yieldOnMsrRead = "TRUE"` |
| Live connect/disconnect | `vm_device` with `device_name` `serial0` |

Parallel port: same pattern with `parallel0.*` (`fileType = "device"`, `fileName = "LPT1"`).

## CD/DVD and ISO
| Goal | Keys |
|---|---|
| Attach ISO on IDE secondary master | `ide1:0.present = "TRUE"`, `ide1:0.deviceType = "cdrom-image"`, `ide1:0.fileName = "C:\ISO\x.iso"`, `ide1:0.startConnected = "TRUE"` |
| Physical drive | `ide1:0.deviceType = "cdrom-raw"`, `ide1:0.fileName = "auto detect"` |
| SATA instead of IDE | `sata0.present = "TRUE"`, `sata0:1.*` with the same subkeys (not for XP without drivers) |
An IDE slave (`ide1:1`) needs a master (`ide1:0`) present.

## Network (prefer `vm_network`)
| Goal | Keys |
|---|---|
| NAT / bridged / host-only | `ethernet0.connectionType = "nat"` / `"bridged"` / `"hostonly"` |
| Specific VMnet | `ethernet0.connectionType = "custom"`, `ethernet0.vnet = "VMnet2"` |
| Adapter model | `ethernet0.virtualDev = "e1000"` (XP: `vlance` or `e1000`; Win7+: `e1000e` or `vmxnet3` with Tools) |
| Disconnected at boot | `ethernet0.startConnected = "FALSE"` |
Host networks and NAT port forwarding: `vm_host_network`.

## USB, sound, boot, display, time
| Goal | Keys |
|---|---|
| USB controller | `usb.present = "TRUE"`; USB 3: `usb_xhci.present = "TRUE"` (not for XP) |
| Remove sound card | `sound.present = "FALSE"` |
| Boot order | `bios.bootOrder = "hdd,cdrom"`; enter BIOS once: `bios.forceSetupOnce = "TRUE"` |
| Firmware | `firmware = "efi"` or remove the key for BIOS (XP/7 32-bit need BIOS) |
| Guest time sync with host | `tools.syncTime = "TRUE"` |
| Auto-answer VMware questions | `msg.autoAnswer = "TRUE"` |
| Disable copy/paste/drag-drop | `isolation.tools.copy.disable = "TRUE"`, `isolation.tools.paste.disable = "TRUE"`, `isolation.tools.dnd.disable = "TRUE"` |

## VNC (screen / mouse / keyboard for this plugin)
`RemoteDisplay.vnc.enabled = "TRUE"`, `RemoteDisplay.vnc.port = "5901"`. Password: set in Workstation (VM > Settings > Options > VNC Connections); older versions also accept `RemoteDisplay.vnc.password` in plain text, which the USER types. Optional keyboard map: `RemoteDisplay.vnc.keyMap = "pt"` (availability varies by version - test).

## Hardware version
`virtualHW.version` - raise with `vm_manage` `upgrade_hardware` only when needed; newer hardware versions do not open in older VMware releases.
