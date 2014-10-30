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
OS Specific Utilities
=====================

Certain utilities to make the life more easy.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import errno as _errno
import fcntl as _fcntl
import os as _os
import resource as _resource
import socket as _socket
import sys as _sys
import threading as _threading
import warnings as _warnings

from wtf import Error, WtfWarning


class IdentityWarning(WtfWarning):
    """ The attempt to change identity caused a soft error """

class IdentityError(Error):
    """ The attempt to change identity caused a hard error """


class SocketError(Error):
    """ Socket error """

class AddressError(SocketError):
    """ Address resolution error """

class TimeoutError(SocketError):
    """ Timeout error """

class SSLError(SocketError):
    """ SSL error """


def raise_socket_error(timeout=None):
    """
    Convert a socket error into an appropriate module exception

    This function needs an already raised ``socket.error``.

    ``raise_socket_error.EAIS`` is a mapping from GAI error numbers to their
    names (``{int: 'name', ...}``)

    :Parameters:
     - `timeout`: applied timeout in seconds, used for the TimeoutError
       description

    :Types:
     - `timeout`: ``float``

    :Exceptions:
     - `TimeoutError`: ``socket.timeout``
     - `AddressError`: address/host resolution error
       (``socket.gaierror/herror``)
     - `SSLError`: ``socket.sslerror``
     - `SocketError`: other socket errors, ``IOError``
     - `Exception`: unrecognized exceptions
    """
    try:
        raise

    except _socket.timeout:
        if timeout is not None:
            raise TimeoutError, "Timed out after %s seconds" % timeout, \
                _sys.exc_info()[2]
        raise TimeoutError, "Timed out", _sys.exc_info()[2]

    except _socket.gaierror, e:
        # pylint: disable = E1101
        raise AddressError, "Address Information Error: %s (%s)" % \
            (raise_socket_error.EAIS.get(e[0], e[0]), e[1]), \
            _sys.exc_info()[2]

    except _socket.herror, e:
        raise AddressError, "Host Resolution Error %s: %s" % \
            (e[0], e[1]), _sys.exc_info()[2]

    except _socket.sslerror, e:
        raise SSLError, "Socket SSL Error: %s" % str(e), _sys.exc_info()[2]

    except _socket.error, e:
        if len(e.args) == 1:
            raise SocketError, "Socket Error: %s" % \
                (e[0],), _sys.exc_info()[2]
        else:
            raise SocketError, "Socket Error %s: %s" % \
                (_errno.errorcode.get(e[0], e[0]), e[1]), _sys.exc_info()[2]

    except IOError, e:
        raise SocketError, "Socket Error %s: %s" % \
            (_errno.errorcode.get(e[0], e[0]), str(e)), \
            _sys.exc_info()[2]

if 1:
    raise_socket_error.EAIS = dict((val, var) # pylint: disable = W0612
        for var, val in vars(_socket).items() if var.startswith('EAI_')
    )


def unlink_silent(filename):
    """
    Unlink a filename, but ignore if it does not exist

    :Parameters:
     - `filename`: The filename to remove

    :Types:
     - `filename`: ``basestring``
    """
    try:
        _os.unlink(filename)
    except OSError, e:
        if e.errno != _errno.ENOENT:
            raise


def close_on_exec(descriptor, close=True):
    """
    Mark `descriptor` to be closed on exec (or not)

    :Warning: This function is not thread safe (race condition)

    :Parameters:
     - `descriptor`: An object with ``fileno`` method or an ``int``
       representing a low level file descriptor
     - `close`: Mark being closed on exec?

    :Types:
     - `descriptor`: ``file`` or ``int``
     - `close`: ``bool``

    :Exceptions:
     - `IOError`: Something went wrong
    """
    try:
        fileno = descriptor.fileno
    except AttributeError:
        fd = descriptor
    else:
        fd = fileno()

    old = _fcntl.fcntl(fd, _fcntl.F_GETFD)
    if close:
        new = old | _fcntl.FD_CLOEXEC
    else:
        new = old & ~_fcntl.FD_CLOEXEC
    _fcntl.fcntl(fd, _fcntl.F_SETFD, new)


def safe_fd(fd):
    """
    Ensure that file descriptor fd is >= 3

    This is done by dup(2) calls until it's greater than 2. After success
    the duped descriptors are closed.

    :Parameters:
     - `fd`: The file descriptor to process

    :Types:
     - `fd`: ``int``

    :return: The new file descriptor (>=3)
    :rtype: ``int``

    :Exceptions:
     - `OSError`: Duping went wrong
    """
    toclose = []
    try:
        while fd < 3:
            toclose.append(fd)
            fd = _os.dup(fd)
    finally:
        for dfd in toclose:
            try:
                _os.close(dfd)
            except OSError:
                pass
    return fd


def close_descriptors(*keep):
    """ Close all file descriptors >= 3 """
    keep = set(keep)
    try:
        flag = _resource.RLIMIT_NOFILE
    except AttributeError:
        try:
            flag = _resource.RLIMIT_OFILE
        except AttributeError:
            flag = None
    if flag is not None:
        try:
            maxfiles = _resource.getrlimit(flag)[0]
        except (_resource.error, ValueError):
            flag = None
    if flag is None:
        maxfiles = 256 # wild guess
    for fd in xrange(3, maxfiles + 1):
        if fd in keep:
            continue
        try:
            _os.close(fd)
        except OSError:
            pass


try:
    _myflag = _socket.TCP_NODELAY
except AttributeError:
    def disable_nagle(sock, peername=None):
        """
        Disable nagle algorithm for a TCP socket

        :Note: This function is a NOOP on this platform (not implemented).

        :Parameters:
         - `sock`: Socket to process
         - `peername`: The name of the remote socket, if ``str``, it's a UNIX
           domain socket and the function does nothing

        :Types:
         - `sock`: ``socket.socket``
         - `peername`: ``str`` or ``tuple``

        :return: The socket and the peername again (if the latter was passed
                 as ``None``, it will be set to something useful
        :rtype: ``tuple``

        :Exceptions:
         - `socket.error`: The socket was probably not connected. If setting
           of the option fails, no socket error is thrown though. It's ignored.
        """
        if peername is None:
            peername = sock.getpeername()
        return sock, peername
else:
    def disable_nagle(sock, peername=None, _flag=_myflag):
        """
        Disable nagle algorithm for a TCP socket

        :Parameters:
         - `sock`: Socket to process
         - `peername`: The name of the remote socket, if ``str``, it's a UNIX
           domain socket and the function does nothing

        :Types:
         - `sock`: ``socket.socket``
         - `peername`: ``str`` or ``tuple``

        :return: The socket and the peername again (if the latter was passed
                 as ``None``, it will be set to something useful
        :rtype: ``tuple``

        :Exceptions:
         - `socket.error`: The socket was probably not connected. If setting
           of the option fails, no socket error is thrown though. It's ignored.
        """
        if peername is None:
            peername = sock.getpeername()
        if not isinstance(peername, str):
            try:
                sock.setsockopt(_socket.IPPROTO_TCP, _flag, 1)
            except _socket.error:
                pass # would have been nice, but, well, not that critical
        return sock, peername


_connect_cache = {}
_connect_cache_lock = _threading.Lock()
def connect(spec, timeout=None, nagle_off=True, cache=0,
            _cache=_connect_cache, _lock=_connect_cache_lock):
    """
    Create and connect a socket to a peer

    :Parameters:
     - `spec`: The peer specification (``(host, port)`` or ``str``)
     - `timeout`: Timeout in seconds
     - `nagle_off`: Disable Nagle's algorithm. This option does not
       apply to UNIX domain sockets.

    :Types:
     - `spec`: ``tuple`` or ``str``
     - `timeout`: ``float``
     - `nagle_off`: ``bool``

    :return: The connected socket or ``None`` if no connectable address
             could be found
    :rtype: ``socket.socket``

    :Exceptions:
     - `SocketError`: socket error (maybe a subclass of `SocketError`)
     - `NotImplementedError`: UNIX domain sockets are not supported in this
       platform
    """
    # pylint: disable = W0102, R0912, R0915

    sock = None
    try:
        adi = None
        if cache > 0:
            _lock.acquire()
            try:
                if spec in _cache:
                    adi, stamp = _cache[spec]
                    if stamp < _datetime.datetime.utcnow():
                        del _cache[spec]
                        adi = None
            finally:
                _lock.release()
        if adi is None:
            if isinstance(spec, str):
                try:
                    AF_UNIX = _socket.AF_UNIX
                except AttributeError:
                    raise NotImplementedError(
                        "UNIX domain sockets are not supported"
                    )
                adi = [(AF_UNIX, _socket.SOCK_STREAM, 0, None, spec)]
            else:
                adi = _socket.getaddrinfo(spec[0], spec[1],
                    _socket.AF_UNSPEC, _socket.SOCK_STREAM, 0, 0)
            if cache > 0:
                _lock.acquire()
                try:
                    if spec not in _cache:
                        _cache[spec] = (
                            adi,
                              _datetime.datetime.utcnow()
                            + _datetime.timedelta(seconds=cache),
                        )
                finally:
                    _lock.release()

        AF_INET6 = getattr(_socket, 'AF_INET6', None)
        for family, stype, proto, _, addr in adi:
            if not _socket.has_ipv6 and family == AF_INET6:
                continue # skip silenty if python was built without it.

            sock = _socket.socket(family, stype, proto)
            sock.settimeout(timeout)
            retry = True
            while retry:
                try:
                    sock.connect(addr)
                except _socket.timeout:
                    break
                except _socket.error, e:
                    if e[0] == _errno.EINTR:
                        continue
                    elif e[0] in (_errno.ENETUNREACH, _errno.ECONNREFUSED):
                        break
                    raise
                retry = False
            else:
                if nagle_off:
                    disable_nagle(sock)
                return sock
            sock.close()
    except (_socket.error, IOError):
        try:
            raise_socket_error(timeout=timeout)
        except SocketError:
            e = _sys.exc_info()
            try:
                if sock is not None:
                    sock.close()
            finally:
                try:
                    raise e[0], e[1], e[2]
                finally:
                    del e
    return None

del _connect_cache, _connect_cache_lock


def change_identity(user, group):
    """
    Change identity of the current process

    This only works if the effective user ID of the current process is 0.

    :Parameters:
     - `user`: User identification, if it is interpretable as ``int``, it's
       assumed to be a numeric user ID
     - `group`: Group identification, if it is interpretable as ``int``, it's
       asummed to be a numeric group ID

    :Types:
     - `user`: ``str``
     - `group`: ``str``

    :Exceptions:
     - `IdentityWarning`: A soft error occured (like not being root)
    """
    if _os.geteuid() != 0:
        _warnings.warn("Not attempting to change identity (not root)",
            category=IdentityWarning)
        return

    user, group = str(user), str(group)

    # resolve user
    import pwd
    try:
        try:
            userid = int(user)
        except (TypeError, ValueError):
            userid = pwd.getpwnam(user).pw_uid
        else:
            user = pwd.getpwuid(userid).pw_name
    except KeyError, e:
        raise IdentityError(
            "User resolution problem of %r: %s" % (user, str(e))
        )

    # resolve group
    import grp
    try:
        try:
            groupid = int(group)
        except (TypeError, ValueError):
            groupid = grp.getgrnam(group).gr_gid
        else:
            group = grp.getgrgid(groupid).gr_name
    except KeyError, e:
        raise IdentityError(
            "Group resolution problem of %r: %s" % (group, str(e))
        )

    # now do change our identity; group first as we might not have the
    # permissions to do so after we left the power of root behind us.
    _os.setgid(groupid)
    try:
        initgroups(user, groupid)
    except NotImplementedError:
        _warnings.warn("initgroups(3) is not implemented. You have to run "
            "without supplemental groups or compile the wtf package "
            "properly.", category=IdentityWarning)
    _os.setuid(userid)


def initgroups(username, gid):
    """
    Implement initgroups(3)

    :Parameters:
     - `username`: The user name
     - `gid`: The group id

    :Types:
     - `username`: ``str``
     - `gid`: ``int``

    :Exceptions:
     - `OSError`: initgroups() didn't succeed
     - `NotImplementedError`: initgroups is not implemented
       (needs c-extension)
    """
    # pylint: disable = W0613

    raise NotImplementedError()


from wtf import c_override
cimpl = c_override('_wtf_cutil')
if cimpl is not None:
    # pylint: disable = E1103
    initgroups = cimpl.initgroups
del c_override, cimpl
