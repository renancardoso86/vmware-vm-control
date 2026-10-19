# vmware-vm-control

Let Claude operate **VMware Workstation** and **VMware Player** virtual machines from the host: see the screen, click, type, press keys, run `cmd`/PowerShell scripts, copy files, manage processes, power and snapshots.

**Host: Windows.** The plugin is built and tested on Windows hosts (Windows 11). Linux and macOS hosts need a manual change to `.mcp.json` (see [Non-Windows hosts](#non-windows-hosts)) and have not been tested.

Install from this repository's marketplace:

```
/plugin install vmware-vm-control --marketplace renancardoso86/vmware-vm-control
```

In the Claude desktop app: Settings > Plugins > Add > Add marketplace > Add from a repository, enter `renancardoso86/vmware-vm-control`, then add **vmware-vm-control**.

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
| Host | Windows, Linux or macOS with any VMware Workstation, Player or Fusion release that ships `vmrun` (or the VIX API); Windows: nothing else - the release package bundles Python; marketplace / Claude Code installs use an installed Python 3.6+ or download the official embeddable Python on first start. Linux / macOS: Python 3.6+. No extra Python packages. |
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

1. Install the plugin. On Windows nothing else is needed: the release package bundles Python, and a marketplace install with no Python on the PC downloads the official embeddable Python on first start (Linux / macOS: Python 3.6+).
2. Ask Claude to prepare a VM by its VMware name, e.g. *"prepare the VM Win7 Lab"*. Claude calls `vm_prepare`, which:
   - finds the VM in VMware's library / recent list (no registration);
   - enables VMware's embedded VNC **bound to 127.0.0.1** with a **random password** written to the .vmx (VM must be off, or Claude asks you before a restart);
   - checks VMware Tools;
   - shows the **native Windows credential dialog** for the VM's Windows login; it is stored encrypted in the **Windows Credential Manager** (target `vmware-vm-control:<vmx path>`), never in plain text and never in the chat;
   - detects the guest keyboard layout so typed text comes out right.
3. Done. Remove a stored login any time with `vm_credentials` (`forget`) or in Windows *Credential Manager*.

### Example prompts

- *"List my VMware VMs."* - `vm_list`: VMs from the library and recent list, which are running, VNC ports.
- *"Prepare the VM Win7 Lab and take a screenshot."* - `vm_prepare` (secure VNC, Tools check, login dialog, keyboard layout), then `vm_screenshot`.
- *"In the VM Win7 Lab, open Notepad and type 'test ç ã'."* - `vm_key` (Win+R), `vm_type` in the guest keyboard layout, `vm_screenshot` to check.
- *"Run ipconfig /all in the VM and tell me its IP address."* - `vm_run` (cmd) through VMware Tools.
- *"Copy C:\\temp\\setup.exe to the VM's desktop and take a snapshot called before-install."* - `vm_copy`, `vm_snapshot`.
- *"Give the VM 4 GB of memory and 2 CPUs."* - `vm_settings` (asks before powering the VM off).

Testing needs VMware Workstation or Player on the host and a VM; there is no hosted test account, because everything runs on the user's PC.

### Optional overrides

`%USERPROFILE%\.vmware-vm-control\config.json` is optional: `vmrun_path`, `host_type`, and per-VM entries (`vmx`, `guest_user`, `guest_password_env`, `vnc_port`, `vnc_password`, `guest_temp`, `guest_cmd`). On Linux/macOS hosts (no credential dialog) use `guest_password_env`. Other files in that folder: `state.json` (remembered keyboard layouts), `changes.log` (every change made), `server\` (runtime copy of the server).

## Security

- `vm_prepare` binds VMware's VNC to 127.0.0.1 (`RemoteDisplay.vnc.ip`), so other machines cannot reach it, and sets a random 8-character password. If you enable VNC by hand in VMware's dialog it listens on **all** interfaces - prefer `vm_prepare`.
- `vmrun` receives the guest password on its command line (visible to local process listings on the host).
- Guest logins live in the Windows Credential Manager (DPAPI-encrypted per user). The optional config file should not hold passwords.

## Data and network

What leaves the PC:

- **Python download (only when needed).** If the plugin finds no Python it can use (none bundled, none downloaded earlier, no installed `py` / `python`), `get-python.ps1` downloads the official embeddable Python once from `https://www.python.org/ftp/python/<version>/` into `%USERPROFILE%\.vmware-vm-control\python`. The version and SHA-256 are pinned in `server/python-embed.txt`; a file with another hash is refused, and `python.exe` must carry a valid Authenticode signature of the Python Software Foundation. Nothing else is downloaded, and nothing is installed system-wide.
- **Tool results go to Claude.** Like any MCP server, the plugin returns its results (VM screenshots, command output, file and process lists, .vmx settings) to the Claude conversation that called the tool. The stored guest password and the VNC password are not returned (`.vmx` secrets show as `<hidden>`).

No other network traffic: the server sends no telemetry and contacts no other service. VNC connections go to the VM's embedded VNC server on `127.0.0.1` (configurable with `vnc_host` in the optional config); `vmrun` runs locally.

What stays on the PC:

- Guest logins: Windows Credential Manager, target `vmware-vm-control:<vmx path>` (DPAPI-encrypted, per Windows user).
- VNC password and port: in the VM's `.vmx` (VMware's own setting).
- `%USERPROFILE%\.vmware-vm-control\`: `server\` (runtime copy of the server files), `python\` (downloaded Python, if any), `state.json` (keyboard layouts), `changes.log` (every change made; `.vmx` password values are hidden, while the first line of each guest script and guest variable values are logged as given), optional `config.json`.
- Timestamped `.vmx` backups next to each VM before every edit.

The plugin does not change Windows settings, permissions or Claude settings. Delete `%USERPROFILE%\.vmware-vm-control` and the `vmware-vm-control:` entries in Credential Manager to remove everything it stored.

## Reporting security issues

Report vulnerabilities privately through GitHub's *Report a vulnerability* (repository > Security), or open an issue without exploit details and ask for a private contact: https://github.com/renancardoso86/vmware-vm-control/issues. Reports are acknowledged and investigated; fixes ship as a new release.

## How it starts (Windows)

`.mcp.json` runs `server\launch.cmd`, which copies the server files (`*.py`) to `%USERPROFILE%\.vmware-vm-control\server` and starts them with the Python bundled in the package (`python\python.exe`, the official embeddable build), or the one downloaded earlier into `%USERPROFILE%\.vmware-vm-control\python`, or else an installed `py -3` / `python` (the Microsoft Store alias is skipped). With none of them, `get-python.ps1` downloads the official embeddable Python from python.org once (version and SHA-256 pinned in `python-embed.txt`, `python.exe` signature checked: Python Software Foundation); this first start took 8 to 21 s in tests and needs internet access to python.org. The copy is needed because Python builds that run isolated (Microsoft Store, Python Install Manager) cannot read files inside `%APPDATA%\Claude`, where plugins are installed. `vm_list` shows the plugin version and which Python is in use.

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

- Typing through VNC knows the guest keyboard layout: US, US-International, Portuguese (Brazil ABNT/ABNT2), Portuguese (Portugal), Spanish, German; other layouts fall back to Alt codes for symbols.
- VMware Player: no snapshots, and **no embedded VNC server** (Player 17.5 reads the `RemoteDisplay.vnc.*` keys but never opens the port), so no mouse/keyboard. On Player the screen is view-only through `vmrun captureScreen` (needs VMware Tools and the stored guest login); commands, files, processes and power work normally. Open the VM in Workstation for full control.
- Keyboard: `vm_type` has full tables for US and Brazilian ABNT/ABNT2 (auto-detected from the guest registry); other layouts fall back to Alt+0NNN codes (Num Lock on). Tested: uppercase, symbols, AltGr symbols, dead-key accents on an ABNT2 Windows 7 guest.
- After installing a new plugin version, restart the Claude desktop app so the new server and tool list are loaded.
- PowerShell exists only on Windows 7 / 2008 R2+ (or XP/2003 with PowerShell 2.0 installed); use `shell: "cmd"` otherwise.
