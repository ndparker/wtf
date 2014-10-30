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
Common Connection Implementation
================================

This module defines a connection abstraction.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import socket as _socket

from wtf import osutil as _osutil
from wtf import stream as _stream


class Connection(object):
    """
    Connection abstraction

    :IVariables:
     - `_sock`: Actual connection socket
     - `server_addr`: tuple of server address and port (the latter is -1 on
       UNIX domain sockets) (``(addr, port)``)
     - `remote_addr`: tuple of remote address and port (the latter is -1 on
       UNIX domain sockets) (``(addr, port)``)

    :Types:
     - `_sock`: ``socket.socket``
     - `server_addr`: ``tuple``
     - `remote_addr`: ``tuple``
    """
    _sock = None

    def __init__(self, sock, peername):
        """
        Initialization

        :Parameters:
         - `sock`: The actual connection socket
         - `peername`: The peername (got from accept)

        :Types:
         - `sock`: ``socket.socket``
         - `peername`: ``str`` or ``tuple``
        """
        # first thing, in order to be able to close it cleanly
        self._sock = sock

        sock, peername = _osutil.disable_nagle(sock, peername)

        sockname = sock.getsockname()
        if isinstance(sockname, str):
            sockname = sockname, -1
        self.server_addr = sockname
        if isinstance(peername, str):
            peername = peername, -1
        self.remote_addr = peername

    def __del__(self):
        self.close()

    def close(self):
        """ Close the connection """
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                try:
                    sock.shutdown(_socket.SHUT_RDWR)
                except _socket.error, e:
                    if e[0] != _errno.ENOTCONN:
                        raise
            finally:
                sock.close()

    def reader(self):
        """
        Create a new reading stream for the socket

        :return: reading stream
        :rtype: ``file``
        """
        return _stream.GenericStream(_stream.MinimalSocketStream(
            self._sock, _socket.SHUT_RD
        ))

    def writer(self):
        """
        Create a new writing stream for the socket

        :return: writing stream
        :rtype: ``file``
        """
        return _stream.GenericStream(_stream.MinimalSocketStream(
            self._sock, _socket.SHUT_WR
        ))

    def settimeout(self, timeout):
        """
        Set a socket timeout for next operations

        :Parameters:
         - `timeout`: Socket timeout to set

        :Types:
         - `timeout`: ``float``
        """
        if timeout is not None:
            timeout = float(timeout)
        self._sock.settimeout(timeout)
