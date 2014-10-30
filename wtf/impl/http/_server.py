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
HTTP Server Implementation
==========================

Here's the http handling implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import re as _re
import socket as _socket
import sys as _sys
import traceback as _traceback
import urlparse as _urlparse

from wtf import impl as _impl
from wtf import stream as _stream
from wtf import webutil as _webutil
from wtf.impl import _connection
from wtf.impl import _gateway
from wtf.impl.http import _request


class HTTPServer(object):
    """
    HTTP server

    :IVariables:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments
     - `timeouts`: Timeout specs
     - `http_version`: Supported HTTP version (``(major, minor)``)
     - `_gateway`: Gateway instance

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``
     - `timeouts`: `_TimeOuts`
     - `http_version`: ``tuple``
     - `_gateway`: `Gateway`
    """
    __implements__ = [_impl.ServerInterface]

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.impl.ServerInterface`
        """
        self.config, self.opts, self.args = config, opts, args
        self.timeouts = _TimeOuts(config)
        version = unicode(config.wtf('http-version', '1.1'))
        vtuple = tuple(map(int, version.split('.')))
        if len(vtuple) != 2 or not((1, 0) <= vtuple <= (1, 1)):
            raise ValueError("Unrecognized HTTP version %s" % version)
        self.http_version = vtuple
        self.keep_alive = not config.wtf('autoreload', False) \
            and config.wtf('keep-alive', True)
        self._gateway = Gateway(config, opts, args)

    def handle(self, (sock, peername), application, flags):
        """
        Handle an accepted socket

        :See: `wtf.impl.ServerInterface`
        """
        # pylint: disable = R0912, R0915

        conn = _connection.Connection(sock, peername)
        try:
            conn.settimeout(self.timeouts.general)
            gateway, first = self._gateway.handle, True
            while True:
                request = _request.HTTPRequest(self, conn, flags)
                try:
                    try:
                        try:
                            gateway(conn, request, application)
                        except _request.RequestTimeout:
                            if first:
                                raise
                            break # kept alive, but no further request
                        except _socket.error, e:
                            if e[0] not in (_errno.EPIPE, _errno.ECONNRESET):
                                raise
                            break # no matter what, connection is done.
                    except (SystemExit, KeyboardInterrupt):
                        raise
                    except _request.ParseError, e:
                        try:
                            request.error(e.status, e.msg)
                        except _socket.error:
                            pass # who cares?
                        break
                    except:
                        if not request.response_started:
                            try:
                                request.error(
                                    "500 Internal Server Error",
                                    "Something went wrong while processing "
                                    "the request. You might want to try "
                                    "again later. Sorry for the "
                                    "inconvenience."
                                )
                            except _socket.error:
                                pass
                        print >> _sys.stderr, \
                            "Request aborted due to exception:\n" + ''.join(
                                _traceback.format_exception(*_sys.exc_info())
                            )
                        break
                    else:
                        if not request.connection.persist:
                            break
                finally:
                    request.close()
                first, _ = False, conn.settimeout(self.timeouts.keep_alive)
        finally:
            try:
                conn.close()
            except (SystemExit, KeyboardInterrupt):
                raise
            except:
                pass # nothing we could do here anyway, maybe log it?


class Gateway(_gateway.Gateway):
    """
    HTTP implementation specific gateway

    :CVariables:
     - `_NORM_SUB`: Regex substitution callable for norming HTTP header names
     - `_SLASH_SPLIT`: Regex splitter callable for encoded slashes
     - `_STRIPPED`: List of HTTP variable names, which are expected to
       appear without the ``HTTP_`` prefix
     - `_HOPS`: Set of standard Hop-by-Hop headers

    :Types:
     - `_NORM_SUB`: ``callable``
     - `_SLASH_SPLIT`: ``callable``
     - `_STRIPPED`: ``tuple``
     - `_HOPS`: ``set``
    """
    _NORM_SUB = _re.compile(r'[^a-zA-Z\d]').sub
    _SLASH_SPLIT = _re.compile(r'%2[fF]').split
    _STRIPPED = ("HTTP_CONTENT_TYPE", "HTTP_CONTENT_LENGTH")
    _HOPS = set(["HTTP_" + _NORM_SUB("_", _HOPS).upper() for _HOPS in """
        Connection
        Keep-Alive
        Proxy-Authenticate
        Proxy-Authorization
        TE
        Trailers
        Transfer-Encoding
        Upgrade
    """.split()])

    def _populate_base_env(self, base_env):
        """
        Add HTTP implementation specific env constants

        :See: `_gateway.Gateway._populate_base_env`
        """
        base_env.update({
            'SERVER_NAME': self.config.wtf.servername,
            'SCRIPT_NAME': '',
        })
        return base_env

    def _init_from_request(self, connection, request):
        """
        Create HTTP implementation specific request environment

        :See: `_gateway.Gateway._init_from_request`
        """
        request.parse()
        environ = dict(("HTTP_" + self._NORM_SUB("_", key).upper(), value)
            for key, value in request.headers.iteritems())
        for key in self._STRIPPED:
            if key in environ:
                environ[key[5:]] = environ.pop(key)
        if 'HTTP_TRANSFER_ENCODING' in environ:
            environ['CONTENT_LENGTH'] = '-1'
        if 'HTTP_CONNECTION' in environ:
            connhops = set(
                "HTTP_" + self._NORM_SUB("_", key.strip()).upper()
                for key in environ['HTTP_CONNECTION'].split(',')
            )
        else:
            connhops = set()
        for key in (self._HOPS | connhops):
            if key in environ:
                del environ[key]

        _, _, path, query, _ = _urlparse.urlsplit(request.url)
        environ.update({
            'REQUEST_METHOD':    request.method,
            'SERVER_PROTOCOL':   "HTTP/%d.%d" % request.protocol,
            'REQUEST_URI':       _urlparse.urlunsplit((
                "", "", path, query, "")),
            'QUERY_STRING':      query,
            'SERVER_ADDR':       connection.server_addr[0],
            'SERVER_PORT':       str(connection.server_addr[1]),
            'REMOTE_ADDR':       connection.remote_addr[0],
            'REMOTE_PORT':       str(connection.remote_addr[1]),

            'wsgi.multithread':  request.flags.multithread,
            'wsgi.multiprocess': request.flags.multiprocess,
            'wsgi.run_once':     request.flags.run_once,
            'wsgi.input':        request.request_body_stream() or
                                     _stream.dev_null,
            'wsgi.url_scheme':   'http', # no ssl for now
        })
        if '%' in path:
            path = '%2F'.join(_webutil.unquote(item)
                for item in self._SLASH_SPLIT(path))
        environ['PATH_INFO'] = path

        def start_response(status, headers):
            """ HTTP response starter """
            request.send_status(status)
            request.send_headers(headers)
            request.finish_headers()
            return request.response_body_stream()

        return environ, start_response


class _TimeOuts(object):
    """
    Timeout specificiations

    :IVariables:
     - `general`: General timeout, defaults to 300.0 secs
     - `keep_alive`: Keep-alive timeout, defaults to 5.0 secs

    :Types:
     - `general`: ``float``
     - `keep_alive`: ``float``
    """

    def __init__(self, config):
        """
        Initialization

        :Parameters:
         - `config`: Configuration

        :Types:
         - `config`: `wtf.config.Config`
        """
        self.general = float(config.wtf.timeout('general', 300))
        self.keep_alive = float(config.wtf.timeout('keep-alive', 5))
