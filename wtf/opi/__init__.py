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
OS Process Integration
======================

The modules in this package implement the different ways of integration
within other frameworks. Currently there are:

daemon
  The application is running as a standalone daemon, optionally forking itself
  into the background (Not forking is a both a debugging and production
  feature -- imagine integration into djb's daemontools and stuff.


The typical way to load the proper implementation is::

    from wtf import opi
    opi.factory(config, opts, args).work()

This evaluates the [wtf] section of the config, where the following options
are recognized:

protocol = ``scgi|http``
  Required option, because there's no sensible default. ``fastcgi`` also
  handles regular CGI if:

  - detach = no
  - listen = stdin
  - STDIN is a pipe

  XXX: implement it!

mode = ``Integration mode``
  ``daemon`` is default.

basedir = ``path``
  The directory to change into immediatly after startup. Default is: ``/``

umask = ``umask``
  The umask to apply. The default umask is 0. The value is interpreted as
  octal number. You can specify ``inherit`` in order to inherit the umask
  from the caller (e.g. the shell).

In daemon mode the following options are used to determine the behaviour
in detail:

detach = ``yes|no``
  Required option, because there's no sensible default. This option determines
  whether the daemon should fork itself into the background or not. If this
  option is set to ``yes``, command line parameters become interesting.
  The last parameter is evaluated and has to be one of the following:

  start
    Start a new daemon. If there's already one running, this is a failure.

  stop
    Stop the daemon. If there's none running, this is not a failure. If
    there's one running, this option is identical to sending a
    SIGTERM + SIGCONT to the process in question.

  logrotate|logreopen
    Reopen the error log file.

  The presence of another running daemon is determined by the pidfile (which
  is advisory locked for this purpose). Furthermore a forked away daemon
  does the usual detaching magic like closing all descriptors and stuff. This
  especially means, that STDIN, STDOUT and STDERR all point to /dev/null.
  If you specify an ``errorlog`` it will be attached to STDERR.

listen = ``[tcp:]host:port | [unix:]path[(perm)] ...``
  Required option, because there's no sensible default. This option determines
  where the daemon should listen for requests. This is a list of socket
  specifications which can be either TCP/IP or a unix domain sockets (you can
  mix them, if you want.) The optional ``perm`` parameter for unix sockets is
  an octal value and controls the permissions of the socket path. Note that
  socket paths are limited in length by the OS. See ``unix(7)`` for details.

workermodel = ``model``
  Required option, because there's no sensible default. This option determines
  the worker pool implementation.

errorlog = ``path``
  The file which STDERR should be attached to. By default STDERR goes to
  ``/dev/null``.

pidfile = ``path``
  The option is required. It contains the name of the file where the PID of
  the main process is written into. The file is also used to determine
  a concurrently running daemon by locking it (The lock is automatically
  cleared if the daemon dies).

user = ``id|name``
  The user the working process should change to. If the application is
  started as root, it's strongly recommended to define such a user. See also
  ``group``. If the application is not started as root, the option is ignored.

group = ``id|name``
  The group the working process should change to. If the application is
  started as root, it's strongly recommended to define such a group. See also
  ``user``. If the application is not started as root, the option is ignored.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import os as _os

from wtf import Error
from wtf.config import ConfigurationError


class OPIError(Error):
    """ OPI error """
    exit_code = 1

class OPIDone(OPIError):
    """ OPI done """
    exit_code = 0


class OPIInterface(object):
    """
    Interface for OPI implementations

    :Groups:
     - `Running Modes`: `MODE_THREADED`, `MODE_FORKED`, `MODE_SINGLE`,
       `MODE_ONCE`

    :CVariables:
     - `MODE_THREADED`: multithreaded mode
     - `MODE_FORKED`: forked mode
     - `MODE_SINGLE`: single process mode
     - `MODE_ONCE`: run-once mode (like CGI)

    :IVariables:
     - `mode`: The running mode (one of the ``Running Modes``)
     - `config`: The application config

    :Types:
     - `MODE_THREADED`: ``int``
     - `MODE_FORKED`: ``int``
     - `MODE_SINGLE`: ``int``
     - `MODE_ONCE`: ``int``

     - `mode`: ``int``
     - `config`: `wtf.config.Config`
    """
    MODE_THREADED, MODE_FORKED, MODE_SINGLE, MODE_ONCE = xrange(4)

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

    def work(self):
        """
        Invoke the worker mechanism (if any)

        This starts handling the incoming request(s)
        """


def factory(config, opts, args):
    """
    Create the OPI instance selected by configuration

    :Parameters:
     - `config`: configuration
     - `opts`: Option container
     - `args`: Fixed arguments

    :Types:
     - `config`: `config.Config`
     - `opts`: ``optparse.OptionContainer``
     - `args`: ``list``

    :return: OPI instance
    :rtype: `OPIInterface`
    """
    self = factory

    basemode = config.wtf('mode', 'daemon')
    if basemode not in self.basemodes: # pylint: disable = E1101
        raise ConfigurationError("Unknown mode %s" % basemode)

    basedir = _os.path.normpath(
        _os.path.join(config.ROOT, config.wtf('basedir', '/')))
    _os.chdir(basedir)

    if 'umask' in config.wtf:
        umask = unicode(config.wtf.umask)
        if umask.lower() == 'inherit':
            uval = _os.umask(0)
        else:
            try:
                uval = int(umask, 8)
            except (ValueError, TypeError), e:
                raise ConfigurationError("Invalid umask: %s" % str(e))
    else:
        uval = 0
    _os.umask(uval)

    # pylint: disable = E1101
    return self.basemodes[basemode](config, opts, args)
factory.basemodes = {} # pylint: disable = W0612


def register(name, klass):
    """
    Register an OPI implementation

    :Parameters:
     - `name`: The name (in the config)
     - `klass`: The implementation class

    :Types:
     - `name`: ``str``
     - `klass`: `OPIInterface`
    """
    factory.basemodes[name] = klass # pylint: disable = E1101
