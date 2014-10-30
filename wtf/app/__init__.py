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
Application wrapper package
===========================

This package contains application wrappers and related stuff, plus a
sample hello-world-application.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"


class Application(object):
    """
    Application wrapper

    :IVariables:
     - `shutdown`: Shutdown callable
     - `call`: Application callable

    :Types:
     - `shutdown`: ``callable``
     - `call`: ``callable``
    """
    shutdown = None

    @classmethod
    def factory(cls, config, opts, args):
        """
        Call the main application factory based on the configuration

        :Parameters:
         - `config`: Configuration
         - `opts`: Command line options
         - `args`: Positioned command line arguments

        :Types:
         - `config`: `wtf.config.Config`
         - `opts`: ``optparse.OptionContainer``
         - `args`: ``list``

        :return: New Application instance
        :rtype: `Application`
        """
        from wtf import services, util

        # BEWARE: Order is important here - first the services, then the app.
        # This is because the app modules may depend on initialized services
        # on top level.
        manager = services.init(
            config, opts, args, config.wtf('services', ())
        )
        app = manager.apply(
            util.load_dotted(config.wtf.application)(config, opts, args)
        )
        return cls(manager, app)

    def __init__(self, manager, app):
        """
        Initialization

        :Parameters:
         - `manager`: Service manager
         - `app`: WSGI callable

        :Types:
         - `manager`: `ServiceManager`
         - `app`: ``callable``
        """
        self.shutdown = manager.shutdown
        self.call = app

    def __del__(self):
        """ Destruction """
        func, self.shutdown = self.shutdown, None
        if func is not None:
            func()

factory = Application.factory


def hello_world(config, opts, args):
    """
    Sample application bootstrapper

    :Parameters:
     - `config`: Configuration
     - `opts`: Command line options
     - `args`: Positioned command line arguments

    :Types:
     - `config`: `wtf.config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``

    :return: WSGI application function
    :rtype: ``callable``
    """
    def myapp(environ, start_response):
        """
        WSGI sample application

        :Parameters:
         - `environ`: Request WSGI environment
         - `start_response`: response starter function

        :Types:
         - `environ`: ``dict``
         - `start_response`: ``callable``

        :return: Response body iterator
        :rtype: ``iterable``
        """
        # pylint: disable = W0613

        start_response("200 OK", [("Content-Type", "text/plain")])
        return ["Hello World\n"]

    return myapp
