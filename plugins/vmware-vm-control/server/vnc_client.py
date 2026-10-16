"""Minimal RFB (VNC) client using only the Python standard library.

Supports RFB 3.3 / 3.7 / 3.8, security types None and VNC Authentication,
the Raw encoding at 32 bpp, pointer and key events. Designed for the VNC
server embedded in VMware Workstation / Player (RemoteDisplay.vnc.*), which
works for any guest OS because it runs in the hypervisor, not in the guest.
"""
import socket
import struct
import time
import zlib

from vnc_des import vnc_auth_response

# ---------------------------------------------------------------- keysyms
KEYSYMS = {
    'enter': 0xff0d, 'return': 0xff0d, 'tab': 0xff09, 'esc': 0xff1b, 'escape': 0xff1b,
    'backspace': 0xff08, 'delete': 0xffff, 'del': 0xffff, 'insert': 0xff63, 'ins': 0xff63,
    'home': 0xff50, 'end': 0xff57, 'pageup': 0xff55, 'pgup': 0xff55, 'pagedown': 0xff56, 'pgdn': 0xff56,
    'left': 0xff51, 'up': 0xff52, 'right': 0xff53, 'down': 0xff54,
    'shift': 0xffe1, 'ctrl': 0xffe3, 'control': 0xffe3, 'alt': 0xffe9, 'altgr': 0xfe03,
    'win': 0xffeb, 'super': 0xffeb, 'cmd': 0xffeb, 'menu': 0xff67, 'apps': 0xff67,
    'space': 0x20, 'printscreen': 0xff61, 'prtsc': 0xff61, 'pause': 0xff13, 'capslock': 0xffe5,
    'numlock': 0xff7f, 'scrolllock': 0xff14,
}
for _i in range(1, 13):
    KEYSYMS['f%d' % _i] = 0xffbe + _i - 1


def char_keysym(ch):
    o = ord(ch)
    if ch == '\n':
        return 0xff0d
    if ch == '\t':
        return 0xff09
    if 0x20 <= o <= 0xff:
        return o
    return 0x01000000 | o


def key_keysym(name):
    n = name.strip().lower()
    if n in KEYSYMS:
        return KEYSYMS[n]
    if len(name.strip()) == 1:
        return char_keysym(name.strip())
    raise ValueError('Unknown key name: %r' % name)


# ---------------------------------------------------------------- PNG
def encode_png(width, height, rgb_rows):
    """rgb_rows: list of bytes objects, each width*3 long."""
    raw = b''.join(b'\x00' + r for r in rgb_rows)

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


class VNCError(Exception):
    pass


class VNCClient:
    def __init__(self, host, port, password=None, timeout=15):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self.sock = None
        self.width = self.height = 0
        self.fb = None  # bytearray BGRX, 4 bytes per pixel

    # -- low level
    def _recv(self, n):
        buf = b''
        while len(buf) < n:
            part = self.sock.recv(n - len(buf))
            if not part:
                raise VNCError('VNC connection closed by server')
            buf += part
        return buf

    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise VNCError('Cannot connect to VNC %s:%s (%s). Is the VM running and VNC enabled '
                           '(RemoteDisplay.vnc.enabled = "TRUE")?' % (self.host, self.port, e))
        ver = self._recv(12)
        if not ver.startswith(b'RFB '):
            raise VNCError('Not a VNC server: %r' % ver)
        major, minor = int(ver[4:7]), int(ver[8:11])
        minor = 8 if (major, minor) >= (3, 8) else (7 if (major, minor) >= (3, 7) else 3)
        self.sock.sendall(b'RFB 003.%03d\n' % minor)
        if minor == 3:
            sec = struct.unpack('>I', self._recv(4))[0]
            if sec == 0:
                raise VNCError(self._reason())
        else:
            n = self._recv(1)[0]
            if n == 0:
                raise VNCError(self._reason())
            types = list(self._recv(n))
            if 2 in types and self.password:
                sec = 2
            elif 1 in types:
                sec = 1
            elif 2 in types:
                raise VNCError('VNC server requires a password; set vnc_password for this VM in the config file.')
            else:
                raise VNCError('Unsupported VNC security types: %s' % types)
            self.sock.sendall(bytes([sec]))
        if sec == 2:
            if not self.password:
                raise VNCError('VNC server requires a password; set vnc_password for this VM in the config file.')
            challenge = self._recv(16)
            self.sock.sendall(vnc_auth_response(self.password, challenge))
        if sec == 2 or minor == 8:
            result = struct.unpack('>I', self._recv(4))[0]
            if result != 0:
                raise VNCError('VNC authentication failed' + (': ' + self._reason() if minor == 8 else '')
                               + '. Check vnc_password (max. 8 characters).')
        self.sock.sendall(b'\x01')  # ClientInit: shared session
        w, h = struct.unpack('>HH', self._recv(4))
        self._recv(16)  # server pixel format (we set our own)
        name_len = struct.unpack('>I', self._recv(4))[0]
        self.name = self._recv(name_len).decode('latin-1', 'replace')
        self.width, self.height = w, h
        # SetPixelFormat: 32bpp, depth 24, little endian, true colour, R<<16 G<<8 B
        pf = struct.pack('>BBBBHHHBBB3x', 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.sock.sendall(b'\x00\x00\x00\x00' + pf)
        # SetEncodings: Raw (0) + DesktopSize pseudo-encoding (-223)
        self.sock.sendall(struct.pack('>BBHii', 2, 0, 2, 0, -223))
        return self

    def _reason(self):
        n = struct.unpack('>I', self._recv(4))[0]
        return self._recv(n).decode('latin-1', 'replace')

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *a):
        self.close()

    # -- framebuffer
    def capture(self):
        """Request a full, non-incremental framebuffer update and read it."""
        self.fb = bytearray(self.width * self.height * 4)
        self.sock.sendall(struct.pack('>BBHHHH', 3, 0, 0, 0, self.width, self.height))
        got_pixels = False
        deadline = time.time() + self.timeout
        while not got_pixels:
            if time.time() > deadline:
                raise VNCError('Timeout waiting for the VNC framebuffer')
            mtype = self._recv(1)[0]
            if mtype == 0:  # FramebufferUpdate
                self._recv(1)
                nrect = struct.unpack('>H', self._recv(2))[0]
                for _ in range(nrect):
                    x, y, w, h, enc = struct.unpack('>HHHHi', self._recv(12))
                    if enc == 0:
                        data = self._recv(w * h * 4)
                        for row in range(h):
                            dst = ((y + row) * self.width + x) * 4
                            self.fb[dst:dst + w * 4] = data[row * w * 4:(row + 1) * w * 4]
                        got_pixels = True
                    elif enc == -223:  # DesktopSize: resolution changed
                        self.width, self.height = w, h
                        self.fb = bytearray(w * h * 4)
                        self.sock.sendall(struct.pack('>BBHHHH', 3, 0, 0, 0, w, h))
                    else:
                        raise VNCError('Unexpected VNC encoding %d' % enc)
            elif mtype == 1:  # SetColourMapEntries
                self._recv(3)
                n = struct.unpack('>H', self._recv(2))[0]
                self._recv(n * 6)
            elif mtype == 2:  # Bell
                pass
            elif mtype == 3:  # ServerCutText
                self._recv(3)
                self._recv(struct.unpack('>I', self._recv(4))[0])
            else:
                raise VNCError('Unexpected VNC message type %d' % mtype)
        return self.width, self.height

    def png(self, region=None, scale=1.0):
        """Encode the framebuffer (optionally a region x0,y0,x1,y1, then scaled) as PNG.
        Returns (png_bytes, out_w, out_h)."""
        x0, y0, x1, y1 = region if region else (0, 0, self.width, self.height)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.width, int(x1)), min(self.height, int(y1))
        sw, sh = x1 - x0, y1 - y0
        ow, oh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
        xs = [x0 + min(sw - 1, int(i / scale)) for i in range(ow)]
        rows = []
        fb, W = self.fb, self.width
        for j in range(oh):
            yy = y0 + min(sh - 1, int(j / scale))
            base = yy * W * 4
            line = fb[base:base + W * 4]
            # BGRX little-endian -> RGB
            if scale == 1.0 and x0 == 0 and x1 == W:
                b = bytes(line)
                r = bytearray(W * 3)
                r[0::3] = b[2::4]
                r[1::3] = b[1::4]
                r[2::3] = b[0::4]
                rows.append(bytes(r))
            else:
                r = bytearray(ow * 3)
                for i, xx in enumerate(xs):
                    p = xx * 4
                    r[i * 3] = line[p + 2]
                    r[i * 3 + 1] = line[p + 1]
                    r[i * 3 + 2] = line[p]
                rows.append(bytes(r))
        return encode_png(ow, oh, rows), ow, oh

    # -- input
    def pointer(self, x, y, mask=0):
        x = max(0, min(self.width - 1, int(x)))
        y = max(0, min(self.height - 1, int(y)))
        self.sock.sendall(struct.pack('>BBHH', 5, mask, x, y))

    def click(self, x, y, button='left', double=False):
        bit = {'left': 1, 'middle': 2, 'right': 4}[button]
        self.pointer(x, y, 0)
        time.sleep(0.05)
        for _ in range(2 if double else 1):
            self.pointer(x, y, bit)
            time.sleep(0.06)
            self.pointer(x, y, 0)
            time.sleep(0.08)

    def drag(self, x0, y0, x1, y1, steps=12):
        self.pointer(x0, y0, 0)
        time.sleep(0.05)
        self.pointer(x0, y0, 1)
        time.sleep(0.1)
        for s in range(1, steps + 1):
            self.pointer(x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps, 1)
            time.sleep(0.03)
        self.pointer(x1, y1, 0)

    def scroll(self, x, y, direction='down', amount=3):
        bit = {'up': 8, 'down': 16, 'left': 32, 'right': 64}[direction]
        for _ in range(amount):
            self.pointer(x, y, bit)
            time.sleep(0.03)
            self.pointer(x, y, 0)
            time.sleep(0.03)

    def key(self, keysym, down):
        self.sock.sendall(struct.pack('>BBxxI', 4, 1 if down else 0, keysym))

    def press_combo(self, combo, repeat=1):
        """combo like 'ctrl+alt+delete', 'alt+f4', 'enter'."""
        parts = [p for p in combo.replace(' ', '').split('+') if p] if combo.strip() != '+' else ['+']
        syms = [key_keysym(p) for p in parts]
        for _ in range(repeat):
            for s in syms:
                self.key(s, True)
                time.sleep(0.03)
            for s in reversed(syms):
                self.key(s, False)
                time.sleep(0.03)
            time.sleep(0.05)

    def run_events(self, events, delay=0.015):
        for e in events:
            if e[0] == 'key':
                self.key(e[1], e[2])
                time.sleep(delay)

    def type_text(self, text, delay=0.02):
        for ch in text:
            s = char_keysym(ch)
            self.key(s, True)
            time.sleep(delay)
            self.key(s, False)
            time.sleep(delay)
