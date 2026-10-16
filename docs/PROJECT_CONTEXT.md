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
| Win Server 2008 R2 Std (US, 1920x1080, not activated) | free port 5902 chosen, resolution change, built-in Administrator elevated, cmd, PS 2.0 + ServerManager, copy, processes, adapters, US typing + Alt codes | wrong password detected/removed; typing blind (Run dialog not open) caused a logoff -> 0.3.2 safeguards |

## Known issues / lessons

- After installing a new plugin version, Claude Desktop keeps the old server process and old tool list until the app is restarted.
- Activation / "not genuine" pop-ups steal focus right after logon on unactivated Windows: always screenshot before typing.
- `vm_power start` right after a shutdown may race; handled in 0.3.2 by waiting for the `.vmx.lck` folder to disappear.
- Alt+0NNN fallback needs Num Lock on in the guest (not yet verified on a guest with Num Lock off).

## Backlog (next)

1. Test on **VMware Player** (no snapshots; check guest operations and VNC via `.vmx`).
2. Test on a **Windows XP / Server 2003** guest with legacy VMware Tools 10.0.12.
3. Test with VMware Tools **missing** (VNC-only mode, `captureScreen` fallback).
4. More keyboard layouts (US-International, Spanish, German, Portuguese-PT) - table + detection.
5. Linux / macOS host: `.mcp.json` variant or launcher that picks `python3`; credentials via keyring or env.
6. (done in repo) Release workflow builds `vmware-vm-control.plugin` on every `v*` tag.
7. Optional: `vm_wait_for` (wait until text/region changes or a process appears) to avoid fixed sleeps.
8. Optional: OCR-free screen diff to detect when a dialog opened.

## Working rules for Claude in this project

- Talk to Renan in Portuguese; explain technical terms; he decides point by point - offer options, not closed recommendations.
- Ask before running anything on his PC, restarting VMs, deleting files or publishing.
- Never type, ask for or store passwords; use the credential dialog.
- Never fill gaps with estimates - write "a levantar".
- Report work in detail: what was recognised, analysed, changed and how it was verified.
- Bump the version in `plugin.json`, `marketplace.json`, `SERVER_VERSION` and `CHANGELOG.md` together; run `python -m unittest discover -s tests -v` before every release.
