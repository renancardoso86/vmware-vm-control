---
name: vm-configure
description: This skill should be used when the user asks to change or inspect any configuration of a VMware VM or of the Windows inside it - "add memory", "give it 2 CPUs", "map COM3 to the VM", "attach this ISO", "change the network to bridged / host-only / VMnet2", "share a folder", "set the IP of the guest", "enable RDP", "disable the firewall", "create a user", "change the computer name", "set the time zone", "install this program silently". It covers VMware Workstation / Player of any version and Windows guests from XP onward.
---

# Configuring a VM and its guest OS

Two layers exist. Identify which one the request touches before acting.

| Layer | Tools | Requires |
|---|---|---|
| **Virtual hardware / VMware options** (.vmx) | `vm_settings`, `vm_network`, `vm_device`, `vm_shared_folders`, `vm_vnc_configure`, `vm_manage`, `vm_host_network`, `vm_variable` | VM powered **off** for .vmx edits; live device changes with the VM on |
| **Guest operating system** (Windows settings) | `vm_run` (cmd / PowerShell), GUI via `vm_screenshot` + input tools | VMware Tools + guest credentials for `vm_run`; nothing for the GUI |

## Workflow

1. Run `vm_list` once; it reports the vmrun version, host type and number of commands this VMware installation supports. Every tool checks support before acting and explains the alternative when a command is missing - follow that alternative instead of guessing.
2. Read the current state first (`vm_settings` with `prefix`, `vm_network` list, `vm_guest_info`, or a read-only `vm_run` such as `ipconfig /all`).
3. State the change you are about to make, then make it. For risky or broad changes, `vm_snapshot` create first (Workstation/Fusion).
4. Verify (read again, or screenshot) and report old -> new values. All changes are written to `changes.log` next to the config file; .vmx edits keep a timestamped backup.

## Rules

- Edit the .vmx only with the VM powered off (`vm_settings` refuses otherwise). Use `vm_device` for live connect/disconnect.
- Never put passwords in tool arguments on the user's behalf (guest accounts, VNC, BIOS, encryption). If a change needs a password, prepare everything and ask the user to type it.
- Pick commands that exist in the guest's Windows version - see `references/guest-recipes.md` (XP-compatible first, newer alternatives after).
- Ask before: deleting VMs, snapshots or files; changing the network of a VM attached to a production network; disabling security features; changing accounts.

## References

- `references/vmx-recipes.md` - common .vmx keys (memory, CPU, serial/COM, ISO, USB, network, boot, display, VNC, time sync).
- `references/guest-recipes.md` - Windows settings by version: IP, DNS, firewall, RDP, users, services, registry, time zone, computer name, silent installs, power.
