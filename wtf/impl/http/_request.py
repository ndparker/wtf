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
r"""
HTTP Request State Machine
==========================

This is a simple state pattern implementing the request flow.

:Variables:
 - `CRLF`: ASCII CRLF sequence (\r\n)

:Types:
 - `CRLF`: ``str``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import re as _re
import socket as _socket

from wtf import Error
from wtf import stream as _stream
from wtf.impl import _util as _impl_util
from wtf.impl.http import _util as _http_util

CRLF = _http_util.CRLF

ParseError = _http_util.ParseError
BadRequest = _http_util.BadRequest

class RequestTimeout(ParseError):
    """ Request timed out """
    status = "408 Request Timeout"

class ExpectationFailed(ParseError):
    """ Expectation failed """
    status = "417 Expectation Failed"

class UnsupportedHTTPVersion(ParseError):
    """ HTTP Version not supported """
    status = "505 HTTP Version Not Supported"

class UnImplemented(ParseError):
    """ A feature is unimplemented """
    status = "501 Unimplemented"

class InvalidRequestLine(BadRequest):
    """ Request line is invalid """

class InvalidContentLength(BadRequest):
    """ The supplied content length is invalid """

class InvalidTransferEncoding(BadRequest):
    """ An invalid transfer encoding was supplied """

class MissingHostHeader(BadRequest):
    """ Host header is mandatory with HTTP/1.1 """


class StateError(Error):
    """ HTTP request state error """


class BaseState(object):
    """
    Base state class

    Every state method raises a StateError in here. Override implemented
    function in derived classes.

    :IVariables:
     - `_request`: The request instance
     - `response_started`: Was the response already started?

    :Types:
     - `_request`: `HTTPRequest`
     - `response_started`: ``bool``
    """
    response_started = None

    def __init__(self, request):
        """
        Initialization

        :Parameters:
         - `request`: Request instance

        :Types:
         - `request`: `HTTPRequest`
        """
        self._request = request

    def _set_state(self, state):
        """
        (Re)set the request state

        :Parameters:
         - `state`: New state class

        :Types:
         - `state`: `BaseState`
        """
        self._request.state = state(self._request)

    def read_request(self):
        """
        Read the request line, parse method, url and protocol version

        :return: A tuple of method, url and protocol version
                 (``('method', 'url', (major, minor))``)
        :rtype: ``tuple``

        :Exceptions:
         - `InvalidRequestLine`: The request line was invalid
        """
        raise StateError()

    def read_headers(self):
        """
        Read and parse the headers

        :return: A dict of comma folded headers, keys are lower cased
        :rtype: ``dict``

        :Exceptions:
         - `http._util.InvalidHeaderLine`: An invalid header line was found
         - `http._util.IncompleteHeaders`: The sents headers are incomplete
        """
        raise StateError()

    def request_body_stream(self):
        """
        Return a stream for the request body.
        
        Chunking and Expect handling are done transparently.

        :return: A stream for the request body
        :rtype: ``dict``
        """
        raise StateError()

    def send_continue(self):
        """ Send 100 Continue intermediate response """
        raise StateError()

    def _send_continue(self):
        """ Actually 100 continue sending impl, for out of state needs """
        assert self._request.protocol >= (1, 1), "Protocol < 1.1"
        writer = self._request.connection.writer
        writer.write("HTTP/1.1 100 Continue" + CRLF + CRLF)
        writer.flush()
        self._request.sent_100 = True

    def send_status(self, status):
        """
        Send the response status line

        :Parameters:
         - `status`: The status line (3 digit code, space, reason)

        :Types:
         - `status`: ``str``
        """
        # pylint: disable = W0613

        raise StateError()

    def send_headers(self, headers):
        """
        Send the headers

        Actually the headers may be accumulated until finish_headers is called

        :Parameters:
         - `headers`: List of headers (``[('name', 'value'), ...]``)

        :Types:
         - `headers`: ``iterable``
        """
        # pylint: disable = W0613

        raise StateError()

    def finish_headers(self):
        """
        Finish header sending, prepare the response for the body

        This function does *not* guarantee, that headers are actually sent.
        It might be implemented in a manner that headers are still being
        modified, when the first body chunk comes in (but they all must
        be flushed then).
        """
        raise StateError()

    def response_body_stream(self):
        """ Retrieve the response body stream """
        raise StateError()


class RequestInitialState(BaseState):
    """
    Initial state of a request, for example on a fresh connection.

    States to go from here:

    - `RequestLineReadyState`

    :CVariables:
     - `_LINE_MATCH`: Regex match callable to check if the line does not 
       start with a WS
     - `_VER_MATCH`: Regex match callable to parse the HTTP version

    :Types:
     - `_LINE_MATCH`: ``callable``
     - `_VER_MATCH`: ``callable``
    """
    response_started = False
    _LINE_MATCH = _re.compile(r'\S').match
    _VER_MATCH = _re.compile(r'HTTP/(?P<major>\d+)\.(?P<minor>\d+)$').match

    def read_request(self):
        """ Read request line """
        request = self._request
        request_line = request.connection.reader.readline()
        if not self._LINE_MATCH(request_line):
            raise InvalidRequestLine("Invalid request line format")

        request_line = request_line.split()
        if len(request_line) == 2:
            (method, url), protocol = request_line, (0, 9)
            if method != 'GET':
                raise InvalidRequestLine("Invalid method on HTTP/0.9 request")
        elif len(request_line) == 3:
            method, url, protocol = request_line
            match = self._VER_MATCH(protocol)
            if not match:
                raise InvalidRequestLine("Invalid protocol string")
            protocol = tuple(map(int, match.group('major', 'minor')))
            if protocol < (1, 0):
                raise InvalidRequestLine("Invalid protocol version")
        else:
            raise InvalidRequestLine("Request line format not recognized")

        request.method = method
        request.url = url
        request.protocol = protocol
        self._set_state(RequestLineReadyState)


class RequestLineReadyState(BaseState):
    """
    The headers can be read now

    States to go from here:

    - `RequestHeadersReadyState`
    """
    response_started = False

    def read_headers(self):
        """ Read and parse the headers """
        request = self._request
        if request.protocol >= (1, 0):
            headers = _http_util.read_headers(request.connection.reader)
            if request.protocol >= (1, 1) and 'host' not in headers:
                raise MissingHostHeader(
                    "HTTP/1.1 requests MUST supply a Host header"
                )
        else:
            headers = {}
        request.headers = headers
        self._set_state(RequestHeadersReadyState)


class RequestHeadersReadyState(BaseState):
    """
    The body can be read now and/or the response can be started

    States to go from here:

    - `ResponseContinueWaitState`
    - `ResponseStatusWaitState`

    :CVariables:
     - `_DECODERS`: Decoder mapping accessor

    :Types:
     - `_DECODERS`: ``callable``
    """
    response_started = False
    _DECODERS = {
        'chunked': _http_util.ChunkedReader,
    }.get

    def __init__(self, request):
        """ Initialization """
        super(RequestHeadersReadyState, self).__init__(request)
        self._request._request_body_stream, self._next_state = \
            self._setup_request_body_stream()

    def _setup_request_body_stream(self):
        """ Return a body stream """
        # pylint: disable = R0912

        next_state, request = ResponseStatusWaitState, self._request
        stream = oldstream = request.connection.reader

        # First look out for Transfer-Encoding
        if request.protocol >= (1, 1):
            codings = [item for item in [
                item.strip().lower() for item in
                request.headers.get('transfer-encoding', '').split(',')
            ] if item and item != 'identity'][::-1]
            if codings:
                if codings[0] != 'chunked':
                    raise InvalidTransferEncoding(
                        "Last transfer encoding MUST be chunked"
                    )
                for coding in codings:
                    decoder = self._DECODERS(coding)
                    if decoder is None:
                        raise UnImplemented(
                            "Transfer-Encoding: %s in not implemented" %
                            coding
                        )
                    stream = decoder(stream)

        # Content-Length is second choice
        if stream == oldstream and 'content-length' in request.headers:
            try:
                clen = int(request.headers['content-length'])
                if clen < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise InvalidContentLength(
                    "Provide a valid Content-Length, please."
                )
            else:
                stream = _impl_util.ContentLengthReader(stream, clen)

        # No body at all
        if stream == oldstream:
            stream = None

        # Expect handling
        elif request.protocol >= (1, 1) and 'expect' in request.headers:
            # the lowering is only partially correct (RFC 2616),
            # but we're checking for the only known (insensitive) token
            # token anyway, so it doesn't hurt.
            expectations = set([item.strip().lower() for item in
                request.headers['expect'].split(',')])
            if '100-continue' in expectations and len(expectations) == 1:
                stream = _http_util.ExpectationReader(stream, request)
            elif expectations:
                raise ExpectationFailed("Unrecognized expectation")
            next_state = ResponseContinueWaitState
            request.expects_100 = True

        if stream is not None and stream != oldstream:
            stream = _stream.GenericStream(stream, read_exact=True)

        return stream, next_state

    def request_body_stream(self):
        """ Determine the stream for the request body """
        self._set_state(self._next_state)
        return self._request._request_body_stream # pylint: disable = W0212

    def send_status(self, status):
        """ Send status line """
        self._set_state(self._next_state)
        return self._request.send_status(status)


class ResponseContinueWaitState(BaseState):
    """
    We're waiting for either 100 continue emission of send_status

    States to go from here:

    - `ResponseStatusWaitState`
    """
    response_started = False

    def send_continue(self):
        """ Send 100 continue intermediate response """
        self._send_continue()
        self._set_state(ResponseStatusWaitState)

    def send_status(self, status):
        """ Send status line """
        self._set_state(ResponseStatusWaitState)
        return self._request.send_status(status)


class ResponseStatusWaitState(BaseState):
    """
    Waiting for status line

    States to go from here:

    - `ResponseHeadersWaitState`
    """
    response_started = False

    def send_status(self, status):
        """ Send status line """
        self._request._response_status_line = status
        self._request.response_status = int(status[:3])
        self._set_state(ResponseHeadersWaitState)


class ResponseHeadersWaitState(BaseState):
    """
    We're waiting for headers to be set and sent

    States to go from here:

    - `ResponseBodyWaitState`

    :IVariables:
     - `_headers`: Ordered list of header names
     - `_hdict`: Dict of header names -> values (``{'name': ['value', ...]}``)

    :Types:
     - `_headers`: ``list``
     - `_hdict`: ``dict``
    """
    response_started = False

    def __init__(self, request):
        """ Initialization """
        super(ResponseHeadersWaitState, self).__init__(request)
        self._headers = ['server', 'date']
        self._hdict = {'server': [], 'date': []}

    def send_headers(self, headers):
        """ Send headers """
        for name, value in headers:
            name = name.lower()
            if name not in self._hdict:
                self._headers.append(name)
                self._hdict[name] = []
            self._hdict[name].append(value)

    def finish_headers(self):
        """ Finalize headers """
        self._set_state(ResponseBodyWaitState)
        request = self._request
        if request.protocol >= (1, 0):
            out, hdict, writer = [], self._hdict, request.connection.writer
            request.response_headers = hdict
            request.connection.compute_status()
            if request.connection.persist or request.sent_100:
                # suck the whole request body, before sending a response
                # (avoiding dead locks)

                if request.expects_100 and not request.sent_100:
                    request.send_continue = self._send_continue
                # pylint: disable = W0212
                stream = request._request_body_stream
                if stream is not None:
                    dummy, read = True, stream.read
                    while dummy:
                        dummy = read(0)
                if request.send_continue == self._send_continue:
                    del request.send_continue

            hdict.update({
                'server': ["WTF"], 'date': [_http_util.make_date()]
            })
            for key, value in request.connection.headers.iteritems():
                if key not in hdict:
                    self._headers.append(key)
                hdict[key] = [value]

            for name in self._headers:
                if name in hdict:
                    cname = name.title()
                    if name == 'set-cookie':
                        out.extend([(cname, val) for val in hdict[name]])
                    else:
                        out.append((cname, ", ".join(hdict[name])))

            writer.write(
                # pylint: disable = W0212
                "HTTP/%d.%d " % request.http_version +
                    request._response_status_line + CRLF
            )
            writer.writelines([
                "%s: %s%s" % (name, value, CRLF) for name, value in out
            ])
            writer.write(CRLF)


class ResponseBodyWaitState(BaseState):
    """
    We're waiting for someone to send the response body

    States to go from here:

    - `ResponseDoneState`
    """
    response_started = True

    def response_body_stream(self):
        """ Determine the response body stream """
        self._set_state(ResponseDoneState)
        request = self._request
        if request.method == 'HEAD':
            stream = _stream.dev_null
        else:
            stream = request.connection.writer
            if request.response_headers and \
                    'transfer-encoding' in request.response_headers:
                stream = _stream.GenericStream(
                    _http_util.ChunkedWriter(stream)
                )
            request._response_body_stream = stream
        return stream


class ResponseDoneState(BaseState):
    """ Nothing can be done here anymore """
    response_started = True


class HTTPRequest(object):
    """
    HTTP Request abstraction

    :IVariables:
     - `_request_body_stream`: Stream for accessing the request body (or
       ``None``). Transfer encodings and the Expect/Continue mechanism
       are dealt with transparently. Just read it.
     - `_response_body_stream`: Stream for writing the response body (or
       ``None``)
     - `_server`: HTTP server instance
     - `state`: Current state object. Additional methods and properties are
       looked up there (see `BaseState` for documentation)
     - `headers`: Request header dictionary
     - `response_status`: Response status code sent to the client
     - `response_headers`: Response headers sent to the client
     - `method`: Request method used
     - `url`: Request URL
     - `protocol`: Request protocol version
     - `connection`: HTTP connection abstraction
     - `http_version`: Maximum supported HTTP version
     - `flags`: Worker flags

    :Types:
     - `_request_body_stream`: `wtf.stream.GenericStream`
     - `_response_body_stream`: `wtf.stream.GenericStream`
     - `_server`: `http.HTTPServer`
     - `state`: `BaseState`
     - `headers`: ``dict``
     - `response_status`: ``int``
     - `response_headers`: ``dict``
     - `method`: ``str``
     - `url`: ``str``
     - `protocol`: ``tuple``
     - `connection`: `HTTPConnection`
     - `http_version`: ``tuple``
     - `flags`: `wtf.impl.FlagsInterface`
    """
    _request_body_stream, _response_body_stream = None, None
    expects_100, sent_100, _response_status_line = False, False, None
    headers, response_status, response_headers = None, None, None
    method, url, protocol = 'GET', '*', (0, 9)
    connection = None

    def __init__(self, server, connection, flags):
        """
        Initialization

        :Parameters:
         - `server`: Server instance
         - `connection`: Connection, this request is served on
         - `flags`: Worker flags

        :Types:
         - `server`: `HTTPServer`
         - `connection`: `Connection`
         - `flags`: `FlagsInterface`
        """
        self._server = server
        self.http_version = server.http_version
        self.keep_alive = server.keep_alive
        self.flags = flags
        self.connection = _http_util.HTTPConnection(self, connection)
        self.state = RequestInitialState(self)

    def close(self):
        """ Close all streams """
        self._set_state(ResponseDoneState)
        if self._response_body_stream is not None:
            self._response_body_stream.close() # flush all pending stuff
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def __getattr__(self, name):
        """
        Delegate call to the current state implementation

        :Parameters:
         - `name`: The symbol to fetch

        :Types:
         - `name`: ``str``

        :return: The resolved symbol depending on the state (should be a
                 callable)
        :rtype: any
        """
        return getattr(self.state, name)

    def parse(self):
        """
        Parse the request

        :return: Request environment (based on the connection environment)
        :rtype: ``dict``
        """
        try:
            self.read_request()
            self.connection.settimeout(self._server.timeouts.general)
            if self.protocol > self.http_version:
                raise UnsupportedHTTPVersion("Sorry.")
            self.read_headers()
        except _socket.timeout:
            raise RequestTimeout("Try typing a little faster")

    def error(self, status, message):
        """
        Emit a simple error

        :Parameters:
         - `status`: The status line to emit, it will be repeated in the body
           (which is labeled text/plain for >= HTTP/1.0 or wrapped into HTML
           for HTTP/0.9)
         - `message`: The message to emit

        :Types:
         - `status`: ``str``
         - `message`: ``str``
        """
        protocol, write = self.protocol, self.connection.writer.write
        if protocol >= (1, 0):
            out = status + CRLF + message + CRLF
            write("HTTP/%d.%d " % self.http_version + status + CRLF)
            write("Date: %s%s" % (_http_util.make_date(), CRLF))
            write("Content-Type: text/plain" + CRLF)
            write("Content-Length: %s%s" % (len(out), CRLF))
            if protocol >= (1, 1):
                write("Connection: close" + CRLF)
            write(CRLF)
            write(out)
        else:
            out = """
<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html>
<head><title>%(status)s</title></head>
<body><h1>%(status)s</h1><p>%(message)s</p></body>
</html>
            """.strip() % {
                'status': status.replace('&', '&amp;').replace('<', '&lt;'),
                'message': message.replace('&', '&amp;').replace('<', '&lt;'),
            }
            write(out + CRLF)
