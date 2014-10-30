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
Single Worker Model
===================

Here's the single worker handling implemented.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import sys as _sys
import traceback as _traceback

from wtf import impl as _impl
from wtf import opi as _opi
from wtf import app as _app
from wtf.opi import worker as _worker


class SingleWorker(object):
    """
    Implement single worker model

    :See: `wtf.opi.worker.WorkerInterface`
    """
    __implements__ = [_worker.WorkerInterface]
    sig_hup = False

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
        return Worker(self, sock, prerun, None, None)


class Worker(object):
    """ Worker "pool" implementation """
    __implements__ = [_worker.WorkerPoolInterface]

    def __init__(self, model, sock, prerun, parent_cleanup, child_cleanup):
        """
        Initialization

        :Parameters:
         - `model`: The worker model implementation
         - `sock`: The main socket
         - `prerun`: Prerunner (maybe ``None``)
         - `parent_cleanup`: Parent cleanup function (ignored)
         - `child_cleanup`: Child cleanup function (ignored)

        :Types:
         - `model`: `SingleWorker`
         - `sock`: ``socket.socket``
         - `prerun`: ``callable``
         - `parent_cleanup`: ``callable``
         - `child_cleanup`: ``callable``
        """
        self.model, self.sock, self.prerun = model, sock, prerun

    def run(self):
        """
        Pool runner

        :See: `wtf.opi.worker.WorkerPoolInterface`
        """
        model, prerun, self.prerun = self.model, self.prerun, None
        impl = _impl.factory(model.config, model.opts, model.args)
        app = _app.factory(model.config, model.opts, model.args)
        try:
            accept, handle, flags = self.sock.accept, impl.handle, Flags()
            if prerun is not None:
                prerun()

            while True:
                try:
                    handle(accept(), app.call, flags)
                except (SystemExit, KeyboardInterrupt, _opi.OPIDone):
                    raise
                except:
                    print >> _sys.stderr, \
                        "Exception caught in single worker:\n" + ''.join(
                            _traceback.format_exception(*_sys.exc_info())
                        )
        finally:
            app.shutdown()

    def shutdown(self):
        """
        Pool shutdown

        :See: `wtf.opi.worker.WorkerPoolInterface`
        """
        pass


class Flags(object):
    """ Flag container for single worker """
    __implements__ = [_impl.FlagsInterface]
    multithread = False
    multiprocess = False
    run_once = False

    def __init__(self):
        """ Initialization """
        pass

    def shutdown(self):
        """ Retrieve shutdown flag """
        return False
