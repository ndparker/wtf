# -*- coding: ascii -*-
u"""
:Copyright:

 Copyright 2012 - 2014
 Andr\xe9 Malo or his licensors, as applicable

:License:

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.

==================
 Application Init
==================

Meta config setup and managed applications helper.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import os as _os
import sys as _sys


def config(configfile, opts=None, dump=False):
    """
    Initialize the configuration and apply basic parameters

    The basic parameters are:

    - The python path
    - sys.checkinterval
    - max descriptors

    :Parameters:
      `configfile` : ``str``
        Config file name (relative to the current working directory)

      `opt`
        Commandline options

      `dump` : ``bool``
        Dump config and exit? If true, the effective config is dumped and the
        process exits with return code 0. Default: false

    :Return: Effective config
    :Rtype: ``
    """
    # pylint: disable = R0912

    from wtf import config as _config

    if configfile is None:
        conf = _config.Config(
            _os.path.normpath(_os.path.abspath(_os.getcwd()))
        )
    else:
        conf = _config.load(configfile)

    if dump:
        _config.dump(conf)
        _sys.exit(0)

    if 'wtf' in conf and 'pythonpath' in conf.wtf:
        _sys.path = list(conf.wtf.pythonpath) + _sys.path

    if opts is not None and opts.checkinterval:
        checkinterval = opts.checkinterval
    elif 'wtf' in conf:
        checkinterval = conf.wtf('checkinterval', 0)
    else:
        checkinterval = 0
    if checkinterval:
        _sys.setcheckinterval(checkinterval)

    if opts is not None and opts.max_descriptors:
        from wtf import cmdline as _cmdline
        max_descriptors = opts.max_descriptors
        exc = _cmdline.CommandlineError
    elif 'wtf' in conf:
        max_descriptors = max(-1, int(conf.wtf('max_descriptors', 0)))
        exc = _config.ConfigurationError
    else:
        max_descriptors = 0
    if max_descriptors:
        try:
            import resource as _resource
        except ImportError:
            raise exc(
                "Cannot set max descriptors: resource module not available"
            )
        else:
            try:
                name = _resource.RLIMIT_NOFILE
            except AttributeError:
                try:
                    name = _resource.RLIMIT_OFILE
                except AttributeError:
                    raise exc(
                        "Cannot set max descriptors: no rlimit constant found"
                    )
            _resource.setrlimit(name, (max_descriptors, max_descriptors))

    return conf


def managed_app(configfile):
    """
    Create a managed application

    :Parameters:
      `configfile` : ``str``
        Config file name

    :Return: Application factory
    :Rtype: callable
    """
    from wtf import app as _app

    return _app.factory(config(configfile), None, None)
