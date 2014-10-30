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
Simple URL resolver
===================

This package contains a simple URL resolver.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import re as _re

from wtf import util as _util
from wtf.app import response as _response


class ResolverInterface(object):
    """
    URL resolver interface

    The resoling methods return callables, which take two parameters: request
    and response, which in turn are instances of
    `wtf.app.request.Request` and `wtf.app.response.Response`.
    """

    def error(self, status, default=None):
        """
        Resolve an HTTP status code to a handler callable

        :Parameters:
         - `status`: The HTTP status code
         - `default`: The default, if no callable if assigned

        :Types:
         - `status`: ``int``
         - `default`: any

        :return: The resolved callable or `default`
        :rtype: any
        """

    def resolve(self, request):
        """
        Resolve the request url to a python callable

        :Parameters:
         - `request`: The request object

        :Types:
         - `request`: `wtf.app.request.Request`

        :return: The request/response handle
        :rtype: ``callable``

        :Exceptions:
         - `response.http.MovedPermanently`: a missing trailing slash was
           detected
         - `response.http.NotFound`: The url could not be resolved
        """


class MapResolver(object):
    """
    Map based URL resolver class

    The class takes a python package, which will be inspected and searched
    in public modules (not starting with ``_``) for the following variables:

    - ``__staticmap__`` - dict (``{'URL': callable, ...}``)
    - ``__dynamicmap__`` - list of tuples (``[('regex', callable), ...]``)
    - ``__errormap__`` - dict (``{int(HTTP-Code): callable, ...}``)

    All of these variables are optional. Conflict resolution rules are as
    follows:

    - The modules/packages in a directory are ordered alphabetically
    - recursing packages are collected immediately
    - The latest one wins (z over a)

    The actual resolver (`resolve`) works as follows:

    - First the URL path is looked up in the static map. If found, the
      callable is returned and we're done
    - Otherwise the path is fed to every regex in the dynamic map. If a match
      is found, the match object is attached to the request and the callable is
      returned
    - A 404 error is raised

    :IVariables:
     - `_staticmap`: final static URL map
     - `_dynamicmap`: final dynamic map
     - `_errormap`: final error map

    :Types:
     - `_staticmap`: ``dict``
     - `_dynamicmap`: ``list``
     - `_errormap`: ``dict``
    """
    __implements__ = [ResolverInterface]

    def __init__(self, config, opts, args):
        """
        Initialization

        :Parameters:
         - `config`: Configuration
         - `opts`: Command line arguments
         - `args`: Positioned command line arguments

        :Types:
         - `config`: `wtf.config.Config`
         - `opts`: ``optparse.OptionContainer``
         - `args`: ``list``
        """
        self._staticmap = {}
        self._errormap = {}
        self._dynamicmap = []
        for mod in _util.walk_package(config.app.package, 'error'):
            modname = mod.__name__
            if '.' in modname:
                modname = modname[modname.rfind('.') + 1:]
            if modname.startswith('_'):
                continue
            static, error, dynamic = [
                getattr(mod, '__%smap__' % name, default) for name, default in
                zip(('static', 'error', 'dynamic'), ({}, {}, []))
            ]
            self._staticmap.update(static)
            self._errormap.update(error)
            self._dynamicmap = [(_re.compile(
                isinstance(regex, basestring) and unicode(regex) or regex
            ).match, func) for regex, func in dynamic] + self._dynamicmap
        self.error = self._errormap.get

    def error(self, status, default=None):
        """ Resolve error code """
        # pylint: disable = E0202, W0613

        raise AssertionError(
            "This method should have been replaced by __init__"
        )

    def resolve(self, request):
        """ Resolve this request """
        url = request.url.path
        staticmap = self._staticmap
        try:
            return staticmap[url]
        except KeyError:
            if not url.endswith('/'):
                candidate = "%s/" % url
                if candidate in staticmap:
                    location = request.abs_uri(request.url)
                    location.path = candidate
                    raise _response.http.MovedPermanently(
                        request, location=str(location)
                    )

            for matcher, func in self._dynamicmap:
                match = matcher(url)
                if match:
                    request.match = match
                    return func
        raise _response.http.NotFound(request)
