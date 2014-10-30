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
Static Resource Delivery
========================

This service provides static delivery helpers. It's based on the
`resource service`_, which must be loaded (read: configured) before this
one.

.. _resource service: `wtf.app.services.resource.ResourceService`
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import os as _os
import sys as _sys

from wtf.app.decorators import Method
from wtf import services as _services
from wtf import stream as _stream

from __svc__.wtf import resource as _resource


class Controller(object):
    """
    Static delivery controller implementation

    :IVariables:
     - `_svc`: The service object
     - `_resource`: The resource list (``[Resource, ...]``)
     - `_group`: The regex group

    :Types:
     - `_svc`: `StaticService`
     - `_resource`: ``list``
     - `_group`: ``unicode``
    """
    def __init__(self, svc, resource, group):
        """
        Initialization

        :Parameters:
         - `svc`: Service
         - `resource`: Resource name
         - `group`: Regex group

        :Types:
         - `svc`: `StaticService`
         - `resource`: ``unicode``
         - `group`: ``unicode``
        """
        self._svc = svc
        self._resource = _resource[resource]
        self._group = group

    @Method('GET')
    def __call__(self, request, response):
        """ Actual controller implementation """
        if self._group is None:
            filename = request.url.path
        else:
            filename = request.match.group(self._group)

        for rsc in self._resource:
            try:
                stream = rsc.open(filename, blockiter=0)
            except IOError:
                continue
            else:
                break
        else:
            response.raise_error(404)

        response.content_length(len(stream))
        response.last_modified(stream.last_modified)
        response.content_type(self._svc.mime_type(filename))
        return stream


class ResponseFactory(object):
    """
    Response hint factory collection

    :IVariables:
      `_env` : ``dict``
        ENV update dict
    """

    def __init__(self, svc, x_sendfile):
        """
        Initialization

        :Parameters:
          `svc` : `StaticService`
            StaticService instance

          `x_sendfile` : ``str``
            X-Sendfile header name or ``None``
        """
        x_sendfile = x_sendfile and str(x_sendfile.strip()) or None
        def sendfile(response):
            """ Response factory for ``sendfile`` """
            return self._sendfile_factory(response, svc, x_sendfile)

        self._env = {
            'wtf.response.sendfile': sendfile,
        }

    def update_env(self, env):
        """
        Update request environment

        :Parameters:
          `env` : ``dict``
            The environment to update

        :Return: The env dict again (MAY be a copy)
        :Rtype: ``dict``
        """
        env.update(self._env)
        return env

    def _sendfile_factory(self, response, svc, x_sendfile):
        """
        Response factory for ``sendfile``

        :Parameters:
          `response` : `wtf.app.response.Response`
            Response object

          `svc` : `StaticService`
            Static service instance

          `x_sendfile` : ``str``
            X-Sendfile header name or ``None``

        :Return: The ``sendfile`` callable
        :Rtype: ``callable``
        """
        def sendfile(name, content_type=None, charset=None, expiry=None,
                     audience=None, local=True):
            """
            Conditional sendfile mechanism

            If configured with::

                [static]
                x_sendfile = 'X-Sendfile'

            The file is not passed but submitted to the gateway with the
            ``X-Sendfile`` header containing the filename, but no body.
            Otherwise the stream is passed directly. In order to make the
            filename passing work, the gateway must be configured to do
            something with the header!

            :Parameters:
              `name` : ``str``
                Filename to send

              `content_type` : ``str``
                Optional content type. If it's the empty string, the mime
                types file is queried. If it's ``None``, it's not touched.

              `charset` : ``str``
                Optional charset

              `expiry` : ``int``
                Expire time in seconds from now

              `audience` : ``str``
                Caching audience (``private`` or ``public``)

              `local` : ``bool``
                Is this file local (vs. remote only on the gateway)? If true,
                content length and last modified time are determined here.
                If ``x_sendfile`` is not configured, this flag is ignored.

            :Return: Iterable delivering the stream
            :Rtype: ``iterable``

            :Exceptions:
              - `Exception` : Anything happened
            """
            if local or not x_sendfile:
                stat = _os.stat(name)
                response.last_modified(_datetime.datetime.utcfromtimestamp(
                    stat.st_mtime
                ))
                response.content_length(stat.st_size)

            if expiry is not None:
                response.cache(expiry, audience=audience)
            if content_type == '':
                content_type = svc.mime_type(name)
            response.content_type(content_type, charset=charset)
            if x_sendfile:
                response.headers.set(x_sendfile, name)
                return ()

            stream = file(name, 'rb')
            try:
                return _stream.GenericStream(stream, blockiter=0)
            except: # pylint: disable = W0702
                e = _sys.exc_info()
                try:
                    stream.close()
                finally:
                    try:
                        raise e[0], e[1], e[2]
                    finally:
                        del e

        return sendfile


class Middleware(object):
    """
    Static middleware - provides ``response.sendfile``

    :IVariables:
      `_func` : ``callable``
        Next WSGI handler

      `_factory` : `ResponseFactory`
        Response factory
    """

    def __init__(self, svc, x_sendfile, func):
        """
        Initialization

        :Parameters:
          `svc` : `StaticService`
            The static service instance

          `x_sendfile` : ``str``
            X-Sendfile-Header name or ``None``

          `func` : ``callable``
            Next WSGI handler
        """
        self._factory = ResponseFactory(svc, x_sendfile)
        self._func = func

    def __call__(self, environ, start_response):
        """
        Middleware handler

        :Parameters:
          `environ` : ``dict``
            WSGI environment

          `start_response` : ``callable``
            Start response callable

        :Return: WSGI response iterable
        :Rtype: ``iterable``
        """
        environ = self._factory.update_env(environ)
        return self._func(environ, start_response)


class GlobalStatic(object):
    """ Actual global service object for static delivery """

    def __init__(self, svc):
        """ Initialization """
        self._svc = svc

    def controller(self, resource, group=None):
        """
        Factory for a simple static file delivery controller

        If `group` is set and not ``None``, the controller assumes
        to be attached to a dynamic map and grabs
        ``request.match.group(group)`` as the (relative) filename to
        deliver. If it's ``None``, the filename resulting from ``request.url``
        is used.

        :Parameters:
         - `resource`: Resource token configured for the base
           directory/directories of the delivered files. The directories
           are tried in order.
         - `group`: Regex group

        :Types:
         - `resource`: ``str``
         - `group`: ``unicode`` or ``int``

        :return: Delivery controller
        :rtype: ``callable``
        """
        return Controller(self._svc, resource, group)


class StaticService(object):
    """
    Static resources delivery
    """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.services.ServiceInterface.__init__`
        """
        default, typefiles = u'application/octet-stream', ()
        if 'static' in config:
            default = config.static('default_type', default)
            typefiles = config.static('mime_types', typefiles)
            x_sendfile = config.static('x_sendfile', None) or None
        else:
            x_sendfile = None
        self._x_sendfile = x_sendfile
        self.mime_type = MimeTypes(default.encode('utf-8'), typefiles)

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.static', GlobalStatic(self)

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return Middleware(self, self._x_sendfile, func)


class MimeTypes(object):
    """
    MIME type query object

    :IVariables:
     - `_types`: Extension->Type mapping (``{u'ext': 'type', ...}``)
     - `_default`: Default type

    :Types:
     - `_types`: ``dict``
     - `_default`: ``str``
    """

    def __init__(self, default, filelist):
        """
        Initialization

        :Parameters:
         - `default`: Default type
         - `filelist`: List of files of mime.type format

        :Types:
         - `default`: ``str``
         - `filelist`: ``iterable``
        """
        types = {}
        for name in filelist:
            types.update(self._parse(_resource(name, isfile=True)))
        self._types = types
        self._default = default

    def _parse(self, resource):
        """
        Parse a single mime.types file

        :Parameters:
         - `resource`: file resource
        
        :Types:
         - `resource`: `wtf.app.services.resource.FileResource`

        :return: Ext->Type mapping (``{u'ext': 'type', ...}``)
        :rtype: ``dict``
        """
        types = {}
        stream = resource.open()
        try:
            for line in stream:
                parts = line.decode('utf-8').split()
                if len(parts) > 1:
                    mtype, exts = parts[0], parts[1:]
                    types.update(dict(
                        (ext.decode('utf-8'), mtype.encode('utf-8'))
                        for ext in exts
                    ))
        finally:
            stream.close()
        return types

    def __call__(self, filename, default=None):
        """
        Retrieve MIME type for a file

        :Parameters:
         - `filename`: filename to inspect
         - `default`: Default type override

        :Types:
         - `filename`: ``unicode``
         - `default`: ``str``

        :return: The mime type
        :rtype: ``str``
        """
        if default is None:
            default = self._default
        parts = _os.path.basename(_os.path.normpath(unicode(
            filename).encode('utf-8'))).decode('utf-8').split(u'.')
        parts.reverse()
        while not parts[-1]:
            parts.pop()
        parts.pop()
        mtype = default
        while parts:
            mtype = self._types.get(parts.pop(), mtype)
        return mtype
