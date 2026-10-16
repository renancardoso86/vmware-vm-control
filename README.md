# vmware-vm-control

**Let Claude operate and configure VMware Workstation / Player virtual machines - any Windows from XP to 11 and Server 2003 to 2025 - from the host.**

Built for people who keep legacy engineering software alive in VMs (PLC / HMI / SCADA tools, old installers, licence dongles): Claude can see the VM screen, click, type in the right keyboard layout, run `cmd`/PowerShell, copy files, and change any VM setting - without installing anything modern inside the guest.

| | |
|---|---|
| Screen, mouse, keyboard | VMware's **embedded VNC** (works at boot, in the BIOS, on any guest OS) |
| Commands, files, processes | `vmrun` + VMware Tools (legacy Tools 10.0.12 for XP / 2003) |
| VM settings | any `.vmx` key, network adapters, devices, shared folders, snapshots, clones |
| Setup | **zero-config**: VMs found by name, VNC secured automatically (127.0.0.1 + random password), guest login typed by you in the **native Windows credential dialog** and kept in Windows Credential Manager |
| Dependencies | Python 3.6+ on the host, standard library only |

## Install

**Claude desktop app (Cowork / chat):** download `vmware-vm-control.plugin` from the [latest release](../../releases/latest), open it in Claude and press *Install*. Restart the Claude app after installing or updating.

**Claude Code:**

```
/plugin marketplace add renancardoso86/vmware-vm-control
/plugin install vmware-vm-control@vmware-vm-control
```

Then ask Claude: *"prepare the VM <name> and take a screenshot"*.

Full documentation, tool list, security notes and troubleshooting: [plugins/vmware-vm-control/README.md](plugins/vmware-vm-control/README.md).

## Tested

VMware Workstation 17.5 (vmrun 1.17), Windows 11 host:

| Guest | Result |
|---|---|
| Windows 7 SP1 Professional, ABNT2 keyboard | screen (incl. boot), click, keys, ABNT2 typing (AltGr, dead-key accents), cmd, PowerShell 2.0, file copy, credential dialog |
| Windows Server 2008 R2 Standard, US keyboard, 1920x1080 | automatic free VNC port, built-in Administrator (elevated), cmd, PowerShell + ServerManager, files, processes, network adapters, US typing with Alt-code accents |

Not yet tested on real hardware/software: VMware Player, Windows XP / Server 2003 guests, Linux and macOS hosts. Reports welcome in [issues](../../issues).

## Development

```
python -m unittest discover -s tests -v     # offline tests, no VMware needed
```

Repository layout: `.claude-plugin/marketplace.json` (install catalogue), `plugins/vmware-vm-control/` (the plugin), `tests/`, `docs/` (design notes, roadmap, project context).

## License

MIT - (c) 2026 Renan Cardoso - Dominio Automacao.
