# Troubleshooting vmware-vm-control

## VNC

| Symptom | Cause / fix |
|---|---|
| `Cannot connect to VNC 127.0.0.1:5901` | VM not running, or VNC not enabled. Check `RemoteDisplay.vnc.enabled = "TRUE"` and the port in the .vmx (`vm_vnc_configure` with the VM off), then start the VM. |
| `VNC server requires a password` / `authentication failed` | The password was set in VMware's dialog (stored as an encrypted key the plugin cannot read). Remove it there and run `vm_prepare` with the VM off, or put that password in `vnc_password` in the optional config. |
| Two VMs fight for one port | Each VM needs a unique port (5901-6001). |
| Black screenshot | Guest display is asleep or the screen saver is on: press `shift` with `vm_key`, then retake. |

## Keyboard layout

VMware's VNC server maps every key to the US key position and does not add Shift. `vm_type` compensates using the guest layout (auto-detected from the guest registry when Tools + login are available, otherwise pass `layout`). Supported tables: `us`, `abnt2` (Brazilian ABNT/ABNT2). Other characters are sent as Alt+0NNN (Windows ANSI), which needs Num Lock on in the guest. If text still comes out wrong, write it with `vm_run` (e.g. into a file or the registry) instead of typing.

## vmrun guest operations

| Symptom | Cause / fix |
|---|---|
| `The VMware Tools are not running in the virtual machine` | Install/start VMware Tools. Windows XP/2003/2000 need the legacy Tools 10.0.12 (`winPreVista.iso`, from VMware's legacy Tools download). |
| `Invalid user name or password for the guest OS` | The user must fix `guest_user` / `guest_password` in the config. Accounts with a blank password are refused by Windows for this kind of logon. |
| Command runs but the GUI program is invisible | Use `interactive: true` (and `no_wait: true`); the guest user must be logged on. |
| `The operation is not supported` on VMware Player | Snapshots and some operations are Workstation/Fusion only. |
| Commands run but fail with "Access is denied" on Vista / 7 / Server 2008 and newer | UAC gives vmrun a filtered (non-elevated) token for any admin account except the built-in Administrator. Use the built-in Administrator account in the config, or run the step through the GUI with "Run as administrator". |
| Server: logon refused for the guest account | Password expired or must be changed at next logon (common on new Server installs) - the user logs on once in the console and sets it. |
| Windows not on C: | Set `guest_cmd` (path to cmd.exe) and `guest_temp` for that VM in the config. |
