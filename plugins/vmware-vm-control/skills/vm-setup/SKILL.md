---
name: vm-setup
description: This skill should be used when the user wants to "set up a VM for Claude", "let Claude control my VMware VM", "prepare this VM", or when a vmware-vm-control tool reports that VNC, VMware Tools or the guest login is missing. It prepares any VMware Workstation / Player VM (Windows XP onward) with a single vm_prepare call.
---

# Preparing a VM (one call)

No configuration file is needed. VMs are discovered from VMware's own library / recent list, by name.

1. Call `vm_list` and pick the VM by its VMware name (a unique part of the name is enough).
2. Call `vm_prepare` with that name. It:
   - enables VMware's embedded VNC bound to **127.0.0.1** on a free port with a **random password** stored in the .vmx (nobody types it);
   - checks VMware Tools;
   - opens the **native Windows credential dialog** on the user's screen for the guest Windows login, stored encrypted in the Windows Credential Manager (Claude never sees it);
   - detects and remembers the guest keyboard layout.
3. If the VM is running and VNC is not yet configured, VMware applies it only at power-on: tell the user, ask permission, then call `vm_prepare` again with `restart_ok: true` (soft shutdown + start). Never restart without asking - the VM may hold unsaved work.
4. Before calling `vm_prepare` with credentials missing, tell the user in one sentence that a Windows login window for the VM will appear and they should type the VM's Windows user and password there.
5. Report what is ready (screen/mouse/keyboard, commands/files, layout) and what is missing.

## Creating a new VM

When the user wants a new VM, agree with them on name, guest preset, install ISO, parent folder, memory, disk size and network, then call `vm_create` (VMware Workstation; Player has no `vmware-vdiskmanager`). It never overwrites an existing folder and leaves the VM powered off with VNC already secured, so no `vm_prepare` restart is needed. Ask before `vm_power start`; follow the installer with `vm_screenshot`. The user types product keys and passwords themselves. VMware Tools are installed after the guest OS (XP / 2003: legacy 10.0.12).

## When something is missing

- **VMware Tools not running**: screen, mouse and keyboard still work. For commands/files: `vm_manage` `install_tools`, then finish the installer through the GUI. XP / 2003 / 2000 need the legacy Tools 10.0.12 (`winPreVista.iso`); Windows 7 needs KB4474419 + KB4490628 before Tools 11+.
- **Guest login rejected**: the plugin removes it automatically; call `vm_credentials` `set` to show the dialog again.
- **Built-in Administrator**: on Vista / 7 / Server 2008 and newer, admin tasks through VMware Tools need the built-in Administrator account (UAC filters other admins).
- **Non-Windows host**: no credential dialog; the user sets `guest_password_env` (name of an environment variable) in the optional config file (see README).

## Optional config file

`%USERPROFILE%\.vmware-vm-control\config.json` only overrides automatic behaviour (vmrun path, host type, per-VM `guest_temp`, `guest_cmd`, `vnc_port`). It is never required.
