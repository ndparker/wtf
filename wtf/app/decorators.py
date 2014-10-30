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
Application decorators
======================

This module implements various application decorators.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import util as _util
from wtf.app import response as _response


class RequestDecorator(_util.BaseDecorator):
    """
    General purpose base request decorator

    Implement the `decorate` method in order to add the action.
    If the response is finised before calling the decorated function,
    raise `response.Done`.
    """

    def __call__(self, *args, **kwargs):
        """ Request handler -> overwrite `decorate` instead """
        if len(args) > 2:
            request, response = args[1:3]
        else:
            request, response = args[:2]
        return self.decorate(request, response, args, kwargs)

    def decorate(self, request, response, args, kwargs):
        """
        Decorating action has to be implemented here.

        :Parameters:
         - `request`: Request object
         - `response`: Response object
         - `args`: Full argument tuple for the decorated function
         - `kwargs`: Full keyword dict for the decorated function

        :Types:
         - `request`: `wtf.app.request.Request`
         - `response`: `wtf.app.response.Response`
         - `args`: ``tuple``
         - `kwargs`: ``dict``

        :return: The return value of the decorated function (maybe modified
                 or replaced by the decoator)
        :rtype: any
        """
        raise NotImplementedError()


class Method(object):
    """
    Decorator which ensures certain HTTP methods

    :IVariables:
     - `methods`: The method set to ensure (``set(['method', ...])``)
     - `options`: Should the decorator handle OPTIONS requests?
     - `h2g`: automatically transform HEAD to GET methods?

    :Types:
     - `methods`: ``set``
     - `options`: ``bool``
     - `h2g`: ``bool``
    """

    def __init__(self, *methods, **kwargs):
        """
        Initialization

        :Parameters:
         - `methods`: method list to ensure (``('method', ...)``)
         - `kwargs`: Behaviour options. The following ones are recognized:
           ``bool(handle_options)``: Should the decorator handle OPTIONS
           requests (defaults to ``True``); ``bool(head_to_get)``:
           automatically transform HEAD to GET methods (defaults to ``True``)?

        :Types:
         - `methods`: ``tuple``
         - `kwargs`: ``dict``

        :Exceptions:
         - `TypeError`: Unrecognized keyword arguments presented
        """
        handle_options = bool(kwargs.pop('handle_options', True))
        head_to_get = bool(kwargs.pop('head_to_get', True))
        if kwargs:
            raise TypeError("Unrecognized keyword arguments")

        methods = set(methods)
        if not methods:
            methods += set(['GET', 'HEAD'])
        elif 'GET' in methods:
            methods.add('HEAD')
        if handle_options:
            methods.add('OPTIONS')
        self.methods = methods
        self.options = handle_options
        self.h2g = head_to_get

    def __call__(self, func):
        """
        Decorate the callable

        :Parameters:
         - `func`: The callable to decorate

        :Types:
         - `func`: ``callable``

        :return: The decorated callable
        :rtype: ``callable``
        """
        class MethodDecorator(RequestDecorator):
            """
            Actual Method checking decorator

            :IVariables:
             - `_config`: Config tuple, containing the method set, option
               handling and head handling flags
               (``(set(['method', ...]), bool, bool)``)

            :Types:
             - `_config`: ``tuple``
            """

            def __init__(self, method, func):
                """
                Initialization

                :Parameters:
                 - `method`: `Method` instance
                 - `func`: decorated callable

                :Types:
                 - `method`: `Method`
                 - `func`: ``callable``
                """
                super(MethodDecorator, self).__init__(func)
                self._config = method.methods, method.options, method.h2g

            def decorate(self, request, response, args, kwargs):
                """ Handle method filtering and OPTION requests. """
                method, (methods, options, h2g) = request.method, self._config

                opt = options and method == 'OPTIONS'
                if opt or method not in methods:
                    if opt:
                        response.headers.set('Allow', ', '.join(methods))
                        raise _response.Done(request)
                    response.raise_error(405, allowed=methods)
                if h2g and method == 'HEAD':
                    request.env['REQUEST_METHOD'] = 'GET'

                return self._func(*args, **kwargs)
        return MethodDecorator(self, func)
