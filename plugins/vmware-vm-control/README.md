# vmware-vm-control

Let Claude operate **VMware Workstation** and **VMware Player** virtual machines from the host: see the screen, click, type, press keys, run `cmd`/PowerShell scripts, copy files, manage processes, power and snapshots.

**Compatibility mode by design:** nothing modern runs inside the guest. Screen, mouse and keyboard use the VNC server embedded in VMware itself, and commands/files use `vmrun` + VMware Tools. That makes it work with **any Windows guest from XP onward, including Windows Server 2003 to 2025 (Desktop Experience or Core)** (and most tools also with Linux guests).

## Version independence

The plugin does not target one VMware or VMware Tools release:

- At start-up it parses the help of the installed `vmrun` (any version) and builds the list of supported commands. Every tool checks that list first; when a command is missing it says so and uses or proposes an alternative (e.g. `captureScreen` when VNC is not set up, `typeKeystrokesInGuest` when VNC is unavailable, .vmx edits when the vmrun network-adapter commands do not exist).
- `.vmx` files are read and written in the encoding they declare (`.encoding`), so VMs created by old releases (windows-1252) are not corrupted; line endings are preserved and every edit keeps a timestamped backup.
- Guest commands only use operations available since early VMware Tools (copy file, run program, delete file), so any Tools version that supports guest operations works.
- Host: Windows, Linux (Workstation/Player) and macOS (Fusion) - same `vmrun` interface.
- All changes are recorded in `changes.log` next to the config file.

## Requirements

| Where | What |
|---|---|
| Host | Windows, Linux or macOS with any VMware Workstation, Player or Fusion release that ships `vmrun` (or the VIX API); Python 3.6+ with the `py` launcher (python.org installer). No extra Python packages. |
| Guest - screen/mouse/keyboard | Nothing. Only VNC enabled in the VM's settings. |
| Guest - commands/files/processes | VMware Tools. XP / 2003 / 2000: legacy **VMware Tools 10.0.12** (`winPreVista.iso`). Windows 7: SHA-2 updates KB4474419 + KB4490628 before Tools 11+. A guest account **with a password**. |

## Tools

| Tool | Purpose |
|---|---|
| `vm_prepare` | **Start here**: secure VNC, Tools check, guest login dialog, keyboard layout - one call |
| `vm_credentials` | Guest login status / set (Windows dialog) / forget |
| `vm_list`, `vm_setup_help`, `vm_config_init` | Discover VMs, show setup steps, create the optional config file |
| `vm_power`, `vm_snapshot` | start / stop / reset / suspend / pause; snapshots (not on Player) |
| `vm_screenshot` | PNG of the guest screen (optionally zoom into a region) |
| `vm_click`, `vm_move`, `vm_drag`, `vm_scroll`, `vm_type`, `vm_key` | Mouse and keyboard through VNC |
| `vm_run` | Run a cmd batch or PowerShell script in the guest, returns exit code and output |
| `vm_copy`, `vm_files`, `vm_processes` | Copy files, list/create/delete in the guest, list/kill processes |
| `vm_settings` | Read or change **any** .vmx setting (memory, CPU, serial/COM, ISO, USB, boot, display...) - VM off, backup + log |
| `vm_network` | List / set / remove network adapters (bridged, NAT, host-only, VMnetX, adapter model) |
| `vm_device` | Connect / disconnect a device while the VM runs (network, CD, serial, USB, sound) |
| `vm_shared_folders`, `vm_variable` | Shared folders; runtime config, guest environment and guest variables |
| `vm_guest_info`, `vm_manage`, `vm_host_network` | Tools state, IP, hardware version; install Tools, upgrade hardware, clone, delete (confirmed); NAT port forwarding |
| `vm_create` | Create a new powered-off VM (Workstation): disk, .vmx from a guest preset XP-2025, install ISO, network, secure VNC |
| `vm_vnc_configure` | Enable/disable VMware's VNC in a powered-off VM's .vmx (makes a backup) |

Guest OS settings (IP, firewall, RDP, users, services, registry, silent installs) go through `vm_run`; the **vm-configure** skill carries version-specific recipes from XP to 11.

## Getting started (no configuration file)

1. Install the plugin. Python 3.6+ must be installed on the host (python.org or Microsoft Store).
2. Ask Claude to prepare a VM by its VMware name, e.g. *"prepare the VM Win7 Lab"*. Claude calls `vm_prepare`, which:
   - finds the VM in VMware's library / recent list (no registration);
   - enables VMware's embedded VNC **bound to 127.0.0.1** with a **random password** written to the .vmx (VM must be off, or Claude asks you before a restart);
   - checks VMware Tools;
   - shows the **native Windows credential dialog** for the VM's Windows login; it is stored encrypted in the **Windows Credential Manager** (target `vmware-vm-control:<vmx path>`), never in plain text and never in the chat;
   - detects the guest keyboard layout so typed text comes out right.
3. Done. Remove a stored login any time with `vm_credentials` (`forget`) or in Windows *Credential Manager*.

### Optional overrides

`%USERPROFILE%\.vmware-vm-control\config.json` is optional: `vmrun_path`, `host_type`, and per-VM entries (`vmx`, `guest_user`, `guest_password_env`, `vnc_port`, `vnc_password`, `guest_temp`, `guest_cmd`). On Linux/macOS hosts (no credential dialog) use `guest_password_env`. Other files in that folder: `state.json` (remembered keyboard layouts), `changes.log` (every change made), `server\` (runtime copy of the server).

## Security

- `vm_prepare` binds VMware's VNC to 127.0.0.1 (`RemoteDisplay.vnc.ip`), so other machines cannot reach it, and sets a random 8-character password. If you enable VNC by hand in VMware's dialog it listens on **all** interfaces - prefer `vm_prepare`.
- `vmrun` receives the guest password on its command line (visible to local process listings on the host).
- Guest logins live in the Windows Credential Manager (DPAPI-encrypted per user). The optional config file should not hold passwords.

## How it starts (Windows)

`.mcp.json` runs `server\launch.cmd`, which copies the server files (`*.py`) to `%USERPROFILE%\.vmware-vm-control\server` and starts them with `py -3` (or `python`). The copy is needed because Python builds that run isolated (Microsoft Store, Python Install Manager) cannot read files inside `%APPDATA%\Claude`, where plugins are installed.

## Non-Windows hosts

Edit `.mcp.json`: `"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/server/vm_control.py"]`.

## Tested

VMware Workstation 17.5 (vmrun 1.17) on Windows 11:

| Guest | Tested |
|---|---|
| Windows 7 SP1 Professional (ABNT2, VMware Tools 12) | VNC screen (also during boot), click, keys, ABNT2 typing incl. AltGr and dead-key accents, cmd, PowerShell 2.0, file copy, Tools state, guest IP, credential dialog + Credential Manager |
| Windows Server 2008 R2 Standard (US layout, 1920x1080) | automatic free-port VNC (5902), resolution change during logon, built-in Administrator (elevated), cmd, PowerShell 2.0 + ServerManager, file copy, process list, network adapters + host networks, layout detection, US typing with Alt-code accents, wrong login detected and removed |

VNC bound to 127.0.0.1 with generated password (wrong/empty password refused) on both.

## Limitations

- VMware Player: no snapshots, and **no embedded VNC server** (Player 17.5 reads the `RemoteDisplay.vnc.*` keys but never opens the port), so no mouse/keyboard. On Player the screen is view-only through `vmrun captureScreen` (needs VMware Tools and the stored guest login); commands, files, processes and power work normally. Open the VM in Workstation for full control.
- Keyboard: `vm_type` has full tables for US and Brazilian ABNT/ABNT2 (auto-detected from the guest registry); other layouts fall back to Alt+0NNN codes (Num Lock on). Tested: uppercase, symbols, AltGr symbols, dead-key accents on an ABNT2 Windows 7 guest.
- After installing a new plugin version, restart the Claude desktop app so the new server and tool list are loaded.
- PowerShell exists only on Windows 7 / 2008 R2+ (or XP/2003 with PowerShell 2.0 installed); use `shell: "cmd"` otherwise.
