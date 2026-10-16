# Changelog

## 0.4.0 - 2026-10-15
- New `vm_create`: creates a powered-off VM on Workstation - folder, growable disk (`vmware-vdiskmanager`), `.vmx` from a guest preset (XP to Server 2025: guestOS id, IDE disk + in-box PCnet NIC for XP/2003, SATA + e1000/e1000e for Vista and later), optional install ISO, network (NAT / bridged / host-only / VMnetX / none) and VMware VNC already on 127.0.0.1 with a random password. Never overwrites an existing folder; logged in `changes.log`.
- VMs created by the plugin are listed by `vm_list` even before VMware adds them to its library.
- Guest commands/files/processes check VMware Tools first and fail with a clear message, instead of opening the credential dialog for nothing when Tools are not running.
- `vm_manage delete_vm` also removes the plugin's own `.vmx` backups, the folder when empty, and the VM's saved state (VMware's `deleteVM` leaves them).
- `vm_manage delete_vm` explains when a powered-off VM is still locked by an open VMware Workstation tab (nothing deleted).
- Tested: `vm_create` XP preset on Workstation 17.5 (IDE disk, CD boot, NAT); XP SP1 setup driven through VNC without VMware Tools (text-mode setup, keys, clicks, combo boxes, typing).
## 0.3.2 - 2026-10-15
- Refuse symbols in `vm_type` when the guest keyboard layout is unknown (letters/digits/space/Enter still allowed).
- `vm_power start` waits for a VM that is still powering off; warns if the VM does not appear as running.
- Skill rule: never type before a screenshot confirms the target window is focused.
- Tested on Windows Server 2008 R2.

## 0.3.1 - 2026-10-15
- Keyboard layout detection follows `HKCU\Keyboard Layout\Substitutes` (ABNT2 is stored as `d0010416` -> `00010416`), with language-id fallback.

## 0.3.0 - 2026-10-15
- Zero-config: VMs discovered from VMware's inventory / recent list by name.
- `vm_prepare`: VNC bound to 127.0.0.1, free port, random password; Tools check; guest login via native Windows credential dialog stored in Credential Manager; layout detection.
- `vm_credentials` (status / set / forget); wrong login detected and removed automatically.
- Layout-aware typing (US, ABNT2 with Shift/AltGr/dead keys, Alt+code fallback).
- Secrets masked in `changes.log`; unique backup names.

## 0.2.x - 2026-10-15
- 0.2.2: Windows launcher copies the server out of `%APPDATA%\Claude` (isolated Python builds cannot read it).
- 0.2.1: Windows Server notes (2003-2025, Core, domain).
- 0.2.0: `vm_settings`, `vm_network`, `vm_device`, `vm_shared_folders`, `vm_variable`, `vm_guest_info`, `vm_manage`, `vm_host_network`; vmrun capability detection; `.vmx` encoding/line-ending preservation; change log.

## 0.1.0 - 2026-10-15
- First version: VNC screen/mouse/keyboard, vmrun power/snapshots/commands/files/processes.
