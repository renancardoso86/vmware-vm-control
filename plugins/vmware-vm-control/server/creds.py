"""Guest credentials without plain-text files.

Windows host: the user types the guest login into the native Windows credential
dialog (CredUIPromptForCredentialsW) and it is stored, encrypted per user, in the
Windows Credential Manager (CredWriteW, generic credential). Claude never sees
the password. Other hosts: environment variable or config file (see README).
"""
import os

IS_WIN = os.name == 'nt'
PREFIX = 'vmware-vm-control:'


def target_for(vmx):
    return PREFIX + os.path.normcase(os.path.abspath(vmx))


if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [('dwLowDateTime', wintypes.DWORD), ('dwHighDateTime', wintypes.DWORD)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                    ('Comment', wintypes.LPWSTR), ('LastWritten', FILETIME),
                    ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)),
                    ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]

    class CREDUI_INFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('hwndParent', wintypes.HWND), ('pszMessageText', wintypes.LPCWSTR),
                    ('pszCaptionText', wintypes.LPCWSTR), ('hbmBanner', wintypes.HBITMAP)]

    _adv = ctypes.WinDLL('advapi32', use_last_error=True)
    _credui = ctypes.WinDLL('credui', use_last_error=True)
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]
    _credui.CredUIPromptForCredentialsW.argtypes = [
        ctypes.POINTER(CREDUI_INFOW), wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
        wintypes.LPWSTR, wintypes.ULONG, wintypes.LPWSTR, wintypes.ULONG, ctypes.POINTER(wintypes.BOOL),
        wintypes.DWORD]
    _credui.CredUIPromptForCredentialsW.restype = wintypes.DWORD
    CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def read(vmx):
    """Return (user, password) or (None, None)."""
    if not IS_WIN:
        return None, None
    p = ctypes.POINTER(CREDENTIALW)()
    if not _adv.CredReadW(target_for(vmx), CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None, None
    try:
        c = p.contents
        blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return c.UserName, blob.decode('utf-16-le')
    finally:
        _adv.CredFree(p)


def write(vmx, user, password, comment='Guest login used by vmware-vm-control (vmrun guest operations)'):
    if not IS_WIN:
        raise RuntimeError('Credential Manager is only available on Windows hosts.')
    blob = password.encode('utf-16-le')
    buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob) if blob else (ctypes.c_byte * 1)()
    c = CREDENTIALW()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = target_for(vmx)
    c.Comment = comment
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    c.UserName = user
    if not _adv.CredWriteW(ctypes.byref(c), 0):
        raise OSError(ctypes.get_last_error(), 'CredWriteW failed')


def delete(vmx):
    if IS_WIN:
        return bool(_adv.CredDeleteW(target_for(vmx), CRED_TYPE_GENERIC, 0))
    return False


def prompt(vmx, vm_label, user_hint='', auth_error=0):
    """Show the native Windows credential dialog. Returns (user, password) or (None, None) if cancelled."""
    if not IS_WIN:
        raise RuntimeError('Interactive credential prompt is only available on Windows hosts; '
                           'use guest_password_env or the config file.')
    info = CREDUI_INFOW()
    info.cbSize = ctypes.sizeof(CREDUI_INFOW)
    info.pszCaptionText = 'vmware-vm-control - %s' % vm_label
    info.pszMessageText = ('Windows login of the VIRTUAL MACHINE "%s".\n'
                           'Used by VMware Tools to run commands and copy files in the VM. '
                           'Stored encrypted in this PC\'s Windows Credential Manager.' % vm_label)
    user = ctypes.create_unicode_buffer(user_hint or '', 514)
    pwd = ctypes.create_unicode_buffer(257)
    save = wintypes.BOOL(False)
    flags = 0x40000 | 0x80 | 0x2  # GENERIC_CREDENTIALS | ALWAYS_SHOW_UI | DO_NOT_PERSIST (we persist ourselves)
    rc = _credui.CredUIPromptForCredentialsW(ctypes.byref(info), 'VM: ' + vm_label, None, auth_error,
                                              user, 514, pwd, 257, ctypes.byref(save), flags)
    if rc == 1223:  # ERROR_CANCELLED
        return None, None
    if rc != 0:
        raise OSError(rc, 'CredUIPromptForCredentialsW failed')
    u, p = user.value, pwd.value
    ctypes.memset(pwd, 0, ctypes.sizeof(pwd))
    return u, p
