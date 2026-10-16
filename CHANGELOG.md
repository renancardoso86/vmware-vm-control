# Changelog

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
