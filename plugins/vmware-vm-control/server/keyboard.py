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


import unicodedata as _ud

_DEAD_NAMES = {'´': 'ACUTE', '`': 'GRAVE', '~': 'TILDE', '^': 'CIRCUMFLEX', '¨': 'DIAERESIS'}


def _build(rows, dead, extra_comb=None):
    """rows: {char: (us_key, shift, altgr)}; dead: {dead_char: (us_key, shift, altgr)}.
    Letters keep their US positions unless overridden in rows. Each dead key gives the bare accent
    (dead + space) and the accented vowels (dead + letter). Characters not listed (e.g. the extra
    ISO key left of Z: < > |) fall back to Alt+0NNN in plan()."""
    m = _us_base()
    for ch, st in rows.items():
        m[ch] = [st]
    for ch, st in dead.items():
        m[ch] = [st, (' ', False, False)]
    for dk, st in dead.items():
        for L in 'aeiouyncAEIOUYNC':
            try:
                acc = _ud.lookup('LATIN %s LETTER %s WITH %s' % (
                    'CAPITAL' if L.isupper() else 'SMALL', L.upper(), _DEAD_NAMES[dk]))
            except KeyError:
                continue
            if acc not in rows:
                m[acc] = [st] + m[L]
    for ch, strokes in (extra_comb or {}).items():
        m[ch] = strokes
    return m


def layout_us_intl():
    """United States-International - KLID 00020409: ' " ` ~ ^ are dead keys."""
    rows = {}
    for base, shifted in {'1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '7': '&', '8': '*', '9': '(', '0': ')',
                          '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|', ';': ':', ',': '<', '.': '>',
                          '/': '?'}.items():
        rows[base] = (base, False, False)
        rows[shifted] = (base, True, False)
    dead = {'´': ("'", False, False), '¨': ("'", True, False), '`': ('`', False, False), '~': ('`', True, False),
            '^': ('6', True, False)}
    m = _build(rows, dead, {"'": [("'", False, False), (' ', False, False)],
                            '"': [("'", True, False), (' ', False, False)]})
    m['ç'] = [("'", False, False), ('c', False, False)]
    m['Ç'] = [("'", False, False), ('c', True, False)]
    return m


def layout_de():
    """German (QWERTZ) - KLID 00000407."""
    S, A = True, True
    r = {'z': ('y', False, False), 'Z': ('y', S, False), 'y': ('z', False, False), 'Y': ('z', S, False),
         '!': ('1', S, False), '"': ('2', S, False), '§': ('3', S, False), '$': ('4', S, False),
         '%': ('5', S, False), '&': ('6', S, False), '/': ('7', S, False), '(': ('8', S, False),
         ')': ('9', S, False), '=': ('0', S, False), '²': ('2', False, A), '³': ('3', False, A),
         '{': ('7', False, A), '[': ('8', False, A), ']': ('9', False, A), '}': ('0', False, A),
         'ß': ('-', False, False), '?': ('-', S, False), '\\': ('-', False, A),
         'ü': ('[', False, False), 'Ü': ('[', S, False), '+': (']', False, False), '*': (']', S, False),
         '~': (']', False, A), 'ö': (';', False, False), 'Ö': (';', S, False), 'ä': ("'", False, False),
         'Ä': ("'", S, False), '#': ('\\', False, False), "'": ('\\', S, False), '°': ('`', S, False),
         ',': (',', False, False), ';': (',', S, False), '.': ('.', False, False), ':': ('.', S, False),
         '-': ('/', False, False), '_': ('/', S, False), '@': ('q', False, A), '€': ('e', False, A),
         'µ': ('m', False, A)}
    dead = {'^': ('`', False, False), '´': ('=', False, False), '`': ('=', S, False)}
    m = _build(r, dead)
    # accented y/z must use the swapped physical keys
    for acc in ('ý', 'Ý'):
        m[acc] = [dead['´'], ('z', acc.isupper(), False)]
    return m


def layout_es():
    """Spanish (Spain) - KLID 0000040A."""
    S, A = True, True
    r = {'!': ('1', S, False), '"': ('2', S, False), '·': ('3', S, False), '$': ('4', S, False),
         '%': ('5', S, False), '&': ('6', S, False), '/': ('7', S, False), '(': ('8', S, False),
         ')': ('9', S, False), '=': ('0', S, False), '|': ('1', False, A), '@': ('2', False, A),
         '#': ('3', False, A), '~': ('4', False, A), '¬': ('6', False, A), '€': ('e', False, A),
         "'": ('-', False, False), '?': ('-', S, False), '¡': ('=', False, False), '¿': ('=', S, False),
         '[': ('[', False, A), '+': (']', False, False), '*': (']', S, False), ']': (']', False, A),
         'ñ': (';', False, False), 'Ñ': (';', S, False), '{': ("'", False, A),
         'ç': ('\\', False, False), 'Ç': ('\\', S, False), '}': ('\\', False, A),
         'º': ('`', False, False), 'ª': ('`', S, False), '\\': ('`', False, A),
         ',': (',', False, False), ';': (',', S, False), '.': ('.', False, False), ':': ('.', S, False),
         '-': ('/', False, False), '_': ('/', S, False)}
    dead = {'`': ('[', False, False), '^': ('[', S, False), '´': ("'", False, False), '¨': ("'", S, False)}
    return _build(r, dead)


def layout_pt():
    """Portuguese (Portugal) - KLID 00000816."""
    S, A = True, True
    r = {'!': ('1', S, False), '"': ('2', S, False), '#': ('3', S, False), '$': ('4', S, False),
         '%': ('5', S, False), '&': ('6', S, False), '/': ('7', S, False), '(': ('8', S, False),
         ')': ('9', S, False), '=': ('0', S, False), '@': ('2', False, A), '£': ('3', False, A),
         '§': ('4', False, A), '{': ('7', False, A), '[': ('8', False, A), ']': ('9', False, A),
         '}': ('0', False, A), '€': ('e', False, A),
         "'": ('-', False, False), '?': ('-', S, False), '«': ('=', False, False), '»': ('=', S, False),
         '+': ('[', False, False), '*': ('[', S, False), 'ç': (';', False, False), 'Ç': (';', S, False),
         'º': ("'", False, False), 'ª': ("'", S, False), '\\': ('`', False, False), '|': ('`', S, False),
         ',': (',', False, False), ';': (',', S, False), '.': ('.', False, False), ':': ('.', S, False),
         '-': ('/', False, False), '_': ('/', S, False)}
    dead = {'´': (']', False, False), '`': (']', S, False), '~': ('\\', False, False), '^': ('\\', S, False),
            '¨': ('[', False, A)}
    return _build(r, dead)


LAYOUTS = {'us': layout_us, 'abnt2': layout_abnt2, 'us-intl': layout_us_intl, 'de': layout_de,
           'es': layout_es, 'pt': layout_pt}
KLID_TO_LAYOUT = {'00000409': 'us', '00000416': 'abnt2', '00010416': 'abnt2', '00020409': 'us-intl',
                  '00000407': 'de', '0000040a': 'es', '00000816': 'pt'}
# fallback by language id (last 4 hex digits of the KLID)
LANG_TO_LAYOUT = {'0409': 'us', '0416': 'abnt2', '0407': 'de', '040a': 'es', '0c0a': 'es', '0816': 'pt'}


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
