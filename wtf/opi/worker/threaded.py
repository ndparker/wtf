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
Threaded Worker Model
=====================

Here's the threadpool handling implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import collections as _collections
import errno as _errno
import os as _os
import signal as _signal
import socket as _socket
import sys as _sys
import thread as _thread
import threading as _threading
import time as _time
import traceback as _traceback

from wtf import autoreload as _reload
from wtf import impl as _impl
from wtf import osutil as _osutil
from wtf import app as _app
from wtf.opi import worker as _worker


class SigTerm(SystemExit):
    """ SIGTERM received """


class ThreadedWorker(object):
    """
    Implement threadpool worker model

    :See: `wtf.opi.worker.WorkerInterface`
    """
    __implements__ = [_worker.WorkerInterface]
    sig_hup = True

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.opi.worker.WorkerInterface`
        """
        self.config, self.opts, self.args = config, opts, args

    def setup(self, sock, prerun, parent_cleanup, child_cleanup):
        """
        Initialization

        :See: `wtf.opi.worker.WorkerInterface`
        """
        return WorkerChild(self, sock, prerun, parent_cleanup, child_cleanup)


class WorkerChild(object):
    """ Worker pool implementation """
    __implements__ = [_worker.WorkerPoolInterface]
    _pid, _usergroup = None, None

    def __init__(self, model, sock, prerun, parent_cleanup, child_cleanup):
        """
        Initialization

        :Parameters:
         - `model`: The worker model implementation
         - `sock`: Main socket
         - `prerun`: Prerunner (maybe ``None``)
         - `parent_cleanup`: Parent cleanup function (maybe ``None``)
         - `child_cleanup`: Child cleanup function (maybe ``None``)

        :Types:
         - `model`: `ThreadedWorker`
         - `sock`: ``socket.socket``
         - `prerun`: ``callable``
         - `parent_cleanup`: ``callable``
         - `child_cleanup`: ``callable``
        """
        self.model = model
        self.sock = sock
        self.prerun = prerun
        self.parent_cleanup = parent_cleanup
        self.child_cleanup = child_cleanup
        if 'user' in model.config.wtf:
            self._usergroup = model.config.wtf.user, model.config.wtf.group

    def run(self):
        """
        Pool runner

        :See: `wtf.opi.worker.WorkerPoolInterface`
        """
        # pylint: disable = R0912

        oldpid, self._pid = self._pid, None
        prerun, self.prerun = self.prerun, None
        parent_cleanup, self.parent_cleanup = self.parent_cleanup, None
        self._pid = _os.fork()
        if self._pid == 0: # child
            try:
                try:
                    if self._usergroup:
                        _osutil.change_identity(*self._usergroup)
                    _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
                    _signal.signal(_signal.SIGHUP, _signal.SIG_IGN)
                    if self.child_cleanup is not None:
                        self.child_cleanup()

                    model = self.model
                    config, opts, args = model.config, model.opts, model.args
                    reload_checker = _reload.Autoreload(config, opts, args)
                    impl = _impl.factory(config, opts, args)
                    app = _app.factory(config, opts, args)

                    try:
                        pool = ThreadPool(
                            self, reload_checker, impl, app.call
                        )
                        if prerun is not None:
                            prerun()
                        pool.run()
                    finally:
                        app.shutdown()
                except SystemExit, e:
                    _os._exit(e.code or 0) # pylint: disable = W0212
                except:
                    _traceback.print_exc()
                    _os._exit(1) # pylint: disable = W0212
            finally:
                _os._exit(0) # pylint: disable = W0212
        else: # parent
            if parent_cleanup is not None:
                parent_cleanup()
            if oldpid is not None:
                _os.kill(oldpid, _signal.SIGTERM)
                _os.waitpid(oldpid, 0)
            self._pid, (_, code) = None, _os.waitpid(self._pid, 0)
            if _os.WIFEXITED(code):
                code = _os.WEXITSTATUS(code)
                if code == _reload.ReloadRequested.CODE:
                    raise _reload.ReloadRequested()

    def shutdown(self):
        """
        Pool shutdown

        :See: `wtf.opi.worker.WorkerPoolInterface`
        """
        oldpid, self._pid = self._pid, None
        if oldpid is not None:
            try:
                _os.kill(oldpid, _signal.SIGTERM)
            except OSError, e:
                if e[0] != _errno.ESRCH:
                    raise
            else:
                _os.waitpid(oldpid, 0)


class ThreadPool(object):
    """
    Dynamic threadpool implementation

    :IVariables:
     - `sock`: Main socket
     - `impl`: WSGI implementation
     - `app`: WSGI application
     - `maxthreads`: Hard limit of number of threads
     - `maxspare`: Maximum number of idle threads
       (remaining ones are killed off)
     - `minspare`: Minimum number of idel threads
       (new threads are started if the threshold is reached)
     - `maxqueue`: Maximum of jobs in the queue (if no thread is available).
       The queue blocks if maxqueue is reached.

    :Types:
     - `sock`: ``socket.socket``
     - `impl`: `wtf.impl.ServerInterface`
     - `app`: ``callable``
     - `maxthreads`: ``int``
     - `maxspare`: ``int``
     - `minspare`: ``int``
     - `maxqueue`: ``int``
    """

    def __init__(self, workerchild, reload_checker, impl, app):
        """
        Initialization

        :Parameters:
         - `workerchild`: Worker pool implementation
         - `reload_checker`: Reload checker
         - `impl`: WSGI implementation
         - `app`: WSGI application

        :Types:
         - `workerchild`: `WorkerChild`
         - `reload_checker`: `wtf.autoreload.Autoreload`
         - `impl`: `wtf.impl.ServerInterface`
         - `app`: ``callable``
        """
        config = workerchild.model.config
        self.sock = workerchild.sock
        self.reload_checker, self.impl, self.app = reload_checker, impl, app
        self.maxthreads = max(1, config.wtf('maxthreads', 5))
        self.maxspare = min(
            self.maxthreads, max(1, config.wtf('maxspare', 4))
        )
        self.minspare = min(
            self.maxspare, max(1, config.wtf('minspare', 1))
        )
        self.maxqueue = max(1, config.wtf('maxqueue', 1))

    def run(self):
        """ Run the pool infinitely """
        def termhandler(*args):
            """ Act on SIGTERM """
            _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)
            raise SigTerm()

        queue, accept = JobWorkerQueue(self), self.sock.accept
        need_reload = self.reload_checker.check
        try:
            try:
                _signal.signal(_signal.SIGTERM, termhandler)
                queue.startup()
                while True:
                    task = accept()
                    changed = need_reload()
                    if changed:
                        print >> _sys.stderr, (
                            "Application reload requested by mtime change "
                            "of module(s):\n  * %s" % "\n  * ".join(changed)
                        )
                        queue.shutdown()
                        self._force_reload(task)
                        raise _reload.ReloadRequested()
                    queue.put_task(task)
            except SigTerm:
                pass
        finally:
            queue.shutdown()

    def _force_reload(self, accepted):
        """
        Force the application reload and handle the one accepted socket

        This method forks the process and proxies the socket to the new one.

        :Parameters:
         - `accepted`: Accepted socket

        :Types:
         - `accepted`: ``tuple``

        :Exceptions:
         - `ReloadRequested`: raised in parent to stop further processing
        """
        # pylint: disable = R0912, R0914, R0915

        osock, _ = accepted
        rfd, wfd = _os.pipe() # need to synchronize

        if _os.fork() != 0: # parent
            osock.close()
            return

        # child
        try:
            try:
                _os.close(wfd)
                _os.read(rfd, 1) # wait for EOF (parent died)
                _os.close(rfd)

                _osutil.close_descriptors(osock.fileno())
                sockname = osock.getsockname()
                if isinstance(sockname, str):
                    family = _socket.AF_UNIX
                elif len(sockname) == 2:
                    family = _socket.AF_INET
                else:
                    family = _socket.AF_INET6

                # dup here, to keep the descriptor IDs low.
                sock = _socket.fromfd(
                    osock.fileno(), family, _socket.SOCK_STREAM
                )
                osock.close()
                psock = _socket.socket(family, _socket.SOCK_STREAM)
                psock.settimeout(10)
                psock.connect(sockname)
                psock.settimeout(0)
                sock.settimeout(0)
                _osutil.disable_nagle(psock)

                import select as _select
                rset = [sock.fileno(), psock.fileno()]
                wset = set()
                peers = {
                    sock.fileno(): psock.fileno(),
                    psock.fileno(): sock.fileno(),
                }
                socks = {sock.fileno(): sock, psock.fileno(): psock}
                buf = {sock.fileno(): [], psock.fileno(): []}
                wwait = {}
                while rset or wset:
                    for fd, flag in wwait.iteritems():
                        if flag:
                            wset.add(fd)
                        wwait[fd] = (wwait[fd] + 1) % 2
                    rfds, wfds, _ = _select.select(rset, wset, [], 1)
                    for fd in rfds:
                        sock = socks[fd]
                        try:
                            data = sock.recv(8192)
                            if data:
                                buf[fd].append(data)
                                wset.add(peers[fd])
                            else:
                                rset.remove(fd)
                                wwait[fd] = 1
                                sock.shutdown(_socket.SHUT_RD)
                        except _socket.error, e:
                            if e[0] != _errno.EAGAIN:
                                raise

                    for fd in wfds:
                        sock = socks[fd]
                        try:
                            data = ''.join(buf[peers[fd]])
                            if data:
                                numsent = sock.send(data)
                                data = data[numsent:]
                            else:
                                rset.remove(peers[fd])
                                socks[peers[fd]].shutdown(_socket.SHUT_RD)
                            if data:
                                buf[peers[fd]] = [data]
                            else:
                                buf[peers[fd]] = []
                                wset.remove(fd)
                                if peers[fd] not in rset:
                                    sock.shutdown(_socket.SHUT_WR)
                        except _socket.error, e:
                            if e[0] != _errno.EAGAIN:
                                raise

                    if len(rset) + len(wset) == 1:
                        if sum(map(len, buf.itervalues())) > 0:
                            continue
                        break

                for sock in socks.itervalues():
                    sock.close()
            except SystemExit:
                raise
            except:
                _traceback.print_exc()
        finally:
            _os._exit(0) # pylint: disable = W0212


class Flags(object):
    """
    Flag container for workers

    :IVariables:
     - `_shutdown`: Shutdown flag and mutex (``(bool, threading.Lock)``)
    """
    __implements__ = [_impl.FlagsInterface]
    multithread = True
    multiprocess = False
    run_once = False

    def __init__(self, shutdown=False):
        """
        Initialization

        :Parameters:
         - `shutdown`: Initial state of shutdown flag

        :Types:
         - `shutdown`: ``bool``
        """
        self._shutdown = bool(shutdown), _threading.Lock()

    def shutdown(self, flag=None):
        """
        Set and/or retrieve shutdown flag

        :Parameters:
         - `flag`: The new shutdown flag value (or ``None``)

        :Types:
         - `flag`: ``bool``

        :return: The previous state of the flag
        :rtype: ``bool``
        """
        # pylint: disable = W0221
        lock = self._shutdown[1]
        lock.acquire()
        try:
            oldflag = self._shutdown[0]
            if flag is not None:
                self._shutdown = bool(flag), lock
            return oldflag
        finally:
            lock.release()


class JobWorkerQueue(object):
    """ Combined management of jobs and workers """

    def __init__(self, pool):
        """
        Initialization

        :Parameters:
         - `pool`: thread pool instance

        :Types:
         - `pool`: `ThreadPool`
        """
        self.pool = pool
        self.flags = Flags()
        self._tasks = _collections.deque()
        self._runners = set()
        self._idle = set()
        self._lock = _threading.Lock()
        self._not_empty = _threading.Condition(self._lock)
        self._not_full = _threading.Condition(self._lock)

    def startup(self):
        """ Start the queue """
        self._not_full.acquire()
        try:
            while len(self._idle) < self.pool.maxspare:
                TaskRunner(self).start()
        finally:
            self._not_full.release()

    def shutdown(self):
        """ Shutdown the queue - finish all threads """
        self.flags.shutdown(True)
        self._not_full.acquire()
        try:
            self._tasks.extendleft([None] * (len(self._runners) + 1))
            self._not_empty.notify()
        finally:
            self._not_full.release()

    def put_task(self, task):
        """
        Put a new task into the queue

        This function blocks until there's actually space in the queue.

        :Parameters:
         - `task`: The task to put, if ``None``, the receiving runner
           should finish

        :Types:
         - `task`: any
        """
        self._not_full.acquire()
        try:
            while (len(self._idle) < self.pool.minspare and
                    len(self._runners) < self.pool.maxthreads):
                TaskRunner(self).start()

            # wait for space
            while True:
                if self._idle \
                        or len(self._runners) < self.pool.maxthreads \
                        or len(self._tasks) < self.pool.maxqueue:
                    break
                self._not_full.wait()

            # ...and queue it
            self._tasks.appendleft(task)
            self._not_empty.notify()
        finally:
            self._not_full.release()

    def get_task(self, runner):
        """
        Get the next task out of the queue.

        This function blocks until there's actually a task available.

        :return: The new task, if ``None``, the receiving runner should finish
        :rtype: any
        """
        self._not_empty.acquire()
        try:
            self._idle.add(runner)
            try:
                while not self._tasks:
                    if len(self._idle) > self.pool.maxspare:
                        task = None
                        break
                    self._not_empty.wait()
                else:
                    task = self._tasks.pop()
            finally:
                self._idle.remove(runner)
            self._not_full.notify()
            return task
        finally:
            self._not_empty.release()

    def register(self, runner):
        """
        Add a runner to the set

        :Parameters:
         - `runner`: The runner to add

        :Types:
         - `runner`: `TaskRunner`
        """
        self._runners.add(runner)
        self._idle.add(runner)

    def unregister(self, runner):
        """
        Remove a runner from the list

        :Parameters:
         - `runner`: The runner to remove

        :Types:
         - `runner`: `TaskRunner`
        """
        self._runners -= set([runner])


class TaskRunner(object):
    """ Run tasks until requested to be finished """

    def __init__(self, queue):
        """
        Initialization

        :Parameters:
         - `queue`: Queue instance

        :Types:
         - `queue`: `JobWorkerQueue`
        """
        self._queue = queue

    def start(self):
        """ Start the worker thread """
        queue = self._queue
        get_task, flags, unregister = \
            queue.get_task, queue.flags, queue.unregister
        handle, app = queue.pool.impl.handle, queue.pool.app

        def work():
            """ Wait for tasks and run them """
            try:
                while True:
                    task = get_task(self)
                    if task is None: # finish command
                        break
                    try:
                        handle(task, app, flags)
                    except: # pylint: disable = W0702
                        _sys.stderr.write(
                            "Uncaught exception in worker thread:\n" +
                            _traceback.format_exc()
                        )
                        break
            finally:
                unregister(self)

        queue.register(self)
        try:
            _thread.start_new_thread(work, ())
        except:
            unregister(self)
            raise
        _time.sleep(0.000001) # 1 usec, to let the thread run (Solaris hack)
