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
HTTP utilities
==============

This module implements various tools for HTTP request/response handling.

:Variables:
 - `CR`: ASCII CR byte (\\r)
 - `LF`: ASCII LF byte (\\n)
 - `CRLF`: ASCII CRLF sequence (\\r\\n)

:Types:
 - `CR`: ``str``
 - `LF`: ``str``
 - `CRLF`: ``str``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import socket as _socket

from wtf import Error
from wtf import httputil as _httputil
from wtf import stream as _stream

CR, LF, CRLF = _httputil.CR, _httputil.LF, _httputil.CRLF
make_date = _httputil.make_date


class ParseError(Error):
    """
    Request parse error

    :CVariables:
     - `status`: Statuscode and message

    :Types:
     - `status`: ``str``
    """
    status = "500 Internal Server Error"

    def __init__(self, message):
        """
        Initialization

        :Parameters:
         - `message`: Message to emit

        :Types:
         - `message`: ``str``
        """
        Error.__init__(self, message)
        self.msg = message


class BadRequest(ParseError):
    """ Bad Request error class """
    status = "400 Bad Request"

class InvalidHeaderLine(BadRequest):
    """ A header line is invalid """

class IncompleteHeaders(BadRequest):
    """ The headers are incomplete """

class InvalidChunkHeader(BadRequest):
    """ Chunk header was bogus """

class IncompleteChunk(BadRequest):
    """ Chunk did not fully arrive """


def read_headers(stream):
    """
    Read MIME headers from stream

    :Parameters:
     - `stream`: The stream to read from

    :Types:
     - `stream`: ``file``

    :return: Dictionary of comma folded headers
    :rtype: ``dict``

    :Exceptions:
     - `IncompleteHeaders`: The stream ended before the final empty line
     - `InvalidHeaderLine`: Unparsable header line
    """
    try:
        return dict((name, ", ".join(values))
            for name, values in _httputil.read_headers(stream).iteritems())
    except _httputil.IncompleteHeaders, e:
        raise IncompleteHeaders(str(e))
    except _httputil.InvalidHeaderLine, e:
        raise InvalidHeaderLine(str(e))


class ChunkedWriter(object):
    """
    Chunked transfer encoding encoder

    :Ivariables:
     - `_stream`: The stream to write the chunks to

    :Types:
     - `_stream`: ``file``
    """

    def __init__(self, stream):
        """
        Initialization

        :Parameters:
         - `stream`: The stream to write the chunks to

        :Types:
         - `stream`: ``file``
        """
        self._stream = stream

    def __getattr__(self, name):
        """
        Delegate undefined attribute requests to the underlying stream

        :Parameters:
         - `name`: Attribute name

        :Types:
         - `name`: ``str``

        :return: The requested attribute
        :rtype: any

        :Exceptions:
         - `AttributeError`: Attribute not found
        """
        return getattr(self._stream, name)

    def write(self, data, _force_empty=False):
        """
        Write a chunk of data

        :Parameters:
         - `data`: The chunk of data to write
         - `_force_empty`: Write the chunk even if data is empty
           (this will be - by definition - the last chunk)

        :Types:
         - `data`: ``str``
         - `_force_empty`: ``bool``
        """
        data = str(data)
        if data or _force_empty:
            self._stream.write('%X' % len(data) + CRLF)
            self._stream.write(data + CRLF)

    def close(self):
        """
        Finish chunked writing

        This writes the last (empty) chunk and closes the stream afterwards.
        """
        self.write("", True)
        try:
            self._stream.close()
        except _socket.error, e:
            if e[0] != _errno.EPIPE:
                raise


class ChunkedReader(object):
    """
    Chunked transfer encoding decoder

    :IVariables:
     - `_stream`: The stream to decode
     - `_state`: Current read function
     - `_left`: Bytes left of the current chunk

    :Types:
     - `_stream`: ``file``
     - `_state`: ``callable``
     - `_left`: ``int``
    """

    def __init__(self, stream):
        """
        Initialization

        :Parameters:
         - `stream`: The stream to decode

        :Types:
         - `stream`: ``file``
        """
        self._stream = stream
        self._state = self._read_header
        self._left = 0

    def read(self, size):
        """
        Read (at max) ``size`` bytes from the stream

        This just calls the current state reader and returns its result.

        :Parameters:
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``

        :Exceptions:
         - `InvalidChunkHeader`: A chunk header was unparsable
         - `InvalidHeaderLine`: A header line (of the trailer) could not be
           parsed
         - `IncompleteHeaders`: The stream ended unexpectedly while parsing
           headers (of the trailer)
         - `IncompleteChunk`: The stream ended unexpectedly in the middle of
           a chunk
        """
        assert size > 0, "size must be > 0"
        return self._state(size)

    def _done(self, size):
        """
        Final state: Hit EOF (or EOS, rather)

        This function always returns an empty string, so `size` is ignored.

        :Parameters:
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``
        """
        # pylint: disable = W0613

        return ""

    def _read_header(self, size):
        """
        Initial State: Read chunk header and follow up the stream

        :Parameters:
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``

        :Exceptions:
         - `InvalidChunkHeader`: The chunk header was unparsable
        """
        line = self._stream.readline().split(';', 1)[0].strip()
        try:
            chunksize = int(line, 16)
            if chunksize < 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise InvalidChunkHeader("Unparsable chunksize")
        if chunksize == 0:
            self._state = self._read_trailer
        else:
            self._left, self._state = chunksize, self._read_data
        return self.read(size)

    def _read_trailer(self, size):
        """
        After last chunk state: Read trailer and finish

        :Parameters:
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``

        :Exceptions:
         - `InvalidHeaderLine`: A header line could not be parsed
         - `IncompleteHeaders`: The stream ended while parsing headers
        """
        # We could add the headers to the request object, but
        # nobody reads them, after the body was fetched. So, why bother?
        read_headers(self._stream)
        self._state = self._done
        return self.read(size)

    def _read_data(self, size):
        """
        Read actual chunk data

        :Parameters:
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``

        :Exceptions:
         - `IncompleteChunk`: The stream ended unexpectedly in the middle of
           the chunk
        """
        rsize = min(self._left, size)
        if rsize <= 0:
            self._state = self._read_suffix
            return self.read(size)
        result = _stream.read_exact(self._stream, rsize)
        if not result:
            raise IncompleteChunk("Missing at least %d bytes" % self._left)
        self._left -= len(result)
        if self._left <= 0:
            self._state = self._read_suffix
        return result

    def _read_suffix(self, size):
        """
        Read trailing CRLF after chunk data

        After that it switches back to `_read_header` and follows up on the
        stream.

        :Parameters: 
         - `size`: The maximum number of bytes to read (>0)

        :Types:
         - `size`: ``int``

        :return: Bytes read (empty on EOF)
        :rtype: ``str``

        :Exceptions:
         - `IncompleteChunk`: Trailing CRLF was missing (or something else)
        """
        eol = self._stream.read(1)
        if eol == CR:
            eol = self._stream.read(1)
        if eol != LF:
            raise IncompleteChunk("Missing trailing CRLF")
        self._state = self._read_header
        return self.read(size)


class ExpectationReader(object):
    """
    Before actual reading send a 100 continue intermediate response

    :IVariables:
     - `_stream`: The stream to read from
     - `_request`: Request instance

    :Types:
     - `_stream`: ``file``
     - `_request`: `HTTPRequest`
    """

    def __init__(self, stream, request):
        """
        Initialization

        :Parameters:
         - `stream`: The stream to actually read data from
         - `request`: Request instance

        :Types:
         - `stream`: ``file``
         - `request`: `HTTPRequest`
        """
        self._stream, self._request = stream, request
        self.read = self._send_continue

    def _send_continue(self, size):
        """
        Send continue before reading

        :Parameters:
         - `size`: Read at max `size` bytes

        :Types:
         - `size`: ``int``

        :return: The read bytes, or empty on EOF
        :rtype: ``str``
        """
        if self.read == self._send_continue:
            self.read = self._stream.read
            self._request.send_continue()
        return self.read(size)


class HTTPConnection(object):
    """
    HTTP connection abstraction

    :CVariables:
     - `DROPPERS`: List of status codes which drop the connection
     - `KEEPERS`: List of status codes which keep the connection without
       content length

    :IVariables:
     - `_request`: The request instance
     - `persist`: Does the connection persist? This property may be queried
       on a higher level in orer to determine whether to close a connection
       or not.
     - `reader`: Reading stream for this connection
     - `writer`: Writing stream for this connection
     - `headers`: Header dictionary to add to the outgoing headers. This
       MAY contain ``Connection`` and ``Transfer-Encoding`` headers.

    :Types:
     - `DROPPERS`: ``dict``
     - `KEEPERS`: ``dict``
     - `_request`: `HTTPRequest`
     - `persist`: ``bool``
     - `reader`: `wtf.stream.GenericStream`
     - `writer`: `wtf.stream.GenericStream`
     - `headers`: ``dict``
    """
    reader, writer, persist = None, None, False
    DROPPERS = dict.fromkeys((400, 405, 408, 411, 413, 414, 500, 501, 503))
    KEEPERS = dict.fromkeys((204, 205, 304))

    def __init__(self, request, connection):
        """
        Initialization

        :Parameters:
         - `request`: The request instance
         - `connection`: The connection instance

        :Types:
         - `request`: `HTTPRequest`
         - `connection`: `wtf.impl.http.Connection`
        """
        self._request = request
        self.reader = connection.reader()
        self.writer = connection.writer()
        self.headers = {'connection': 'close'}
        self.settimeout = connection.settimeout

    def __del__(self):
        self.close()

    def close(self):
        """ Close the HTTP streams """
        try:
            try:
                reader, self.reader = self.reader, None
                if reader is not None:
                    reader.close()
            finally:
                writer, self.writer = self.writer, None
                if writer is not None:
                    writer.close()
        except _socket.error, e:
            if e[0] != _errno.EPIPE:
                raise

    def compute_status(self):
        """
        Compute the connection persistance status

        This function "only" has side effects. It sets ``headers`` and
        ``persist`` according to request and response parameters.
        """
        # pylint: disable = R0912

        request = self._request
        protocol = request.protocol
        if protocol < (1, 0):
            self.persist = False
            self.headers = {}
        else:
            headers_out = request.response_headers
            if 'keep-alive' in headers_out:
                del headers_out['keep-alive']
            if 'connection' in headers_out:
                rtokens = [item.strip().lower()
                    for item in headers_out['connection'].split(',')]
                for token in rtokens:
                    if token in headers_out:
                        del headers_out[token]
                del headers_out['connection']
            if 'transfer-encoding' in headers_out:
                del headers_out['transfer-encoding']

            if 'connection' in request.headers:
                tokens = [item.strip().lower()
                    for item in request.headers['connection'].split(',')]
            else:
                tokens = ()
            status = request.response_status
            if not self._request.keep_alive or \
                    (status is not None and status in self.DROPPERS):
                self.persist = False
                if protocol >= (1, 1) or (
                        protocol == (1, 0) and 'keep-alive' in tokens):
                    self.headers = {'connection': 'close'}
            else:
                if 'close' in tokens:
                    self.persist = False
                    if protocol >= (1, 1):
                        self.headers = {'connection': 'close'}
                elif protocol == (1, 0):
                    if 'keep-alive' in tokens:
                        self.persist = True
                        self.headers = {'connection': 'Keep-Alive'}
                    else:
                        self.persist = False
                        self.headers = {}
                elif protocol >= (1, 1):
                    self.persist = True
                    self.headers = {}

            if 'content-length' not in headers_out and \
                    status not in self.KEEPERS and request.method != 'HEAD':
                if protocol == (1, 0):
                    self.persist = False
                    if 'keep-alive' in tokens:
                        self.headers = {'connection': 'close'}
                    else:
                        self.headers = {}
                else:
                    self.headers['transfer-encoding'] = 'chunked'

    def settimeout(self, timeout): # pylint: disable = E0202
        """
        Set a socket timeout for next operations

        :Parameters:
         - `timeout`: Socket timeout to set

        :Types:
         - `timeout`: ``float``
        """
        # pylint: disable = W0613

        raise AssertionError("Object not initialized properly")
