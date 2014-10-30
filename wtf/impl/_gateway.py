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
Gateway Implementation
======================

Here's the gateway implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import os as _os
import sys as _sys
import traceback as _traceback

from wtf import Error
from wtf.util import Property


class GatewayError(Error):
    """ Misuse of the gateway """

class ResponseNotStarted(GatewayError):
    """ Attempt to deliver data without calling start_response """

class ResponseAlreadyStarted(GatewayError):
    """ The response was already started """


class Gateway(object):
    """
    WS gateway logic

    :IVariables:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments
     - `_baseenv`: Base environment (``((key, value), ...)``)

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``
     - `_baseenv`: ``tuple``
    """

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
        self.config, self.opts, self.args = config, opts, args
        # populate from os environment, but don't pollute with gateway stuff
        base_env = dict((key, value) for key, value in _os.environ.iteritems()
            if not key.startswith('HTTP_')
            and key not in ('CONTENT_LENGTH', 'CONTENT_TYPE')
        )
        base_env.update({
            'wsgi.version': (1, 0),
            'wsgi.errors': _sys.stderr,
        })
        # base_env is used by every request. To make it thread safe,
        # we need it shallow-copied for every request - making it
        # readonly is the best way to ensure that.
        self._baseenv = tuple(self._populate_base_env(base_env).iteritems())

    def _populate_base_env(self, base_env):
        """
        Modify base_env before it's finalized

        This is for subclasses to allow modifiying the base environment.
        By default this method is a no-op.

        :Parameters:
         - `base_env`: The base environment so far

        :Types:
         - `base_env`: ``dict``

        :return: The modified base_env (maybe the same dict as passed in)
        :rtype: ``dict``
        """
        return base_env

    def handle(self, connection, request, application):
        """
        Gateway between the request and the application

        :Parameters:
         - `connection`: Connection instance
         - `request`: Request instance (only specific subclasses have to
           understand it)
         - `application`: WSGI application

        :Types:
         - `connection`: `Connection`
         - `request`: any
         - `application`: ``callable``
        """
        environ = dict(self._baseenv)
        renv, start_response = self._init_from_request(connection, request)
        environ.update(renv)
        responder = ResponseStarter(start_response)
        iterator = application(environ, responder)
        try:
            close = iterator.close
        except AttributeError:
            close = lambda: None

        try:
            # Try determining content length
            if not responder.started:
                iterator = iter(iterator)
                try:
                    chunk = iterator.next()
                except StopIteration:
                    # we could say Content-Length: 0, but there might be
                    # a reason not to (like body-less responses)
                    chunk, ilen = "", -1
                else:
                    try:
                        ilen = len(iterator)
                    except TypeError: # unsized object
                        ilen = -1
                if ilen == 0 and not responder.started:
                    have_length = 'content-length' in [key.lower()
                        for key, _ in responder.headers]
                    if not have_length:
                        responder.headers.append(
                            ('Content-Length', str(len(chunk)))
                        )
                responder.write(chunk)
            # Pump out
            for chunk in iterator:
                if chunk:
                    responder.write(chunk)
        finally:
            close()

        # Write at least the headers
        if not responder.started:
            responder.write_headers("", True)

    def _init_from_request(self, connection, request):
        """
        Initialize env and response starter from request implementation

        Subclasses must override the method.

        :Parameters:
         - `connection`: The connection the request is handled on
         - `request`: The request instance

        :Types:
         - `connection`: `Connection`
         - `request`: any

        :return: A tuple of the request env and a specific response starter
                 (```(dict, callable)``)
        :rtype: ``dict``
        """
        raise NotImplementedError()


class ResponseStarter(object):
    """
    WSGI start_response callable with context

    :IVariables:
     - `_stream`: Response body stream
     - `_start_response`: Implementation defined response starter
     - `_response`: Status and headers supplied by the application
     - `write`: Current write callable
     - `started`: Flag indicating whether the response was started or not

    :Types:
     - `_stream`: ``file``
     - `_start_response`: ``callable``
     - `_response`: ``tuple``
     - `write`: ``callable``
     - `started`: ``bool``
    """
    started, _response, _stream = False, None, None

    def __init__(self, start_response):
        """
        Initialization

        :Parameters:
         - `start_response`: Implementation specific response starter;
           a callable, which takes status and headers and returns a body
           stream

        :Types:
         - `start_response`: ``callable``
        """
        self._start_response = start_response
        self.write = self.write_initial

    def __call__(self, status, headers, exc_info=None):
        """
        Actual WSGI start_response function

        :Parameters:
         - `status`: Status line
         - `headers`: Header list
         - `exc_info`: Optional exception (output of ``sys.exc_info()``)

        :Types:
         - `status`: ``str``
         - `headers`: ``list``
         - `exc_info`: ``tuple``

        :return: Write callable (according to PEP 333)
        :rtype: ``callable``
        """
        if self._response is not None:
            if exc_info is None:
                raise ResponseAlreadyStarted()
            elif self.started:
                try:
                    raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    exc_info = None
            else:
                try:
                    print >> _sys.stderr, \
                        "start_response() called with exception:\n" + ''.join(
                            _traceback.format_exception(*exc_info)
                        )
                finally:
                    exc_info = None
        self._response = status, headers
        self.write = self.write_headers
        return self.write

    @Property
    def headers():
        """
        The response headers as supplied by the application

        Exceptions:
          `ResponseNotStarted` : The response was not started yet

        :Type: ``list``
        """
        # pylint: disable = E0211, C0111, W0212, W0612
        def fget(self):
            if self._response is None:
                raise ResponseNotStarted()
            return self._response[1]
        return locals()

    @Property
    def status():
        """
        The response status as supplied by the application

        Exceptions:
          `ResponseNotStarted` : The response was not started yet

        :Type: ``str``
        """
        # pylint: disable = E0211, C0111, W0212, W0612
        def fget(self):
            if self._response is None:
                raise ResponseNotStarted()
            return self._response[0]
        return locals()

    def write_initial(self, data):
        """
        Initial write callable - raises an error

        If this method is called as ``.write``, it generates an error,
        because the gateway was misused (__call__ not executed).

        :Parameters:
         - `data`: The string to write

        :Types:
         - `data`: ``str``

        :Exceptions:
         - `ResponseNotStarted`: Response was not started properly
        """
        if self.write == self.write_initial:
            raise ResponseNotStarted()
        if data:
            self.write(data)

    def write_headers(self, data, _do_init=False):
        """
        Secondary write callable - sends headers before real data

        This write callable initializes the response on the first real
        occurence of data. The ``write`` method will be set directly to
        the stream's write method after response initialization.

        :Parameters:
         - `data`: The data to write
         - `_do_init`: Initialize the headers anyway (regardless of data?)

        :Types:
         - `data`: ``str``
         - `_do_init`: ``bool``
        """
        if self.write == self.write_headers:
            if data or _do_init:
                self.started = True
                self._stream = self._start_response(*self._response)
                self.write = self.write_body
        if data:
            self.write(data)

    def write_body(self, data):
        """
        Final write callable

        This adds a flush after every write call to the stream -- as
        required by the WSGI specification.

        :Parameters:
         - `data`: The data to write

        :Types:
         - `data`: ``str``
        """
        if data:
            self._stream.write(data)
            self._stream.flush()
