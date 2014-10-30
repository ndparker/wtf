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
Application Wrapper
===================

This modules wraps the WSGI interface, initializes middleware and provides
an application friendly wrapper.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import util as _util
from wtf.app import response as _response


class Dispatcher(object):
    """
    Main dispatching loop

    :IVariables:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``
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
        self._resolver = _util.load_dotted(config.app.resolver)(
            config, opts, args
        )
        self._request = _util.load_dotted(
            config.app('request', 'wtf.app.request.Request'))
        self._response = _util.load_dotted(
            config.app('response', 'wtf.app.response.Response'))

        if 'codec' in config.app and 'cookie' in config.app.codec:
            cookie_codec = config.app.codec.cookie.encode('ascii')
        else:
            cookie_codec = 'wtf.app.cookie.DefaultCookie'

        self._addenv = {
            'wtf.codec.cookie':
                _util.load_dotted(cookie_codec)(config, opts, args)(),
        }

    def __call__(self, environ, start_response):
        """
        WSGI entry point

        :Parameters:
         - `environ`: WSGI environment
         - `start_response`: Response starter callable

        :Types:
         - `environ`: ``dict``
         - `start_response`: ``callable``
        """
        environ.update(self._addenv)
        req = self._request(environ)
        resp = self._response(req, start_response)
        func, errorfuncs = None, set()
        while True:
            try:
                try:
                    try:
                        if func is None:
                            func = self._resolver.resolve(req)
                        ret = func(req, resp)
                    except _response.Done:
                        ret = None
                    resp.write('') # make sure, start_response is called
                    return ret or []
                except _response.http.HTTPRedirectResponse, e:
                    e.param['location'] = abs_location(
                        req, e.param['location']
                    )
                    raise
            except _response.http.HTTPResponse, e:
                resp.status(e.status, e.reason)
                func = self._resolver.error(e.status)
                if func and func not in errorfuncs: # avoid error loops
                    errorfuncs.add(func)
                    continue
                e.headers(resp.headers)
                resp.write('')
                return [e.body()]

            # never reached:
            break


def abs_location(request, location):
    """ Make absolute location """
    import urlparse as _urlparse

    if isinstance(location, unicode):
        location = location.encode('utf-8')
    else:
        location = str(location)
    parsed = _urlparse.urlparse(location)
    if parsed[0] and parsed[1]:
        return location
    return str(request.abs_uri(location, decode=False))
