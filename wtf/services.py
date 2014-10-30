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
Service Loading and Initialization
==================================

This module provides for service loading and initialization.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import Error, WtfWarning
from wtf import util as _util


class ServiceError(Error):
    """ Service intialization failure """

class ServiceInterfaceWarning(WtfWarning):
    """ Service interface warning """


class ServiceInterface(object):
    """
    Interface for global and local services, initialized at startup time
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

    def shutdown(self):
        """
        Shutdown the service

        This method is called when the services are no longer needed.
        It can be used to release external resources etc in a clean way.
        """

    def global_service(self):
        """
        Return the global service object

        If there's no global service provided, the method is expected to
        return ``None``

        :return: A tuple containing the global object the service provides
                 and the name which the object will be stored under in the 
                 service module (``('name', any)``)
        :rtype: ``tuple``
        """

    def middleware(self, func):
        """
        Middleware factory

        :Parameters:
         - `func`: The function to wrap (WSGI compatible callable)

        :Types:
         - `func`: ``callable``

        :return: A WSGI callable. If the service does not
                 provide a WSGI middleware, the `func` argument should just
                 be returned, the initialized middleware (wrapping `func`)
                 otherwise.
        :rtype: ``callable``
        """


class ServiceManager(object):
    """
    Service manager

    :IVariables:
     - `_finalized`: Manager was finalized
     - `_down`: Manager was shut down
     - `_services`: List of services

    :Types:
     - `_finalized`: ``bool``
     - `_down`: ``bool``
     - `_services`: ``list``
    """
    _finalized, _down, _services = False, False, ()

    def __init__(self):
        """ Initialization """
        self._services = []

    def __del__(self):
        """ Destruction """
        self.shutdown()

    def finalize(self):
        """ Lock the manager. No more services can be added """
        self._services.reverse()
        self._finalized = True

    def add(self, service):
        """ Add a new service """
        assert not self._finalized, "ServiceManager was already finalized"
        self._services.append(service)

    def apply(self, app):
        """
        Apply the middlewares to the application

        :Parameters:
         - `app`: The WSGI application callable to wrap

        :Types:
         - `app`: ``callable``

        :return: Wrapped application (if there are middlewares to apply, the
                 original callable otherwise)
        :rtype: ``callable``
        """
        assert self._finalized, "ServiceManager was not finalized yet"
        assert not self._down, "ServiceManager was already shutdown"
        for service in self._services:
            app = service.middleware(app)
        return app

    def shutdown(self):
        """ Shutdown the services """
        self._down = True
        services, self._services = self._services, []
        for service in services:
            try:
                func = service.shutdown
            except AttributeError:
                ServiceInterfaceWarning.emit(
                    "Missing 'shutdown' method for service %r" % (service,)
                )
            else:
                func()


def init(config, opts, args, services, module='__svc__'):
    """
    Initialize services

    The function can only be called once (because the module will be only
    initialized once)

    :Parameters:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments
     - `services`: List of services to initialize. The list items can either
       be classes (which are instanciated) or strings containing dotted class
       names (which will be loaded and instanciated). Service classes must
       implement the `ServiceInterface`.
     - `module`: Dotted module name, where global services are put into

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``
     - `services`: ``iterable``
     - `module`: ``str``

    :return: Service manager
    :rtype: `ServiceManager`
    """
    _, fresh = _util.make_dotted(module)
    assert fresh, "Services already initialized"

    module, manager = module.split('.'), ServiceManager()
    for service in services:
        if isinstance(service, basestring):
            service = _util.load_dotted(str(service))
        service = service(config, opts, args)
        manager.add(service)
        svc = service.global_service()
        if svc is not None:
            name, svc = svc
            name = module + name.split('.')
            if len(name) > 1:
                (prename, _), name = _util.make_dotted(
                    '.'.join(name[:-1])), name[-1]
            if getattr(prename, name, None) is not None:
                raise ServiceError("%s.%s already exists" % (prename, name))
            setattr(prename, name, svc)

    manager.finalize()
    return manager
