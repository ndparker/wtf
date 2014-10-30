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
Autoreload of python code
=========================

This module provides logic to implemented the autoreload mechanism. This is
implemented by forking early, remembering the module's mtimes and dealing
with changed mtimes by going back right before the fork point.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import os as _os
import sys as _sys
import time as _time


class ReloadRequested(SystemExit):
    """
    Reload requested exception

    :CVariables:
     - `CODE`: Exit code for the child process

    :Types:
     - `CODE`: ``int``
    """
    CODE = 9

    def __init__(self):
        """ Initialization """
        SystemExit.__init__(self, self.CODE)


class Autoreload(object):
    """ Autoreload logic container """
    _check_mtime, _before = None, None

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
        autoreload = config.wtf('autoreload', False)
        if autoreload:
            self._check_mtime = _time.time()
            self._before = set(_sys.modules.iterkeys())
            self.check = self._check
        else:
            self.check = lambda: ()

    def _check(self):
        """
        Check the need of reloading in case autoreload has been turned on

        This method takes a snapshot of the current sys.modules, mtimes
        are compared with an older snapshot and on differences true is
        returned. False otherwise.

        :return: Names of the changed modules (empty if nothing's changed)
        :rtype: ``iterable``
        """
        check_mtime, changed = _time.time(), []
        for name, mod in _sys.modules.items():
            if mod is None or name in self._before:
                continue
            mtime = self._mtime(mod)
            if mtime is None:
                continue
            if mtime > self._check_mtime:
                changed.append(name)
        self._check_mtime = check_mtime
        return changed

    def _mtime(self, mod):
        """
        Determine the mtime of a module

        :Parameters:
         - `mod`: The module to inspect

        :Types:
         - `mod`: ``module``

        :return: The mtime or ``None`` if it couldn't be determined (``float``
                 or ``int``, depending on the ``os.stat_float_times`` setting)
        :rtype: number
        """
        filename = getattr(mod, '__file__', None)
        if filename is not None:
            try:
                if filename.endswith('.pyo') or filename.endswith('.pyc'):
                    newname = filename[:-1]
                    return _os.stat(newname).st_mtime
                raise OSError()
            except OSError:
                try:
                    return _os.stat(filename).st_mtime
                except OSError:
                    pass
        return None
