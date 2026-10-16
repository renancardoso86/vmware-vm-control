# vmware-vm-control - project context (for Claude)

Upload this file to the Claude project "vmware-vm-control". It is the hand-off of everything decided and learned so far, so a new conversation can continue without re-discovery.

## Goal

A plugin that lets Claude operate and configure **any VMware Workstation / Player VM, any Windows guest from XP onward (incl. Server 2003-2025)**, usable by any professional - not tied to one VMware version, one VMware Tools version or one machine. Owner: Renan Cardoso - Dominio Automacao. Licence MIT. Public repo: `github.com/renancardoso86/vmware-vm-control`.

## Decisions (with the reason)

| Decision | Why |
|---|---|
| Everything runs on the **host**; nothing modern inside the guest | Windows-MCP / Node / Python 3.13 do not run on XP/7; compatibility mode by design |
| Screen/mouse/keyboard via **VMware's embedded VNC** (`RemoteDisplay.vnc.*`) | Works for any guest OS, at boot and in the BIOS, without guest software; does not occupy the user's screen (RDP + desktop computer-use did) |
| Commands/files via **vmrun** guest operations | Present in every Workstation/Player/Fusion; only needs VMware Tools |
| **Capability detection** by parsing `vmrun` help | Commands differ between versions (e.g. network-adapter commands removed in 17) |
| **Zero-config** (`vm_prepare`) | User feedback: the first versions required editing JSON and VMware dialogs - impractical for other users |
| VNC bound to **127.0.0.1** + **random password** written as `RemoteDisplay.vnc.password` | Tested on WS 17.5: VMware's default listens on 0.0.0.0 with no password; `.ip` binding and plain-text password key both work (VMware later adds an encrypted `.key` too) |
| Guest login typed by the user in **CredUIPromptForCredentialsW**, stored in **Windows Credential Manager** | Claude must never type or see passwords; no plain-text files |
| **Layout-aware typing** (US, ABNT2 tables; Alt+0NNN fallback) | VMware VNC maps keysyms to US scan codes and never adds Shift |
| Pure Python 3.6+ stdlib, own RFB client and DES | Installable by anyone; no pip |
| `launch.cmd` copies server to `%USERPROFILE%\.vmware-vm-control\server` | Python from Microsoft Store / Python Install Manager is sandboxed and cannot read `%APPDATA%\Claude` |
| Every change logged (`changes.log`, secrets masked) + timestamped `.vmx` backups | Traceability on customer/engineering VMs |
| Text in English (plugin, README); conversation with Renan in Portuguese | Distribution to any professional |
| `vm_create` (0.4.0) writes the `.vmx` itself + `vmware-vdiskmanager` disk, guest presets XP-2025 | Creating test VMs without the VMware wizard; XP/2003 get IDE disk + default PCnet NIC (in-box drivers), Vista+ SATA + e1000/e1000e; Windows 11 left to the wizard (TPM + encryption) |
| Hardware version: only verified mappings (`vmrun 1.17` -> 20), else highest among existing VMs, else ask | Never guess; hw 20 also opens on Workstation 17.0 (Renan's existing VMs use 21) |
| Guest operations check VMware Tools before asking for the login | Without Tools the credential dialog appeared for nothing (found in the XP test) |

## Architecture

```
Claude Desktop -> plugin .mcp.json -> cmd /c launch.cmd -> py -3 vm_control.py  (stdio JSON-RPC, MCP)
vm_control.py : tools, discovery (inventory.vmls / preferences.ini), vmrun wrapper, .vmx editing, state.json
vnc_client.py : RFB 3.3/3.7/3.8, VNC auth, Raw + DesktopSize, PNG encoder, pointer/key events
vnc_des.py    : DES for VNC auth
keyboard.py   : layout tables -> key events
creds.py      : CredUI prompt + CredRead/Write/Delete (ctypes)
```

User data: `%USERPROFILE%\.vmware-vm-control\` -> `server\` (runtime copy), `state.json` (layout per VM), `changes.log`, optional `config.json`.

## Test matrix (real hardware, 2026-10-15)

Host: Windows 11, VMware Workstation 17.5 (vmrun 1.17.0 build-23298084), Python 3.14 (Python Install Manager).

| Guest | Passed | Notes |
|---|---|---|
| Win 7 SP1 Pro (ABNT2, Tools 12, VMnet2 host-only) | VNC screen incl. boot, click, keys, ABNT2 typing, cmd, PS 2.0, copy, Tools/IP, credential dialog | first layout detection missed the `d0010416` substitute -> fixed 0.3.1 |
| Win XP Pro SP1 (setup only, no VMware Tools) - 2026-10-16, plugin 0.4.0 test build | `vm_create` XP preset (IDE disk seen as "atapi", CD boot, NAT, VNC 127.0.0.1:5903 auto-picked); VNC from first boot second incl. text-mode setup; keys (Enter, F8, arrows with repeat), clicks on lists/tabs/combos, typing; regional = Portuguese (Brazil) + ABNT2 set in setup; `vm_guest_info` / `vm_prepare` without Tools | stopped at product key (no XP licence); `vm_run` not run (would have opened the credential dialog -> fixed); `deleteVM` refused while the VM tab was open in Workstation -> clear message + cleanup of plugin backups added |
| Win Server 2008 R2 Std - 0.4.3 test build 2026-10-16 | PowerShell 2.0 output with accents intact (UTF-8); cmd on cp437: ç é ü intact, `ã` -> `?` (not in 437); a 60 s command answered at 30 s and kept running in the guest (output file complete afterwards); credential dialog came to the front and was typed by Renan; install_tools answered within 40 s with instructions | - |
| Win Server 2019 Std Evaluation (Desktop Experience) created by `vm_create` preset 2019 - 2026-10-16, plugin 0.4.2 | Setup saw the SATA disk (adapter lsilogic on sata0:0) and the e1000e NIC (Intel 82574L, DHCP over NAT) without drivers; whole install through VNC (edition, licence, disk, Administrator password, Ctrl+Alt+Del, logon); region zoom read the progress; Tools installed; vm_run PowerShell 5.1 elevated (High Mandatory Level); copy, processes; layout detected "us" | credential dialog opened behind other windows; accents lost (cmd cp437 / PowerShell console encoding); first PowerShell run > 60 s; install_tools > 60 s (vmrun waits for an installer Server does not autostart) -> 0.4.3 |
| Win Server 2008 R2 Std - 0.4.2 test build 2026-10-16 | `reset soft` answered in 40 s with "still in progress"; screenshot of a suspended VM explains it and how to resume | - |
| Win Server 2008 R2 Std on **VMware Player 17.5.1** (the vmplayer.exe shipped with Workstation) - 2026-10-16 | power start/stop, vm_run, vm_files, vm_processes, guest_info; snapshot refused with a clear message | **no VNC server on Player** (vmware.log: no "Started VNC server"; port closed) -> no mouse/keyboard; captureScreen fallback works with the stored login after the 0.4.2 fix; typeKeystrokesInGuest refused like on Workstation |
| Win Server 2008 R2 Std + linked clone - real-use round 2026-10-16 | two VMs at once on 5902/5903; VNC reconnects after a guest restart (640x480 during boot -> 1920x1080) and after suspend/resume; captureScreen fallback with VNC off (stored login) | `reset soft` blocked > 60 s waiting for the guest; suspended VM gave a generic VNC error -> 0.4.2 |
| Win Server 2008 R2 Std - 0.4.1 fixes 2026-10-16 (test build) | `vm_power start` with Workstation closed answered in seconds; `vm_guest_info wait` answered in 40 s; `vm_device` with `device_name` disconnect/reconnect (ping 0/6 -> 6/6); permission hints for NAT and Tools typing; region zoom 4x readable; linked clone got port 5903 + new password and appeared in `vm_list`; upgrade_hardware no-op message; vnc_configure off/on messages | first 0.4.1 build still froze: vmrun output read through a pipe kept open by the Workstation window -> output to temp file |
| Win Server 2008 R2 Std - tool sweep 2026-10-16, plugin 0.4.0 | snapshot list/create/revert/delete, guest_info, files mkdir/list/exists/rename, copy both ways (same hash), processes, variables (runtimeConfig/guestEnv/guestVar), shared folders read-only (write denied as expected), network/host-network list, VNC typing with all symbols, scroll, drag, move/hover, linked clone + delete, settings set, upgrade_hardware, vnc_configure off/on | `vm_device` lost its `device` parameter in the remote bridge; NAT `set_forward` and `vm_type method tools` refused (host rights, cause: a levantar); clone copied VNC port/password; region zoom shrank; stale vnc_configure messages -> all fixed in 0.4.1 |
| Win Server 2008 R2 Std (US, 1920x1080, not activated) | free port 5902 chosen, resolution change, built-in Administrator elevated, cmd, PS 2.0 + ServerManager, copy, processes, adapters, US typing + Alt codes | wrong password detected/removed; typing blind (Run dialog not open) caused a logoff -> 0.3.2 safeguards |

## Known issues / lessons

- After installing a new plugin version, Claude Desktop keeps the old server process and old tool list until the app is restarted.
- Activation / "not genuine" pop-ups steal focus right after logon on unactivated Windows: always screenshot before typing.
- `vm_power start` right after a shutdown may race; handled in 0.3.2 by waiting for the `.vmx.lck` folder to disappear.
- Alt+0NNN fallback needs Num Lock on in the guest (not yet verified on a guest with Num Lock off).
- Installing a test `.plugin` with the same name and version as the installed one is refused by the app ("A plugin named ... already exists"); test builds need a different version, or remove the installed plugin first (exact rule: a levantar).
- `vmrun deleteVM` fails with "Insufficient permissions" while the powered-off VM is still open in a Workstation tab (`.vmx.lck` kept); close the tab first.
- ISOs on the SharePoint/OneDrive sync folder may be cloud-only (attributes Offline + RecallOnDataAccess); copy them to a local folder before booting a VM from them.
- No legitimate public product key exists for Windows XP; XP tests beyond setup need a real licence.
- `vm_type` remembers the `layout` passed explicitly; after changing the guest layout, pass the new one or run `vm_prepare` with `redetect_layout` (needs Tools).
- Tool calls from a Claude cloud session go through a bridge to the PC that gives up after about 60 s; the plugin server answers one call at a time, so a long call delays the next ones. Keep every tool under ~40 s.
- Never read vmrun output through a pipe: `vmrun start` launches vmware.exe, which inherits the pipe and keeps it open until Workstation closes, freezing the (single-threaded) plugin server. Output goes to a temp file (0.4.1).
- A Claude cloud session keeps the tool descriptions it saw when it started; after a plugin update the new server runs, but new parameter names only show up in a new conversation (extra parameters are still passed through).
- The bridge drops a tool parameter called `device` (it uses that name itself); never name a parameter `device`.
- `vmrun setPortForwarding` and `typeKeystrokesInGuest` fail from the Claude app on Renan's PC ("Failed to set port forwarding", "Insufficient permissions in the host operating system"); likely needs administrator rights (a levantar).
- Copying the repo to OneDrive: use `git -c core.autocrlf=false archive` from the tag - a clone on Windows converts line endings and a robocopy also takes `__pycache__`.
- `vm_create` SATA presets verified on Server 2019 (2026-10-16): disk with adapter `lsilogic` on `sata0:0` works without drivers.
- The Claude app can run two instances of the plugin server at the same time (seen after reconnections); each keeps its own state in memory.
- Windows dialogs opened by the plugin server (credential prompt) appear behind the user's windows unless brought to the front (done in 0.4.3).
- Copying a 5.6 GB ISO from the SharePoint sync folder took about 10 minutes (~13 MB/s download).

## Backlog (next)

1. ~~Test on VMware Player~~ - done 2026-10-16: Player has no VNC; view-only + commands/files (0.4.2). Standalone Player install on another PC: a levantar.
2. Test on a **Windows XP / Server 2003** guest with legacy VMware Tools 10.0.12 - blocked: needs an XP/2003 licence (XP SP1 ISO exists in `Instaladores\ISO`; whether Tools 10.0.12 accepts SP1: a levantar).
3. ~~Test with VMware Tools missing~~ - done 2026-10-16 (XP setup, Tools precheck, captureScreen fallback with VNC off).
3a. ~~Test a `vm_create` SATA preset~~ - done 2026-10-16 with the Server 2019 evaluation ISO.
4. More keyboard layouts (US-International, Spanish, German, Portuguese-PT) - table + detection.
5. Linux / macOS host: `.mcp.json` variant or launcher that picks `python3`; credentials via keyring or env.
6. (done in repo) Release workflow builds `vmware-vm-control.plugin` on every `v*` tag.
7. Optional: `vm_wait_for` (wait until text/region changes or a process appears) to avoid fixed sleeps.
8. Optional: OCR-free screen diff to detect when a dialog opened.

## Source of truth and release flow

- **GitHub (`renancardoso86/vmware-vm-control`) is the source of truth.** The OneDrive folder `C:\Users\RenanCardoso\OneDrive\Documentos\Pessoal\Claude\vmware-vm-control` is a plain copy (no `.git`, never sync a `.git` folder through OneDrive).
- Cloud sessions can read the repo but cannot push to it. Changes are pushed **from Renan's PC** with his `gh`/`git` (already logged in as `renancardoso86`), only after he approves: clone or update a working copy in `%TEMP%`, apply changes, run the tests, commit, `git push`, then `git tag vX.Y.Z` + `git push origin vX.Y.Z`.
- A `v*` tag triggers the release workflow: tests run and `vmware-vm-control.plugin` is attached to the GitHub release automatically.
- **After every release, update the OneDrive copy** (whole repo tree without `.git`, plus `dist\vmware-vm-control-X.Y.Z.plugin`) so the folder always matches the latest release.
- Install/update on Renan's PC: install the new `.plugin`, then restart the Claude app (otherwise the old server and tool list stay loaded).

## Working rules for Claude in this project

- Talk to Renan in Portuguese; explain technical terms; he decides point by point - offer options, not closed recommendations.
- Ask before running anything on his PC, restarting VMs, deleting files or publishing.
- Never type, ask for or store passwords; use the credential dialog.
- Never fill gaps with estimates - write "a levantar".
- Report work in detail: what was recognised, analysed, changed and how it was verified.
- Bump the version in `plugin.json`, `marketplace.json`, `SERVER_VERSION` and `CHANGELOG.md` together; run `python -m unittest discover -s tests -v` before every release.
