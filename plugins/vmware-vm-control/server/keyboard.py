"""Layout-aware typing for VMware's VNC server.

VMware's VNC server converts every keysym into the scan code of the key that
produces that character on a US keyboard, and it does NOT add Shift by itself.
So to type a character we must pick the *physical* key (named by its US
unshifted keysym) plus the modifiers that the GUEST's keyboard layout needs.

Each layout maps a character to a list of strokes; a stroke is
(us_key, shift, altgr). Dead keys are expressed as two strokes.
Characters with no mapping fall back to Alt + numpad code (Windows ANSI).
"""

SHIFT, CTRL, ALT = 0xffe1, 0xffe3, 0xffe9
KP = [0xffb0 + i for i in range(10)]  # KP_0 .. KP_9


def _k(ch):
    """keysym for a US physical key given by its unshifted character."""
    return 0x20 if ch == ' ' else ord(ch)


def _us_base():
    m = {}
    for c in 'abcdefghijklmnopqrstuvwxyz':
        m[c] = [(c, False, False)]
        m[c.upper()] = [(c, True, False)]
    for c in '0123456789 ':
        m[c] = [(c, False, False)]
    return m


def layout_us():
    m = _us_base()
    pairs = {'`': '~', '1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '6': '^', '7': '&', '8': '*', '9': '(',
             '0': ')', '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|', ';': ':', "'": '"', ',': '<', '.': '>',
             '/': '?'}
    for base, shifted in pairs.items():
        m[base] = [(base, False, False)]
        m[shifted] = [(base, True, False)]
    return m


def layout_abnt2():
    """Portuguese (Brazil) ABNT / ABNT2 - KLID 00000416 / 00010416."""
    m = _us_base()
    S, A = True, True

    def put(ch, key, shift=False, altgr=False):
        m[ch] = [(key, shift, altgr)]
    # number row (shifted symbols; '6' + shift is the dead diaeresis, below)
    put('!', '1', S); put('@', '2', S); put('#', '3', S); put('$', '4', S); put('%', '5', S)
    put('&', '7', S); put('*', '8', S); put('(', '9', S); put(')', '0', S)
    put('-', '-'); put('_', '-', S); put('=', '='); put('+', '=', S)
    put('¹', '1', altgr=A); put('²', '2', altgr=A); put('³', '3', altgr=A); put('£', '4', altgr=A)
    put('¢', '5', altgr=A); put('¬', '6', altgr=A); put('§', '=', altgr=A)
    # key left of 1 (US `)
    put("'", '`'); put('"', '`', S)
    # US [ = dead acute / dead grave ; US ] = [ {
    put('[', ']'); put('{', ']', S); put('ª', ']', altgr=A)
    # US ; = ç ; US ' = dead tilde / dead circumflex ; US \ = ] }
    put('ç', ';'); put('Ç', ';', S)
    put(']', '\\'); put('}', '\\', S); put('º', '\\', altgr=A)
    put(',', ','); put('<', ',', S); put('.', '.'); put('>', '.', S)
    put(';', '/'); put(':', '/', S)
    put('/', 'q', altgr=A); put('?', 'w', altgr=A); put('°', 'e', altgr=A)
    # dead keys
    dead = {'´': ('[', False), '`': ('[', True), '~': ("'", False), '^': ("'", True), '¨': ('6', True)}
    for ch, (key, sh) in dead.items():
        m[ch] = [(key, sh, False), (' ', False, False)]
    comb = {'´': 'aeiouyAEIOUY', '`': 'aeiouAEIOU', '~': 'aonAON', '^': 'aeiouAEIOU', '¨': 'aeiouyAEIOU'}
    import unicodedata
    names = {'´': 'ACUTE', '`': 'GRAVE', '~': 'TILDE', '^': 'CIRCUMFLEX', '¨': 'DIAERESIS'}
    for dk, letters in comb.items():
        key, sh = dead[dk]
        for L in letters:
            try:
                ch = unicodedata.lookup('LATIN %s LETTER %s WITH %s' % (
                    'CAPITAL' if L.isupper() else 'SMALL', L.upper(), names[dk]))
            except KeyError:
                continue
            m[ch] = [(key, sh, False)] + m[L]
    return m


LAYOUTS = {'us': layout_us, 'abnt2': layout_abnt2}
KLID_TO_LAYOUT = {'00000409': 'us', '00000416': 'abnt2', '00010416': 'abnt2'}
# fallback by language id (last 4 hex digits of the KLID)
LANG_TO_LAYOUT = {'0409': 'us', '0416': 'abnt2'}


def plan(text, layout='us'):
    """Return (events, unsupported). events: list of ('key', keysym, down) / ('sleep',)"""
    table = LAYOUTS.get(layout, layout_us)()
    ev, bad = [], []
    for ch in text:
        if ch == '\n':
            ev += [('key', 0xff0d, True), ('key', 0xff0d, False)]
            continue
        if ch == '\t':
            ev += [('key', 0xff09, True), ('key', 0xff09, False)]
            continue
        strokes = table.get(ch)
        if strokes:
            for key, shift, altgr in strokes:
                mods = ([CTRL, ALT] if altgr else []) + ([SHIFT] if shift else [])
                ev += [('key', m_, True) for m_ in mods]
                ev += [('key', _k(key), True), ('key', _k(key), False)]
                ev += [('key', m_, False) for m_ in reversed(mods)]
            continue
        try:
            code = ch.encode('cp1252')[0]
        except UnicodeEncodeError:
            bad.append(ch)
            continue
        digits = '0%03d' % code  # Alt+0NNN = Windows ANSI code page
        ev.append(('key', ALT, True))
        for dgt in digits:
            ev += [('key', KP[int(dgt)], True), ('key', KP[int(dgt)], False)]
        ev.append(('key', ALT, False))
    return ev, bad
