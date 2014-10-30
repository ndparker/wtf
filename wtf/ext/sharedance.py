# -*- coding: ascii -*-
#
# Copyright 2007-2012
# Andr\xe9 Malo or his licensors, as applicable
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
================
 Sharedance API
================

This module implements a sharedance_ API implementation and connector.

.. _sharedance: http://sharedance.pureftpd.org/project/sharedance

:Variables:
 - `DEFAULT_PORT`: Sharedance default port
 - `FLAG_COMPRESSED`: Flag for compressed storage
 - `NO_FLAGS`: Bit mask for checking invalid flag bits

:Types:
 - `DEFAULT_PORT`: ``int``
 - `FLAG_COMPRESSED`: ``int``
 - `NO_FLAGS`: ``int``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import itertools as _it
import os as _os
import socket as _socket
import struct as _struct
try:
    import zlib as _zlib
except ImportError:
    _zlib = None

from wtf import Error
from wtf import osutil as _osutil
from wtf import stream as _stream
from wtf import util as _util

DEFAULT_PORT = 1042

FLAG_COMPRESSED = 1 # 2 ** 0
NO_FLAGS = ~(FLAG_COMPRESSED)

# python hash() differs between 32bit and 64bit!
hashfunc = _util.hash32


class SharedanceError(Error):
    """ Sharedance communication error """

class SharedanceConnectError(SharedanceError):
    """ Sharedance connection error """

class SharedanceCommandError(SharedanceError):
    """ Sharedance command error """

class SharedanceFormatError(SharedanceError):
    """ The format of received extended data is broken """


def escape(value):
    """
    Escape a value as a sharedance key

    The value will be Base64 encoded (but with a slightly modified alphabet)

    :Parameters:
     - `value`: Value to escape

    :Types:
     - `value`: ``str``

    :return: The escaped value
    :rtype: ``str``
    """
    return value.encode('base64').replace('\n', '').replace('=', ''
        ).replace('/', '_').replace('+', '-')


class Sharedance(object):
    """
    Sharedance API

    :IVariables:
     - `conns`: List of connectors
     - `_weighted`: Weighted list of connectors

    :Types:
     - `conns`: ``tuple``
     - `_weighted`: ``tuple``
    """

    def __init__(self, conns):
        """
        Initialization

        :Parameters:
         - `conns`: List of sharedance connectors

        :Types:
         - `conns`: ``iterable``
        """
        self.conns = tuple(conns)
        self._weighted = tuple(_it.chain(*[[conn] * conn.weight
            for conn in self.conns]))

    def store(self, key, data):
        """ Store an item """
        return self._get_conn(key).store(key, data)

    def fetch(self, key):
        """ Fetch an item """
        return self._get_conn(key).fetch(key)

    def delete(self, key):
        """ Delete a key """
        return self._get_conn(key).delete(key)

    def check(self, key=None, content=None, fetch=None):
        """ Check the servers for functionality """
        return [conn.check(key=key, content=content, fetch=fetch)
            for conn in self.conns]

    def _get_conn(self, key):
        """ Determine connector based on the weighted list """
        return self._weighted[int(abs(hashfunc(key))) % len(self._weighted)]


class _Connected(_util.BaseDecorator):
    """ Separation of the socket handling out of the connection object """

    def __call__(self, inst, *args, **kwargs):
        """
        Decorating logic

        :Parameters:
         - `inst`: Proxy instance
         - `args`: function parameters
         - `kwargs`: function parameters

        :Types:
         - `inst`: `Sharedance`
         - `args`: ``tuple``
         - `kwargs`: ``dict``

        :return: Whatever the deocorated function returns
        :rtype: any
        """
        # pylint: disable = W0221

        try:
            sock = _osutil.connect((inst.host, inst.port),
                timeout=inst.timeout, cache=3600)
            if sock is None:
                raise SharedanceConnectError(
                    "No connectable address found for %s:%s" % (
                        inst.host, inst.port
                    )
                )
            try:
                conn = \
                    _stream.GenericStream(
                        _stream.MinimalSocketStream(sock), read_exact=True
                    )
                try:
                    kwargs['_conn'] = conn
                    return self._func(inst, *args, **kwargs)
                finally:
                    sock, _ = None, conn.close()
            finally:
                if sock is not None:
                    sock.close()
        except (_osutil.SocketError, _socket.error), e:
            raise SharedanceConnectError(str(e))


class SharedanceConnector(object):
    """
    Sharedance connection abstraction

    If magic is enabled (see `__init__`), the data will be extended with
    the magic string (`_MAGIC`), followed by 0 byte, a flag number
    (decimal notation), a LF, the data length (decimal, too) and another
    LF. On the read this data will be used to transparently check for
    consistency and evaluate the flags (Currently there's only one:
    compressed)

    :CVariables:
     - `_RETURN_OK`: OK return value
     - `_MAGIC`: Magic string to mark our own format

    :Types:
     - `_RETURN_OK`: ``str``
     - `_MAGIC`: ``str``
    """
    _RETURN_OK = "OK\n"
    _MAGIC = "%#\\U;" # Looks strange? This is a classic! Have fun :-)

    def __init__(self, spec, compress_threshold=None, timeout=None,
                 weight=None, magic=-1):
        """
        Initialization

        The magic parameter determines whether the connection object should
        transparently handle extended values:

        ``0`` or ``False``
          No magic should be applied (neither on reads nor writes)
        ``1`` or ``True``
          Full magic should be applied
        ``-1``
          No write magic should be applied (but reads are interpreted)

        :Parameters:
         - `spec`: server spec
         - `timeout`: Timeout in seconds
         - `magic`: Magic behaviour

        :Types:
         - `spec`: ``tuple``
         - `timeout`: ``float``
         - `magic`: ``int``
        """
        self.host, self.port = spec
        self.timeout, self.magic = timeout, int(magic)
        self.compress_threshold = compress_threshold
        if weight is None:
            weight = 1
        self.weight = weight

    @_Connected
    def store(self, key, data, _conn=None):
        """
        Store data in sharedance

        :Parameters:
         - `key`: Key to store under
         - `data`: Data to store

        :Types:
         - `key`: ``str``
         - `data`: ``str``

        :Exceptions:
         - `SharedanceCommandError`: The storage was not successful
        """
        key, data = str(key), str(data)
        flags, vlen = 0, len(data)
        if self.magic > 0:
            if self.compress_threshold is not None and \
                    vlen >= self.compress_threshold and _zlib is not None:
                flags |= FLAG_COMPRESSED
                data = _zlib.compress(data)
                vlen = len(data)
            flags, dlen = str(flags), str(vlen)
            vlen += len(self._MAGIC) + len(flags) + len(dlen) + 3

        write = _conn.write
        write("S%s" % _struct.pack('!LL', len(key), vlen))
        write(key)
        if self.magic > 0:
            write("%s\0%s\n%s\n" % (self._MAGIC, flags, dlen))
        write(data)
        _conn.flush()
        res = _conn.read()
        if res != self._RETURN_OK:
            raise SharedanceCommandError(
                "Storage failed for key %s: %r" % (key, res)
            )

    @_Connected
    def fetch(self, key, _conn=None):
        """
        Fetch data from sharedance

        :Parameters:
         - `key`: The key to fetch

        :Types:
         - `key`: ``str``

        :Exceptions:
         - `KeyError`: The key does not exist
         - `SharedanceCommandError`: The result was not interpretable
        """
        key, write = str(key), _conn.write
        write("F%s" % _struct.pack('!L', len(key)))
        write(key)
        _conn.flush()

        expected, flags = -1, 0
        if self.magic:
            value = _stream.read_exact(_conn, len(self._MAGIC))
            if not value:
                raise KeyError(key)
            elif value == self._MAGIC and _conn.read(1) == '\0':
                line = _conn.readline()
                try:
                    flags = int(line.rstrip())
                except (TypeError, ValueError):
                    raise SharedanceFormatError("Invalid flags: %r" % line)
                if flags & NO_FLAGS:
                    raise SharedanceFormatError(
                        "Unrecognized flags: %s" % flags)
                line = _conn.readline()
                try:
                    expected = int(line.rstrip())
                except (TypeError, ValueError):
                    raise SharedanceFormatError(
                        "Invalid value length: %r" % line)

        data = _stream.read_exact(_conn, expected)

        if expected >= 0 and len(data) != expected:
            raise SharedanceCommandError("Fetch incomplete")
        if flags & FLAG_COMPRESSED:
            if _zlib is None:
                raise SharedanceCommandError(
                    "Cannot uncompress fetched value (no zlib)")
            else:
                try:
                    data = _zlib.decompress(data)
                except _zlib.error, e:
                    raise SharedanceFormatError(
                        "Decompression error: %s" % str(e))
        return data

    @_Connected
    def delete(self, key, _conn=None):
        """
        Delete data from sharedance

        :Parameters:
         - `key`: The key to delete

        :Types:
         - `key`: ``str``
        """
        key, write = str(key), _conn.write
        write("D%s" % _struct.pack('!L', len(key)))
        write(key)
        _conn.flush()
        if _conn.read() != self._RETURN_OK:
            raise SharedanceCommandError("Deletion failed")

    def check(self, key=None, content=None, fetch=None):
        """
        Check sharedance server for functionality

        The check results are stored in a dict with the following keys:

        ``spec``
          [tuple] host and port (``('host', port)``)
        ``error``
          [bool] Was there an error?
        ``status``
          [unicode] Human readable status description
        ``time``
          [int] Time taken for the whole check in microseconds
          (basically a store/fetch/delete cycle)
        ``weight``
          [int] Weight of this particular sharedance (just for convenience)

        :Parameters:
         - `key`: Key to store under. If omitted or ``None`` it defaults to
           ``CHECK-<random>``.
         - `content`: Content to store. If omitted or ``None`` it defaults
           to a random string
         - `fetch`: Try fetching the content? If omitted or ``None`` it
           defaults to ``True``

        :Types:
         - `key`: ``str``
         - `content`: ``str``
         - `fetch`: ``bool``

        :return: Check results
        :rtype: ``dict``
        """
        # pylint: disable = R0912

        if key is None:
            key = "CHECK-%s" % escape(_os.urandom(6))
        if content is None:
            content = _os.urandom(8)
        if fetch is None:
            fetch = True

        error, status = False, u"OK"
        start = _datetime.datetime.utcnow()

        try:
            self.store(key, content)
        except SharedanceError, e:
            error, status = True, u"Store of %s failed: %s" % (
                repr(key).decode('latin-1'),
                str(e).decode('latin-1'),
            )
        else:
            try:
                if fetch:
                    result = self.fetch(key)
                else:
                    result = content
            except KeyError:
                error, status = (
                    True,
                    u"Fetch failed: Key does not exist: %s" %
                        repr(key).decode('latin-1')
                )
            except SharedanceError, e:
                error, status = True, u"Fetch of %s failed: %s" % (
                    repr(key).decode('latin-1'),
                    str(e).decode('latin-1'),
                )
            else:
                if result != content:
                    error, status = (
                        True,
                        u"Store/Fetch cycle of %s failed: %s != %s" % (
                            repr(key).decode('latin-1'),
                            repr(result).decode('latin-1'),
                            repr(content).decode('latin-1'),
                        )
                    )

            # Always try to delete, once it was stored
            try:
                self.delete(key)
            except SharedanceError, e:
                msg = u"Deletion of %s failed: %s" % (
                    repr(key).decode('latin-1'), str(e).decode('latin-1')
                )
                if error:
                    status = u", ".join(status, msg)
                else:
                    error, status = True, msg

        timediff = _datetime.datetime.utcnow() - start
        timediff = timediff.seconds * 1000000 + timediff.microseconds
        return dict(
            spec = (self.host, self.port),
            error = error,
            status = status,
            time = timediff,
            weight = self.weight,
        )
