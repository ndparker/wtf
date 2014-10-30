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
Memcache service
================

The service provides configuration and construction of memcache connectors.

Configuration
~~~~~~~~~~~~~

You need to configure the memcache service to be loaded
(``wtf.app.services.memcache.MemcacheService``) in the services section). This
requires the following additional configuration::

  [memcache]
  servers = host[:port] ...

  # pool failover/maintenance options
  # ---------------------------------
  #grace_time = [int] Grace time on dead pools until they're backuped
  #             (Default: 30)
  #retry_time = [int] Retry interval after they're backuped (Default: 60)

  # storage options
  #compress_threshold = [int] Min size for value compression (Default: 128)
  #padded = [bool] Use padding for small values (< 16 bytes)? (Default: yes)
  #prefix = [str] Prefix keys with some arbitrary string (intended for
  #         developers using the same memcache) (Default: ``''``)
  #split = [bool] Allow splitting of values if they are bigger than the
  #        largest slab? See largest_slab option below. (Default: yes)
  #largest_slab = [int] Size of the largest slab in bytes. The value is
  #               directly connected to the memcache implementation.
  #               (Default: 1MB)

  # global defaults
  #max_age = [int] expire time (max age) per item
  #          (Default: no default max_age)

  # default values *per server*
  #maxconn = [int] hard connection maximum (Default: 0 == unlimited)
  #maxcached = [int] max cached connections (Default: 0)
  #weight = [int] relative weight, compared to the other servers. The higher
  #         the more requests it gets. (Default: 1)
  #timeout = [float] communication timeout in seconds. (Default: 2.6)

  # You can refine various settings per server with optional sections:
  #[memcache host[:port]]
  # set specific settings per server here
  # (maxconn, maxcached, weight, timeout)


Usage
~~~~~

Now you can import ``__svc__.wtf.memcache`` and take the ``connection``
decorator from there. It will inject you an ``mc`` keyword into the argument
list::

  from __svc__.wtf import memcache

  @memcache.connection
  def foo(..., mc=None):
      mc.set(...)

The decorator takes optional arguments, ``max_age``, ``nocache``,
``prepare`` and ``exceptions``. ``max_age`` defines the default max age for
this connector (overriding the configured one).

``nocache`` determines whether the ``nocache`` call argument should be
evaluated. The value can be ``False`` (``0``), ``True`` (``1``), ``2`` or
``-1``. If it evaluates to ``False``, no special handling will be applied.
Otherwise the  function (keyword) argument ``nocache`` will be checked as
boolean. If the caller supplies a true value, the memcache connector will
behave like the memcache was not available. If the decorator ``nocache``
argument is ``2`` (``> 1``), the ``nocache`` function call argument will be
passed through, otherwise it's been swallowed by the decorator. If it's
``-1``, the nocache parameter is swallowed but not evaluated. Default is
``False``. Now this all sounds confusing, I guess. Here's an example::

  @memcache.connection(nocache=True)
  def foo(..., mc=None):
    ...

  foo(nocache=True)

The call to ``foo`` causes every memcache operation inside ``foo`` like
the memcache was not running, without any change on ``foo``. For a more
complex handling, you can define::

  @memcache.connection(nocache=2)
  def foo(..., nocache=None, mc=None):
    ...

  foo(nocache=True)

This call to ``foo`` causes the same "oblivion" of the memcache connector, but
passes the nocache value to the ``foo`` function for further evaluation.

One further note: If the connector is passed from outside, like::

  @memcache.connection(nocache=True)
  def foo(..., mc=None):
    ...

  @memcache.connection(nocache=False)
  def bar(..., mc=None):
    foo(..., mc=mc)

The "inside" settings (here: ``foo``'s decorator's parameters) are ignored.

``prepare`` defines a key preparation callable (overriding the default one,
which MD5s the keys). This callables takes a key and returns a key (at least
the returned value must be a ``str``)::

  # identify preparation. Note that a configured prefix is still applied to
  # the result.
  prepare = lambda x: x

  @memcache.connection(prepare=prepare)
  def foo(..., mc=None):
      mc.set(...)

``exceptions`` determines whether the memcache user wants to see memcache
exceptions or not. If ``True`` the exceptions are passed through. If
``False``, they're swallowed and treated as failed memcache response.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import copy as _copy
try:
    import hashlib as _md5
except ImportError:
    import md5 as _md5
import time as _time

from wtf import services as _services
from wtf import util as _util
from wtf.ext import memcache as _memcache

def memcached(keygen, **kwargs):
    """ Failsafe memcached decorator (against missing service) """
    try:
        # pylint: disable = E0611
        from __svc__.wtf import memcache
    except ImportError:
        kwargs['disabled'] = True
        def inner(func):
            """ Decorator """
            return TransparentCacheDecorator(
                func, keygen, NoMemcacheWrapper(), 0, **kwargs
            )
    else:
        def inner(func):
            """ Decorator """
            return memcache.memcached(keygen, **kwargs)(func)
    return inner


def connection(*args, **kwargs):
    """ Failsafe connection decorator (against missing service) """
    try:
        # pylint: disable = E0611
        from __svc__.wtf import memcache
    except ImportError:
        if len(args) == 1 and not kwargs and callable(args[0]):
            return args[0]
        def inner(func):
            """ Decorator """
            return func
        return inner

    return memcache.connection(*args, **kwargs)


class TransparentCacheDecorator(_util.BaseDecorator):
    """ Decorator which transparently memoizes a function call """

    def __new__(cls, func, keygen, mcc, max_age, nocache=False,
                disabled=False, pass_=False, local=False, nolocal=False,
                recache=False):
        """ Construction """
        # pylint: disable = R0913
        self = super(TransparentCacheDecorator, cls).__new__(cls)
        extra = {}
        if nocache == 1:
            extra['nocache'] = False
        if nolocal == 1:
            extra['nolocal'] = False
        if recache:
            extra['recache'] = False
        self.__init__(func, keygen, mcc, max_age,
            nocache=nocache,
            disabled=disabled,
            pass_=pass_,
            local=local,
            nolocal=nolocal,
            recache=recache,
        )
        return _util.decorating(func, extra=extra or None)(self)

    def __init__(self, func, keygen, mcc, max_age, nocache=False,
                 disabled=False, pass_=False, local=False, nolocal=False,
                 recache=False):
        """
        Initialization

        :Parameters:
          `func` : ``callable``
            The function to decorate

          `keygen` : ``callable``
            Key generator callable

          `mcc` : `Memcache`
            Memcache connector

          `nocache` : ``int``
            Evaluate nocache argument?

          `disabled` : ``bool``
            Is this decorator disabled?

          `pass_` : ``bool``
            Pass memcache to the function?

          `local` : ``bool`` or ``float``
            Cache locally as well? (It will be deepcopied for usage)
            The local cachetime will be `local` * max_age of the memcache age.
            (if False, it's 0, if True, it's 1)

          `nolocal` : ``int``
            Evaluate nolocal argument?

          `recache` : ``bool``
            Evaluate recache argument? Useful for backfilling.
            The memcache won't be asked, but set unconditionally.
        """
        # pylint: disable = R0913
        super(TransparentCacheDecorator, self).__init__(func)
        self._keygen = keygen
        self._mc = mcc
        self._nocache = nocache
        self._disabled = disabled
        self._pass = pass_
        self._recache = recache
        self._nolocal = nolocal
        if local and max_age > 0:
            max_age = int(max_age * local)
            if max_age > 0:
                self._local = max_age, {}
            else:
                self._local = None
        else:
            self._local = None

    def __call__(self, *args, **kwargs):
        """
        Compute the key, check for presence and return the cached result

        If the key is not cached yet, just call the function and store the
        result in the cache. Except nocache is requested by the caller and
        activated in this decorator instance.

        :Parameters:
          `args` : ``tuple``
            Function's positional arguments

          `kwargs` : ``dict``
            Function's keyword arguments

        :Return: Whatever the decorated function returns
        :Rtype: any

        :Exceptions:
          - `Exception` : Whatever the decorated function raises
        """
        # pylint: disable = R0912
        if self._recache:
            recache = kwargs.pop('recache', False)
        else:
            recache = False
        if self._nocache:
            nocache = kwargs.pop('nocache', False)
        else:
            nocache = False
        if self._nolocal:
            nolocal = kwargs.pop('nolocal', False)
        else:
            nolocal = False
        if self._disabled or self._nocache:
            if self._disabled:
                nocache = True
            if self._nocache > 1:
                kwargs['nocache'] = nocache
            if self._nolocal > 1:
                kwargs['nolocal'] = nolocal
            if self._pass:
                kwargs['mc'] = NoMemcacheWrapper()
            if nocache and self._nocache > 0:
                return self._func(*args, **kwargs)

        mcc = self._mc
        if self._pass:
            kwargs['mc'] = mcc
        key = self._keygen(*args, **kwargs)
        if not nolocal:
            local = self._local
            if local is not None and not recache:
                found = local[1].get(key)
                if found is not None:
                    stamp, found = found
                    if stamp >= _time.time():
                        return _copy.deepcopy(found)
                    try:
                        del local[1][key]
                    except KeyError:
                        pass
        if not recache:
            cached = mcc.get(key)
            if cached:
                if not nolocal and local is not None:
                    local[1][key] = (
                        _time.time() + local[0],
                        _copy.deepcopy(cached[key])
                    )
                return cached[key]
        result = self._func(*args, **kwargs)
        mcc.set(key, result)
        if not nolocal and local is not None:
            local[1][key] = (_time.time() + local[0], _copy.deepcopy(result))
        return result


class MemcacheDecorator(_util.BaseDecorator):
    """
    Memcache decorator

    :IVariables:
     - `_mc`: Memcache connector

    :Types:
     - `_mc`: `MemcacheWrapper` or `Memcache`
    """

    def __init__(self, func, mcc, nocache=False, disabled=False):
        """
        Initialization

        :Parameters:
         - `func`: The function to decorate
         - `mcc`: The memcache connector
         - `nocache`: Nocache behavior
         - `disabled`: Is this decorator disabled?

        :Types:
         - `func`: ``callable``
         - `mcc`: `MemcacheWrapper` or `Memcache`
         - `nocache`: ``int``
         - `disabled`: ``bool``
        """
        super(MemcacheDecorator, self).__init__(func)
        self._mc = mcc
        self._nocache = int(nocache)
        self._disabled = disabled

    def __call__(self, *args, **kwargs):
        """
        Create a memcache connector or reuse a supplied one

        The resulting connector is passed as a keyword argument into the
        decorated function.

        :Parameters:
         - `args`: Function's positional arguments
         - `kwargs`: Function's keyword arguments

        :Types:
         - `args`: ``tuple``
         - `kwargs`: ``dict``

        :return: Whatever the decorated function returns
        :rtype: any

        :Exceptions:
         - `Exception`: Whatever the decorated function raises
        """
        if self._disabled:
            kwargs['mc'] = NoMemcacheWrapper()
        else:
            mcc = kwargs.get('mc')
            if not mcc:
                mcc = self._mc
                if self._nocache:
                    nocache = kwargs.pop('nocache', False)
                    if self._nocache > 1:
                        kwargs['nocache'] = nocache
                    if self._nocache > 0 and nocache:
                        mcc = NoMemcacheWrapper()
                kwargs['mc'] = mcc
        return self._func(*args, **kwargs)


class NoMemcacheWrapper(object):
    """ Dummy connector, which does nothing actually, but provide the API """

    def set(self, key, value, max_age=None):
        """
        Set a key/value pair unconditionally

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = W0613

        return False

    def add(self, key, value, max_age=None):
        """
        Set a key/value pair if the key does not exist yet

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = W0613

        return False

    def replace(self, key, value, max_age=None):
        """
        Set a key/value pair only if the key does exist already

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = W0613

        return False

    def delete(self, key, block_time=None, all_pools=False):
        """
        Delete a key/value pair from the cache

        :Parameters:
         - `key`: The key to identify the item to delete
         - `block_time`: Time to block add and replace requests for this key
           in seconds. If omitted or ``None``, the blocking time is ``0``.
         - `all_pools`: Issue delete to each pool? This may be useful to
           enforce the deletion on backup pools, too. However, it won't
           delete the key from currently dead pools. So, it might be not
           that useful after all, but it's the best we can do from this
           side of the ocean.

        :Types:
         - `key`: ``str``
         - `block_time`: ``int``
         - `all_pools`: ``bool``

        :return: Whether it was really deleted from the main pool (or the
                 current backup pool) of this key (i.e. whether it existed
                 before)
        :rtype: ``bool``
        """
        # pylint: disable = W0613

        return False

    def get(self, *keys):
        """
        Get a list of key/value pairs from the cache (if applicable)

        The returned dict contains all pairs it could get. But keys maybe
        missing or the dict might be completely empty (of course).

        :Parameters:
         - `keys`: The keys to fetch

        :Types:
         - `keys`: ``tuple``

        :return: The dict of key/value pairs
        :rtype: ``dict``
        """
        # pylint: disable = W0613

        return {}


class ExceptionWrapper(object):
    """
    Exception catching wrapper

    :IVariables:
     - `_mc`: Memcache connector

    :Types:
     - `_mc`: `Memcache`
    """

    def __init__(self, mcc):
        """
        Initialization

        :Parameters:
         - `mcc`: Memcache connector

        :Types:
         - `mcc`: `Memcache`
        """
        self._mc = mcc

    def __getattr__(self, name):
        """
        Create proxy around callables, catching memcache errors.

        The proxy functions are cached.

        :Parameters:
         - `name`: The attribute to wrap up

        :Types:
         - `name`: ``str``

        :return: The original attribute or the proxied placeholder
        :rtype: any

        :Exceptions:
         - `AttributeError`: The attribute was not found
        """
        attr = getattr(self._mc, name)
        if callable(attr):
            def proxy(*args, **kwargs):
                """ Catching proxy """
                try:
                    return attr(*args, **kwargs)
                except _memcache.Error:
                    return False
            try:
                proxy.__name__ = attr.__name__ # pylint: disable = W0622
            except AttributeError:
                pass
            proxy.__doc__ = attr.__doc__ # pylint: disable = W0622
            setattr(self, name, proxy)
            return proxy
        return attr

    def get(self, *keys):
        """
        Get a list of key/value pairs from the cache (if applicable)

        The returned dict contains all pairs it could get. But keys maybe
        missing or the dict might be completely empty (of course).

        :Parameters:
         - `keys`: The keys to fetch

        :Types:
         - `keys`: ``tuple``

        :return: The dict of key/value pairs
        :rtype: ``dict``
        """
        try:
            return self._mc.get(*keys)
        except _memcache.Error:
            return {}


class MemcacheWrapper(object):
    """
    `Memcache` wrapper, applying default max age

    This is, what the decorator injects if a default max age is configured
    or the exceptions are caught.

    :IVariables:
     - `_mc`: Memcache connector
     - `_max_age`: Default max age

    :Types:
     - `_mc`: `Memcache`
     - `_max_age`: ``int``
    """

    def __init__(self, mcc, max_age, exceptions):
        """
        Initialization

        :Parameters:
         - `mcc`: Memcache connector
         - `max_age`: Default expire time
         - `exceptions`: pass exceptions to the caller?

        :Types:
         - `mcc`: `Memcache`
         - `max_age`: ``int``
         - `exceptions`: ``bool``
        """
        if not exceptions:
            mcc = ExceptionWrapper(mcc)
        self._mc = mcc
        self._max_age = max_age

        self.delete = mcc.delete
        self.get = mcc.get
        if max_age is None:
            self.set = mcc.set
            self.add = mcc.add
            self.replace = mcc.replace

    def set(self, key, value, max_age=None):
        """
        Set a key/value pair unconditionally

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = E0202

        if max_age is None:
            max_age = self._max_age
        return self._mc.store("set", key, value, max_age)

    def add(self, key, value, max_age=None):
        """
        Set a key/value pair if the key does not exist yet

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = E0202

        if max_age is None:
            max_age = self._max_age
        return self._mc.store("add", key, value, max_age)

    def replace(self, key, value, max_age=None):
        """
        Set a key/value pair only if the key does exist already

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds. If omitted or ``None`` the
           default is applied.

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        # pylint: disable = E0202

        if max_age is None:
            max_age = self._max_age
        return self._mc.store("replace", key, value, max_age)


class GlobalMemcache(object):
    """
    Actual global memcache service object

    :IVariables:
     - `_pools`: Pool list
     - `_create`: Memcache wrapper creator
     - `_max_age`: Globally configured max age
     - `_mc`: Default memcache wrapper

    :Types:
     - `_pools`: ``tuple``
     - `_create`: ``callable``
     - `_max_age`: ``int``
     - `_mc`: `MemcacheWrapper` or `Memcache`
    """

    def __init__(self, pools, max_age, grace_time, retry_time,
                 compress_threshold, padded, split, prefix, largest_slab):
        """
        Initialization

        :Parameters:
         - `pools`: Pool list
         - `max_age`: Default expire time (``None`` for no such default)
         - `grace_time`: Grace time, see `ext.memcache.Memcache.__init__`
           for details
         - `retry_time`: Retry time, see `ext.memcache.Memcache.__init__`
           for details
         - `compress_threshold`: Compression threshold
         - `padded`: Padded, yes/no? (``None`` for the default)
         - `split`: Split yes/no? (``None`` for the default)
         - `prefix`: global key prefix
         - `largest_slab`: Largest slab size (``None`` for the default)

        :Types:
         - `pools`: ``iterable``
         - `max_age`: ``int``
         - `grace_time`: ``int``
         - `retry_time`: ``int``
         - `compress_threshold`: ``int``
         - `padded`: ``bool``
         - `split`: ``bool``
         - `prefix`: ``str``
         - `largest_slab`: ``int``
        """
        self._pools = tuple(pools)

        def create(prepare, max_age, exceptions):
            """
            Memcache connector creator

            :Parameters:
             - `prepare`: Key preparation function
             - `max_age`: Default expire time (or ``None``)
             - `exceptions`: Raise exceptions?

            :Types:
             - `prepare`: ``callable``
             - `max_age`: ``int``
             - `exceptions`: ``bool``

            :return: The memcache connector
            :rtype: `Memcache` or `MemcacheWrapper`
            """
            mcc = _memcache.Memcache(self._pools,
                prepare=prepare,
                grace_time=grace_time,
                retry_time=retry_time,
                compress_threshold=compress_threshold,
                padded=padded,
                split=split,
                prefix=prefix,
                largest_slab=largest_slab,
            )
            if max_age is not None or not exceptions:
                mcc = MemcacheWrapper(mcc, max_age, exceptions)
            return mcc
        self._max_age = max_age
        self._create = create
        self._mc = create(self._prepare, max_age, False)

    def status(self):
        """
        Determine pool status

        Each status is a dict
        ``{'spec': 'spec', 'alive': bool, 'weight': int}``.

        :return: The status of the pools (``[status, ...]``)
        :rtype: ``list``
        """
        return [dict(
            spec=pool.spec,
            weight=pool.weight,
            alive=not pool.dead,
        ) for pool in self._pools]

    def shutdown(self):
        """
        Shutdown the memcache pools

        The pools are no longer usable after that. This is for final
        application shutdown. Don't use it in the application itself!
        """
        pools, self._pools = self._pools, ()
        for pool in pools:
            try:
                pool.shutdown()
            except (SystemExit, KeyboardInterrupt):
                raise
            except:
                pass

    def connect(self, max_age=None, prepare=None, exceptions=None):
        """
        Create a memcache connector

        Although the method name suggests it, the method doesn't actually
        connect. The connection is selected by key later when using the
        connector to actually do something.

        :Parameters:
         - `max_age`: Default max age for store commands in seconds (overriding
           the configured default)
         - `prepare`: Key preparation function (overriding the default)
         - `exceptions`: Pass exceptions to the caller? (Default: ``False``)

        :Types:
         - `max_age`: ``int``
         - `prepare`: ``callable``
         - `exceptions`: ``bool``

        :return: The memcache connector (may be wrapped for requested
                 functionality, so it's not necessarily a real `Memcache`)
        :rtype: `Memcache`
        """
        if max_age is None and prepare is None and exceptions is None:
            return self._mc

        if max_age is None:
            max_age = self._max_age
        if prepare is None:
            prepare = self._prepare
        if exceptions is None:
            exceptions = False
        return self._create(prepare, max_age, exceptions)

    def memcached(self, keygen, **kwargs):
        """
        Cache the function transparently

        Recognized keyword parameters:

        ``max_age``
          [int] Default expire time for storing operations
        ``prepare``
          [callable] Key preparation function
        ``nocache``
          [int] Nocache behavior. See `services.memcache` for details.
        ``recache``
          [bool] Recache behavioue. See `services.memcache` for details.
        ``disabled``
          [bool] Disable this memcache decorator (useful for debugging)?
        ``pass_``
          [bool] If true, the memcache connector will be passed to the
          function
        ``exceptions``
          [bool] Memcache exception behavior (pass through = True)

        :Parameters:
          `keygen` : ``callable``
            Key generator function

          `kwargs` : ``dict``
            Keyword arguments

        :Return: The memcached decorator
        :Rtype: `TransparentCacheDecorator`
        """
        if self._max_age is None and kwargs.get('max_age') is None:
            raise RuntimeError("@memcached needs a max age set")

        nocache = kwargs.pop('nocache', None)
        disabled = kwargs.pop('disabled', None)
        pass_ = kwargs.pop('pass_', None)
        local = kwargs.pop('local', None)
        nolocal = kwargs.pop('nolocal', None)
        recache = kwargs.pop('recache', None)
        if disabled is None:
            disabled = False
        if nocache is None:
            nocache = False
        if nolocal is None:
            nolocal = False
        if recache is None:
            recache = False
        if pass_ is None:
            pass_ = False
        mcc = self.connect(**kwargs)
        def factory(func):
            """
            Decorator factory

            :Parameters:
             - `func`: The function to decorate

            :Types:
             - `func`: ``callable``

            :return: The decorated function
            :rtype: ``callable``
            """
            return TransparentCacheDecorator(func, keygen, mcc, self._max_age,
                nocache=nocache,
                disabled=disabled,
                pass_=pass_,
                local=local,
                nolocal=nolocal,
                recache=recache,
            )
        return factory

    def connection(self, *args, **kwargs):
        """
        Inject a new connector into function's arguments

        The method takes either one positional argument (the function to
        decorate) *or* keyword arguments which override default options:

        ``max_age``
          [int] Default expire time for storing operations
        ``prepare``
          [callable] Key preparation function
        ``nocache``
          [int] Nocache behavior. See `services.memcache` for details.
        ``disabled``
          [bool] Disable the memcache connection (useful for debugging)
        ``exceptions``
          [bool] Memcache exception behaviour (pass through = True)

        :Parameters:
         - `args`: Positional arguments
         - `kwargs`: keyword arguments

        :Types:
         - `args`: ``tuple``
         - `kwargs`: ``tuple``

        :return: Decorator or decorator factory
        :rtype: ``callable``

        :Exceptions:
         - `TypeError`: The arguments are formally invalid
        """
        if len(args) == 1 and not kwargs and callable(args[0]):
            return MemcacheDecorator(args[0], self._mc)
        elif not args:
            nocache = kwargs.pop('nocache', None)
            disabled = kwargs.pop('disabled', None)
            if nocache is None:
                nocache = False
            if disabled is None:
                disabled = False
            mcc = self.connect(**kwargs)
            def factory(func):
                """
                Decorator factory

                :Parameters:
                 - `func`: The function to decorate

                :Types:
                 - `func`: ``callable``

                :return: The decorated function
                :rtype: ``callable``
                """
                return MemcacheDecorator(func, mcc, nocache=nocache)
            return factory
        raise TypeError(
            "Arguments have to be either one callable positional argument "
            "or keyword arguments"
        )

    def _prepare(self, key):
        """
        Default key preparator

        The input key is assumed to be a string and is just MD5 hashed.
        The hexdigest is the resulting key then.

        :Parameters:
         - `key`: The key to prepare

        :Types:
         - `key`: ``str``

        :return: The prepared key
        :rtype: ``str``
        """
        return _md5.md5(key).hexdigest()


class MemcacheService(object):
    """
    Memcache service

    This service provides a global memcache access.

    :IVariables:
     - `_mc`: Global memcache service

    :Types:
     - `_mc`: `GlobalMemcache`
    """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """ :See: `wtf.services.ServiceInterface.__init__` """
        section = config.memcache
        servertokens = tuple(section.servers)
        pools = []
        for server in servertokens:
            key = u'memcache %s' % server
            if key in config:
                subsection = config[key]
            else:
                subsection = section
            server = _util.parse_socket_spec(server, _memcache.DEFAULT_PORT)
            pools.append(_memcache.MemcacheConnectionPool(
                subsection('maxconn', section('maxconn', 0)),
                subsection('maxcached', section('maxcached', 0)),
                server,
                weight=subsection('weight', section('weight', None)),
                timeout=subsection('timeout', section('timeout', 2.6)),
            ))
        max_age = unicode(section('max_age', u'')) or None
        if max_age is not None:
            max_age = int(max_age)
        self._mc = GlobalMemcache(pools,
            max_age,
            section('grace_time', None),
            section('retry_time', None),
            section('compress_threshold', None),
            section('padded', None),
            section('split', None),
            unicode(section('prefix', u'')).encode('utf-8'),
            section('largest_slab', None),
        )

    @classmethod
    def simple(cls, *spec, **kwargs):
        """
        Create simple on-the-fly configured service

        Recognized keyword args:

        ``max_age``
          [int] Default max age
        ``prefix``
          [unicode] Global key prefix
        ``padded``
          [bool] Padded small values?
        ``timeout``
          [float] Server timeout

        :Parameters:
         - `spec`: Memcache servers (``('spec', ...)``)
         - `kwargs`: Keyword parameters for memcache config

        :Types:
         - `spec`: ``tuple``
         - `kwargs`: ``dict``

        :return: The memcache service
        :rtype: `GlobalMemcache`

        :Exceptions:
         - `TypeError`: Unrecognized keyword args
        """
        from wtf import config as _config
        config = _config.Config(None)
        config['memcache'] = _config.Section()
        config['memcache']['servers'] = list(spec)

        max_age = kwargs.pop('max_age', None)
        if max_age is not None:
            config['memcache']['max_age'] = int(max_age)

        prefix = kwargs.pop('prefix', None)
        if prefix is not None:
            config['memcache']['prefix'] = unicode(prefix)

        padded = kwargs.pop('padded', None)
        if padded is not None:
            config['memcache']['padded'] = bool(padded)

        timeout = kwargs.pop('timeout', None)
        if timeout is not None:
            config['memcache']['timeout'] = float(timeout)

        if kwargs:
            raise TypeError("Unrecognized keyword args: %s" % ", ".join(
                kwargs.iterkeys()
            ))
        return cls(config, None, []).global_service()[1]

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        self._mc.shutdown()

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.memcache', self._mc

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return func
