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
Log service
===========

The service provides a global log configuration.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import logging as _logging
import os as _os
import sys as _sys
import types as _types

from wtf import services as _services


BaseLogger = _logging.getLoggerClass()
class WtfLogger(BaseLogger):
    """
    Improved logger class, which can wind up stack more than one frame

    Unfortunately the logging code is not flexible enough to simply extend
    the API, so we're actually copying the code with slight differences.
    Always the same game :-(
    """

    def _log(self, level, msg, args, exc_info=None, stackwind=1):
        """
        Low-level logging routine which creates a LogRecord and then calls
        all the handlers of this logger to handle the record.
        """
        # pylint: disable = W0212, C0103

        if _logging._srcfile:
            fn, lno, _ = self.findCaller(stackwind)
        else:
            fn, lno, _ = "(unknown file)", 0, "(unknown function)"
        if exc_info:
            if type(exc_info) != _types.TupleType:
                exc_info = _sys.exc_info()
        record = self.makeRecord(
            self.name, level, fn, lno, msg, args, exc_info
        )
        self.handle(record)

    def findCaller(self, stackwind=1):
        """
        Find the stack frame of the caller so that we can note the source
        file name, line number and function name.
        """
        # pylint: disable = W0221, C0103

        # + 2 = findCaller, _log
        f, idx = _logging.currentframe(), max(1, stackwind) + 2
        while idx:
            if f.f_back is None:
                break
            f = f.f_back
            idx -= 1
        rv = "(unknown file)", 0, "(unknown function)"
        while 1:
            co = getattr(f, "f_code", None)
            if co is None:
                break
            co = f.f_code
            filename = _os.path.normcase(co.co_filename)
            if filename == _logging._srcfile: # pylint: disable = W0212
                f = f.f_back
                continue
            rv = (filename, f.f_lineno, co.co_name)
            break
        return rv

    def exception(self, msg, *args, **kwargs):
        """
        Convenience method for logging an ERROR with exception information.
        """
        kwargs['exc_info'] = 1
        kwargs['stackwind'] = kwargs.get('stackwind', 1) + 1
        self.error(msg, *args, **kwargs)

# Another glitch: The logger manager in the logging module doesn't seem
# to be able to simply take a logger instance from outside. Arrrrgh.
#
# The result is: the following two lines cannot be considered thread safe.
# However, since it's run during the startup phase, it shouldn't impose a
# problem.
_logging.setLoggerClass(WtfLogger)
_logging.getLogger('wtf')


class LogService(object):
    """
    Log service

    The services provides a global interface to the logging facilities.

    :See: `wtf.services.ServiceInterface`

    :Groups:
     - `Log levels`: `CRITICAL`, `FATAL`, `ERROR`, `WARNING`, `WARN`, `INFO`
       `DEBUG`
     - `Loggers`: `log`, `critical`, `fatal`, `error`, `exception`, `warning`,
       `warn`, `info`, `debug`

    :CVariables:
     - `_DEFAULT_REC_FORMAT`: Default record format
     - `_DEFAULT_TIME_FORMAT`: Default time format
     - `_DEFAULT_LEVEL`: Default log level
     - `CRITICAL`: CRITICAL log level
     - `FATAL`: FATAL log level (== CRITICAL)
     - `ERROR`: ERROR log level
     - `WARNING`: WARNING log level
     - `WARN`: WARN log level (== WARNING)
     - `INFO`: INFO log level
     - `DEBUG`: DEBUG log level

    :IVariables:
     - `log`: logger for all levels
     - `critical`: critical logger
     - `fatal`: fatal logger (== critical)
     - `error`: error logger
     - `exception`: error logger with exception
     - `warning`: warning logger
     - `warn`: warn logger (== warning)
     - `info`: info logger
     - `debug`: debug logger

    :Types:
     - `_DEFAULT_REC_FORMAT`: ``unicode``
     - `_DEFAULT_TIME_FORMAT`: ``None``
     - `_DEFAULT_LEVEL`: ``unicode``
     - `CRITICAL`: ``int``
     - `FATAL`: ``int``
     - `ERROR`: ``int``
     - `WARNING`: ``int``
     - `WARN`: ``int``
     - `INFO`: ``int``
     - `DEBUG`: ``int``
     - `log`: ``callable``
     - `critical`: ``callable``
     - `fatal`: ``callable``
     - `error`: ``callable``
     - `exception`: ``callable``
     - `warning`: ``callable``
     - `warn`: ``callable``
     - `info`: ``callable``
     - `debug`: ``callable``
    """
    __implements__ = [_services.ServiceInterface]
    _DEFAULT_REC_FORMAT = \
        u'%(asctime)s %(levelname)s [%(filename)s:%(lineno)s] %(message)s'
    _DEFAULT_TIME_FORMAT = None
    _DEFAULT_LEVEL = u'WARN'

    CRITICAL = _logging.CRITICAL
    FATAL = _logging.FATAL
    ERROR = _logging.ERROR
    WARNING = _logging.WARNING
    WARN = _logging.WARN
    INFO = _logging.INFO
    DEBUG = _logging.DEBUG

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.services.ServiceInterface.__init__`
        """
        conf = 'log' in config and config.log or {}.get
        rec_format = conf('record', self._DEFAULT_REC_FORMAT).encode('utf-8')
        time_format = conf('time', self._DEFAULT_TIME_FORMAT)
        loglevel = conf('level', self._DEFAULT_LEVEL).upper().encode('utf-8')
        if time_format is not None:
            time_format = time_format.encode('utf-8')

        handler = _logging.StreamHandler(_sys.stderr)
        handler.setFormatter(_logging.Formatter(rec_format, time_format))
        level = _logging.getLevelName(loglevel)

        logger = _logging.getLogger('wtf')
        logger.addHandler(handler)
        logger.setLevel(level)

        # populate symbols to service
        methlist = ('debug', 'info', 'warning', 'warn', 'error',
            'exception', 'critical', 'fatal', 'log')
        for method in methlist:
            setattr(self, method, getattr(logger, method))

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.log', self

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return func

    def __call__(self, msg, level=ERROR, *args, **kwargs):
        """
        Shortcut for log.log() with easier signature

        :Parameters:
         - `msg`: Log message
         - `level`: Log level
         - `args`: Additional arguments
         - `kwargs`: Additional keyword arguments

        :Types:
         - `msg`: ``str``
         - `level`: ``int``
         - `args`: ``tuple``
         - `kwargs`: ``dict``

        :return: Whatever ``self.log()`` returns
        :rtype: any
        """
        kwargs['stackwind'] = kwargs.get('stackwind', 1) + 1
        return self.log(level, msg, *args, **kwargs) # pylint: disable = E1101
