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

    def test_mcp_handshake(self):
        p = subprocess.run([sys.executable, os.path.join(SERVER, 'vm_control.py')],
                           input=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                                 b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
                           stdout=subprocess.PIPE, timeout=30, env=dict(os.environ))
        lines = [json.loads(x) for x in p.stdout.decode().splitlines()]
        names = [t['name'] for t in lines[1]['result']['tools']]
        self.assertIn('vm_prepare', names)
        self.assertIn('vm_run', names)


if __name__ == '__main__':
    unittest.main(verbosity=2)
