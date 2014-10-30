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
WSGI Implementations
====================

This package holds implementations of specific WSGI bridges.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf.config import ConfigurationError


class ServerInterface(object):
    """
    Interface for WSGI server implementations
    """

    def __init__(self, config, opts, args):
        """
        Initialization

        :Parameters:
         - `config`: The application config
         - `opts`: Command line option container
         - `args`: Fixed commandline arguments

        :Types:
         - `config`: `wtf.config.Config`
         - `opts`: ``optparse.OptionContainer``
         - `args`: ``list``
        """

    def handle(self, accepted, application, flags):
        """
        Handle an accepted socket

        :Parameters:
         - `accepted`: The accepted socket, being a tuple of socket object and
           peername
         - `application`: The WSGI application to call
         - `flags`: Worker flags

        :Types:
         - `accepted`: ``tuple``
         - `application`: ``callable``
         - `flags`: `FlagsInterface`
        """


class FlagsInterface(object):
    """
    Interface for worker flag containers

    :CVariables:
     - `multithread`: Is it a multithreaded server?
     - `multiprocess`: Is it a multiprocessed server?
     - `run_once`: Is the server supposed to run once?

    :Types:
     - `multithread`: ``bool``
     - `multiprocess`: ``bool``
     - `run_once`: ``bool``
    """

    def shutdown(self):
        """
        Retrieve shutdown-pending flag

        :return: The state of the flag
        :rtype: ``bool``
        """


def factory(config, opts, args):
    """
    Create the server instance selected by configuration

    :Parameters:
     - `config`: configuration
     - `opts`: Option container
     - `args`: Fixed arguments

    :Types:
     - `config`: `config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``

    :return: server instance
    :rtype: `ServerInterface`
    """
    self = factory

    try:
        protocol = config.wtf.protocol
    except KeyError:
        raise ConfigurationError("Missing protocol configuration")

    if protocol not in self.impl: # pylint: disable = E1101
        raise ConfigurationError("Unknown protocol %s" % protocol)

    return self.impl[protocol](config, opts, args) # pylint: disable = E1101
factory.impl = {} # pylint: disable = W0612


def register(name, klass):
    """
    Register a server implementation

    :Parameters:
     - `name`: The name (in the config)
     - `klass`: The implementation class

    :Types:
     - `name`: ``str``
     - `klass`: `ServerInterface`
    """
    factory.impl[name] = klass # pylint: disable = E1101
