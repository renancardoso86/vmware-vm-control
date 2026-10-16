# Guest Windows recipes (XP -> 11)

Run with `vm_run`. Use `shell: "cmd"` unless noted; PowerShell exists on Windows 7 / Server 2008 R2 and newer (XP/2003 only if PowerShell 2.0 was installed). Check the version first with `ver`.

## Identify the guest
```
ver
systeminfo | findstr /B /C:"OS Name" /C:"OS Version" /C:"System Type"
```

## Network
| Goal | XP / 2003 / Vista+ (cmd) | Win8 / 2012+ (PowerShell alternative) |
|---|---|---|
| Show config | `ipconfig /all` | `Get-NetIPConfiguration` |
| List adapter names | `netsh interface ip show config` | `Get-NetAdapter` |
| Static IP | `netsh interface ip set address name="Local Area Connection" static 192.168.1.50 255.255.255.0 192.168.1.1` | `New-NetIPAddress -InterfaceAlias Ethernet0 -IPAddress 192.168.1.50 -PrefixLength 24 -DefaultGateway 192.168.1.1` |
| DHCP | `netsh interface ip set address name="Local Area Connection" dhcp` | `Set-NetIPInterface -InterfaceAlias Ethernet0 -Dhcp Enabled` |
| DNS | `netsh interface ip set dns name="Local Area Connection" static 8.8.8.8` | `Set-DnsClientServerAddress -InterfaceAlias Ethernet0 -ServerAddresses 8.8.8.8` |
| Ping test | `ping -n 2 192.168.1.1` | `Test-Connection 192.168.1.1 -Count 2` |
Adapter names are localized (e.g. "Conexão local" in Portuguese) - list them first.

## Firewall
| Goal | XP SP2 / 2003 | Vista / 7 and newer |
|---|---|---|
| State | `netsh firewall show state` | `netsh advfirewall show allprofiles` |
| Disable (ask first) | `netsh firewall set opmode disable` | `netsh advfirewall set allprofiles state off` |
| Open a port | `netsh firewall add portopening TCP 502 Modbus` | `netsh advfirewall firewall add rule name="Modbus" dir=in action=allow protocol=TCP localport=502` |

## Remote Desktop
```
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 0 /f
```
Then open TCP 3389 in the firewall (above). XP Home has no RDP server.

## Accounts (passwords are typed by the user, never by Claude)
| Goal | Command |
|---|---|
| List users | `net user` |
| Create user (user then sets the password interactively) | `net user tecnico /add` then ask the user to run `net user tecnico *` in the VM |
| Add to Administrators | `net localgroup Administrators tecnico /add` (localized group name, e.g. `Administradores`) |

## Services and processes
| Goal | Command |
|---|---|
| List | `sc query state= all` / `tasklist` |
| Start / stop | `net start "Name"` / `net stop "Name"` |
| Startup type | `sc config "Name" start= auto` (`demand`, `disabled`) - the space after `start=` is required |

## Registry
`reg query`, `reg add ... /f`, `reg delete ... /f`, `reg export HKLM\Software\Vendor C:\backup.reg` (export before changing).

## System
| Goal | Command |
|---|---|
| Computer name | `wmic computersystem where name="%COMPUTERNAME%" call rename name="NEWNAME"` (XP+), then reboot |
| Time zone | XP: `control.exe timedate.cpl,,/Z E. South America Standard Time`; Win7+: `tzutil /s "E. South America Standard Time"` |
| Reboot / shutdown | `shutdown -r -t 0` / `shutdown -s -t 0` (prefer `vm_power` from the host) |
| Power plan never sleep | Vista+: `powercfg -change -standby-timeout-ac 0`; XP: `powercfg /change "Always On" /standby-timeout-ac 0` |
| Installed programs | `wmic product get name,version` (slow) or `reg query HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall /s /v DisplayName` |

## Silent installs
Copy the installer with `vm_copy` to `C:\Windows\Temp`, then:
| Installer | Switches |
|---|---|
| MSI | `msiexec /i "C:\Windows\Temp\x.msi" /qn /norestart /l*v "C:\Windows\Temp\x.log"` |
| InstallShield (setup.exe) | `setup.exe /s /v"/qn"` (record a response file with `/r` if needed) |
| Inno Setup | `setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` |
| NSIS | `setup.exe /S` |
Old engineering software often needs "Run as administrator" and a GUI wizard - fall back to the GUI tools when silent switches fail, and read the installer log.

## Running GUI programs
`vm_run` with `interactive: true, no_wait: true` and a command like `start "" "C:\Program Files\App\app.exe"`, then `vm_screenshot`. Programs needing elevation will show UAC on Vista+; the user may have to confirm, or the guest account must be the built-in Administrator.

## Windows Server notes (2003 -> 2025)
| Version | Notes |
|---|---|
| Server 2003 / 2003 R2 | Like XP: legacy VMware Tools 10.0.12, `netsh firewall`, no PowerShell unless 2.0 was installed. |
| Server 2008 | PowerShell 1.0 is an optional feature (`servermanagercmd -install PowerShell`); `netsh advfirewall`. |
| Server 2008 R2 | PowerShell 2.0 built in; needs SHA-2 updates KB4474419 + KB4490628 before VMware Tools 11+. |
| Server 2012 -> 2025 | Full PowerShell; `Install-WindowsFeature` / `Get-WindowsFeature` for roles. |
| Server Core (any) | No desktop: prefer `vm_run`; the console shows `sconfig` / cmd, which still works through VNC. |
| Domain members / DCs | Guest user may be `DOMAIN\user`; local groups are unavailable on domain controllers. |

Roles and features: 2008/2008 R2 `servermanagercmd -query` / `Add-WindowsFeature`; 2012+ `Install-WindowsFeature <Name> -IncludeManagementTools`.
