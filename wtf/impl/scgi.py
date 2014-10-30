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
SCGI Implementation
===================

Here's the SCGI handling implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import itertools as _it
import socket as _socket
import sys as _sys
import traceback as _traceback

from wtf import Error
from wtf import impl as _impl
from wtf import stream as _stream
from wtf.config import ConfigurationError
from wtf.impl import _connection
from wtf.impl import _gateway
from wtf.impl import _util as _impl_util


class NetStringError(Error):
    """ Netstring error """


class SCGIServer(object):
    """
    SCGI server

    :IVariables:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``
    """
    __implements__ = [_impl.ServerInterface]

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.impl.ServerInterface`
        """
        self.config, self.opts, self.args = config, opts, args
        self._gateway = Gateway(config, opts, args)

    def handle(self, (sock, peername), application, flags):
        """
        Handle an accepted socket

        :See: `wtf.impl.ServerInterface`
        """
        conn = _connection.Connection(sock, peername)
        try:
            conn.settimeout(None)
            request = SCGIRequest(self, conn, flags)
            try:
                try:
                    self._gateway.handle(conn, request, application)
                except _socket.error, e:
                    if e[0] not in (_errno.EPIPE, _errno.ECONNRESET):
                        raise
                    print >> _sys.stderr, "Connection to webserver died."
                except (SystemExit, KeyboardInterrupt):
                    raise
                except:
                    try:
                        request.error(
                            "500 Internal Server Error",
                            "Something went wrong while processing the "
                            "request. You might want to try again later. "
                            "Sorry for the inconvenience."
                        )
                    except _socket.error:
                        pass
                    print >> _sys.stderr, \
                        "Request aborted due to exception:\n" + ''.join(
                            _traceback.format_exception(*_sys.exc_info())
                        )
            finally:
                request.close()
        finally:
            try:
                conn.close()
            except (SystemExit, KeyboardInterrupt):
                raise
            except:
                pass # not much we can do here anyway. Log it?


class Gateway(_gateway.Gateway):
    """ SCGI implementation specific gateway """

    def __init__(self, config, opts, args):
        """
        Initialization

        :Parameters:
         - `config`: Configuration
         - `opts`: Command line options
         - `args`: Positioned command line arguments

        :Types:
         - `config`: `wtf.config.Config`
         - `opts`: ``optparse.OptionContainer``
         - `args`: ``list``
        """
        super(Gateway, self).__init__(config, opts, args)

        detector = self._detect_scheme_default
        if 'scgi' in config.wtf:
            option = config.wtf.scgi('ssl_detection', 'default')
            if option:
                try:
                    detector = getattr(self,
                        "_detect_scheme_%s" % option.encode('ascii')
                    )
                except (AttributeError, UnicodeError):
                    raise ConfigurationError(
                        "Unrecognized SSL detection method %r" % (option,)
                    )
        self._detect_scheme = detector

    def _init_from_request(self, connection, request):
        """
        Create SCGI implementation specific request environment

        :See: `_gateway.Gateway._init_from_request`
        """
        environ = request.read_environ()
        if 'SCGI' in environ:
            del environ['SCGI']
        environ.update({
            'wsgi.multithread':  request.flags.multithread,
            'wsgi.multiprocess': request.flags.multiprocess,
            'wsgi.run_once':     request.flags.run_once,
            'wsgi.input':        request.request_body_stream or
                                     _stream.dev_null,
            'wsgi.url_scheme':   self._detect_scheme(environ) or
                                    self._detect_scheme_default(environ),
        })

        return environ, request.start_response

    def _detect_scheme_default(self, environ):
        """ HTTPS environment scheme detector (SSL directly in gateway) """
        if environ.get('HTTPS', '').lower() == 'on':
            return 'https'
        return 'http'

    def _detect_scheme_remote_lighttpd(self, environ):
        """
        Scheme detector when lighttpd offloads SSL in the front of the GW

        The lighttpd acts as a HTTP proxy.
        """
        scheme = environ.get('HTTP_X_FORWARDED_PROTO', '').lower()
        if scheme in ('http', 'https'):
            # TODO: allow non-default port configuration
            port = dict(http=80, https=443)[scheme]
            environ['SERVER_PORT'] = str(port)
            if ':' in environ['SERVER_NAME']:
                shost, sport = environ['SERVER_NAME'].rsplit(':', 1)
                try:
                    int(sport)
                except ValueError:
                    pass
                else:
                    environ['SERVER_NAME'] = '%s:%s' % (shost, port)
            return scheme
        return None


class SCGIRequest(object):
    """ SCGI Request abstraction """
    _response_body_stream = None
    request_body_stream = None
    _env = None

    def __init__(self, server, connection, flags):
        """
        Initialization

        :Parameters:
         - `server`: Server instance
         - `connection`: Connection, this request is served on
         - `flags`: Worker flags

        :Types:
         - `server`: `SCGIServer`
         - `connection`: `Connection`
         - `flags`: `FlagsInterface`
        """
        self._server = server
        self.connection = SCGIConnection(connection)
        self.flags = flags

    def close(self):
        """ Close all streams """
        if self._response_body_stream is not None:
            self._response_body_stream.close() # fluuuush
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def read_environ(self):
        """
        Read the environ from the socket

        :return: The header dict
        :rtype: ``dict``

        :Exceptions:
         - `NetStringError`: Error reading or interpreting the netstring
        """
        block = iter(self.connection.read_netstring().split('\0'))
        env = dict(_it.izip(block, block))
        clen = int(env['CONTENT_LENGTH'])
        if clen > 0:
            self.request_body_stream = _stream.GenericStream(
                _impl_util.ContentLengthReader(
                    self.connection.reader, clen
                ),
                read_exact=True,
            )
        self._env = env
        return env

    def start_response(self, status, headers):
        """
        Start response and determine output stream

        :Parameters:
         - `status`: Response status line
         - `headers`: Response headers (``[(key, value), ...]``)

        :Types:
         - `status`: ``str``
         - `headers`: ``list``

        :return: response stream
        :rtype: `stream.GenericStream`
        """
        writer = self.connection.writer
        writer.write("Status: %s\n" % status)
        writer.writelines("%s: %s\n" % (key, value) for key, value in headers)
        writer.write("\n")
        if self._env['REQUEST_METHOD'] == 'HEAD':
            stream = _stream.dev_null
        else:
            self._response_body_stream = stream = writer
        return stream

    def error(self, status, message):
        """
        Emit a simple error

        :Parameters:
         - `status`: Status line
         - `message`: Message

        :Types:
         - `status`: ``str``
         - `message`: ``str``
        """
        out = "%s\n%s\n" % (status, message)
        write = self.connection.writer.write
        write("Status: %s\n" % status)
        write("Content-Type: text/plain\n")
        write("Content-Length: %s\n" % len(out))
        write("\n")
        write(out)


class SCGIConnection(object):
    """
    SCGI connection

    :IVariables:
     - `reader`: Connection read stream
     - `writer`: Connection write stream
     - `settimeout`: Timeout setter

    :Types:
     - `reader`: `stream.GenericStream`
     - `writer`: `stream.GenericStream`
     - `settimeout`: ``callable``
    """

    def __init__(self, connection):
        """
        Initialization

        :Parameters:
         - `connection`: Socket connection

        :Types:
         - `connection`: `Connection`
        """
        self.reader = connection.reader()
        self.writer = connection.writer()
        self.settimeout = connection.settimeout

    def __del__(self):
        self.close()

    def close(self):
        """ Close the streams """
        try:
            reader, self.reader = self.reader, None
            if reader is not None:
                reader.close()
        finally:
            writer, self.writer = self.writer, None
            if writer is not None:
                writer.close()

    def read_netstring(self):
        """
        Read "netstring" from connection

        :return: The netstring value
        :rtype: ``str``

        :Exceptions:
         - `NetStringError`: Error reading or interpreting the netstring
        """
        data = _stream.read_exact(self.reader, self._netstring_size())
        if self.reader.read(1) != ',':
            raise NetStringError("EOS before netstring delimiter")
        return data

    def _netstring_size(self):
        """
        Read netstring size from connection

        :return: The netstring size
        :rtype: ``int``

        :Exceptions:
         - `NetStringError`: Error reading or interpreting the number
        """
        chars, read = [], self.reader.read
        push = chars.append
        while True:
            char = read(1)
            if not char:
                raise NetStringError("EOS before netstring size delimiter")
            if char == ':':
                break
            push(char)
        chars = ''.join(chars)
        try:
            return int(chars)
        except ValueError:
            raise NetStringError("Invalid netstring size: %r" % chars)
