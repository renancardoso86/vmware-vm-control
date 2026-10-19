"""Offline tests - no VMware needed. Run: python -m unittest discover -s tests -v

Covers: DES/VNC auth, RFB client against a mock server, keyboard plans,
MCP JSON-RPC handshake, .vmx editing (encoding, CRLF, backups, secret masking),
VM discovery from a fake VMware inventory, vm_prepare on a powered-off VM.
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, '..', 'plugins', 'vmware-vm-control', 'server')
sys.path.insert(0, SERVER)

from vnc_des import des_encrypt_block, vnc_auth_response  # noqa: E402
from vnc_client import VNCClient, VNCError  # noqa: E402
import keyboard  # noqa: E402


class DesTest(unittest.TestCase):
    def test_known_vector(self):
        self.assertEqual(des_encrypt_block(bytes.fromhex('133457799BBCDFF1'),
                                           bytes.fromhex('0123456789ABCDEF')).hex(), '85e813540f0ab405')


def mock_vnc(password, events, w=200, h=100):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    s.listen(5)
    port = s.getsockname()[1]

    def serve():
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            r = lambda n: c.recv(n, socket.MSG_WAITALL)  # noqa: E731
            c.sendall(b'RFB 003.008\n'); r(12)
            c.sendall(bytes([1, 2])); r(1)
            ch = os.urandom(16); c.sendall(ch)
            ok = r(16) == vnc_auth_response(password, ch)
            c.sendall(struct.pack('>I', 0 if ok else 1))
            if not ok:
                c.sendall(struct.pack('>I', 4) + b'nope'); c.close(); continue
            r(1); c.sendall(struct.pack('>HH', w, h) + b'\0' * 16 + struct.pack('>I', 4) + b'mock')
            while True:
                t = c.recv(1)
                if not t:
                    break
                t = t[0]
                if t == 0:
                    r(19)
                elif t == 2:
                    _, n = struct.unpack('>BH', r(3)); r(4 * n)
                elif t == 3:
                    r(9)
                    px = bytes([0, 0, 255, 0]) * (w * h)  # B,G,R,X -> pure red
                    c.sendall(struct.pack('>BxH', 0, 1) + struct.pack('>HHHHi', 0, 0, w, h, 0) + px)
                elif t == 4:
                    events.append(('key',) + struct.unpack('>BxxI', r(7)))
                elif t == 5:
                    events.append(('ptr',) + struct.unpack('>BHH', r(5)))
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    return port, s


class VncTest(unittest.TestCase):
    def test_auth_capture_input(self):
        ev = []
        port, srv = mock_vnc('segredo1', ev)
        try:
            with VNCClient('127.0.0.1', port, 'segredo1') as v:
                self.assertEqual((v.width, v.height), (200, 100))
                v.capture()
                png, w, h = v.png(scale=0.5)
                self.assertEqual((w, h), (100, 50))
                self.assertTrue(png.startswith(b'\x89PNG'))
                v.click(10, 20)
            time.sleep(0.2)
            self.assertIn(('ptr', 1, 10, 20), ev)
            ptr = [e for e in ev if e[0] == 'ptr']
            self.assertEqual(ptr[0], ('ptr', 0, 7, 17))           # approach move next to the target first
            self.assertLess(ptr.index(('ptr', 0, 10, 20)), ptr.index(('ptr', 1, 10, 20)))
            with self.assertRaises(VNCError):
                VNCClient('127.0.0.1', port, 'errada12').connect()
        finally:
            srv.close()


class KeyboardTest(unittest.TestCase):
    def _keys(self, text, layout):
        ev, bad = keyboard.plan(text, layout)
        self.assertEqual(bad, [])
        return [e[1] for e in ev if e[2]]  # key-down keysyms

    def test_us_uppercase_uses_shift(self):
        self.assertEqual(self._keys('A', 'us'), [keyboard.SHIFT, ord('a')])

    def test_abnt2_slash_is_altgr_q(self):
        self.assertEqual(self._keys('/', 'abnt2'), [keyboard.CTRL, keyboard.ALT, ord('q')])

    def test_abnt2_cedilla_and_dead_tilde(self):
        self.assertEqual(self._keys('ç', 'abnt2'), [ord(';')])
        self.assertEqual(self._keys('ã', 'abnt2'), [ord("'"), ord('a')])

    def test_german_qwertz(self):
        C, A, S = keyboard.CTRL, keyboard.ALT, keyboard.SHIFT
        self.assertEqual(self._keys('z', 'de'), [ord('y')])               # Y/Z swapped
        self.assertEqual(self._keys('ü', 'de'), [ord('[')])
        self.assertEqual(self._keys('@', 'de'), [C, A, ord('q')])
        self.assertEqual(self._keys('é', 'de'), [ord('='), ord('e')])      # dead acute + e
        self.assertEqual(self._keys('ý', 'de'), [ord('='), ord('z')])      # accent on the swapped key
        self.assertEqual(self._keys('<', 'de')[0], A)                      # extra ISO key -> Alt code

    def test_spanish(self):
        self.assertEqual(self._keys('ñ', 'es'), [ord(';')])
        self.assertEqual(self._keys('¿', 'es'), [keyboard.SHIFT, ord('=')])
        self.assertEqual(self._keys('ü', 'es'), [keyboard.SHIFT, ord("'"), ord('u')])

    def test_portuguese_portugal(self):
        self.assertEqual(self._keys('ç', 'pt'), [ord(';')])
        self.assertEqual(self._keys('ã', 'pt'), [ord('\\'), ord('a')])
        self.assertEqual(self._keys('ê', 'pt'), [keyboard.SHIFT, ord('\\'), ord('e')])

    def test_us_international_dead_quote(self):
        self.assertEqual(self._keys("'", 'us-intl'), [ord("'"), 0x20])    # dead key + space = literal
        self.assertEqual(self._keys('ç', 'us-intl'), [ord("'"), ord('c')])

    def test_every_layout_types_plain_text(self):
        for lay in keyboard.LAYOUTS:
            ev, bad = keyboard.plan('Hello World 0123456789 .,-', lay)
            self.assertEqual(bad, [], lay)

    def test_layout_detection_tables(self):
        self.assertEqual(keyboard.KLID_TO_LAYOUT['00000407'], 'de')
        self.assertEqual(keyboard.KLID_TO_LAYOUT['0000040a'], 'es')
        self.assertEqual(keyboard.KLID_TO_LAYOUT['00000816'], 'pt')
        self.assertEqual(keyboard.KLID_TO_LAYOUT['00020409'], 'us-intl')

    def test_unmapped_uses_alt_code(self):
        ks = self._keys('\\', 'abnt2')
        self.assertEqual(ks[0], keyboard.ALT)
        self.assertEqual(ks[1:], [keyboard.KP[0], keyboard.KP[0], keyboard.KP[9], keyboard.KP[2]])


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.vmrun = os.path.join(t, 'vmrun.cmd' if os.name == 'nt' else 'vmrun')
        with open(self.vmrun, 'w') as f:
            f.write('@echo Total running VMs: 0\n' if os.name == 'nt' else '#!/bin/sh\necho "Total running VMs: 0"\n')
        os.chmod(self.vmrun, 0o755)
        os.makedirs(os.path.join(t, 'vm'))
        self.vmx = os.path.join(t, 'vm', 'xp.vmx')
        with open(self.vmx, 'wb') as f:
            f.write('displayName = "M\xe1quina XP"\r\nmemsize = "512"\r\n'.encode('cp1252'))
        self.cfg = os.path.join(t, 'cfg', 'config.json')
        os.makedirs(os.path.dirname(self.cfg))
        with open(self.cfg, 'w') as f:
            json.dump({'vmrun_path': self.vmrun, 'host_type': 'ws'}, f)
        os.environ['VMCTL_CONFIG'] = self.cfg
        import importlib
        import vm_control
        self.m = importlib.reload(vm_control)
        self.m.inventory_sources = lambda: []                       # tests never read the host's VMware library

    def tearDown(self):
        os.environ.pop('VMCTL_CONFIG', None)
        self.tmp.cleanup()

    def test_vmx_edit_keeps_encoding_crlf_and_masks_secrets(self):
        m = self.m
        out = m.t_vm_settings({'vm': self.vmx, 'action': 'set',
                               'set': {'memsize': '1024', 'RemoteDisplay.vnc.password': 'abc12345'}})
        self.assertIn('memsize', out)
        raw = open(self.vmx, 'rb').read()
        self.assertIn(b'M\xe1quina', raw)        # cp1252 preserved
        self.assertIn(b'\r\n', raw)               # CRLF preserved
        log = open(os.path.join(os.path.dirname(self.cfg), 'changes.log'), encoding='utf-8').read()
        self.assertNotIn('abc12345', log)         # secret masked
        backups = [f for f in os.listdir(os.path.dirname(self.vmx)) if '.bak-vmctl-' in f]
        self.assertEqual(len(backups), 1)

    def test_prepare_powered_off_vm(self):
        m = self.m
        rep = '\n'.join(m.t_vm_prepare({'vm': self.vmx, 'ask_credentials': False}))
        self.assertIn('VNC: configured', rep)
        k = m._read_vmx(self.vmx)
        self.assertEqual(k['remotedisplay.vnc.ip'], '127.0.0.1')
        self.assertEqual(len(k['remotedisplay.vnc.password']), 8)

    def _fake_vdiskmanager(self):
        t = self.tmp.name
        vdm = os.path.join(t, 'vdm.cmd' if os.name == 'nt' else 'vdm')
        with open(vdm, 'w') as f:
            if os.name == 'nt':
                f.write('@echo off\r\ntype nul > "%~8"\r\necho Virtual disk creation successful.\r\n')
            else:
                f.write('#!/bin/sh\n: > "$8"\necho "Virtual disk creation successful."\n')
        os.chmod(vdm, 0o755)
        with open(self.cfg, 'w') as f:
            json.dump({'vmrun_path': self.vmrun, 'host_type': 'ws', 'vdiskmanager_path': vdm}, f)

    def test_create_xp_vm(self):
        self._fake_vdiskmanager()
        m = self.m
        iso = os.path.join(self.tmp.name, 'xp.iso')
        open(iso, 'wb').close()
        parent = os.path.join(self.tmp.name, 'VMs')
        rep = '\n'.join(m.t_vm_create({'name': 'XP Test', 'guest': 'xp', 'iso': iso, 'folder': parent,
                                        'network': 'nat', 'hardware_version': 20}))
        vmx = os.path.join(parent, 'XP Test', 'XP Test.vmx')
        self.assertIn('Created VM', rep)
        k = m._read_vmx(vmx)
        self.assertEqual(k['guestos'], 'winxppro')
        self.assertEqual(k['virtualhw.version'], '20')
        self.assertEqual(k['ide0:0.filename'], 'XP Test.vmdk')     # XP has no SATA driver: IDE disk
        self.assertEqual(k['ide1:0.filename'], iso)
        self.assertEqual(k['ide1:0.devicetype'], 'cdrom-image')
        self.assertEqual(k['ethernet0.connectiontype'], 'nat')
        self.assertNotIn('ethernet0.virtualdev', k)                 # VMware default (PCnet) has an XP driver
        self.assertEqual(k['remotedisplay.vnc.ip'], '127.0.0.1')
        self.assertEqual(len(k['remotedisplay.vnc.password']), 8)
        self.assertTrue(os.path.exists(os.path.join(parent, 'XP Test', 'XP Test.vmdk')))
        self.assertIn(vmx, [c['vmx'] for c in m.discover_vms()])   # visible to vm_list without VMware library
        log = open(os.path.join(os.path.dirname(self.cfg), 'changes.log'), encoding='utf-8').read()
        self.assertNotIn(k['remotedisplay.vnc.password'], log)
        with self.assertRaises(RuntimeError):                       # never overwrites
            m.t_vm_create({'name': 'XP Test', 'guest': 'xp', 'folder': parent, 'hardware_version': 20})

    def test_create_modern_vm_uses_sata_and_needs_hw_version(self):
        self._fake_vdiskmanager()
        m = self.m
        parent = os.path.join(self.tmp.name, 'VMs')
        m.inventory_sources = lambda: []                            # ignore the real VMware library on this host
        with self.assertRaises(RuntimeError):                       # fake vmrun reports no version, no hw VMs
            m.t_vm_create({'name': 'W10', 'guest': '10-64', 'folder': parent})
        self.assertFalse(os.path.exists(os.path.join(parent, 'W10')))
        m.t_vm_create({'name': 'W10', 'guest': '10-64', 'folder': parent, 'hardware_version': 20,
                       'network': 'custom', 'vnet': 'VMnet2'})
        k = m._read_vmx(os.path.join(parent, 'W10', 'W10.vmx'))
        self.assertEqual(k['sata0:0.filename'], 'W10.vmdk')
        self.assertEqual(k['sata0:1.devicetype'], 'atapi-cdrom')
        self.assertEqual(k['ethernet0.vnet'], 'VMnet2')
        self.assertEqual(k['ethernet0.virtualdev'], 'e1000e')
        with self.assertRaises(ValueError):
            m.t_vm_create({'name': 'bad/name', 'guest': 'xp', 'folder': parent, 'hardware_version': 20})

    def _fake_vmrun(self, body_posix, body_nt):
        with open(self.vmrun, 'w') as f:
            f.write(body_nt if os.name == 'nt' else '#!/bin/sh\n' + body_posix)
        os.chmod(self.vmrun, 0o755)
        import importlib
        self.m = importlib.reload(self.m)
        self.m.inventory_sources = lambda: []

    def test_guest_command_without_tools_fails_before_credentials(self):
        # vmrun that knows checkToolsState and answers "unknown" (Tools not running)
        self._fake_vmrun(
            'if [ -z "$1" ]; then printf "vmrun version 1.17.0 build-1\\n\\n'
            'checkToolsState      Path to vmx file     Query the state of tools\\n'
            'runProgramInGuest    Path to vmx file     Run a program in Guest OS\\n"; exit 0; fi\n'
            'case "$*" in *checkToolsState*) echo unknown;; *) echo "Total running VMs: 0";; esac\n',
            '@echo off\r\nif "%~1"=="" (echo vmrun version 1.17.0 build-1& echo.& '
            'echo checkToolsState      Path to vmx file     Query the state of tools& '
            'echo runProgramInGuest    Path to vmx file     Run a program in Guest OS& exit /b 0)\r\n'
            'echo %* | find "checkToolsState" >nul && (echo unknown& exit /b 0)\r\necho Total running VMs: 0\r\n')
        m = self.m
        asked = []
        m.creds.read = lambda vmx: (None, None)
        m.creds.prompt = lambda *a, **k: asked.append(1) or (None, None)
        with self.assertRaises(RuntimeError) as cm:
            m.t_vm_run({'vm': self.vmx, 'command': 'ver'})
        self.assertIn('VMware Tools are not running', str(cm.exception))
        self.assertEqual(asked, [])                                  # no credential dialog shown

    def test_shared_folder_on_running_vm_without_tools_fails_fast(self):
        # vmrun waits for Tools forever on addSharedFolder; the tool must refuse before calling it
        self._fake_vmrun(
            'if [ -z "$1" ]; then printf "vmrun version 1.17.0 build-1\\n\\n'
            'checkToolsState      Path to vmx file     Query the state of tools\\n'
            'addSharedFolder      Path to vmx file     Add a Host-Guest shared folder\\n"; exit 0; fi\n'
            'case "$*" in *checkToolsState*) echo unknown;; *addSharedFolder*) sleep 600;; *) echo "Total running VMs: 0";; esac\n',
            '@echo off\r\nif "%~1"=="" (echo vmrun version 1.17.0 build-1& echo.& '
            'echo checkToolsState      Path to vmx file     Query the state of tools& '
            'echo addSharedFolder      Path to vmx file     Add a Host-Guest shared folder& exit /b 0)\r\n'
            'echo %* | find "checkToolsState" >nul && (echo unknown& exit /b 0)\r\necho Total running VMs: 0\r\n')
        m = self.m
        m._is_running = lambda v, vmx: True
        t0 = time.time()
        with self.assertRaises(RuntimeError) as cm:
            m.t_vm_shared_folders({'vm': self.vmx, 'action': 'add', 'share_name': 's', 'host_path': self.tmp.name})
        self.assertIn('needs VMware Tools', str(cm.exception))
        self.assertLess(time.time() - t0, 20)

    def test_delete_locked_vm_explains_open_tab(self):
        m = self.m
        os.makedirs(self.vmx + '.lck')
        with self.assertRaises(RuntimeError) as cm:
            m.t_vm_manage({'vm': self.vmx, 'action': 'delete_vm', 'confirm': m.resolve_vm(m.load_config()[0], self.vmx)['name']})
        self.assertIn('Workstation tab', str(cm.exception))
        self.assertTrue(os.path.exists(self.vmx))

    def test_delete_vm_removes_plugin_backups_and_state(self):
        m = self.m
        m.t_vm_settings({'vm': self.vmx, 'action': 'set', 'set': {'memsize': '768'}})   # creates a backup
        m.set_vm_state(self.vmx, keyboard_layout='us')
        folder = os.path.dirname(self.vmx)
        os.remove(self.vmx)                    # what vmrun deleteVM does: VMware's own files are gone
        out = m._cleanup_deleted(self.vmx)
        self.assertIn('removed plugin backup', out)
        self.assertFalse(os.path.exists(folder))
        self.assertNotIn(os.path.normcase(os.path.abspath(self.vmx)), m.load_state())

    def test_delete_cleanup_when_vmware_removed_the_folder(self):
        m = self.m
        import shutil as sh
        sh.rmtree(os.path.dirname(self.vmx))
        out = m._cleanup_deleted(self.vmx)
        self.assertIn('already removed by VMware', out)
        self.assertNotIn('incomplete', out)

    def test_permission_errors_get_a_hint(self):
        m = self.m
        with self.assertRaises(RuntimeError) as cm:
            m._ok(1, 'Error: Failed to set port forwarding', 'setPortForwarding')
        self.assertIn('Virtual Network Editor', str(cm.exception))
        with self.assertRaises(RuntimeError) as cm:
            m._ok(1, 'Error: Insufficient permissions in the host operating system', 'typeKeystrokesInGuest')
        self.assertIn('method "vnc"', str(cm.exception))
        with self.assertRaises(RuntimeError) as cm:
            m._ok(1, 'Error: Insufficient permissions', 'somethingElse')
        self.assertIn('administrator', str(cm.exception))

    def test_device_tool_uses_device_name(self):
        m = self.m
        schema = [t for t in m.TOOLS if t[0] == 'vm_device'][0][2]
        self.assertIn('device_name', schema['properties'])
        self.assertNotIn('device', schema['properties'])           # "device" is swallowed by remote bridges
        with self.assertRaises(ValueError):
            m.t_vm_device({'vm': self.vmx, 'action': 'connect'})

    def test_clone_gets_its_own_vnc_port_and_password(self):
        m = self.m
        m.t_vm_settings({'vm': self.vmx, 'action': 'set', 'set': {
            'RemoteDisplay.vnc.enabled': 'TRUE', 'RemoteDisplay.vnc.port': '5901',
            'RemoteDisplay.vnc.password': 'origpass', 'RemoteDisplay.vnc.key': 'oldkey'}})
        m.set_vm_state(self.vmx, keyboard_layout='us')
        st = m.load_state(); st['_created'] = [self.vmx]; m.save_state(st)   # source visible to the port picker
        clone = os.path.join(self.tmp.name, 'clone', 'clone.vmx')
        os.makedirs(os.path.dirname(clone))
        import shutil as sh
        sh.copyfile(self.vmx, clone)
        out = m._after_clone(clone)
        k = m._read_vmx(clone)
        self.assertNotEqual(k['remotedisplay.vnc.port'], '5901')
        self.assertNotEqual(k['remotedisplay.vnc.password'], 'origpass')
        self.assertNotIn('remotedisplay.vnc.key', k)
        self.assertIn(clone, [c['vmx'] for c in m.discover_vms()])
        self.assertIn('own port', out)

    def test_vnc_configure_keeps_real_port_and_current_message(self):
        m = self.m
        m.t_vm_settings({'vm': self.vmx, 'action': 'set', 'set': {
            'RemoteDisplay.vnc.enabled': 'TRUE', 'RemoteDisplay.vnc.port': '5902'}})
        off = m.t_vm_vnc_configure({'vm': self.vmx, 'enable': False})
        self.assertIn('was port 5902', off)
        on = m.t_vm_vnc_configure({'vm': self.vmx, 'enable': True})
        self.assertNotIn('config.json', on)
        k = m._read_vmx(self.vmx)
        self.assertEqual(k['remotedisplay.vnc.ip'], '127.0.0.1')
        self.assertEqual(len(k['remotedisplay.vnc.password']), 8)

    @unittest.skipIf(os.name == 'nt', 'uses a POSIX shell to leave a child holding the output handle')
    def test_vmrun_output_does_not_wait_for_children(self):
        # like `vmrun start` opening the Workstation window: the child keeps vmrun's output handle open
        m = self.m
        script = os.path.join(self.tmp.name, 'spawner')
        with open(script, 'w') as f:
            f.write('#!/bin/sh\necho started\nsleep 20 &\nexit 0\n')
        os.chmod(script, 0o755)
        t0 = time.time()
        out, rc = m._run_to_file([script], 30, {})
        self.assertLess(time.time() - t0, 5)
        self.assertEqual((out, rc), ('started', 0))

    @unittest.skipIf(os.name == 'nt', 'POSIX fake vmrun')
    def test_power_actions_never_block_past_the_limit(self):
        # a soft stop that waits for the guest: the tool must answer in time and say it is still in progress
        self._fake_vmrun('case "$1 $2 $3" in *stop*) sleep 20;; esac\necho "Total running VMs: 0"\n', '')
        m = self.m
        m.START_WAIT = 2
        t0 = time.time()
        out = m.t_vm_power({'vm': self.vmx, 'action': 'stop'})
        self.assertLess(time.time() - t0, 8)
        self.assertIn('still in progress', out)

    def test_guest_console_code_page_is_probed_once(self):
        m = self.m
        calls = []
        real = m.t_vm_run
        m.t_vm_run = lambda a: calls.append(a) or 'P\xe1gina de c\xf3digo ativa: 850'
        try:
            d = {'vmx': self.vmx, 'name': 'xp'}
            self.assertEqual(m._guest_oem_cp(d), 'cp850')
            self.assertEqual(m._guest_oem_cp(d), 'cp850')      # remembered in state.json
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['command'], 'chcp')
        finally:
            m.t_vm_run = real

    def test_state_file_with_bom_is_read(self):
        m = self.m
        m.set_vm_state(self.vmx, keyboard_layout='de')
        raw = open(m.state_path(), 'rb').read()
        open(m.state_path(), 'wb').write(b'\xef\xbb\xbf' + raw)      # as Notepad / PowerShell 5 would save it
        self.assertEqual(m.vm_state(self.vmx).get('keyboard_layout'), 'de')

    def test_mcp_handshake(self):
        p = subprocess.run([sys.executable, os.path.join(SERVER, 'vm_control.py')],
                           input=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                                 b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
                           stdout=subprocess.PIPE, timeout=30, env=dict(os.environ))
        lines = [json.loads(x) for x in p.stdout.decode().splitlines()]
        names = [t['name'] for t in lines[1]['result']['tools']]
        self.assertIn('vm_prepare', names)
        self.assertIn('vm_run', names)
        self.assertIn('vm_create', names)


class PackagingTest(unittest.TestCase):
    ROOT = os.path.join(HERE, '..')

    def test_every_tool_has_annotations(self):
        import vm_control
        tools = vm_control.handle({'id': 1, 'method': 'tools/list'})['result']['tools']
        self.assertEqual(len(tools), len(vm_control.TOOLS))
        for t in tools:
            a = t['annotations']
            self.assertTrue(a['title'])
            self.assertIn('readOnlyHint', a)
            self.assertFalse(a['openWorldHint'])
            if not a['readOnlyHint']:
                self.assertIn('destructiveHint', a)
        ro = {t['name'] for t in tools if t['annotations']['readOnlyHint']}
        self.assertEqual(ro, {'vm_list', 'vm_setup_help', 'vm_screenshot', 'vm_guest_info'})

    def test_mcp_json_runs_launcher_directly(self):
        # no "cmd /c" wrapper and forward slashes (the directory validator blocks a backslash path as computed): the directory scan holds servers started through a shell; the Claude app and
        # Claude Code both start a .cmd command themselves (tested 2026-10-19 on Windows 11)
        m = json.load(open(os.path.join(self.ROOT, 'plugins', 'vmware-vm-control', '.mcp.json')))
        srv = m['mcpServers']['vmware-vm-control']
        self.assertEqual(srv['command'], '${CLAUDE_PLUGIN_ROOT}/server/launch.cmd')  # literal path, forward slashes
        self.assertEqual(srv.get('args', []), [])

    def test_launcher_order_bundled_downloaded_installed_then_download(self):
        t = open(os.path.join(SERVER, 'launch.cmd'), encoding='ascii').read()
        emb, py, alias = t.index('..\\python\\python.exe'), t.index('where py'), t.index('python -c "import sys"')
        dl, fetch = t.index('%HOME_DIR%\\python\\python.exe'), t.index('get-python.ps1"')
        self.assertLess(emb, dl)                        # bundled first, then a Python downloaded earlier
        self.assertLess(dl, py)
        self.assertLess(py, alias)                      # plain "python" only after a real start check
        self.assertLess(alias, fetch)                   # download only when nothing else works
        self.assertNotIn('where python', t)

    def test_first_start_download_checks_hash_and_signature(self):
        t = open(os.path.join(SERVER, 'get-python.ps1'), encoding='ascii').read()
        self.assertIn('python-embed.txt', t)
        self.assertIn('Get-FileHash -Algorithm SHA256', t)
        self.assertIn('Get-AuthenticodeSignature', t)
        self.assertIn('Python Software Foundation', t)
        self.assertNotIn('Write-Output', t)             # stdout is the MCP channel

    def test_release_bundles_pinned_embeddable_python(self):
        import re
        t = open(os.path.join(self.ROOT, '.github', 'workflows', 'release.yml'), encoding='utf-8').read()
        self.assertIn('python-embed.txt', t)            # same pin as the first-start download
        self.assertIn('sha256sum -c', t)
        pin = open(os.path.join(SERVER, 'python-embed.txt'), encoding='ascii').read()
        self.assertRegex(pin, r'(?m)^version=3\.\d+\.\d+\s*$')
        self.assertRegex(pin, r'(?m)^sha256=[0-9a-f]{64}\s*$')
        self.assertTrue(re.search(r'unzip .*plugins/vmware-vm-control/python', t))
        self.assertIn('unzip -q python3*.zip -d Lib', t)          # the app refuses a zip inside the .plugin
        self.assertIn("grep -qi '\\.zip$'", t)

    def test_server_reports_version_and_python_origin(self):
        import vm_control
        self.assertIn(vm_control.SERVER_VERSION, vm_control.server_info())
        pth = 'python%d%d._pth' % sys.version_info[:2]
        old_exe, old_env = sys.executable, {k: os.environ.get(k) for k in ('HOME', 'USERPROFILE')}
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, pth), 'w').close()
            home_py = os.path.join(d, 'home', '.vmware-vm-control', 'python')
            os.makedirs(home_py)
            open(os.path.join(home_py, pth), 'w').close()
            try:
                sys.executable = os.path.join(d, 'python.exe')
                self.assertEqual(vm_control.python_origin(), 'bundled')
                os.environ['HOME'] = os.environ['USERPROFILE'] = os.path.join(d, 'home')
                sys.executable = os.path.join(home_py, 'python.exe')
                self.assertEqual(vm_control.python_origin(), 'downloaded')
            finally:
                sys.executable = old_exe
                for k, val in old_env.items():
                    if val is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = val
        self.assertEqual(vm_control.python_origin(), 'installed')

    def test_versions_match(self):
        import vm_control
        plugin = json.load(open(os.path.join(self.ROOT, 'plugins', 'vmware-vm-control', '.claude-plugin', 'plugin.json')))
        market = json.load(open(os.path.join(self.ROOT, '.claude-plugin', 'marketplace.json')))
        self.assertEqual(plugin['version'], vm_control.SERVER_VERSION)
        self.assertEqual(market['plugins'][0]['version'], vm_control.SERVER_VERSION)
        self.assertIn('## %s' % vm_control.SERVER_VERSION, open(os.path.join(self.ROOT, 'CHANGELOG.md'), encoding='utf-8').read())


if __name__ == '__main__':
    unittest.main(verbosity=2)
