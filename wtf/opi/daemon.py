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
Daemon Integration
==================

Here's the daemon handling implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import errno as _errno
import fcntl as _fcntl
import os as _os
import signal as _signal
import sys as _sys
import time as _time
import warnings as _warnings

from wtf import Error, WtfWarning
from wtf import autoreload as _reload
from wtf import opi as _opi
from wtf import osutil as _osutil
from wtf.cmdline import CommandlineError
from wtf.config import ConfigurationError
from wtf.opi import listener as _listener
from wtf.opi import worker as _worker


class SignalError(Error):
    """ Error while signalling another daemon process """

class PidfileError(Error):
    """ Something's wrong with the pidfile """

class PidfileValidError(PidfileError):
    """ Pidfile already exists and is valid """

class PidfileGarbageError(PidfileError):
    """ Pidfile contained garbage """

class PidfileEmptyError(PidfileGarbageError):
    """ Pidfile was empty """

class PidfileWarning(WtfWarning):
    """ Warning category for pidfile issues """


class SigTerm(SystemExit):
    """ SIGTERM received """

class SigHup(SystemExit):
    """ SIGHUP received """


class DaemonOPI(object):
    """
    Implement daemonized application

    :See: `wtf.opi.OPIInterface`

    :IVariables:
     - `_work`: Specialized doer based on the running mode
     - `pidfile`: pidfile object

    :Types:
     - `_work`: ``callable``
     - `pidfile`: `Pidfile`
    """
    __implements__ = [_opi.OPIInterface]
    pidfile = None

    def __init__(self, config, opts, args):
        self.config = config
        self.opts = opts
        self.args = args

        if not opts.keep_descriptors:
            _osutil.close_descriptors()

        if 'pidfile' not in config.wtf:
            raise ConfigurationError("Missing pidfile configuration")
        self.pidfile = Pidfile(
            _os.path.normpath(_os.path.join(config.ROOT, config.wtf.pidfile))
        )

        if 'detach' not in config.wtf:
            raise ConfigurationError("Missing detach configuration")
        self._work = config.wtf.detach and \
            DetachedRunner(self).run or Runner(self).run

        self.mode = _opi.OPIInterface.MODE_THREADED
        self.errorlog = config.wtf('errorlog')
        if self.errorlog is not None:
            self.errorlog = _os.path.normpath(
                _os.path.join(config.ROOT, self.errorlog)
            )

    def work(self):
        """ :see: `wtf.opi.OPIInterface` """
        try:
            return self._work()
        except PidfileValidError, e:
            raise _opi.OPIDone(str(e))
        except PidfileError, e:
            raise ConfigurationError(str(e))


class Runner(object):
    """
    Runner logic, socket setup and that all

    :CVariables:
     - `detached`: Is the runner detached?

    :IVariables:
     - `_daemonopi`: DaemonOPI instance

    :Types:
     - `detached`: ``bool``
     - `_daemonopi`: `DaemonOPI`
    """
    detached = False

    def __init__(self, daemonopi):
        """
        Initialization

        :Parameters:
         - `daemonopi`: `DaemonOPI` instance

        :Types:
         - `daemonopi`: `DaemonOPI`
        """
        self._daemonopi = daemonopi

    def run(self, prerun=None, parent_cleanup=None, child_cleanup=None,
            logrotate=None):
        """
        Finalize the setup and start the worker

        :Parameters:
         - `prerun`: Optional initializer/finalizer executed before actually
           starting up. Called in the worker child (if any).
         - `parent_cleanup`: Optional function which is called in the parent
           after a main worker child fork happens.
         - `child_cleanup`: Optional function which is called in the child
           after a main worker child fork happens.
         - `logrotate`: Optional log rotation function

        :Types:
         - `prerun`: ``callable``
         - `parent_cleanup`: ``callable``
         - `child_cleanup`: ``callable``
         - `logrotate`: ``callable``
        """
        # pylint: disable = R0912

        opi = self._daemonopi
        if opi.opts.listen:
            bind = opi.opts.listen
        else:
            try:
                bind = opi.config.wtf.listen
            except KeyError:
                raise ConfigurationError("Missing listen configuration")
        sock = _listener.ListenerSocket(bind, basedir=opi.config.ROOT)
        try:
            baseworker = _worker.factory(opi.config, opi.opts, opi.args)
            worker = baseworker.setup(
                sock, prerun, parent_cleanup, child_cleanup
            )
            try:
                while True:
                    try:
                        self._setup_signals(baseworker)
                        worker.run()
                    except SigTerm:
                        break # just shut down
                    except SigHup:
                        if logrotate is not None:
                            print >> _sys.stderr, "Reopening log file now."
                            logrotate()
                    except _reload.ReloadRequested:
                        print >> _sys.stderr, "Restarting the worker now."
                    else:
                        raise RuntimeError("Worker finished unexpectedly...")
            finally:
                worker.shutdown()
        finally:
            sock.close()

    def _setup_signals(self, baseworker):
        """
        Setup signal handlers

        :Parameters:
         - `baseworker`: The worker model instance

        :Types:
         - `baseworker`: `worker.WorkerInterface`
        """
        def termhandler(*args):
            """ TERM handler """
            _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)
            raise SigTerm()
        _signal.signal(_signal.SIGTERM, termhandler)

        if not self.detached:
            # job control sends HUP on shell exit -> terminate
            huphandler = termhandler
        elif baseworker.sig_hup:
            def huphandler(*args):
                """ HUP handler """
                _signal.signal(_signal.SIGHUP, _signal.SIG_IGN)
                raise SigHup()
        else:
            huphandler = _signal.SIG_IGN
        _signal.signal(_signal.SIGHUP, huphandler)

        if not self.detached:
            def inthandler(*args):
                """ INT handler """
                _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
                raise _opi.OPIDone()
        else:
            inthandler = _signal.SIG_IGN
        _signal.signal(_signal.SIGINT, inthandler)


class DetachedRunner(Runner):
    """ Derived runner, which detaches itself from the terminal """
    detached = True

    def __init__(self, daemonopi):
        """
        Initialization

        :Parameters:
         - `daemonopi`: `DaemonOPI` instance

        :Types:
         - `daemonopi`: `DaemonOPI`
        """
        if len(daemonopi.args) <= 1:
            raise CommandlineError("Missing argument(s)")
        command = daemonopi.args[-1]
        try:
            self.run = dict(
                start     = self._start,
                stop      = self._stop,
                logrotate = self._logreopen,
                logreopen = self._logreopen,
            )[command]
        except KeyError:
            raise CommandlineError("Unrecognized command: %s" % command)
        super(DetachedRunner, self).__init__(daemonopi)

    def run(self): # pylint: disable = W0221, E0202
        """ :see: Runner.run """
        raise AssertionError("DetachedRunner not properly initialized")

    def _start(self):
        """
        Do the start command

        Actually detach the current process from the terminal and start
        the regular runner.
        """
        rfd, wfd = map(_osutil.safe_fd, _os.pipe())
        pid = _os.fork()

        # Parent
        if pid:
            _os.close(wfd)
            _os.waitpid(pid, 0)
            while True:
                try:
                    success = _os.read(rfd, 1)
                except OSError, e:
                    if e[0] == _errno.EINTR:
                        continue
                    raise
                break
            _os.close(rfd)
            exit_code = not(bool(success))
            _os._exit(exit_code) # pylint: disable = W0212

        # 1st Child
        else:
            _os.close(rfd)
            _os.setsid()
            _signal.signal(_signal.SIGHUP, _signal.SIG_IGN)
            pid = _os.fork()
            if pid:
                _os._exit(0) # pylint: disable = W0212

            # 2nd Child
            else:
                err_fd, logrotate = self._setup_detached()
                prerun, pcleanup, ccleanup = \
                    self._make_finalizers(err_fd, wfd)
                return super(DetachedRunner, self).run(
                    prerun=prerun,
                    parent_cleanup=pcleanup,
                    child_cleanup=ccleanup,
                    logrotate=logrotate,
                )

    def _make_finalizers(self, err_fd, wfd):
        """
        Make finalizers

        :Parameters:
         - `err_fd`: Deferred error fd setup
         - `wfd`: success fd to the parent

        :Types:
         - `err_fd`: `_DeferredStreamSetup`
         - `wfd`: ``int``

        :return: Three callables, prerun, parent_cleanup and child_cleanup
        :rtype: ``tuple``
        """
        def prerun():
            """ Finalize detaching setup """
            err_fd.finish()
            while True:
                try:
                    if _os.write(wfd, "!") > 0:
                        break
                except OSError, e:
                    if e[0] == _errno.EPIPE:
                        print >> _sys.stderr, "Parent died, so do I."
                        _sys.exit(1)
                    elif e[0] == _errno.EINTR:
                        continue
                    raise
            _os.close(wfd)

        def parent_cleanup():
            """ Cleanup parent after fork """
            _os.close(wfd)

        pidfile = self._daemonopi.pidfile
        def child_cleanup():
            """ Cleanup child after fork """
            pidfile.close()

        return prerun, parent_cleanup, child_cleanup

    def _setup_detached(self):
        """
        Setup the detached main process

        :return: The error stream setup object and a logrotator
                 (maybe ``None``). The setup is deferred so more errors go to
                 the caller's shell
        :rtype: ``tuple``

        :Exceptions:
         - `PidfileValidError`: The pidfile is used by another daemon
         - `PidfileError`: Error while handling the pidfile
         - `ConfigurationError`: Happening while setting up the streams
        """
        pidfile = self._daemonopi.pidfile
        if not pidfile.acquire():
            raise PidfileValidError(
                "Pidfile %r already in use and locked. There's "
                "probably another daemon running already." %
                (pidfile.name,)
            )
        try:
            pidfile.read() # just to print a warning if it's rubbish
        except PidfileEmptyError:
            pass
        pidfile.write(_os.getpid())
        self._setup_stream(0, '/dev/null', _os.O_RDONLY)
        self._setup_stream(1, '/dev/null', _os.O_WRONLY)
        if self._daemonopi.errorlog is not None:
            err_fd = self._setup_stream(2, self._daemonopi.errorlog,
                _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, defer=True)
            def logrotate():
                """ Rotate error log """
                self._setup_stream(2, self._daemonopi.errorlog,
                    _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND)
        else:
            logrotate, err_fd = None, self._setup_stream(2, '/dev/null',
                _os.O_WRONLY, defer=True)
        return err_fd, logrotate

    def _stop(self, signals=('TERM',)):
        """
        Do the stop command

        :Parameters:
         - `signals`: List of signals to send (``('name', ...)``)

        :Types:
         - `signals`: ``tuple``

        :Exceptions:
         - `AttributeError`: A signal name does not exist
         - `SignalError`: Error sending the signal
        """
        msg = "No daemon found running"
        try:
            locked = self._daemonopi.pidfile.acquire()
        except PidfileError:
            raise _opi.OPIDone(msg)

        try:
            if locked:
                raise _opi.OPIDone(msg)
            try:
                pid = self._daemonopi.pidfile.read()
            except PidfileGarbageError, e:
                _warnings.warn(str(e), category=PidfileWarning)
                raise _opi.OPIDone(msg)

            for signame in signals:
                self._signal(pid, signame)
            raise _opi.OPIDone("Sent %s to pid %d" % ("/".join(signals), pid))
        finally:
            self._daemonopi.pidfile.release()

    def _logreopen(self):
        """
        Do the logrotate/logreopen command

        This calls `_stop` with a different signal set.
        """
        return self._stop(signals=('HUP', 'CONT'))

    def _signal(self, pid, signame):
        """
        Send a signal named `signame` to process `pid`.

        :Parameters:
         - `pid`: pid
         - `signame`: signal name

        :Types:
         - `pid`: ``int``
         - `signame`: ``str``

        :Exceptions:
         - `AttributeError`: The signal name does not exist
         - `SignalError`: Error sending the signal
        """
        sig = getattr(_signal, "SIG%s" % signame)
        try:
            _os.kill(pid, sig)
        except OSError, e:
            if e.errno != _errno.ESRCH:
                raise SignalError("Error sending signal %s to pid %d: %s" % (
                    signame, pid, str(e)))

    def _setup_stream(self, fileno, filename, flags, defer=False):
        """
        Setup a stream to point to a particular file

        :Parameters:
         - `fileno`: The descriptor number of the target stream
         - `filename`: The name of the file to attach
         - `flags`: Flags to be passed to the open(2) call
         - `defer`: Actually dupe the file descriptor to fileno?

        :Types:
         - `fileno`: ``int``
         - `filename`: ``str``
         - `flags`: ``int``
         - `defer`: ``bool``

        :return: A `_DeferredStreamSetup` object if the setup is deferred,
                 ``None`` otherwise
        :rtype: `_DeferredStreamSetup`

        :Exceptions:
         - `ConfigurationError`: Error while opening `filename`
         - `OSError`: dup2(2) error
        """
        try:
            fd = _os.open(filename, flags, 0666)
        except OSError, e:
            raise ConfigurationError(
                "Could not open %s: %s" % (filename, str(e)))
        if defer:
            return _DeferredStreamSetup(fd, fileno)
        if fd != fileno:
            try:
                _os.dup2(fd, fileno)
            finally:
                _os.close(fd)


class _DeferredStreamSetup(object):
    """
    Finalizer for deferred setup streams

    :IVariables:
     - `_fd`: The descriptor to finalize
     - `_fileno`: The target descriptor number

    :Types:
     - `_fd`: ``int``
     - `_fileno`: ``int``
    """
    def __init__(self, fd, fileno):
        """
        Initialization

        :Parameters:
         - `fd`: The descriptor to finalize
         - `fileno`: The target descriptor number

        :Types:
         - `fd`: ``int``
         - `fileno`: ``int``
        """
        self._fd, self._fileno = fd, fileno

    def finish(self):
        """ Actually finalize the descriptor setup """
        fd, fileno = self._fd, self._fileno
        if fd != fileno:
            try:
                _, self._fd = _os.dup2(fd, fileno), fileno
            finally:
                _os.close(fd)


class Pidfile(object):
    """
    PID file representation

    :CVariables:
     - `_O_FLAGS`: opening flags for the pid file
     - `_L_FLAGS`: locking flags for the pid file

    :IVariables:
     - `name`: The name of the pidfile

    :Types:
     - `name`: ``str``
     - `_O_FLAGS`: ``int``
     - `_L_FLAGS`: ``int``
    """
    _O_FLAGS = _os.O_RDWR | _os.O_CREAT
    _L_FLAGS = _fcntl.LOCK_EX | _fcntl.LOCK_NB

    _fp, _locked, name = None, False, None

    def __init__(self, name):
        """
        Initialization

        :Parameters:
         - `name`: The name of the pid file

        :Types:
         - `name`: ``str``
        """
        self.name = name

    def __del__(self):
        self.release()

    def release(self):
        """ Close the pid file, remove it and release any lock """
        try:
            name, self.name = self.name, None
            if name is not None and self._fp is not None and self._locked:
                _osutil.unlink_silent(name)
        finally:
            fp, self._fp, self._locked = self._fp, None, False
            if fp is not None:
                fp.close()

    def close(self):
        """ Close the pidfile (do not release it) """
        fp, self.name, self._fp, self._locked = self._fp, None, None, False
        if fp is not None:
            fp.close()

    def acquire(self):
        """
        Open the pid file and acquire a lock

        :return: Did we acquire the lock?
        :rtype: ``bool``

        :Exceptions:
         - `PidfileError`: An error happened while opening or locking
        """
        self._fp = self._open()
        return self._lock()

    def read(self):
        """
        Read the pid from the file

        :return: The pid from the file
        :rtype: ``int``

        :Exceptions:
         - `AssertionError`: The pid file was not open
         - `PidfileEmptyError`: The pid file was empty
         - `PidfileGarbageError`: The pid file contained garbage
        """
        fp = self._fp
        if fp is None:
            raise AssertionError("Pidfile not open")

        try:
            fp.seek(0)
            pid = fp.read()
            if not pid:
                raise PidfileEmptyError("Pidfile %r was empty" % (self.name,))
            try:
                return int(pid.rstrip())
            except (ValueError, TypeError), e:
                raise PidfileGarbageError(
                    "Pidfile %r contained garbage (huh?)" % (self.name,)
                )
        except (OSError, IOError), e:
            raise PidfileError(str(e))

    def write(self, pid):
        """
        Write a pid into the file

        :Parameters:
         - `pid`: The PID to write

        :Types:
         - `pid`: ``int``

        :Exceptions:
         - `AssertionError`: The pid file was not open or not locked
         - `PidfileError`: I/O error while writing the file
        """
        fp = self._fp
        if fp is None:
            raise AssertionError("Pidfile not open")
        elif not self._locked:
            raise AssertionError("Pidfile not locked")

        try:
            fp.seek(0)
            fp.truncate()
            fp.write("%d\n" % pid)
            fp.flush()
        except IOError, e:
            raise PidfileError(str(e))

    def _open(self):
        """
        Open the pid file

        :return: The file object
        :rtype: ``file``

        :Exceptions:
         - `PidfileError`: The file could not be opened
        """
        fp = self._fp
        if fp is not None:
            return fp
        try:
            fd = _osutil.safe_fd(_os.open(self.name, self._O_FLAGS, 0666))
            try:
                _osutil.close_on_exec(fd)
                return _os.fdopen(fd, 'w+')
            except: # pylint: disable = W0702
                e = _sys.exc_info()
                try:
                    _os.close(fd)
                finally:
                    try:
                        raise e[0], e[1], e[2]
                    finally:
                        del e
        except (OSError, IOError), e:
            raise PidfileError(str(e))

    def _lock(self):
        """
        Try locking the pid file

        :return: Did we get the lock?
        :rtype: ``bool``

        :Exceptions:
         - `AssertionError`: Pidfile is not open
         - `PidfileError`: Some I/O error occurred while accessing the
           descriptor
        """
        fp = self._fp
        if fp is None:
            raise AssertionError("Pidfile not open")

        locked, tries = False, 2
        while True:
            try:
                _fcntl.lockf(fp.fileno(), self._L_FLAGS)
            except IOError, e:
                if e.errno not in (_errno.EACCES, _errno.EAGAIN):
                    raise PidfileError(str(e))
                tries -= 1
                if tries <= 0:
                    break
                _time.sleep(0.1)
            else:
                locked = True
                break
        self._locked = locked
        return locked
