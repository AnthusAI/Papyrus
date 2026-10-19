"""Minimal generic-password adapter to Apple's supported Security framework.

No subprocess password arguments, token files, or third-party keyring fallback.
Frameworks load only when a real interactive CLI session requests this adapter.
"""
from __future__ import annotations
import ctypes as C
import sys


class MacOSKeychain:
    def __init__(self):
        if sys.platform != 'darwin':
            raise RuntimeError('macOS Keychain is required')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.sec = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        signatures = {
            'CFStringCreateWithCString': ([C.c_void_p, C.c_char_p, C.c_uint32], C.c_void_p),
            'CFDataCreate': ([C.c_void_p, C.c_void_p, C.c_long], C.c_void_p),
            'CFDictionaryCreate': ([C.c_void_p, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p), C.c_long, C.c_void_p, C.c_void_p], C.c_void_p),
            'CFDataGetLength': ([C.c_void_p], C.c_long),
            'CFDataGetBytePtr': ([C.c_void_p], C.c_void_p),
            'CFRelease': ([C.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.cf, name)
            function.argtypes, function.restype = arguments, result
        for name, args in {
            'SecItemAdd':[C.c_void_p,C.POINTER(C.c_void_p)],
            'SecItemCopyMatching':[C.c_void_p,C.POINTER(C.c_void_p)],
            'SecItemUpdate':[C.c_void_p,C.c_void_p],
            'SecItemDelete':[C.c_void_p],
        }.items():
            function = getattr(self.sec, name)
            function.argtypes, function.restype = args, C.c_int32

    def _constant(self, name):
        return C.c_void_p.in_dll(self.sec, name).value

    def _dictionary(self, service, account, *, value=None, read=False, payload_only=False):
        owned=[]
        pairs=[]
        def text(name, value):
            pointer=self.cf.CFStringCreateWithCString(None,value.encode('utf-8'),0x08000100)
            if not pointer:raise RuntimeError('Keychain allocation failed')
            owned.append(pointer);pairs.append((self._constant(name),pointer))
        if not payload_only:
            pairs.append((self._constant('kSecClass'),self._constant('kSecClassGenericPassword')))
            text('kSecAttrService',service);text('kSecAttrAccount',account)
            # Do not trigger an unexpected unlock/authentication dialog from a worker.
            pairs.append((self._constant('kSecUseAuthenticationUI'),self._constant('kSecUseAuthenticationUIFail')))
        if read:
            pairs.append((self._constant('kSecReturnData'),C.c_void_p.in_dll(self.cf,'kCFBooleanTrue').value))
            pairs.append((self._constant('kSecMatchLimit'),self._constant('kSecMatchLimitOne')))
        if value is not None:
            encoded=value.encode('utf-8')
            pointer=self.cf.CFDataCreate(None,encoded,len(encoded))
            if not pointer:raise RuntimeError('Keychain allocation failed')
            owned.append(pointer);pairs.append((self._constant('kSecValueData'),pointer))
        keys=(C.c_void_p*len(pairs))(*(x[0] for x in pairs))
        values=(C.c_void_p*len(pairs))(*(x[1] for x in pairs))
        pointer=self.cf.CFDictionaryCreate(None,keys,values,len(pairs),None,None)
        if not pointer:raise RuntimeError('Keychain allocation failed')
        return pointer,owned

    def _release(self, dictionary):
        pointer,owned=dictionary
        self.cf.CFRelease(pointer)
        for item in owned:self.cf.CFRelease(item)

    def get_password(self, service, account):
        dictionary=self._dictionary(service,account,read=True)
        result=C.c_void_p()
        try:
            status=self.sec.SecItemCopyMatching(dictionary[0],C.byref(result))
            if status == -25300:return None # errSecItemNotFound
            if status != 0:raise RuntimeError('Keychain read failed')
            try:
                return C.string_at(self.cf.CFDataGetBytePtr(result),self.cf.CFDataGetLength(result)).decode('utf-8')
            finally:self.cf.CFRelease(result)
        finally:self._release(dictionary)

    def set_password(self, service, account, value):
        dictionary=self._dictionary(service,account,value=value)
        try:
            status=self.sec.SecItemAdd(dictionary[0],None)
        finally:self._release(dictionary)
        if status == -25299: # errSecDuplicateItem: update without deleting the old secret first.
            query=self._dictionary(service,account)
            payload=self._dictionary(service,account,value=value,payload_only=True)
            try:status=self.sec.SecItemUpdate(query[0],payload[0])
            finally:self._release(payload);self._release(query)
        if status != 0:raise RuntimeError('Keychain save failed')

    def delete_password(self, service, account):
        dictionary=self._dictionary(service,account)
        try:status=self.sec.SecItemDelete(dictionary[0])
        finally:self._release(dictionary)
        if status not in (0,-25300):raise RuntimeError('Keychain delete failed')
