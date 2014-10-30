# -*- coding: ascii -*-
#
# Copyright 2005-2012
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
Generic Buffered ``file`` Stream
================================

In order to use the stream, you need to supply an actual implementation
of the low level octet stream. This stream implementation is useful
in order to decorate other streams and not implement the full API every time.

:Variables:
 - `dev_null`: /dev/null like stream (EOF on reading, doing nothing on
   writing)

:Types:
 - `dev_null`: `GenericStream`
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"


import errno as _errno
import socket as _socket

from wtf.util import Property


class GenericStream(object):
    """
    Represents a buffered stream

    :CVariables:
     - `_DEFAULT_CHUNK_SIZE`: Default buffer size

    :IVariables:
     - `_octet_stream`: The stream to actually fetch the data from
     - `_chunk_size`: Actual buffer size to use
     - `_blockiter`: Block iteration size (``1: block = line``)
     - `_rbuffer`: read buffer
     - `_wbuffer`: write buffer
     - `_flush`: underlying flush function
     - `_closed`: Is the stream closed?
     - `softspace`: Softspace parameter

    :Types:
     - `_DEFAULT_CHUNK_SIZE`: ``int``
     - `_octet_stream`: ``file``
     - `_chunk_size`: ``int``
     - `_blockiter`: ``int``
     - `_rbuffer`: ``list``
     - `_wbuffer`: ``list``
     - `_flush`: ``callable``
     - `_closed`: ``bool``
     - `softspace`: ``bool``
    """
    _DEFAULT_CHUNK_SIZE = 8192 # must be > 1
    _octet_stream = None
    _closed = True
    softspace = False

    def __new__(cls, stream, buffering=-1, blockiter=1, read_exact=False):
        """
        Construction

        :Parameters:
         - `stream`: The low level stream
         - `buffering`: The buffer specification:
           (``< 0``: default buffer size, ``==0``: unbuffered,
           ``>0``: this very buffer size)
         - `blockiter`: iteration block spec
           (``<= 0: default chunk, 1: line, > 1: this blocksize``)
         - `read_exact`: Try reading up to the requested size? If ``False``,
           a simple ``.read(size)`` will always yield the chunk size at max.
           This is normal behaviour on slow calls, e.g. sockets. However,
           some software expects to get the maximum (or even the exact value)
           bytes. In this case use a stream with ``read_exact`` set to
           ``True``.

        :Types:
         - `stream`: ``file``
         - `buffering`: ``int``
         - `blockiter`: ``int``
         - `read_exact`: ``bool``
        """
        # pylint: disable = W0212, W0621

        self = super(GenericStream, cls).__new__(cls)
        if buffering < 0:
            buffering = self._DEFAULT_CHUNK_SIZE
        elif buffering == 0:
            buffering = 1
        self._octet_stream = stream
        self._chunk_size = buffering
        self._blockiter = max(0, blockiter) or self._DEFAULT_CHUNK_SIZE
        self._rbuffer = []
        self._wbuffer = []
        self._closed = False
        try:
            self._flush = self._octet_stream.flush
        except AttributeError:
            self._flush = lambda: None
        if read_exact:
            self.read = self.read_exact
        return self

    def __del__(self):
        self.close()

    def __iter__(self):
        """ Iterator generator """
        return self

    def next(self):
        """ Return the next line or block """
        if self._blockiter == 1: # pylint: disable = E1101
            line = self.readline()
        else:
            line = self.read(self._blockiter) # pylint: disable = E1101
        if not line:
            raise StopIteration()
        return line

    @Property
    def name():
        """
        The name of the stream, if any

        :Type: ``str``
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            return self._octet_stream.name
        return locals()

    @Property
    def closed():
        """
        Is the stream is closed?

        :Type: ``bool``
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            stream = self._octet_stream
            if stream is not None:
                try:
                    return stream.closed
                except AttributeError:
                    return self._closed
            return True
        return locals()

    def fileno(self):
        """ Determine underlying fileno """
        if self.closed:
            raise ValueError("I/O operation on closed stream")

        return self._octet_stream.fileno()

    def close(self):
        """
        Close the stream

        The call is passed to the underlying octet stream.
        """
        if not self.closed:
            try:
                self.flush(False)
            finally:
                self._closed, stream, self._octet_stream = \
                    True, self._octet_stream, None
                if stream is not None:
                    try:
                        close = stream.close
                    except AttributeError:
                        pass # well, just don't close it then
                    else:
                        close()

    def flush(self, _passdown=True):
        """
        Flush the write buffer

        :Parameters:
         - `_passdown`: Call flush() on the underlying stream, too

        :Types:
         - `_passdown`: ``bool``
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")

        # pylint: disable = W0201
        buf, self._wbuffer = "".join(self._wbuffer), []
        if buf:
            self._octet_stream.write(buf)
        if _passdown:
            self._flush() # pylint: disable = E1101

    def isatty(self):
        """
        Does the stream refer to a tty?

        :return: Does the stream refer to a tty?
        :rtype: ``bool``
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")

        try:
            isatty = self._octet_stream.isatty
        except AttributeError:
            return False
        return isatty()

    def read(self, size=-1):
        """
        Reads a specified amount of bytes (at max) from the stream

        :Parameters:
         - `size`: The maximum number of bytes to read (``< 0`` means
           to slurp the whole stream; ``== 0`` means to return the current
           buffer or the next buffer it the current buffer is empty)

        :Types:
         - `size`: ``int``

        :return: The read bytes; if empty you've hit EOF
        :rtype: ``str``

        :Exceptions:
         - `ValueError`: The stream is closed
        """
        return self._bufferedread(size)

    def read_exact(self, size=-1):
        """
        Read exactly size bytes from stream, except on EOF

        :Parameters:
         - `size`: expected number of bytes

        :Types:
         - `size`: ``int``

        :return: The read bytes
        :rtype: ``str``
        """
        return _read_exact(self._bufferedread, size)

    def readline(self, size=0):
        """
        Read a line from the stream

        :Parameters:
         - `size`: The maximum number of bytes to read (``<= 0`` means
           to read until the next newline or EOF, which is the default
           behaviour)

        :Types:
         - `size`: ``int``

        :return: The read bytes including the newline; if empty you've hit
                 EOF
        :rtype: ``str``
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")

        if size < 0:
            size = 0 # read default chunks

        read = self._bufferedread
        linebuffer = read(size)
        if linebuffer:
            findstart = 0
            while True:
                newbuffer = None
                eolpos = linebuffer.find("\n", findstart)
                if eolpos >= 0 and (size == 0 or eolpos < size):
                    self._unread(linebuffer[eolpos + 1:])
                    linebuffer = linebuffer[:eolpos + 1]
                    break
                elif size > 0:
                    llen = len(linebuffer)
                    if llen == size:
                        break
                    elif llen > size:
                        self._unread(linebuffer[size:])
                        linebuffer = linebuffer[:size]
                        break
                    else:
                        newbuffer = read(size - llen)
                else:
                    newbuffer = read(size)
                if not newbuffer:
                    break
                findstart = len(linebuffer)
                linebuffer += newbuffer
        return linebuffer

    def readlines(self, size=0):
        """
        Returns all lines as a list

        :Parameters:
         - `size`: Maximum size for a single line.

        :Types:
         - `size`: ``int``
        """
        lines = []
        while True:
            line = self.readline(size)
            if not line:
                break
            lines.append(line)
        return lines

    def xreadlines(self):
        """
        Iterator of the lines

        :Depreciated: Use the iterator API instead
        """
        return self

    def write(self, data):
        """
        Write data into the stream

        :Parameters:
         - `data`: The data to write

        :Types:
         - `data`: ``str``
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")

        if data:
            self._wbuffer.append(data)
            # pylint: disable = E1101
            if self._chunk_size <= 0 or \
                    sum(map(len, self._wbuffer)) > self._chunk_size:
                self.flush(False)

    def writelines(self, lines):
        """
        Write lines to the stream

        :Parameters:
         - `lines`: The list of lines to write

        :Types:
         - `lines`: ``iterable``
        """
        for line in lines:
            self.write(line)

    def _unread(self, tounread):
        """
        Pushes `tounread` octets back

        :Parameters:
         - `tounread`: The buffer to push back

        :Types:
         - `tounread`: ``str``
        """
        if tounread:
            self._rbuffer.append(tounread)

    def _bufferedread(self, size):
        """
        Read a specified amount of bytes (at max) from the stream

        :Parameters:
         - `size`: The maximum number of bytes to read (``< 0`` means
           to slurp the whole stream; ``== 0`` means to return the current
           buffer or the next buffer it the current buffer is empty)

        :Types:
         - `size`: ``int``

        :return: The read bytes; if empty you've hit EOF
        :rtype: ``str``

        :Exceptions:
         - `ValueError`: The stream is closed
        """
        # pylint: disable = E1101, R0912

        if self.closed:
            raise ValueError("I/O operation on closed stream")

        buf, chunk_size = self._rbuffer, self._chunk_size
        if size == 0:
            if buf:
                return buf.pop()
            # else:
            size = chunk_size

        # return `size` bytes; < 0 means 'slurp all'
        buf = "".join(buf[::-1]) # flatten the reverse buffer array
        if size < 0:
            chunks = [buf]
        else:
            chunks, buf = [buf[:size]], buf[size:]
            if buf:
                self._rbuffer = [buf]
                return chunks[0]
        self._rbuffer = []

        bytes_return = size < 0 and size - 1 or len(chunks[0])
        while bytes_return < size:
            if size > 0:
                chunk_size = min(size - bytes_return, chunk_size)
            chunk = self._octet_stream.read(chunk_size)
            if not chunk:
                break
            elif size < 0:
                chunks.append(chunk)
            else:
                bytes_toadd = size - bytes_return
                chunk_toadd = chunk[:bytes_toadd]
                chunks.append(chunk_toadd)
                buf = chunk[bytes_toadd:]
                if buf:
                    self._rbuffer = [buf] # pylint: disable = W0201
                    break
                bytes_return += len(chunk_toadd)
            if size > 0:
                break
        return "".join(chunks)


class MinimalSocketStream(object):
    """
    Minimal stream out of a socket

    This effectively maps ``recv`` to ``read`` and ``sendall`` to ``write``.

    :See: `GenericStream`

    :IVariables:
      `_sock` : ``socket.socket``
        The socket in question

      `_shutdown` : ``int``
        shutdown parameter on close
    """
    name = '<socket>'

    def __init__(self, sock, shutdown=None):
        """
        Initialization

        :Parameters:
          `sock` : ``socket.socket``
            The socket in question

          `shutdown` : ``int``
            Shutdown parameter on close (``socket.SHUT_*``). If omitted or
            ``None``, the close method of the socket is called (if exists).
        """
        if shutdown is not None and shutdown < 0:
            shutdown = None
        self._shutdown = shutdown
        self._sock = sock

    def __del__(self):
        self.close()

    def __getattr__(self, name):
        """
        Delegate all unknown symbol requests to the socket itself

        :Parameters:
         - `name`: The symbol to lookup

        :Types:
         - `name`: ``str``

        :return: The looked up symbol
        :rtype: any

        :Exceptions:
         - `AttributeError`: Symbol not found
        """
        return getattr(self._sock, name)

    @Property
    def closed():
        """
        Is the stream closed?

        :Type: ``bool``
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            return self._sock is None
        return locals()

    def close(self):
        """ Close the stream (not necessarily the socket) """
        try:
            sock, self._sock = self._sock, None
        except AttributeError:
            pass
        else:
            if sock is not None:
                if self._shutdown is not None:
                    try:
                        shutdown = sock.shutdown
                    except AttributeError:
                        pass
                    else:
                        try:
                            shutdown(self._shutdown)
                        except _socket.error, e:
                            if e[0] != _errno.ENOTCONN:
                                raise
                else:
                    try:
                        close = sock.close
                    except AttributeError:
                        pass
                    else:
                        close()

    def read(self, size):
        """
        Read `size` bytes (or less) from the socket

        :Parameters:
         - `size`: The number of bytes to read (``> 0``)

        :Types:
         - `size`: ``int``

        :return: The bytes read
        :rtype: ``str``

        :Exceptions:
         - `ValueError`: The stream is closed
         - `socket.error`: Something happened to the socket
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")
        return self._sock.recv(size)

    def write(self, data):
        """
        Write data to the socket

        :Parameters:
         - `data`: The data to write

        :Types:
         - `data`: ``str``

        :Exceptions:
         - `ValueError`: The stream is closed
         - `socket.error`: Something happened to the socket
        """
        if self.closed:
            raise ValueError("I/O operation on closed stream")
        self._sock.sendall(data)


def read_exact(stream, size):
    """
    Read exactly size bytes from stream, except on EOF

    :Parameters:
     - `stream`: The stream to read from.
     - `size`: expected number of bytes

    :Types:
     - `stream`: ``file``
     - `size`: ``int``

    :return: The read bytes
    :rtype: ``str``
    """
    return _read_exact(stream.read, size)


def _read_exact(read, size):
    """
    Read exactly size bytes with `read`, except on EOF

    :Parameters:
     - `read`: The reading function
     - `size`: expected number of bytes

    :Types:
     - `read`: ``callable``
     - `size`: ``int``

    :return: The read bytes
    :rtype: ``str``
    """
    if size < 0:
        return read(size)
    vlen, buf = 0, []
    push = buf.append
    while vlen < size:
        val = read(size - vlen)
        if not val:
            break
        vlen += len(val)
        push(val)
    return "".join(buf)


from wtf import c_override
cimpl = c_override('_wtf_cstream')
if cimpl is not None:
    # pylint: disable = E1103
    GenericStream = cimpl.GenericStream
    MinimalSocketStream = cimpl.MinimalSocketStream
    read_exact = cimpl.read_exact
del c_override, cimpl


class dev_null(object): # pylint: disable = C0103
    """
    /dev/null like stream

    Returns EOF on read requests and throws away any written stuff.
    """
    def read(self, size=-1):
        """ Return EOF """
        # pylint: disable = W0613

        return ""

    def write(self, data):
        """ Do nothing """
        pass
dev_null = GenericStream(dev_null())
