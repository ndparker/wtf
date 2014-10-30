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
Worker Models
=============

The modules in this package implement the different ways of worker
pool models. Currently there are:

threaded
  There's one single process managing a threadpool. Accepted sockets
  are dispatched to a single worker thread.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf.config import ConfigurationError


class WorkerInterface(object):
    """
    Interface for worker implementations

    :IVariables:
     - `sig_hup`: Should SIGHUP restart the worker?

    :Types:
     - `sig_hup`: ``bool``
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

    def setup(self, sock, prerun, parent_cleanup, child_cleanup):
        """
        Setup the worker pool

        :Parameters:
         - `sock`: The main listener socket
         - `prerun`: Pre-runner (called right after finishing the setup), called
           once
         - `parent_cleanup`: Parent cleanup, if the implementation forks, called
           once
         - `child_cleanup`: Child cleanup, if the implementation forks, called
           every time

        :return: The worker pool
        :rtype: `WorkerPoolInterface`
        """


class WorkerPoolInterface(object):
    """ Interface for worker pools """

    def run(self):
        """ Run the pool """

    def shutdown(self):
        """ Shutdown the pool """


def factory(config, opts, args):
    """
    Create the worker instance selected by configuration

    :Parameters:
     - `config`: configuration
     - `opts`: Option container
     - `args`: Fixed arguments

    :Types:
     - `config`: `config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``

    :return: worker instance
    :rtype: `WorkerInterface`
    """
    self = factory

    model = opts.workermodel or config.wtf.workermodel
    if model not in self.models: # pylint: disable = E1101
        raise ConfigurationError("Unknown workermodel %r" % (model,))

    return self.models[model](config, opts, args) # pylint: disable = E1101
factory.models = {} # pylint: disable = W0612

def register(name, klass):
    """
    Register a worker implementation

    :Parameters:
     - `name`: The name (in the config)
     - `klass`: The implementation class

    :Types:
     - `name`: ``str``
     - `klass`: `WorkerInterface`
    """
    factory.models[name] = klass # pylint: disable = E1101
