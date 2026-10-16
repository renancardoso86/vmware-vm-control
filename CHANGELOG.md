# Changelog

## 0.5.0 - 2026-10-16
- **No Python installation needed on Windows with the release package** (`vmware-vm-control.plugin`): it now bundles the official embeddable Python (3.14.8, Windows x64, signed by the Python Software Foundation, licence in `python/LICENSE.txt`). The release workflow downloads it from python.org, checks its SHA-256 and unpacks its standard library (`pythonXY.zip`) into `python/Lib`, because the Claude app refuses a `.plugin` that contains a zip file.
- `launch.cmd` uses the bundled Python first, then an installed `py`, then `python` - skipping the Microsoft Store `python` alias, which is not a real Python. Installs from the Git repository (marketplace, Claude Code) do not carry the bundled Python and keep needing an installed Python 3.6+.
- `vm_list` (and `--self-test`) start with the plugin version and the Python in use (bundled or installed), so the running version can be checked from Claude.

## 0.4.4 - 2026-10-16
- New keyboard layouts for typing through VNC: German (QWERTZ, 00000407), Spanish (0000040A), Portuguese - Portugal (00000816) and United States-International (00020409), with dead keys and AltGr; detected automatically from the guest registry. The extra ISO key left of Z (`< > |`) is typed with Alt codes.
- Tested on Windows Server 2008 R2: each layout typed a sample with every special character of the language into Notepad and the result matched exactly.
- `state.json` is read even when saved with a BOM (Notepad / PowerShell 5).

## 0.4.3 - 2026-10-16
Fixes from the Windows Server 2019 (SATA preset) test:
- The credential dialog is brought to the foreground - it opened behind the user's windows, so nobody saw it.
- `vm_run` keeps accents: cmd scripts are written and read in the guest's console code page (probed once with `chcp` and remembered: 437 on English Windows, 850 on Portuguese...); PowerShell answers in UTF-8. Characters the code page lacks (e.g. `ã` in 437) come back as `?` in cmd - use PowerShell for such text.
- `vm_run` answers within ~30 s: a longer command keeps running in the guest and the reply says where its output is being written.
- `vm_manage install_tools` answers within 40 s (vmrun waited for an installer that Windows Server does not start by itself) and says how to run it.
- Tested: `vm_create` preset 2019 on Workstation 17.5 - SATA disk and e1000e seen by Windows Setup without drivers; full install through VNC; Tools; PowerShell 5.1; elevated built-in Administrator.

## 0.4.2 - 2026-10-16
- VMware Player: detected and explained - Player never starts the embedded VNC server, so mouse/keyboard tools say so clearly; `vm_screenshot` falls back to `vmrun captureScreen` and `vm_prepare` reports the limitation.
- `vm_screenshot` fallback to `captureScreen` also works with the login stored in Credential Manager (it used to require a config file).
- All `vm_power` actions answer within 40 s (a soft stop/reset waits for the guest and used to exceed the ~60 s limit of remote callers).
- `vm_screenshot` on a suspended or powered-off VM says so and how to resume/start it.
- Tested: two VMs at once (VNC 5902 + 5903), VNC reconnects after a guest restart and after suspend/resume, captureScreen fallback with VNC off.

## 0.4.1 - 2026-10-16
Fixes from the test round on Workstation 17.5 / Windows Server 2008 R2:
- `vm_device`: parameter renamed to `device_name` - remote callers (Claude cloud sessions linked to the PC) drop a parameter called `device`.
- `vm_manage clone`: the clone gets its own free VNC port and a new random password (it used to copy the source's port and password) and is listed by `vm_list`.
- `vm_screenshot` with `region` really zooms (at least 1:1, up to 4x); it used to shrink the region with the full-screen scale.
- `vm_vnc_configure`: shows the real port, keeps the current port (or picks a free one instead of 5901), and no longer tells the user to set a password by hand.
- `vm_manage upgrade_hardware` says when nothing changed (already at the highest version).
- vmrun output goes to a temp file instead of a pipe: `vmrun start` opens the Workstation window, which inherited the pipe and kept every later tool call waiting until Workstation was closed (root cause of the time-outs).
- `vm_power start` and `vm_guest_info wait` answer within 40 s (remote callers give up after about 60 s and queue the next calls).
- Clear hints when VMware refuses an operation for lack of host rights (NAT port forwarding, typing through Tools).
- `delete_vm` cleanup no longer reports an error when VMware already removed the folder.

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
