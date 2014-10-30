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
Crash handler service
=====================

This service provides a global ``dump_request`` method, which can be called
from anywhere, plus it puts a middleware onto the stack, which catches
exceptions and dumps them to disk (by calling ``dump_request`` itself).

The crash handler can be configured to display a crash page when dumping (if
the response hasn't been started already). If configured in debug mode, the
middleware shows a page containing the traceback.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import os as _os
import pprint as _pprint
import sys as _sys
import tempfile as _tempfile
import traceback as _traceback
import warnings as _warnings

from wtf import WtfWarning
from wtf import services as _services
from wtf.app.services import _crash_tb


class DumpWarning(WtfWarning):
    """ A non-fatal error occured while writing a dump """


class Iterator(object):
    """
    Result iterator with crash dumper

    :IVariables:
     - `close`: The iterable's close method (only if there's one)
     - `_wrapped`: The wrapped iterable
     - `_first`: If ``True``, `_wrapped` is actually a tuple, consisting of
       the first iterable item and the iterable itself
     - `_crash`: Crash service instance
     - `_environ`: Request environment

    :Types:
     - `close`: ``callable``
     - `_wrapped`: ``iterable``
     - `_first`: ``bool``
     - `_crash`: `CrashService`
     - `_environ`: ``dict``
    """

    def __init__(self, wrapped, crashservice, environ):
        """
        Initialization

        :Parameters:
         - `wrapped`: The iterable to wrap
         - `crashservice`: The crash service instance
         - `environ`: The request environment

        :Types:
         - `wrapped`: ``iterable``
         - `crashservice`: `CrashService`
         - `environ`: ``dict``
        """
        try:
            close = wrapped.close
        except AttributeError:
            pass
        else:
            self.close = close
        self._wrapped = iter(wrapped)
        try:
            # pylint: disable = E1103
            first = self._wrapped.next()
            while not first:
                first = self._wrapped.next()
            self._wrapped = first, self._wrapped
        except StopIteration:
            self._first = False
            self._wrapped = iter(())
        else:
            self._first = True
        self._crash, self._environ = crashservice, environ

    def __iter__(self):
        """
        Return iterator object (iterator protocol)

        :return: The iterator object
        :rtype: `Iterator`
        """
        return self

    def next(self):
        """
        Return next item of the iterable (iterator protocol)

        :return: The next item
        :rtype: any
        """
        if self._first:
            self._first, (item, self._wrapped) = False, self._wrapped
        else:
            try:
                # pylint: disable = E1103
                item = self._wrapped.next()
            except (SystemExit, KeyboardInterrupt, StopIteration):
                raise
            except:
                exc_info = _sys.exc_info()
                try:
                    self._crash.dump_request(
                        exc_info, self._environ, True, _bail=False
                    )
                    raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    exc_info = None
        return item

    def __len__(self):
        """
        Determine the length of the iterable

        :return: The length
        :rtype: ``int``

        :Exceptions:
         - `TypeError`: The iterable is unsized
        """
        return len(self._wrapped) + self._first


class Middleware(object):
    """
    Crash middleware

    :IVariables:
     - `_crash`: Crash service instance
     - `_func`: Wrapped WSGI callable
     - `_debug`: Debugging enabled?
     - `_display`: Tuple of crash page content and status line

    :Types:
     - `_crash`: `CrashService`
     - `_func`: ``callable``
     - `_debug`: ``bool``
     - `_display`: ``tuple``
    """

    def __init__(self, crashservice, debug, display, func):
        """
        Initialization

        :Parameters:
         - `crashservice`: Crash service instance
         - `debug`: Debugging enabled?
         - `display`: Tuple of crash page content and status line
         - `func`: WSGI callable to wrap

        :Types:
         - `crashservice`: `CrashService`
         - `debug`: ``bool``
         - `display`: ``tuple``
         - `func`: ``callable``
        """
        self._crash, self._func = crashservice, func
        self._debug, self._display = debug, display

    def __call__(self, environ, start_response):
        """
        Middleware handler

        :Parameters:
         - `environ`: WSGI environment
         - `start_response`: Start response callable

        :Types:
         - `environ`: ``dict``
         - `start_response`: ``callable``

        :return: WSGI response iterable
        :rtype: ``iterable``
        """
        # pylint: disable = R0912

        started, result = set(), None

        def my_start_response(status, response_headers, exc_info=None):
            """ Thin start_response wrapper, creating a a decorated writer """
            write = start_response(status, response_headers, exc_info)
            def my_write(data):
                """ Writer, which remembers if it was called """
                write(data)
                if data:
                    started.add(1)
            return my_write

        try:
            result = self._func(environ, my_start_response)
            return Iterator(result, self._crash, environ)
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            exc_info = _sys.exc_info()
            try:
                if self._debug:
                    status, page = (
                        "500 Internal Server Error",
                        _crash_tb.debug_info(environ, exc_info)
                    )
                else:
                    if self._display is None:
                        raise exc_info[0], exc_info[1], exc_info[2]
                    page, status, fname, mtime = self._display
                    try:
                        fp = open(fname, 'rb')
                        try:
                            xtime = _os.fstat(fp.fileno()).st_mtime
                            if xtime > mtime:
                                page = fp.read()
                                self._display = page, status, fname, xtime
                        finally:
                            fp.close()
                    except (IOError, OSError):
                        pass
                try:
                    start_response(status, [
                        ("Content-Type", "text/html; charset=utf-8")
                    ], exc_info)
                except (SystemExit, KeyboardInterrupt):
                    raise
                except:
                    started = True
                    raise
                return [page]
            finally:
                try:
                    try:
                        self._crash.dump_request(
                            exc_info, environ, bool(started), _bail=False
                        )
                    except (SystemExit, KeyboardInterrupt):
                        raise
                    except:
                        try:
                            print >> _sys.stderr, \
                                "Crashandler: Failed dumping request " \
                                "info:\n%s" % ''.join(
                                    _traceback.format_exception(
                                        *_sys.exc_info()
                                    )
                                )
                            print >> _sys.stderr, \
                                "Original traceback was:\n%s" % ''.join(
                                    _traceback.format_exception(*exc_info)
                                )
                        except (SystemExit, KeyboardInterrupt):
                            raise
                        except:
                            # can't do more without jeopardizing the
                            # crash page.
                            pass
                finally:
                    exc_info = None
        return []


class CrashService(object):
    """
    Crash service

    This service provides a middleware which catches exceptions,
    dumps a traceback and displays an error page.

    :IVariables:
     - `_debug`: Debug mode?
     - `_display`: Tuple of display template and status
       (``('template', 'status')``)
     - `_dumpdir`: Dump directory
     - `_perms`: Dump permissions

    :Types:
     - `_debug`: ``bool``
     - `_display`: ``tuple``
     - `_dumpdir`: ``str``
     - `_perms`: ``int``
    """
    __implements__ = [_services.ServiceInterface]
    _debug, _display = False, None
    _dumpdir, _dumpdir_unicode, _perms = None, None, None

    def __init__(self, config, opts, args):
        """ :See: `wtf.services.ServiceInterface.__init__` """
        section = config.crash
        self._debug = bool(section('debug', False))
        if 'display' in section:
            fname, status = section.display.template, section.display.status
            fp = open(fname, 'rb')
            try:
                page = fp.read()
                mtime = _os.fstat(fp.fileno()).st_mtime
            finally:
                fp.close()
            self._display = page, status, fname, mtime
        if 'dump' in section:
            self._perms = int(section.dump('perms', '0644'), 8)
            self._dumpdir = _os.path.join(config.ROOT, unicode(
                section.dump.directory
            ).encode(_sys.getfilesystemencoding()))
            try:
                self._dumpdir_unicode = self._dumpdir.decode(
                    _sys.getfilesystemencoding()
                )
            except UnicodeError:
                self._dumpdir_unicode = self._dumpdir.decode('latin-1')

            # check write access
            fp, name = self._make_dumpfile()
            try:
                fp.write("!")
            finally:
                try:
                    fp.close()
                finally:
                    _os.unlink(name)

    def status(self):
        """
        Determine crash dump directory status

        The dump count is ``-1`` if it could not be determined.

        :return: A dict containing status information
                 (``{'status': u'status', 'count': int, 'dir': u'dumpdir'}``)
        :rtype: ``dict``
        """
        if self._dumpdir_unicode:
            try:
                count = len(_os.listdir(self._dumpdir))
            except OSError, e:
                status = u"WARNING -- Can't open dump directory: %s" % \
                    unicode(repr(str(e)))
                count = -1
            else:
                if count == 0:
                    status = u"OK -- 0 dumps"
                else:
                    status = u"WARNING -- %s dumps" % count

            return dict(
                status=status,
                dir=self._dumpdir_unicode,
                count=count,
            )
        return dict(
            status=u"WARNING -- No dump directory configured",
            count=-1,
            dir=u"n/a",
        )

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.crash', self

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return Middleware(self, self._debug, self._display, func)

    def dump_request(self, exc_info, environ, started=False, _bail=True):
        """
        Dump a request

        :Parameters:
         - `exc_info`: Exception to dump (as provides by ``sys.exc_info()``)
         - `environ`: Request environment
         - `started`: Has the response been started already?
         - `_bail`: Emit a warning if no dump directory is configured?

        :Types:
         - `exc_info`: ``tuple``
         - `environ`: ``dict``
         - `started`: ``bool``
         - `_bail`: ``bool``
        """
        if self._dumpdir is None:
            if _bail:
                _warnings.warn(
                    "Cannot write requested dump: dump.directory not "
                    "configured", category=DumpWarning
                )
        else:
            fp, name = self._make_dumpfile()
            fp.write(
                "Response started: %s\nEnvironment:\n%s\n\n%s\n" % (
                started,
                _pprint.pformat(environ),
                exc_info and ''.join(_traceback.format_exception(*exc_info)),
            ))
            fp.close()
            print >> _sys.stderr, \
                "Crashhandler: Dumped request info to %s" % name

    def _make_dumpfile(self):
        """
        Create a file for the request dump

        :return: Open stream and the filename (``(file, 'name')``)
        :rtype: ``tuple``
        """
        prefix = _datetime.datetime.utcnow().strftime("dump.%Y-%m-%dT%H%M%S.")
        fd, dumpname = _tempfile.mkstemp(prefix=prefix, dir=self._dumpdir)
        try:
            try:
                _os.chmod(dumpname, self._perms)
            except OSError, e:
                _warnings.warn("chmod(%s, %04o) failed: %s" % (
                    dumpname, self._perms, str(e)), category=DumpWarning)
            return _os.fdopen(fd, 'wb'), dumpname
        except:
            try:
                _os.close(fd)
            finally:
                _os.unlink(dumpname)
            raise
