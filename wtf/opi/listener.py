# -*- coding: ascii -*-
#
# Copyright 2006-2012
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
Listener Socket
===============

Here's the abstraction to the socket handling implemented.

:Variables:
 - `AF_INET`: INET address family
 - `AF_INET6`: INET6 address family (``None`` if not available)
 - `AF_UNIX`: UNIX address family (``None`` if not available)

:Types:
 - `AF_INET`: ``int``
 - `AF_INET6`: ``int``
 - `AF_UNIX`: ``int``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import os as _os
import re as _re
import socket as _socket
import sys as _sys
import warnings as _warnings

from wtf import Error, WtfWarning
from wtf import osutil as _osutil
from wtf.config import ConfigurationError

AF_INET = _socket.AF_INET
AF_INET6 = getattr(_socket, "AF_INET6", None)
AF_UNIX = getattr(_socket, "AF_UNIX", None)


class ShutdownWarning(WtfWarning):
    """ Socket shutdown failures """

class ListenerWarning(WtfWarning):
    """ Duplicate listener detected """

class SocketError(Error):
    """ Socket error """

class SocketTimeout(SocketError):
    """ Socket timeout """

class SocketPollError(SocketError):
    """ Socket poll error """


class ListenerSocket(object):
    """
    Abstraction to the listener socket

    This actually can contain more than one actual socket, but provides
    an interface as it was one.

    :CVariables:
     - `_TYPES`: Supported socket types and configuration patterns
       (``(('name', (regex, ...)), ...)``)

    :IVariables:
     - `_sockets`: List of actual sockets (``[socket, ...]``)

    :Types:
     - `_TYPES`: ``tuple``
    """
    _TYPES = (
        (u'tcp', (
            _re.compile(ur'(?:(?P<ip>[^:]+|\[[^\]]+]|\*):)?(?P<port>\d+)$'),
        )),
        (u'unix', (
            _re.compile(ur'(?P<path>.+)\((?P<perm>\d+)\)$'),
            _re.compile(ur'(?P<path>.+)(?P<perm>)$'),
        )),
    )
    _sockets = None

    def __init__(self, listen, basedir=None):
        """
        Initialization

        :Parameters:
         - `listen`: The addresses to listen on, may not be empty
         - `basedir`: Basedir for relative paths

        :Types:
         - `listen`: ``iterable``
         - `basedir`: ``str``
        """
        # pylint: disable = R0912

        if not listen:
            raise ConfigurationError("No listeners configured")

        # The way some OS work require us to follow a two-step-approach here:
        # First we "prepare" the sockets by determining the details for
        # every socket. The we reorder them, so we can filter out dupes
        # or includes. Includes are bindings which are already handled
        # by another binding, like localhost:1206 is included in *:1206
        # A special, but related problem is the inclusion of IPv4 in IPv6.
        msg = "Invalid listen configuration: %s"
        self._sockets, kinds = [], dict(self._TYPES)
        for bind in listen:
            obind, fixed, tocheck = repr(bind), None, self._TYPES
            if ':' in bind:
                fixed = bind[:bind.find(':')].lower()
                if fixed in kinds:
                    tocheck = (fixed, kinds[fixed])
                    bind = bind[len(fixed) + 1:]
                else:
                    fixed = None
            for kind, rexs in tocheck:
                if bind.startswith(kind + ':'):
                    fixed, bind = bind, bind[len(kind) + 1:]
                for rex in rexs:
                    match = rex.match(bind)
                    if match:
                        break
                else:
                    match = None
                if match is not None:
                    method = getattr(self, "_setup_" + kind)
                    try:
                        method(match.group, basedir)
                    except ConfigurationError, e:
                        stre = str(e)
                        e = _sys.exc_info()
                        try:
                            raise e[0], (msg % obind) + ": " + stre, e[2]
                        finally:
                            del e
                    break
            else:
                raise ConfigurationError(msg % obind)

        self.accept = self._finalize_listeners(msg)

    def _finalize_listeners(self, msg):
        """
        Finalize the listening sockets

        This method actually sets the sockets to the LISTEN state.

        :Parameters:
         - `msg`: Configuration error message template

        :Types:
         - `msg`: ``str``

        :return: Socket acceptor
        :rtype: ``callable``

        :Exceptions:
         - `ConfigurationError`: No listeners available
        """
        if not self._sockets:
            raise ConfigurationError("No listener sockets")

        memory, toremove = {}, []
        for socket in sorted(self._sockets):
            if socket.key() in memory or socket.anykey() in memory:
                # Do not issue the warning on any-ipv4/ipv6 inclusion
                if socket.key() != socket.anykey() or \
                        memory[socket.key()] == socket.family():
                    _warnings.warn("Duplicate listen: %s" % (socket.bindspec),
                        category=ListenerWarning)
                toremove.append(socket)
                continue
            _osutil.close_on_exec(socket)
            socket.setblocking(False)
            try:
                socket.bind()
                socket.listen(_socket.SOMAXCONN)
            except _socket.error, e:
                stre = str(e)
                e = _sys.exc_info()
                try:
                    raise ConfigurationError, \
                        (msg % socket.bindspec) + ": " + stre, e[2]
                finally:
                    del e
            else:
                memory[socket.key()] = socket.family()

        while toremove:
            socket = toremove.pop()
            self._sockets.remove(socket)
            try:
                socket.close()
            except (_socket.error, OSError), e:
                _warnings.warn("Socket shutdown problem: %s" % str(e),
                    category=ShutdownWarning)

        return Acceptor(item.realsocket for item in self._sockets)

    def __del__(self):
        self.close()

    def close(self):
        """ Shutdown the sockets """
        sockets, self._sockets = self._sockets, None
        if sockets is not None:
            for socket in sockets:
                try:
                    socket.close()
                except (_socket.error, OSError), e:
                    _warnings.warn("Socket shutdown problem: %s" % str(e),
                        category=ShutdownWarning)

    def _setup_tcp(self, bind, basedir=None):
        """
        Setup TCP/IP(v6) socket and append it to the global list

        :Parameters:
         - `bind`: Bind parameter accessor (``match.group``)
         - `basedir`: Basedir for relative paths (unused)

        :Types:
         - `bind`: ``callable``
         - `basedir`: ``basestring``
        """
        # pylint: disable = W0613

        obind = repr(bind(0))
        host, port, flags = bind(u'ip'), bind(u'port'), 0
        port = int(port)
        if not host or host == u'*':
            host, flags = None, _socket.AI_PASSIVE
        elif host.startswith(u'[') and host.endswith(u']'):
            host = host[1:-1].encode('ascii') # IPv6 notation [xxx:xxx:xxx]
        else:
            host = host.encode('idna')
        try:
            adi = _socket.getaddrinfo(host, port,
                _socket.AF_UNSPEC, _socket.SOCK_STREAM, 0, flags)
            for family, stype, proto, _, bind in adi:
                if not _socket.has_ipv6 and family == AF_INET6:
                    continue

                try:
                    socket = _socket.socket(family, stype, proto)
                except _socket.error, e:
                    if e[0] == _errno.EAFNOSUPPORT and host is None and \
                            family == AF_INET6:
                        # grmpf.
                        # There are systems (e.g. linux) which emit
                        # IPv6 on ANY, even if they don't support it.
                        # Or is it the libc? Who cares anyway...
                        continue
                    raise
                socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                self._sockets.append(
                    InetSocket(socket, obind, host, family, bind)
                )
        except _socket.error:
            e = _sys.exc_info()
            try:
                raise ConfigurationError, e[1], e[2]
            finally:
                del e

    def _setup_unix(self, bind, basedir=None):
        """
        Setup UNIX domain socket

        :Parameters:
         - `bind`: Bind parameter accessor (``match.group``)
         - `basedir`: Basedir for relative paths

        :Types:
         - `bind`: ``callable``
         - `basedir`: ``str``
        """
        if AF_UNIX is None:
            raise ConfigurationError("UNIX domain sockets are not available")

        obind = repr(bind(0))
        if bind(u'perm'):
            try:
                socket_perm = int(bind('perm'), 8)
            except (TypeError, ValueError):
                raise ConfigurationError("Invalid permission")
            umask = 0777 & ~socket_perm
        else:
            umask = None
        basedir = basedir or _os.getcwd()
        if not isinstance(basedir, unicode):
            basedir = basedir.decode(_sys.getfilesystemencoding())
        path = _os.path.normpath(_os.path.join(
            basedir, bind(u'path')
        )).encode(_sys.getfilesystemencoding())
        socket = _socket.socket(AF_UNIX, _socket.SOCK_STREAM)
        self._sockets.append(UnixSocket(socket, obind, path, umask))


class SocketDecorator(object):
    """
    Socket decorating container

    Derive from this container in order to build new concrete containers.
    These containers are necessary for proper duplicate/warning/error
    handling, because we need some context for the socket. The socket
    ordering is also defined in these containers (via `__cmp__`).

    :See: `UnixSocket`, `InetSocket`

    :CVariables:
     - `_famcomp`: Index for address family comparisons

    :IVariables:
     - `realsocket`: The actual socket object
     - `bindspec`: The bind specification from the config

    :Types:
     - `_famcomp`: ``dict``
     - `realsocket`: ``socket.socket``
     - `bindspec`: ``str``
    """
    _famcomp = dict((fam, idx) for idx, fam in enumerate((
        AF_UNIX, AF_INET6, AF_INET
    )) if fam is not None)

    def __init__(self, socket, bindspec):
        """
        Initialization

        :Parameters:
         - `socket`: The socket object to decorate
         - `bindspec`: The bind specification from config

        :Types:
         - `socket`: ``socket.socket``
         - `bindspec`: ``str``
        """
        self.realsocket = socket
        self.bindspec = bindspec

    def __cmp__(self, other):
        """
        Compare 3-way with another object

        Comparison is done by the socket family index. If the other object
        is not a `SocketDecorator`, the ``id()`` s are compared.

        :Parameters:
         - `other`: The other object

        :Types:
         - `other`: `SocketDecorator`

        :return: Comparison result (``-1``, ``0``, ``1``) for `self` being
                 less, equal or greater than/to `other`
        :rtype: ``int``

        :Exceptions:
         - `NotImplementedError`: The socket family of either socket is not
           in the index
        """
        if not isinstance(other, self.__class__):
            return cmp(id(self), id(other))
        try:
            return cmp(
                self._famcomp[self.family()],
                self._famcomp[other.family()]
            )
        except KeyError:
            raise NotImplementedError()

    def __eq__(self, other):
        """
        Compary (2-way) by identity

        :Parameters:
         - `other`: The other object

        :Types:
         - `other`: `SocketDecorator`

        :return: Are the objects identical?
        :rtype: ``bool``
        """
        return id(self) == id(other)

    def __repr__(self):
        """
        String representation of the object (suitable for debugging)

        :return: The string representation
        :rtype: ``str``
        """
        return "<%s.%s fileno=%s, family=%s, key=%r>" % (
            self.__class__.__module__, self.__class__.__name__,
            self.fileno(), self.family(), self.key(),
        )

    def __del__(self):
        """ Destructor """
        self.close()

    def __getattr__(self, name):
        """
        Delegate all undefined symbol requests to the real socket

        :Parameters:
         - `name`: The symbol to look up

        :Types:
         - `name`: ``str``
        """
        return getattr(self.realsocket, name)

    def bind(self):
        """ Bind the socket according to its bindspec """
        raise NotImplementedError()

    def family(self):
        """
        Determine the socket address family

        :return: The family
        :rtype: ``int``
        """
        raise NotImplementedError()

    def key(self):
        """
        Determine the key of the socket, derived from the bindspec

        This key can be considered a normalized version of the bindspec. It
        has to be hashable.

        :return: The key
        :rtype: any
        """
        raise NotImplementedError()

    def anykey(self):
        """
        Determine the key of the socket if bindspec would point to ANY

        :See: `key`

        :return: The key
        :rtype: any
        """
        raise NotImplementedError()


class UnixSocket(SocketDecorator):
    """
    Decorator for UNIX domain sockets

    :IVariables:
     - `_bound`: Was the socket bound to a path?
     - `_path`: The path to bind to
     - `_umask`: The umask to be set when binding to the path (maybe ``None``)
     - `_normpath`: The normalized path (symlinks resolved) (used as key)

    :Types:
     - `_bound`: ``bool``
     - `_path`: ``str``
     - `_umask`: ``int``
     - `_normpath`: ``str``
    """
    def __init__(self, socket, bindspec, path, umask):
        """
        Initialization

        :Parameters:
         - `socket`: The actual socket object
         - `bindspec`: Binding string from configuration
         - `path`: Path to bind to
         - `umask`: Umask to apply when binding to the path

        :Types:
         - `socket`: ``socket.socket``
         - `bindspec`: ``str``
         - `path`: ``str``
         - `umask`: ``int``
        """
        super(UnixSocket, self).__init__(socket, bindspec)
        self._bound, self._path, self._umask = False, path, umask
        self._normpath = _os.path.normpath(_os.path.realpath(path))

    def close(self):
        """ Remove the socket path and close the file handle """
        _osutil.unlink_silent(self._path)
        self.realsocket.close()

    def bind(self):
        """ Bind to the socket path """
        old_umask = None
        try:
            if self._umask is not None:
                old_umask = _os.umask(self._umask)
            _osutil.unlink_silent(self._path)
            self._bound, _ = True, self.realsocket.bind(self._path)
        finally:
            if old_umask is not None:
                _os.umask(old_umask)

    def family(self):
        """ Determine the socket family """
        return AF_UNIX

    def key(self):
        """ Determine the socket key """
        return self._normpath

    def anykey(self):
        """ Determine ANY key """
        return None


class InetSocket(SocketDecorator):
    """
    Decorator for TCP/IP(v6) sockets

    :IVariables:
     - `_bind`: bind value from ``getaddrinfo(3)``
     - `_host`: Hostname/IP (or ``None`` for ANY)
     - `_family`: socket family

    :Types:
     - `_bind`: ``tuple``
     - `_host`: ``str``
     - `_family`: ``int``
    """
    def __init__(self, socket, bindspec, host, family, bind):
        """
        Initialization

        :Parameters:
         - `socket`: Actual socket object
         - `bindspec`: Bind specification from config
         - `host`: Hostname/IP or ``None``
         - `family`: Socket family
         - `bind`: bind value from ``getaddrinfo(3)``

        :Types:
         - `socket`: ``socket.socket``
         - `bindspec`: ``str``
         - `host`: ``str``
         - `family`: ``int``
         - `bind`: ``tuple``
        """
        super(InetSocket, self).__init__(socket, bindspec)
        self._bind, self._host, self._family = bind, host, family

    def __cmp__(self, other):
        """
        Compare (3-way) to a different object

        In addition to the base's ``__cmp__`` method, we compare the host
        and the rest of the bind value.
        """
        # pylint: disable = W0212
        return (
            super(InetSocket, self).__cmp__(other) or
            cmp(self._host or '', other._host or '') or
            cmp(self._bind[1:], other._bind[1:])
        )

    def bind(self):
        """ Bind the socket according to bindspec """
        self.realsocket.bind(self._bind)

    def family(self):
        """ Determine the socket family """
        return self._family

    def key(self):
        """ Determine the socket key """
        if self._host is None:
            return self.anykey()
        return (self._host, self._family, self._bind[1])

    def anykey(self):
        """ Determine the socket ANY key """
        return (None, AF_INET, self._bind[1])


class Acceptor(object):
    """ Acceptor for multiple connections """
    _IGNOREFAIL = set(getattr(_errno, _name, None) for _name in """
        EINTR
        ENOBUFS
        EPROTO
        ECONNABORTED
        ECONNRESET
        ETIMEDOUT
        EHOSTUNREACH
        ENETUNREACH
        EAGAIN
        EWOULDBLOCK
    """.split())
    if None in _IGNOREFAIL:
        _IGNOREFAIL.remove(None)

    def __init__(self, sockets):
        """
        Initialization

        :Parameters:
         - `sockets`: List of sockets to poll

        :Types:
         - `sockets`: ``iterable``
        """
        import collections, select
        try:
            pollset = select.poll
        except AttributeError:
            pollset = _SelectAdapter()
        else:
            pollset = _PollAdapter()
        self._fdmap = {}
        for socket in sockets:
            fd = socket.fileno()
            pollset.add(fd)
            self._fdmap[fd] = socket
        self._set = pollset
        self._backlog = collections.deque()

    def __call__(self, timeout=None):
        """
        Accept a new connection

        :Parameters:
         - `timeout`: Timeout in seconds

        :Types:
         - `timeout`: ``float``

        :return: New socket and the peername
        :rtype: ``tuple``

        :Exceptions:
         - `SocketTimeout`: accept call timed out
         - `SocketError`: An error occured while accepting the socket
        """
        while True:
            try:
                sock, peer = self._accept(timeout)
            except _socket.error, e:
                if e[0] in self._IGNOREFAIL:
                    continue
                e = _sys.exc_info()
                try:
                    raise SocketError, e[1], e[2]
                finally:
                    del e
            _osutil.close_on_exec(sock.fileno())
            return sock, peer

    def _accept(self, timeout=None):
        """
        Accept a connection

        :Parameters:
         - `timeout`: Timeout in seconds

        :Types:
         - `timeout`: ``float``

        :return: The new connection socket and the peername
        :rtype: ``tuple``

        :Exceptions:
         - `SocketTimeout`: accept call timed out
         - `SocketPollError`: Error with poll call
         - `socket.error`: Socket error
        """
        backlog = self._backlog
        if not backlog:
            pollset, timeout_used = self._set, timeout
            if timeout_used is None:
                timeout_used = 1000
            else:
                timeout_used = int(timeout_used * 1000)
            while True:
                try:
                    ready = pollset.poll(timeout_used)
                except pollset.error, e:
                    if e[0] == _errno.EINTR:
                        continue
                    e = _sys.exc_info()
                    try:
                        raise SocketPollError, e[1], e[2]
                    finally:
                        del e
                if ready:
                    break
                elif timeout is None:
                    continue
                raise SocketTimeout(timeout)
            backlog.extendleft(item[0] for item in ready)
        return self._fdmap[backlog.pop()].accept()


class _AdapterInterface(object):
    """
    Adapter poll API to select implementation

    :IVariables:
     - `error`: Exception to catch on poll()

    :Types:
     - `error`: ``Exception``
    """

    def __init__(self):
        """ Initialization """

    def add(self, fd):
        """
        Register a new file descriptor

        :Parameters:
         - `fd`: File descriptor to register

        :Types:
         - `fd`: ``int``

        :Exceptions:
         - `ValueError`: Error while creating an integer out of `fd`
         - `TypeError`: Error while creating an integer out of `fd`
        """

    def remove(self, fd):
        """
        Unregister a file descriptor

        :Parameters:
         - `fd`: File descriptor to unregister

        :Types:
         - `fd`: ``int``

        :Exceptions:
         - `ValueError`: Error while creating an integer out of `fd`
         - `TypeError`: Error while creating an integer out of `fd`
         - `KeyError`: The descriptor was not registered before
        """

    def poll(self, timeout=None):
        """
        Poll the list of descriptors

        :Parameters:
         - `timeout`: Poll timeout in milliseconds

        :Types:
         - `timeout`: ``int``

        :return: List of (descriptor, event) tuples, event is useless, though
        :rtype: ``list``

        :Exceptions:
         - `self.error`: Select error occured
        """


class _SelectAdapter(object):
    # pylint: disable = C0111
    __implements__ = [_AdapterInterface]

    def __init__(self):
        import select
        self.error = select.error
        self._rfds = set()

    def add(self, fd):
        self._rfds.add(int(fd))

    def remove(self, fd):
        self._rfds.remove(int(fd))

    def poll(self, timeout=None):
        import select
        if timeout is not None:
            timeout = float(timeout) / 1000.0
        rfds, _, _ = select.select(self._rfds, (), (), timeout)
        return [(item, 0) for item in rfds]


class _PollAdapter(object):
    # pylint: disable = C0111
    __implements__ = [_AdapterInterface]

    def __init__(self):
        import select
        self.error = select.error
        self._pollset = select.poll()
        self.poll = self._pollset.poll

    def add(self, fd):
        import select
        self._pollset.register(fd, select.POLLIN)

    def remove(self, fd):
        self._pollset.unregister(fd)

    def poll(self, timeout=None): # pylint: disable = E0202
        return self._pollset.poll(timeout)
