#!/usr/bin/env python3
"""vmware-vm-control - MCP server (stdio) to operate VMware Workstation / Player VMs.

Everything runs on the HOST. Nothing modern has to run inside the guest, so it
works with any Windows guest from XP onward (and Linux guests for most tools):

* Screen, mouse and keyboard: the VNC server embedded in VMware
  (RemoteDisplay.vnc.*), spoken to by a tiny built-in RFB client.
* Commands, files and processes: `vmrun` guest operations (need VMware Tools
  in the guest; Windows XP/2003 need the legacy Tools 10.0.12).
* Power and snapshots: `vmrun` (snapshots are not available on VMware Player).

Standard library only (Python 3.6+). Configuration: see README.md.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnc_client import VNCClient, VNCError  # noqa: E402
import creds  # noqa: E402
import keyboard  # noqa: E402
import secrets  # noqa: E402
import socket  # noqa: E402
import string  # noqa: E402

SERVER_NAME = 'vmware-vm-control'
SERVER_VERSION = '0.3.2'
IS_WIN = os.name == 'nt'


# ======================================================================== config
def config_path():
    p = os.environ.get('VMCTL_CONFIG')
    if p:
        return os.path.expanduser(p)
    return os.path.join(os.path.expanduser('~'), '.vmware-vm-control', 'config.json')


EXAMPLE_CONFIG = {
    "vmrun_path": "",
    "host_type": "",
    "vms": {
        "example-xp": {
            "vmx": "C:\\VMs\\WinXP\\WinXP.vmx",
            "guest_user": "Administrator",
            "guest_password": "",
            "guest_password_env": "",
            "vnc_host": "127.0.0.1",
            "vnc_port": 5901,
            "vnc_password": "",
            "guest_temp": "C:\\Windows\\Temp",
            "notes": "Fill in guest_password (or guest_password_env) and vnc_password yourself."
        }
    }
}


def load_config():
    p = config_path()
    if not os.path.exists(p):
        return {'vms': {}}, p
    with open(p, 'r', encoding='utf-8-sig') as f:
        return json.load(f), p


def find_vmrun(cfg):
    cand = []
    if cfg.get('vmrun_path'):
        cand.append(cfg['vmrun_path'])
    if os.environ.get('VMRUN_PATH'):
        cand.append(os.environ['VMRUN_PATH'])
    if IS_WIN:
        for base in (os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     os.environ.get('ProgramFiles', r'C:\Program Files')):
            for sub in ('VMware Workstation', 'VMware Player', 'VMware VIX'):
                cand.append(os.path.join(base, 'VMware', sub, 'vmrun.exe'))
    else:
        cand += ['/usr/bin/vmrun', '/usr/local/bin/vmrun',
                 '/Applications/VMware Fusion.app/Contents/Library/vmrun']
    w = shutil.which('vmrun')
    if w:
        cand.append(w)
    for c in cand:
        if c and os.path.exists(c):
            return c
    raise RuntimeError('vmrun not found. Install VMware Workstation/Player (or VIX) or set "vmrun_path" in %s'
                       % config_path())


def host_type(cfg, vmrun):
    if cfg.get('host_type'):
        return cfg['host_type']
    if 'fusion' in vmrun.lower():
        return 'fusion'
    if IS_WIN:
        ws = os.path.join(os.path.dirname(vmrun), 'vmware.exe')
        return 'ws' if os.path.exists(ws) else 'player'
    return 'ws' if shutil.which('vmware') else 'player'


def _parse_kv(path):
    out = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re.match(r'\s*([^=#]+?)\s*=\s*"(.*)"\s*$', line)
                if m:
                    out[m.group(1).strip()] = m.group(2)
    except OSError:
        pass
    return out


def inventory_sources():
    h = os.path.expanduser('~')
    if IS_WIN:
        ad = os.environ.get('APPDATA', os.path.join(h, 'AppData', 'Roaming'))
        return [os.path.join(ad, 'VMware', 'inventory.vmls'), os.path.join(ad, 'VMware', 'preferences.ini')]
    if sys.platform == 'darwin':
        return [os.path.join(h, 'Library', 'Application Support', 'VMware Fusion', 'vmInventory'),
                os.path.join(h, 'Library', 'Preferences', 'VMware Fusion', 'preferences')]
    return [os.path.join(h, '.vmware', 'inventory.vmls'), os.path.join(h, '.vmware', 'preferences')]


def discover_vms(extra_paths=()):
    """VMs known to VMware on this host (Workstation library, Player recent list, Fusion inventory)."""
    found, seen = [], set()

    def add(vmx, name=''):
        if not vmx or not vmx.lower().endswith('.vmx'):
            return
        key = os.path.normcase(os.path.abspath(vmx))
        if key in seen or not os.path.exists(vmx):
            return
        seen.add(key)
        if not name:
            name = _read_vmx(vmx).get('displayname') or os.path.splitext(os.path.basename(vmx))[0]
        found.append({'name': name, 'vmx': vmx})
    for src in inventory_sources():
        kv = _parse_kv(src)
        for k, val in kv.items():
            m = re.match(r'(vmlist\d+)\.config$', k, re.I)
            if m:
                add(val, kv.get(m.group(1) + '.DisplayName', ''))
            m = re.match(r'(pref\.mruVM\d+)\.filename$', k, re.I)
            if m:
                add(val, kv.get(m.group(1) + '.displayName', ''))
    for p in extra_paths:
        add(p)
    return found


def resolve_vm(cfg, vm, running=()):
    """vm = configured name, VMware display name (or a unique part of it), or a .vmx path."""
    if not vm:
        raise ValueError('Parameter "vm" is required: a VM name as shown in VMware, or a .vmx path. '
                         'Call vm_list to see the VMs found on this PC.')
    vms = cfg.get('vms', {})

    def with_cfg(name, vmx):
        d = {'name': name, 'vmx': vmx}
        for cname, cd in vms.items():
            if os.path.normcase(cd.get('vmx', '')) == os.path.normcase(vmx):
                d.update(cd)
                d['name'] = name or cname
        return d
    if vm in vms:
        d = dict(vms[vm])
        d['name'] = vm
        return d
    if vm.lower().endswith('.vmx'):
        return with_cfg(_read_vmx(vm).get('displayname') or os.path.basename(vm), vm)
    cands = discover_vms(list(running) + [d.get('vmx', '') for d in vms.values()])
    q = vm.strip().lower()
    exact = [c for c in cands if c['name'].lower() == q]
    if len(exact) == 1:
        return with_cfg(exact[0]['name'], exact[0]['vmx'])
    part = [c for c in cands if q in c['name'].lower() or q in os.path.basename(c['vmx']).lower()]
    if len(part) == 1:
        return with_cfg(part[0]['name'], part[0]['vmx'])
    if len(part) > 1:
        raise ValueError('"%s" matches several VMs: %s. Use the full name or the .vmx path.' % (
            vm, '; '.join('%s (%s)' % (c['name'], c['vmx']) for c in part)))
    raise ValueError('No VM matches "%s". VMs found on this PC: %s. You can also pass a .vmx path.' % (
        vm, '; '.join(c['name'] for c in cands) or 'none'))


def guest_password(d):
    if d.get('guest_password_env'):
        v = os.environ.get(d['guest_password_env'])
        if v is not None:
            return v
    return d.get('guest_password', '')


# ---------------------------------------------------------------- state
def state_path():
    return os.path.join(os.path.dirname(config_path()), 'state.json')


def load_state():
    try:
        with open(state_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(state_path()), exist_ok=True)
    with open(state_path(), 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=2)


def vm_state(vmx):
    return load_state().get(os.path.normcase(os.path.abspath(vmx)), {})


def set_vm_state(vmx, **kw):
    st = load_state()
    k = os.path.normcase(os.path.abspath(vmx))
    st.setdefault(k, {}).update(kw)
    save_state(st)


# ---------------------------------------------------------------- guest login
def guest_login(d, interactive=True):
    """(user, password) for vmrun guest operations: config/env -> Windows Credential Manager -> native prompt."""
    if d.get('guest_user') and (d.get('guest_password') or d.get('guest_password_env')):
        return d['guest_user'], guest_password(d)
    u, p = creds.read(d['vmx'])
    if u:
        return u, p
    if interactive and creds.IS_WIN:
        u, p = creds.prompt(d['vmx'], d['name'], d.get('guest_user', ''))
        if u is None:
            raise RuntimeError('The user cancelled the credential dialog. Commands, files and processes in the VM '
                               'need the guest Windows login; screen, mouse and keyboard work without it.')
        creds.write(d['vmx'], u, p)
        return u, p
    raise RuntimeError('No guest login stored for VM "%s". Call vm_credentials (action "set") so the user can '
                       'type it in the Windows credential dialog. Never ask for it in chat.' % d['name'])


# ======================================================================== vmrun
_CAPS_CACHE = {}

ALTERNATIVES = {
    'runprograminguest': 'use the GUI through VNC (win+r, cmd) - output cannot be read back without VMware Tools',
    'capturescreen': 'enable VMware VNC for the VM (vm_vnc_configure) and use vm_screenshot',
    'typekeystrokesinguest': 'use vm_type with method "vnc"',
    'checktoolsstate': 'try any guest operation (vm_files exists C:\\) to see if Tools respond',
    'snapshot': 'shut down and copy the VM folder as a manual backup',
    'clone': 'shut down and copy the VM folder, then open the copy and answer "I copied it"',
}


class VmRun:
    def __init__(self):
        self.cfg, self.cfg_path = load_config()
        self.path = find_vmrun(self.cfg)
        self.type = host_type(self.cfg, self.path)
        self.version, self.commands = self._capabilities()

    def _capabilities(self):
        """Discover what THIS vmrun supports (any VMware version) by parsing its help text."""
        key = (self.path, os.path.getmtime(self.path) if os.path.exists(self.path) else 0)
        if key in _CAPS_CACHE:
            return _CAPS_CACHE[key]
        kw = {'creationflags': 0x08000000} if IS_WIN else {}
        try:
            p = subprocess.run([self.path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30, **kw)
            txt = p.stdout.decode('utf-8', 'replace')
        except (OSError, subprocess.TimeoutExpired):
            txt = ''
        m = re.search(r'vmrun version\s+(\S+(?:\s+build-\d+)?)', txt)
        cmds = set()
        for line in txt.splitlines():
            mm = re.match(r'^([A-Za-z][A-Za-z]+)\s{2,}\S', line)
            if mm and not mm.group(1).isupper():
                cmds.add(mm.group(1).lower())
        res = (m.group(1) if m else 'unknown', cmds)
        _CAPS_CACHE[key] = res
        return res

    def has(self, command):
        # if the help text could not be parsed, assume yes and let vmrun answer
        return not self.commands or command.lower() in self.commands

    def need(self, command, alternative=''):
        if not self.has(command):
            raise RuntimeError('This vmrun (version %s, host type %s) does not support "%s".%s' % (
                self.version, self.type, command, (' Alternative: ' + alternative) if alternative else ''))

    def run(self, args, d=None, guest=False, timeout=120):
        if args and args[0] != 'list':
            self.need(args[0], ALTERNATIVES.get(args[0].lower(), ''))
        cmd = [self.path, '-T', self.type]
        if guest:
            gu, gp = guest_login(d)
            cmd += ['-gu', gu, '-gp', gp]
        cmd += args
        kw = {}
        if IS_WIN:
            kw['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, **kw)
        out = p.stdout.decode('utf-8', 'replace').strip()
        if guest and p.returncode != 0 and re.search(r'invalid user name or password|incorrect user name',
                                                     out, re.I):
            if creds.read(d['vmx'])[0]:
                creds.delete(d['vmx'])
            raise RuntimeError('The guest rejected the stored login (removed). Call vm_credentials with action '
                               '"set" so the user can type it again in the Windows dialog.')
        return p.returncode, out


def _ok(rc, out, what):
    if rc != 0:
        raise RuntimeError('%s failed (vmrun exit %s): %s' % (what, rc, out or 'no output'))
    return out


# ======================================================================== tools
STATE = {'scale': {}}  # last screenshot scale per VM
LOCK = threading.Lock()


def _vnc(d):
    host = d.get('vnc_host', '127.0.0.1')
    port = d.get('vnc_port')
    if not port:
        port = _vnc_port_from_vmx(d.get('vmx', ''))
    if not port:
        raise RuntimeError('VNC is not enabled for VM "%s". Call vm_prepare - it enables VMware\'s VNC bound to '
                           '127.0.0.1 with a random password (needs the VM powered off or a restart).' % d['name'])
    pw = d.get('vnc_password') or _read_vmx(d.get('vmx', '')).get('remotedisplay.vnc.password') or None
    return VNCClient(host, int(port), pw)


def vmx_encoding(vmx):
    """Old VMs are windows-1252 unless the file declares .encoding (UTF-8 on modern versions)."""
    try:
        with open(vmx, 'rb') as f:
            head = f.read(4096).decode('latin-1')
        m = re.search(r'^\s*\.encoding\s*=\s*"([^"]+)"', head, re.M)
        if m:
            enc = m.group(1).lower()
            return {'utf-8': 'utf-8', 'utf8': 'utf-8', 'windows-1252': 'cp1252'}.get(enc, enc)
    except OSError:
        pass
    return 'cp1252'


def read_vmx_lines(vmx):
    with open(vmx, 'r', encoding=vmx_encoding(vmx), errors='replace', newline='') as f:
        raw = f.read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    return raw.splitlines(), nl


def write_vmx_lines(vmx, lines, nl):
    with open(vmx, 'w', encoding=vmx_encoding(vmx), errors='replace', newline='') as f:
        f.write(nl.join(lines) + nl)


def _read_vmx(vmx):
    keys = {}
    if vmx and os.path.exists(vmx):
        for line in read_vmx_lines(vmx)[0]:
            m = re.match(r'\s*([^=#]+?)\s*=\s*"(.*)"\s*$', line)
            if m:
                keys[m.group(1).lower()] = m.group(2)
    return keys


def _vnc_port_from_vmx(vmx):
    k = _read_vmx(vmx)
    if k.get('remotedisplay.vnc.enabled', '').lower() == 'true':
        return int(k.get('remotedisplay.vnc.port', '5900'))
    return None


def _map(d, x, y):
    s = STATE['scale'].get(d['name'], 1.0)
    return x / s, y / s


def t_vm_list(a):
    v = VmRun()
    rc, out = v.run(['list'])
    running = [l.strip() for l in out.splitlines()[1:] if l.strip()]
    lines = ['vmrun: %s (version %s, host type: %s, %d commands detected)' % (
        v.path, v.version, v.type, len(v.commands)), 'config (optional overrides): %s%s' % (
        v.cfg_path, '' if os.path.exists(v.cfg_path) else ' (none - not needed)'), '']
    lines.append('VMs found on this PC (VMware library / recent list / running / config):')
    for c in discover_vms(running + [d.get('vmx', '') for d in v.cfg.get('vms', {}).values()]):
        on = any(os.path.normcase(r) == os.path.normcase(c['vmx']) for r in running)
        k = _read_vmx(c['vmx'])
        vnc = ('127.0.0.1:%s' % k.get('remotedisplay.vnc.port') if k.get('remotedisplay.vnc.ip') == '127.0.0.1'
               else ('ALL interfaces:%s' % k.get('remotedisplay.vnc.port', '5900'))) \
            if k.get('remotedisplay.vnc.enabled', '').lower() == 'true' else 'off (vm_prepare)'
        lines.append('  - %s | %s | VNC %s | login %s | %s' % (
            c['name'], 'RUNNING' if on else 'off', vnc, 'stored' if creds.read(c['vmx'])[0] else 'not stored',
            c['vmx']))
    lines.append('')
    lines.append('Running VMs (vmrun list): %d' % len(running))
    for r in running:
        lines.append('  - ' + r)
    return lines


def t_vm_power(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    action = a['action']
    if action == 'start':
        for _ in range(15):  # a VM still powering off (lock folder present) cannot be started yet
            lck = d['vmx'] + '.lck'
            if not _is_running(v, d['vmx']) and not os.path.isdir(lck):
                break
            if _is_running(v, d['vmx']):
                return 'start: VM is already running.'
            time.sleep(2)
    args = [action, d['vmx']]
    if action == 'start':
        args.append('gui' if a.get('gui', True) else 'nogui')
    elif action in ('stop', 'reset', 'suspend'):
        args.append(a.get('mode', 'soft'))
    r = _ok(*v.run(args, timeout=300), what='vmrun ' + action) or ('%s: OK' % action)
    if action == 'start':
        time.sleep(3)
        if not _is_running(v, d['vmx']):
            return r + ' - but the VM is not listed as running; check the VMware window for a question dialog.'
    return r


def t_vm_snapshot(a):
    v = VmRun()
    if v.type == 'player':
        raise RuntimeError('Snapshots are not supported by VMware Player (vmrun -T player).')
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a['action']
    if act == 'list':
        return _ok(*v.run(['listSnapshots', d['vmx'], 'showTree']), what='listSnapshots')
    name = a.get('name')
    if not name:
        raise ValueError('"name" is required for create/revert/delete')
    cmd = {'create': 'snapshot', 'revert': 'revertToSnapshot', 'delete': 'deleteSnapshot'}[act]
    return _ok(*v.run([cmd, d['vmx'], name], timeout=900), what=cmd) or ('%s "%s": OK' % (act, name))


def t_vm_screenshot(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    scale = float(a.get('scale') or 0)
    region = a.get('region')
    try:
        with LOCK, _vnc(d) as c:
            w, h = c.capture()
            if not scale:
                scale = min(1.0, 1280.0 / max(w, 1))
            png, ow, oh = c.png(region=region, scale=scale)
    except (VNCError, RuntimeError) as e:
        if not v.has('captureScreen') or not d.get('guest_user'):
            raise
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, 'screen.png')
            _ok(*v.run(['captureScreen', d['vmx'], f], d, True), what='captureScreen')
            with open(f, 'rb') as fh:
                png = fh.read()
        STATE['scale'][d['name']] = 1.0
        return [{'type': 'text', 'text': 'VNC unavailable (%s). Fallback: vmrun captureScreen (view only, full size; '
                 'mouse/keyboard still need VNC, typing can use vm_type method "tools").' % e},
                {'type': 'image', 'data': base64.b64encode(png).decode('ascii'), 'mimeType': 'image/png'}]
    if not region:
        STATE['scale'][d['name']] = scale
    txt = ('Guest screen %dx%d. Image %dx%d (scale %.3f%s). Give click/move coordinates in THIS image\'s pixels '
           '(the server converts using the last full screenshot\'s scale).' % (
               w, h, ow, oh, scale, ', region %s' % region if region else ''))
    return [{'type': 'text', 'text': txt},
            {'type': 'image', 'data': base64.b64encode(png).decode('ascii'), 'mimeType': 'image/png'}]


def _after_shot(d, a, msg):
    if a.get('screenshot', False):
        time.sleep(float(a.get('wait', 0.6)))
        return [{'type': 'text', 'text': msg}] + t_vm_screenshot({'vm': d['name'], 'scale': a.get('scale')})
    return msg


def t_vm_click(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    x, y = _map(d, a['x'], a['y'])
    with LOCK, _vnc(d) as c:
        c.click(x, y, a.get('button', 'left'), bool(a.get('double', False)))
    return _after_shot(d, a, 'Clicked %s at guest (%d, %d).' % (a.get('button', 'left'), x, y))


def t_vm_move(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    x, y = _map(d, a['x'], a['y'])
    with LOCK, _vnc(d) as c:
        c.pointer(x, y, 0)
    return 'Moved pointer to guest (%d, %d).' % (x, y)


def t_vm_drag(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    x0, y0 = _map(d, a['x0'], a['y0'])
    x1, y1 = _map(d, a['x1'], a['y1'])
    with LOCK, _vnc(d) as c:
        c.drag(x0, y0, x1, y1)
    return _after_shot(d, a, 'Dragged (%d,%d) -> (%d,%d).' % (x0, y0, x1, y1))


def t_vm_scroll(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    x, y = _map(d, a['x'], a['y'])
    with LOCK, _vnc(d) as c:
        c.scroll(x, y, a.get('direction', 'down'), int(a.get('amount', 3)))
    return _after_shot(d, a, 'Scrolled %s x%s.' % (a.get('direction', 'down'), a.get('amount', 3)))


def t_vm_type(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    method = a.get('method') or 'vnc'
    if method == 'vnc':
        try:
            _vnc(d)
        except RuntimeError:
            if v.has('typeKeystrokesInGuest') and d.get('guest_user'):
                method = 'tools'
    if method == 'tools':
        _ok(*v.run(['typeKeystrokesInGuest', d['vmx'], a['text']], d, True), what='typeKeystrokesInGuest')
        return _after_shot(d, a, 'Typed %d characters via VMware Tools.' % len(a['text']))
    lay = a.get('layout') or vm_state(d['vmx']).get('keyboard_layout')
    if not lay and creds.read(d['vmx'])[0]:
        lay = _detect_layout(v, d)
    if not lay:
        risky = sorted(set(ch for ch in a['text'] if not (ch.isalnum() and ord(ch) < 128) and ch not in ' \n\t'))
        if risky:
            raise RuntimeError('Guest keyboard layout unknown, so these characters could come out wrong: %r. '
                               'Run vm_prepare (detects the layout when VMware Tools + login are available) or pass '
                               '"layout" explicitly. Letters, digits, space and Enter are safe.' % ''.join(risky))
        lay = 'us'
    if a.get('layout'):
        set_vm_state(d['vmx'], keyboard_layout=lay)
    events, bad = keyboard.plan(a['text'], lay)
    with LOCK, _vnc(d) as c:
        c.run_events(events, float(a.get('delay', 0.015)))
    msg = 'Typed %d characters (guest layout: %s).' % (len(a['text']), lay)
    if bad:
        msg += ' Not typable: %r - use vm_run to write such text.' % ''.join(bad)
    return _after_shot(d, a, msg)


def t_vm_key(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    with LOCK, _vnc(d) as c:
        c.press_combo(a['keys'], int(a.get('repeat', 1)))
    return _after_shot(d, a, 'Pressed %s%s.' % (a['keys'], ' x%s' % a['repeat'] if a.get('repeat') else ''))


def _decode(b):
    for enc in ('utf-8', 'cp850', 'cp1252'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin-1', 'replace')


def t_vm_run(a):
    """Run a cmd or PowerShell script in the guest and return its output."""
    v = VmRun()
    d = a.get('_resolved') or resolve_vm(v.cfg, a.get('vm'))
    shell = a.get('shell', 'cmd')
    script = a['command']
    _audit('run:' + shell, d['name'], script.strip().splitlines()[0][:200] if script.strip() else '')
    timeout = int(a.get('timeout', 120))
    tmp = d.get('guest_temp', 'C:\\Windows\\Temp').rstrip('\\')
    rid = 'vmctl_' + uuid.uuid4().hex[:8]
    g_out = '%s\\%s.out.txt' % (tmp, rid)
    g_files = []
    with tempfile.TemporaryDirectory() as td:
        if shell == 'powershell':
            ps_local = os.path.join(td, rid + '.ps1')
            with open(ps_local, 'w', encoding='utf-8-sig', newline='\r\n') as f:
                f.write(script)
            g_ps = '%s\\%s.ps1' % (tmp, rid)
            _ok(*v.run(['copyFileFromHostToGuest', d['vmx'], ps_local, g_ps], d, True), what='copy script')
            g_files.append(g_ps)
            body = ('@echo off\r\npowershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass '
                    '-File "%s" > "%s" 2>&1\r\nexit /b %%ERRORLEVEL%%\r\n' % (g_ps, g_out))
        else:
            inner_local = os.path.join(td, rid + '.inner.cmd')
            with open(inner_local, 'wb') as f:
                f.write(('@echo off\r\n' + script.replace('\r\n', '\n').replace('\n', '\r\n') + '\r\n')
                        .encode(a.get('encoding', 'cp1252'), 'replace'))
            g_inner = '%s\\%s.inner.cmd' % (tmp, rid)
            _ok(*v.run(['copyFileFromHostToGuest', d['vmx'], inner_local, g_inner], d, True), what='copy script')
            g_files.append(g_inner)
            body = '@echo off\r\ncall "%s" > "%s" 2>&1\r\nexit /b %%ERRORLEVEL%%\r\n' % (g_inner, g_out)
        cmd_local = os.path.join(td, rid + '.cmd')
        with open(cmd_local, 'wb') as f:
            f.write(body.encode('cp1252', 'replace'))
        g_cmd = '%s\\%s.cmd' % (tmp, rid)
        _ok(*v.run(['copyFileFromHostToGuest', d['vmx'], cmd_local, g_cmd], d, True), what='copy script')
        g_files.append(g_cmd)
        flags = []
        if a.get('interactive'):
            flags += ['-interactive', '-activeWindow']
        if a.get('no_wait'):
            flags.append('-noWait')
        guest_cmd = d.get('guest_cmd', 'C:\\Windows\\System32\\cmd.exe')
        rc, out = v.run(['runProgramInGuest', d['vmx']] + flags + [guest_cmd, '/c', g_cmd],
                        d, True, timeout=timeout + 30)
        exit_code = 0
        m = re.search(r'exit code:\s*(-?\d+)', out)
        if m:
            exit_code = int(m.group(1))
        elif rc != 0:
            for g in g_files:
                v.run(['deleteFileInGuest', d['vmx'], g], d, True)
            raise RuntimeError('runProgramInGuest failed: %s' % out)
        text = ''
        if not a.get('no_wait'):
            local_out = os.path.join(td, rid + '.out.txt')
            rc2, o2 = v.run(['copyFileFromGuestToHost', d['vmx'], g_out, local_out], d, True)
            if rc2 == 0 and os.path.exists(local_out):
                with open(local_out, 'rb') as f:
                    raw = f.read()
                if raw.startswith(b'\xff\xfe'):
                    text = raw.decode('utf-16-le', 'replace')
                else:
                    text = _decode(raw)
                g_files.append(g_out)
            else:
                text = '(no output file: %s)' % o2
        for g in g_files:
            v.run(['deleteFileInGuest', d['vmx'], g], d, True)
    limit = int(a.get('max_chars', 20000))
    if len(text) > limit:
        text = text[:limit] + '\n... [truncated, %d chars total]' % len(text)
    return 'exit code: %s\n%s' % (exit_code, text.strip() or '(no output)')


def t_vm_copy(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    if a['direction'] == 'to_guest':
        args = ['copyFileFromHostToGuest', d['vmx'], a['host_path'], a['guest_path']]
    else:
        args = ['copyFileFromGuestToHost', d['vmx'], a['guest_path'], a['host_path']]
    return _ok(*v.run(args, d, True, timeout=900), what=args[0]) or 'Copied.'


def t_vm_files(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a['action']
    p = a['guest_path']
    cmd = {'list': 'listDirectoryInGuest', 'mkdir': 'createDirectoryInGuest', 'exists': 'fileExistsInGuest',
           'delete_file': 'deleteFileInGuest', 'dir_exists': 'directoryExistsInGuest',
           'delete_dir': 'deleteDirectoryInGuest', 'rename': 'renameFileInGuest'}[act]
    extra = [a['new_path']] if act == 'rename' else []
    rc, out = v.run([cmd, d['vmx'], p] + extra, d, True)
    if act in ('delete_file', 'delete_dir', 'rename', 'mkdir') and rc == 0:
        _audit(cmd, d['name'], ' '.join([p] + extra))
    if act in ('exists', 'dir_exists'):
        return out
    return _ok(rc, out, cmd) or 'OK'


def t_vm_processes(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    if a.get('kill_pid'):
        return _ok(*v.run(['killProcessInGuest', d['vmx'], str(a['kill_pid'])], d, True), what='kill') or 'Killed.'
    out = _ok(*v.run(['listProcessesInGuest', d['vmx']], d, True), what='listProcessesInGuest')
    f = (a.get('filter') or '').lower()
    lines = [l for l in out.splitlines() if not f or f in l.lower()]
    return '\n'.join(lines)


def t_vm_vnc_configure(a):
    """Enable/disable the embedded VNC server in a (powered off) VM's .vmx."""
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    vmx = d['vmx']
    rc, out = v.run(['list'])
    if any(os.path.normcase(l.strip()) == os.path.normcase(vmx) for l in out.splitlines()[1:]):
        raise RuntimeError('The VM is running. Shut it down first; VMware rewrites the .vmx while a VM runs.')
    enable = a.get('enable', True)
    port = int(a.get('port', 5901))
    lines, nl = read_vmx_lines(vmx)
    backup = _backup_name(vmx)
    shutil.copyfile(vmx, backup)
    keep = [l for l in lines if not re.match(r'\s*RemoteDisplay\.vnc\.(enabled|port|ip)\s*=', l, re.I)]
    if enable:
        keep += ['RemoteDisplay.vnc.enabled = "TRUE"', 'RemoteDisplay.vnc.port = "%d"' % port,
                 'RemoteDisplay.vnc.ip = "127.0.0.1"']
        if not any(re.match(r'\s*RemoteDisplay\.vnc\.(password|key)\s*=', l, re.I) for l in keep):
            keep.append('RemoteDisplay.vnc.password = "%s"' % ''.join(
                secrets.choice(string.ascii_letters + string.digits) for _ in range(8)))
    write_vmx_lines(vmx, keep, nl)
    _audit('vnc_configure', d['name'], 'enabled=%s port=%s' % (enable, port))
    return ('VNC %s in %s (port %d). Backup: %s.\nNext: set a VNC password (max 8 chars) - in Workstation: '
            'VM > Settings > Options > VNC Connections; the user then writes the same password in "vnc_password" '
            'in %s. Without a password anyone who can reach this port can control the VM.'
            % ('enabled' if enable else 'disabled', vmx, port, backup, v.cfg_path))


# ------------------------------------------------------------- VM configuration
def _audit(action, vm, detail):
    """Append every configuration change to a local log next to the config file."""
    try:
        p = os.path.join(os.path.dirname(config_path()), 'changes.log')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write('%s\t%s\t%s\t%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), vm, action, detail))
    except OSError:
        pass


def _backup_name(vmx):
    base = vmx + '.bak-vmctl-' + time.strftime('%Y%m%d-%H%M%S')
    p, i = base, 1
    while os.path.exists(p):
        i += 1
        p = '%s-%d' % (base, i)
    return p


def _is_running(v, vmx):
    rc, out = v.run(['list'])
    return any(os.path.normcase(l.strip()) == os.path.normcase(vmx) for l in out.splitlines()[1:])


def t_vm_settings(a):
    """Read or change any .vmx setting (hardware, devices, options)."""
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    vmx = d['vmx']
    act = a.get('action', 'get')
    lines, nl = read_vmx_lines(vmx)
    rx = re.compile(r'\s*([^=#]+?)\s*=\s*"(.*)"\s*$')
    if act == 'get':
        flt = [s.lower() for s in (a.get('keys') or [])]
        pre = (a.get('prefix') or '').lower()
        out = []
        for l in lines:
            m = rx.match(l)
            if not m:
                continue
            k = m.group(1)
            if flt and k.lower() not in flt:
                continue
            if pre and not k.lower().startswith(pre):
                continue
            if re.search(r'password|\.key$|encryption', k, re.I):
                out.append('%s = "<hidden>"' % k)
            else:
                out.append('%s = "%s"' % (k, m.group(2)))
        return '%s\n%d setting(s)%s\n%s' % (vmx, len(out), ' (VM RUNNING: values may change at power-off)'
                                           if _is_running(v, vmx) else '', '\n'.join(out))
    if _is_running(v, vmx):
        raise RuntimeError('The VM is running. Shut it down before changing .vmx settings (VMware rewrites the file '
                           'while it runs). For live changes use vm_device, vm_shared_folders or vm_variable.')
    sets = a.get('set') or {}
    removes = [k.lower() for k in (a.get('remove') or [])]
    if act == 'set' and not sets:
        raise ValueError('"set" must be an object {key: value}')
    if act == 'remove' and not removes:
        raise ValueError('"remove" must be a list of keys')
    backup = _backup_name(vmx)
    shutil.copyfile(vmx, backup)
    lower_sets = {k.lower(): (k, str(v_).lower() if isinstance(v_, bool) else str(v_)) for k, v_ in sets.items()}
    new, changes, seen = [], [], set()
    for l in lines:
        m = rx.match(l)
        if m:
            kl = m.group(1).lower()
            if kl in removes:
                changes.append('- %s (was "%s")' % (m.group(1), m.group(2)))
                continue
            if kl in lower_sets:
                k, val = lower_sets[kl]
                val = val.upper() if val in ('true', 'false') else val
                if kl not in seen:
                    new.append('%s = "%s"' % (m.group(1), val))
                    if m.group(2) != val:
                        changes.append('~ %s: "%s" -> "%s"' % (m.group(1), m.group(2), val))
                    seen.add(kl)
                continue
        new.append(l)
    for kl, (k, val) in lower_sets.items():
        if kl not in seen:
            val = val.upper() if val in ('true', 'false') else val
            new.append('%s = "%s"' % (k, val))
            changes.append('+ %s = "%s"' % (k, val))
    write_vmx_lines(vmx, new, nl)
    changes = [re.sub(r'((?:password|\.key)\s*(?:=|:)\s*)"[^"]*"', r'\1"<hidden>"', c, flags=re.I) for c in changes]
    changes = [re.sub(r'("[^"]*" -> )"[^"]*"$', r'\1"<hidden>"', c) if re.search(r'password|\.key', c, re.I)
               else c for c in changes]
    _audit('settings', d['name'], '; '.join(changes) + ' | backup ' + backup)
    return 'Changed %s (backup %s):\n%s' % (vmx, backup, '\n'.join(changes) or '(no differences)')


def t_vm_device(a):
    """Connect/disconnect a virtual device while the VM runs (e.g. ethernet0, ide1:0, serial0, sound, usb)."""
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    cmd = 'connectNamedDevice' if a['action'] == 'connect' else 'disconnectNamedDevice'
    r = _ok(*v.run([cmd, d['vmx'], a['device']]), what=cmd)
    _audit(cmd, d['name'], a['device'])
    return r or '%s %s: OK' % (a['action'], a['device'])


def t_vm_shared_folders(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a['action']
    if act == 'enable':
        args = ['enableSharedFolders', d['vmx']] + (['runtime'] if a.get('runtime') else [])
    elif act == 'disable':
        args = ['disableSharedFolders', d['vmx']] + (['runtime'] if a.get('runtime') else [])
    elif act == 'add':
        args = ['addSharedFolder', d['vmx'], a['share_name'], a['host_path']]
    elif act == 'remove':
        args = ['removeSharedFolder', d['vmx'], a['share_name']]
    elif act == 'set_state':
        args = ['setSharedFolderState', d['vmx'], a['share_name'], a['host_path'],
                'writable' if a.get('writable', True) else 'readonly']
    else:
        raise ValueError('action must be enable, disable, add, remove or set_state')
    r = _ok(*v.run(args), what=args[0])
    _audit(args[0], d['name'], ' '.join(args[2:]))
    return r or '%s: OK (guest path on Windows: \\\\vmware-host\\Shared Folders\\<share>)' % args[0]


def t_vm_variable(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    scope = a.get('scope', 'runtimeConfig')
    guest = scope in ('guestEnv',)
    if a.get('value') is None:
        return _ok(*v.run(['readVariable', d['vmx'], scope, a['name']], d, guest), what='readVariable')
    r = _ok(*v.run(['writeVariable', d['vmx'], scope, a['name'], str(a['value'])], d, guest), what='writeVariable')
    _audit('writeVariable', d['name'], '%s %s=%s' % (scope, a['name'], a['value']))
    return r or 'OK'


def t_vm_guest_info(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    out = []
    out.append('vmrun %s, host type %s' % (v.version, v.type))
    if v.has('checkToolsState'):
        rc, t = v.run(['checkToolsState', d['vmx']])
        out.append('VMware Tools: %s' % t)
    elif d.get('guest_user'):
        rc, t = v.run(['directoryExistsInGuest', d['vmx'], 'C:\\'], d, True)
        out.append('VMware Tools: %s (probed with a guest operation)' % ('responding' if rc == 0 else 'not responding: ' + t))
    k = _read_vmx(d['vmx'])
    out.append('Virtual hardware version: %s | guest OS type: %s' % (k.get('virtualhw.version', '?'), k.get('guestos', '?')))
    if v.has('getGuestIPAddress'):
        rc, ip = v.run(['getGuestIPAddress', d['vmx']] + (['-wait'] if a.get('wait') else []), timeout=300)
        out.append('Guest IP: %s' % ip)
    elif d.get('guest_user'):
        out.append('Guest IP: getGuestIPAddress not in this vmrun; use vm_run with "ipconfig".')
    out.append('Running: %s' % _is_running(v, d['vmx']))
    return out


def t_vm_manage(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a['action']
    if act == 'install_tools':
        args = ['installTools', d['vmx']]
    elif act == 'upgrade_hardware':
        args = ['upgradevm', d['vmx']]
    elif act == 'clone':
        if v.type == 'player':
            raise RuntimeError('Cloning is not available on VMware Player.')
        args = ['clone', d['vmx'], a['dest_vmx'], a.get('clone_type', 'full')]
        if a.get('snapshot'):
            args.append('-snapshot=%s' % a['snapshot'])
        if a.get('clone_name'):
            args.append('-cloneName=%s' % a['clone_name'])
    elif act == 'delete_vm':
        if a.get('confirm') != d['name']:
            raise RuntimeError('Deleting a VM removes all its files permanently. Ask the user, then call again with '
                               'confirm set to the exact VM name ("%s").' % d['name'])
        args = ['deleteVM', d['vmx']]
    else:
        raise ValueError('action must be install_tools, upgrade_hardware, clone or delete_vm')
    r = _ok(*v.run(args, timeout=3600), what=args[0])
    _audit(args[0], d['name'], ' '.join(args[2:]))
    return r or '%s: OK' % act


def t_vm_host_network(a):
    v = VmRun()
    act = a.get('action', 'list')
    if act == 'list':
        return _ok(*v.run(['listHostNetworks']), what='listHostNetworks')
    if act == 'list_forwards':
        return _ok(*v.run(['listPortForwardings', a['network']]), what='listPortForwardings')
    if act == 'set_forward':
        args = ['setPortForwarding', a['network'], a.get('protocol', 'tcp'), str(a['host_port']),
                a['guest_ip'], str(a['guest_port'])] + ([a['description']] if a.get('description') else [])
    elif act == 'delete_forward':
        args = ['deletePortForwarding', a['network'], a.get('protocol', 'tcp'), str(a['host_port'])]
    else:
        raise ValueError('action must be list, list_forwards, set_forward or delete_forward')
    r = _ok(*v.run(args), what=args[0])
    _audit(args[0], a['network'], ' '.join(args[2:]))
    return r or 'OK'


def t_vm_network(a):
    """Network adapters of a VM. Works on every VMware version through the .vmx; uses the vmrun adapter commands
    when this vmrun has them (they exist in some versions only)."""
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a.get('action', 'list')
    k = _read_vmx(d['vmx'])
    if act == 'list':
        out = ['Adapters in .vmx:']
        for i in range(10):
            pre = 'ethernet%d.' % i
            if k.get(pre + 'present', '').lower() == 'true':
                out.append('  ethernet%d: type=%s vnet=%s virtualDev=%s startConnected=%s mac=%s' % (
                    i, k.get(pre + 'connectiontype', '?'), k.get(pre + 'vnet', '-'), k.get(pre + 'virtualdev', 'default'),
                    k.get(pre + 'startconnected', '?'), k.get(pre + 'generatedaddress', k.get(pre + 'address', '?'))))
        if v.has('listNetworkAdapters') and _is_running(v, d['vmx']):
            out.append('vmrun listNetworkAdapters: ' + v.run(['listNetworkAdapters', d['vmx']])[1])
        if v.has('listHostNetworks'):
            out.append('Host networks:\n' + v.run(['listHostNetworks'])[1])
        return out
    if act == 'set':
        i = int(a.get('index', 0))
        pre = 'ethernet%d.' % i
        ctype = a['connection']  # bridged | nat | hostonly | custom
        vals = {pre + 'present': 'TRUE', pre + 'connectionType': ctype}
        if ctype == 'custom':
            if not a.get('vnet'):
                raise ValueError('connection "custom" needs vnet, e.g. "VMnet2"')
            vals[pre + 'vnet'] = a['vnet']
        if a.get('virtual_device'):
            vals[pre + 'virtualDev'] = a['virtual_device']
        if a.get('start_connected') is not None:
            vals[pre + 'startConnected'] = a['start_connected']
        if _is_running(v, d['vmx']) and v.has('setNetworkAdapter'):
            args = ['setNetworkAdapter', d['vmx'], str(i), ctype] + ([a['vnet']] if ctype == 'custom' else [])
            r = _ok(*v.run(args), what='setNetworkAdapter')
            _audit('setNetworkAdapter', d['name'], ' '.join(args[2:]))
            return r or 'Adapter %d set to %s (live).' % (i, ctype)
        return t_vm_settings({'vm': a.get('vm'), 'action': 'set', 'set': vals})
    if act == 'remove':
        i = int(a.get('index', 0))
        keys = [kk for kk in k if kk.startswith('ethernet%d.' % i)]
        return t_vm_settings({'vm': a.get('vm'), 'action': 'remove', 'remove': keys})
    raise ValueError('action must be list, set or remove')



# ------------------------------------------------------------- one-call preparation
def _port_free(port):
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sk.bind(('127.0.0.1', port))
        return True
    except OSError:
        return False
    finally:
        sk.close()


def _pick_vnc_port(vmx):
    used = set()
    for c in discover_vms():
        if os.path.normcase(c['vmx']) == os.path.normcase(vmx):
            continue
        k = _read_vmx(c['vmx'])
        if k.get('remotedisplay.vnc.enabled', '').lower() == 'true':
            try:
                used.add(int(k.get('remotedisplay.vnc.port', '5900')))
            except ValueError:
                pass
    for port in range(5901, 6002):
        if port not in used and _port_free(port):
            return port
    raise RuntimeError('No free VNC port between 5901 and 6001.')


def _vnc_wanted(vmx):
    """Keys that make VMware's VNC safe: on, localhost only, random password, own port."""
    k = _read_vmx(vmx)
    want = {}
    if k.get('remotedisplay.vnc.enabled', '').lower() != 'true':
        want['RemoteDisplay.vnc.enabled'] = 'TRUE'
    if not k.get('remotedisplay.vnc.port'):
        want['RemoteDisplay.vnc.port'] = str(_pick_vnc_port(vmx))
    if k.get('remotedisplay.vnc.ip') != '127.0.0.1':
        want['RemoteDisplay.vnc.ip'] = '127.0.0.1'
    if not k.get('remotedisplay.vnc.password') and not k.get('remotedisplay.vnc.key'):
        want['RemoteDisplay.vnc.password'] = ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    return want


def _detect_layout(v, d):
    """Guest keyboard layout from the registry (needs VMware Tools + stored login)."""
    try:
        r = t_vm_run({'vm': d['vmx'], '_resolved': d, 'command':
                      'reg query "HKCU\\Keyboard Layout\\Preload" /v 1\n'
                      'reg query "HKCU\\Keyboard Layout\\Substitutes"'})
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'\b1\s+REG_SZ\s+([0-9A-Fa-f]{8})', r)
    if not m:
        return None
    klid = m.group(1).lower()
    sub = re.search(r'\b%s\s+REG_SZ\s+([0-9A-Fa-f]{8})' % klid, r, re.I)
    real = sub.group(1).lower() if sub else klid
    lay = keyboard.KLID_TO_LAYOUT.get(real) or keyboard.KLID_TO_LAYOUT.get(klid)
    if not lay:
        lay = keyboard.LANG_TO_LAYOUT.get(real[-4:], 'us')
    set_vm_state(d['vmx'], keyboard_layout=lay, keyboard_klid=real)
    return lay


def t_vm_prepare(a):
    """Make a VM ready in one call: secure VNC, VMware Tools check, guest login, keyboard layout."""
    v = VmRun()
    rc, out = v.run(['list'])
    running_list = [l.strip() for l in out.splitlines()[1:] if l.strip()]
    d = resolve_vm(v.cfg, a.get('vm'), running_list)
    vmx = d['vmx']
    running = any(os.path.normcase(r) == os.path.normcase(vmx) for r in running_list)
    rep = ['VM: %s' % d['name'], '.vmx: %s' % vmx, 'State: %s' % ('running' if running else 'powered off')]
    # 1) VNC
    want = _vnc_wanted(vmx)
    if not want:
        rep.append('VNC: ready (127.0.0.1:%s, password set)' % _read_vmx(vmx).get('remotedisplay.vnc.port'))
    elif not running:
        t_vm_settings({'vm': vmx, 'action': 'set', 'set': want, '_quiet': True})
        rep.append('VNC: configured (127.0.0.1:%s, random password stored in the .vmx) - active at next power-on'
                   % _read_vmx(vmx).get('remotedisplay.vnc.port'))
    elif a.get('restart_ok'):
        _ok(*v.run(['stop', vmx, 'soft'], timeout=300), what='stop')
        t_vm_settings({'vm': vmx, 'action': 'set', 'set': want, '_quiet': True})
        _ok(*v.run(['start', vmx, 'gui'], timeout=300), what='start')
        running = True
        rep.append('VNC: configured and VM restarted (127.0.0.1:%s)' % _read_vmx(vmx).get('remotedisplay.vnc.port'))
    else:
        rep.append('VNC: NOT ready - the VM is running and VMware applies VNC settings only at power-on. Ask the '
                   'user, then call vm_prepare again with restart_ok=true (soft shutdown + start), or power it off.')
    # 2) VMware Tools
    tools_ok = False
    if running:
        if v.has('checkToolsState'):
            rc, t = v.run(['checkToolsState', vmx])
            tools_ok = 'running' in t.lower()
            rep.append('VMware Tools: %s' % t)
        else:
            rep.append('VMware Tools: state not reported by this vmrun; will be probed on first guest command')
            tools_ok = True
    else:
        rep.append('VMware Tools: checked when the VM is running')
    if running and not tools_ok:
        rep.append('  -> Install VMware Tools for commands/files (vm_manage install_tools). XP/2003: legacy Tools '
                   '10.0.12. Screen, mouse and keyboard already work without Tools.')
    # 3) guest login
    if tools_ok and a.get('ask_credentials', True):
        try:
            u, _ = guest_login(d, interactive=True)
            rep.append('Guest login: stored for user "%s" (Windows Credential Manager)' % u)
        except RuntimeError as e:
            rep.append('Guest login: not stored (%s)' % e)
    else:
        u, _ = creds.read(vmx)
        rep.append('Guest login: %s' % ('stored for "%s"' % u if u else 'not stored yet'))
    # 4) keyboard layout
    lay = vm_state(vmx).get('keyboard_layout')
    if a.get('redetect_layout'):
        lay = None
    if not lay and tools_ok and creds.read(vmx)[0]:
        lay = _detect_layout(v, d)
    rep.append('Keyboard layout for typing: %s' % (lay or 'unknown - "us" assumed; pass layout to vm_type'))
    return rep


def t_vm_credentials(a):
    v = VmRun()
    d = resolve_vm(v.cfg, a.get('vm'))
    act = a.get('action', 'status')
    if act == 'set':
        u, p = creds.prompt(d['vmx'], d['name'], creds.read(d['vmx'])[0] or '')
        if u is None:
            return 'Cancelled by the user.'
        creds.write(d['vmx'], u, p)
        _audit('credentials_set', d['name'], 'user=%s' % u)
        return 'Login stored for "%s" in the Windows Credential Manager.' % u
    if act == 'forget':
        ok = creds.delete(d['vmx'])
        _audit('credentials_forget', d['name'], '')
        return 'Removed.' if ok else 'Nothing stored.'
    u, _ = creds.read(d['vmx'])
    return 'Stored login for "%s": %s' % (d['name'], u or 'none')


def t_vm_setup_help(a):
    p = config_path()
    return ('Config file: %s (%s)\n\nExample:\n%s\n\nSteps: 1) install VMware Tools in the guest (XP/2003: legacy '
            'Tools 10.0.12, winPreVista.iso); 2) shut the VM down and enable VNC (vm_vnc_configure, or VM > Settings > '
            'Options > VNC Connections in Workstation), choose a unique port 5901-6001 and a password; 3) the USER '
            'fills guest_user/guest_password (or guest_password_env) and vnc_password in the config file; '
            '4) start the VM and call vm_screenshot.'
            % (p, 'exists' if os.path.exists(p) else 'NOT created yet', json.dumps(EXAMPLE_CONFIG, indent=2)))


def t_vm_config_init(a):
    p = config_path()
    if os.path.exists(p):
        return 'Config already exists at %s - not overwritten.' % p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cfg = {'vmrun_path': '', 'host_type': '', 'vms': {}}
    for name, vmx in (a.get('vms') or {}).items():
        cfg['vms'][name] = {'vmx': vmx, 'guest_user': '', 'guest_password': '', 'guest_password_env': '',
                            'vnc_host': '127.0.0.1', 'vnc_port': _vnc_port_from_vmx(vmx) or 0,
                            'vnc_password': '', 'guest_temp': 'C:\\Windows\\Temp'}
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    return ('Created %s with %d VM(s). The user must now open it and fill in guest_user, guest_password '
            '(or guest_password_env) and vnc_password - do not type passwords for them.' % (p, len(cfg['vms'])))


# ======================================================================== schema
VM = {'type': 'string', 'description': 'VM name as shown in VMware (or a unique part of it), or the .vmx path'}
SHOT = {'type': 'boolean', 'description': 'Return a screenshot after the action (default false)'}


def S(props, req):
    return {'type': 'object', 'properties': props, 'required': req}


TOOLS = [
    ('vm_prepare', 'START HERE for a VM: makes it ready in one call - enables VMware VNC bound to 127.0.0.1 with a '
     'random password (VM must be off, or restart_ok=true after asking the user), checks VMware Tools, opens the '
     'Windows credential dialog for the guest login if missing (stored in Credential Manager), detects the guest '
     'keyboard layout.',
     S({'vm': VM, 'restart_ok': {'type': 'boolean', 'description': 'allow a soft shutdown + start to apply VNC'},
        'ask_credentials': {'type': 'boolean', 'description': 'default true'},
        'redetect_layout': {'type': 'boolean', 'description': 'read the guest keyboard layout again'}}, ['vm']),
     t_vm_prepare),
    ('vm_credentials', 'Guest Windows login used for commands/files: status, set (opens the native Windows dialog '
     'for the USER to type it) or forget.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['status', 'set', 'forget']}}, ['vm']), t_vm_credentials),
    ('vm_list', 'List configured VMs, which are running, their VNC ports, and the vmrun/host type in use.',
     S({}, []), t_vm_list),
    ('vm_setup_help', 'Show where the config file lives, an example config and the setup steps for a new VM.',
     S({}, []), t_vm_setup_help),
    ('vm_config_init', 'Create the config file (only if missing) with the given VMs; passwords are left blank '
     'for the user to fill in.', S({'vms': {'type': 'object', 'description': 'map name -> .vmx path',
                                            'additionalProperties': {'type': 'string'}}}, []), t_vm_config_init),
    ('vm_power', 'Start, stop, reset, suspend, pause or unpause a VM.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['start', 'stop', 'reset', 'suspend', 'pause', 'unpause']},
        'mode': {'type': 'string', 'enum': ['soft', 'hard'], 'description': 'stop/reset/suspend mode (default soft)'},
        'gui': {'type': 'boolean', 'description': 'start with the VMware window (default true)'}},
       ['vm', 'action']), t_vm_power),
    ('vm_snapshot', 'List, create, revert or delete snapshots (VMware Workstation/Fusion only, not Player).',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['list', 'create', 'revert', 'delete']},
        'name': {'type': 'string'}}, ['vm', 'action']), t_vm_snapshot),
    ('vm_screenshot', 'Capture the VM screen through VMware\'s embedded VNC (works for any guest OS, even at boot). '
     'Returns a PNG; later click coordinates use this image\'s pixels.',
     S({'vm': VM, 'scale': {'type': 'number', 'description': '0.1-1; default fits width 1280'},
        'region': {'type': 'array', 'items': {'type': 'number'}, 'description': 'optional [x0,y0,x1,y1] in GUEST '
                   'pixels to zoom into (does not change the click scale)'}}, ['vm']), t_vm_screenshot),
    ('vm_click', 'Click in the VM at (x, y) from the last screenshot.',
     S({'vm': VM, 'x': {'type': 'number'}, 'y': {'type': 'number'},
        'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}, 'double': {'type': 'boolean'},
        'screenshot': SHOT}, ['vm', 'x', 'y']), t_vm_click),
    ('vm_move', 'Move the VM mouse pointer to (x, y) (hover).', S({'vm': VM, 'x': {'type': 'number'},
                                                                  'y': {'type': 'number'}}, ['vm', 'x', 'y']), t_vm_move),
    ('vm_drag', 'Drag with the left button from (x0,y0) to (x1,y1).',
     S({'vm': VM, 'x0': {'type': 'number'}, 'y0': {'type': 'number'}, 'x1': {'type': 'number'},
        'y1': {'type': 'number'}, 'screenshot': SHOT}, ['vm', 'x0', 'y0', 'x1', 'y1']), t_vm_drag),
    ('vm_scroll', 'Scroll the mouse wheel at (x, y).',
     S({'vm': VM, 'x': {'type': 'number'}, 'y': {'type': 'number'},
        'direction': {'type': 'string', 'enum': ['up', 'down', 'left', 'right']},
        'amount': {'type': 'integer'}, 'screenshot': SHOT}, ['vm', 'x', 'y']), t_vm_scroll),
    ('vm_type', 'Type text into the focused window of the VM. Never use it to type passwords for the user.',
     S({'vm': VM, 'text': {'type': 'string'}, 'delay': {'type': 'number', 'description': 'seconds between keys'},
        'layout': {'type': 'string', 'enum': sorted(keyboard.LAYOUTS), 'description': 'guest keyboard layout '
                   '(auto-detected and remembered when VMware Tools + login are available)'},
        'method': {'type': 'string', 'enum': ['vnc', 'tools'], 'description': 'vnc (default, any guest) or tools '
                   '(vmrun typeKeystrokesInGuest; try it when the guest keyboard layout garbles symbols)'},
        'screenshot': SHOT}, ['vm', 'text']), t_vm_type),
    ('vm_key', 'Press a key or combination, e.g. "enter", "alt+f4", "ctrl+alt+delete", "win+r", "ctrl+shift+esc".',
     S({'vm': VM, 'keys': {'type': 'string'}, 'repeat': {'type': 'integer'}, 'screenshot': SHOT},
       ['vm', 'keys']), t_vm_key),
    ('vm_run', 'Run a cmd batch script (any Windows) or a PowerShell script (only where PowerShell exists) in the '
     'guest via VMware Tools and return exit code + output.',
     S({'vm': VM, 'command': {'type': 'string', 'description': 'script text; multi-line allowed'},
        'shell': {'type': 'string', 'enum': ['cmd', 'powershell'], 'description': 'default cmd'},
        'timeout': {'type': 'integer', 'description': 'seconds, default 120'},
        'interactive': {'type': 'boolean', 'description': 'run in the logged-on user desktop (for GUI programs)'},
        'no_wait': {'type': 'boolean', 'description': 'start and return immediately (no output)'},
        'max_chars': {'type': 'integer'}}, ['vm', 'command']), t_vm_run),
    ('vm_copy', 'Copy a file between host and guest.',
     S({'vm': VM, 'direction': {'type': 'string', 'enum': ['to_guest', 'from_guest']},
        'host_path': {'type': 'string'}, 'guest_path': {'type': 'string'}},
       ['vm', 'direction', 'host_path', 'guest_path']), t_vm_copy),
    ('vm_files', 'Guest file system: list a directory, create a directory, check existence, delete a file.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['list', 'mkdir', 'exists', 'dir_exists', 'delete_file',
                                                       'delete_dir', 'rename']},
        'guest_path': {'type': 'string'}, 'new_path': {'type': 'string', 'description': 'for rename'}},
       ['vm', 'action', 'guest_path']), t_vm_files),
    ('vm_processes', 'List guest processes (optional text filter) or kill one by PID.',
     S({'vm': VM, 'filter': {'type': 'string'}, 'kill_pid': {'type': 'integer'}}, ['vm']), t_vm_processes),
    ('vm_settings', 'Read or change ANY VM setting in the .vmx (memory, CPUs, network adapters, serial/parallel ports, '
     'CD/ISO, USB, display, VNC, boot order, etc.). get works anytime (secrets hidden); set/remove need the VM powered '
     'off, make a timestamped backup and are logged.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['get', 'set', 'remove']},
        'keys': {'type': 'array', 'items': {'type': 'string'}, 'description': 'get: only these keys'},
        'prefix': {'type': 'string', 'description': 'get: keys starting with this, e.g. "ethernet0." or "serial0."'},
        'set': {'type': 'object', 'description': 'set: {key: value}, e.g. {"memsize": "4096", "numvcpus": "2"}'},
        'remove': {'type': 'array', 'items': {'type': 'string'}}}, ['vm']), t_vm_settings),
    ('vm_device', 'Connect or disconnect a virtual device while the VM runs (ethernet0, ide1:0, sata0:1, serial0, '
     'sound, usb...).', S({'vm': VM, 'action': {'type': 'string', 'enum': ['connect', 'disconnect']},
                          'device': {'type': 'string'}}, ['vm', 'action', 'device']), t_vm_device),
    ('vm_shared_folders', 'Host-guest shared folders: enable/disable, add, remove, set writable/readonly.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['enable', 'disable', 'add', 'remove', 'set_state']},
        'share_name': {'type': 'string'}, 'host_path': {'type': 'string'}, 'writable': {'type': 'boolean'},
        'runtime': {'type': 'boolean', 'description': 'enable/disable only for the current power cycle'}},
       ['vm', 'action']), t_vm_shared_folders),
    ('vm_variable', 'Read (omit value) or write a VM variable: runtimeConfig (live .vmx value), guestEnv (guest '
     'environment variable), guestVar.',
     S({'vm': VM, 'scope': {'type': 'string', 'enum': ['runtimeConfig', 'guestEnv', 'guestVar']},
        'name': {'type': 'string'}, 'value': {'type': 'string'}}, ['vm', 'name']), t_vm_variable),
    ('vm_guest_info', 'VMware Tools state and guest IP address.', S({'vm': VM, 'wait': {'type': 'boolean'}}, ['vm']),
     t_vm_guest_info),
    ('vm_manage', 'Install/upgrade VMware Tools (mounts the ISO), upgrade virtual hardware, clone (full/linked) or '
     'delete a VM (delete requires confirm = exact VM name, after asking the user).',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['install_tools', 'upgrade_hardware', 'clone', 'delete_vm']},
        'dest_vmx': {'type': 'string'}, 'clone_type': {'type': 'string', 'enum': ['full', 'linked']},
        'snapshot': {'type': 'string'}, 'clone_name': {'type': 'string'}, 'confirm': {'type': 'string'}},
       ['vm', 'action']), t_vm_manage),
    ('vm_host_network', 'VMware host networks (vmnet) and NAT port forwarding: list, list_forwards, set_forward, '
     'delete_forward.',
     S({'action': {'type': 'string', 'enum': ['list', 'list_forwards', 'set_forward', 'delete_forward']},
        'network': {'type': 'string', 'description': 'e.g. vmnet8'}, 'protocol': {'type': 'string', 'enum': ['tcp', 'udp']},
        'host_port': {'type': 'integer'}, 'guest_ip': {'type': 'string'}, 'guest_port': {'type': 'integer'},
        'description': {'type': 'string'}}, []), t_vm_host_network),
    ('vm_network', 'List, set or remove VM network adapters (bridged / nat / hostonly / custom VMnetX, adapter model). '
     'Works on any VMware version via the .vmx (VM off); live change when this vmrun supports setNetworkAdapter.',
     S({'vm': VM, 'action': {'type': 'string', 'enum': ['list', 'set', 'remove']}, 'index': {'type': 'integer'},
        'connection': {'type': 'string', 'enum': ['bridged', 'nat', 'hostonly', 'custom']},
        'vnet': {'type': 'string', 'description': 'for custom, e.g. VMnet2'},
        'virtual_device': {'type': 'string', 'description': 'e.g. e1000, e1000e, vmxnet3, vlance (XP: vlance/e1000)'},
        'start_connected': {'type': 'boolean'}}, ['vm']), t_vm_network),
    ('vm_vnc_configure', 'Enable or disable VMware\'s embedded VNC server in a POWERED-OFF VM\'s .vmx (backup made).',
     S({'vm': VM, 'enable': {'type': 'boolean'}, 'port': {'type': 'integer', 'description': '5901-6001'}},
       ['vm']), t_vm_vnc_configure),
]
TOOL_MAP = {t[0]: t[3] for t in TOOLS}


# ======================================================================== JSON-RPC
def send(msg):
    sys.stdout.write(json.dumps(msg) + '\n')
    sys.stdout.flush()


def handle(req):
    mid = req.get('id')
    method = req.get('method')
    params = req.get('params') or {}
    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': params.get('protocolVersion', '2025-06-18'),
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
            'instructions': ('Operate VMware Workstation/Player VMs from the host. Screen/mouse/keyboard via VMware '
                             'embedded VNC (any guest OS), commands/files via vmrun + VMware Tools. Take a screenshot '
                             'before acting. Never type passwords for the user; credentials live in the config file.')}}
    if method in ('notifications/initialized', 'notifications/cancelled'):
        return None
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': [
            {'name': n, 'description': desc, 'inputSchema': sch} for n, desc, sch, _ in TOOLS]}}
    if method == 'tools/call':
        name = params.get('name')
        args = params.get('arguments') or {}
        fn = TOOL_MAP.get(name)
        if not fn:
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': 'Unknown tool ' + str(name)}}
        try:
            r = fn(args)
            if isinstance(r, list) and r and isinstance(r[0], dict):
                content = r
            elif isinstance(r, list):
                content = [{'type': 'text', 'text': '\n'.join(r)}]
            else:
                content = [{'type': 'text', 'text': str(r)}]
            return {'jsonrpc': '2.0', 'id': mid, 'result': {'content': content, 'isError': False}}
        except (VNCError, RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as e:
            return {'jsonrpc': '2.0', 'id': mid, 'result': {
                'content': [{'type': 'text', 'text': '%s: %s' % (type(e).__name__, e)}], 'isError': True}}
    if mid is None:
        return None
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'Method not found: %s' % method}}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', newline='\n')
        sys.stdin.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
            continue
        reqs = req if isinstance(req, list) else [req]
        for r in reqs:
            resp = handle(r)
            if resp is not None:
                send(resp)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        cfg, p = load_config()
        print('config:', p, 'exists' if os.path.exists(p) else 'missing')
        try:
            print('vmrun:', find_vmrun(cfg))
        except RuntimeError as e:
            print(e)
        sys.exit(0)
    main()
