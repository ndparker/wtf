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
Common Utilities
================

Certain utilities to make the life more easy.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import imp as _imp
import inspect as _inspect
import keyword as _keyword
import os as _os
import re as _re
import sys as _sys
import traceback as _traceback
import warnings as _warnings
import weakref as _weakref

from wtf import WtfWarning


class ImportWarning(WtfWarning): # pylint: disable = W0622
    """ A package import failed, but is configured to not be fatal """


def decorating(decorated, extra=None, skip=0):
    """
    Create decorator for designating decorators.

    :Parameters:
      `decorated` : function
        Function to decorate

      `extra` : ``dict``
        Dict of consumed keyword parameters (not existing in the originally
        decorated function), mapping to their defaults. If omitted or
        ``None``, no extra keyword parameters are consumed. The arguments
        must be consumed by the actual decorator function.

      `skip` : ``int``
        Skip positional parameters at the beginning

    :Return: Decorator
    :Rtype: ``callable``
    """
    # pylint: disable = R0912
    idmatch = _re.compile(r'[a-zA-Z_][a-zA-Z_\d]*$').match
    def flat_names(args):
        """ Create flat list of argument names """
        for arg in args:
            if isinstance(arg, basestring):
                yield arg
            else:
                for arg in flat_names(arg):
                    yield arg
    try:
        name = decorated.__name__
    except AttributeError:
        if isinstance(decorated, type):
            name = decorated.__class__.__name__
            decorated = decorated.__init__
        else:
            name = decorated.__class__.__name__
            decorated = decorated.__call__
    oname = name
    if not idmatch(name) or _keyword.iskeyword(name):
        name = 'unknown_name'

    try:
        dargspec = argspec = _inspect.getargspec(decorated)
    except TypeError:
        dargspec = argspec = ([], 'args', 'kwargs', None)
    if skip:
        argspec[0][:skip] = []
    if extra:
        keys = extra.keys()
        argspec[0].extend(keys)
        defaults = list(argspec[3] or ())
        for key in keys:
            defaults.append(extra[key])
        argspec = (argspec[0], argspec[1], argspec[2], defaults)

    # assign a name for the proxy function.
    # Make sure it's not already used for something else (function
    # name or argument)
    counter, proxy_name = -1, 'proxy'
    names = dict.fromkeys(flat_names(argspec[0]))
    names[name] = None
    while proxy_name in names:
        counter += 1
        proxy_name = 'proxy%s' % counter

    def inner(decorator):
        """ Actual decorator """
        # Compile wrapper function
        space = {proxy_name: decorator}
        if argspec[3]:
            kwnames = argspec[0][-len(argspec[3]):]
        else:
            kwnames = None
        passed = _inspect.formatargspec(argspec[0], argspec[1], argspec[2],
            kwnames, formatvalue=lambda value: '=' + value
        )
        # pylint: disable = W0122
        exec "def %s%s: return %s%s" % (
            name, _inspect.formatargspec(*argspec), proxy_name, passed
        ) in space
        wrapper = space[name]
        wrapper.__dict__ = decorated.__dict__
        wrapper.__doc__ = decorated.__doc__
        if extra and decorated.__doc__ is not None:
            if not decorated.__doc__.startswith('%s(' % oname):
                wrapper.__doc__ = "%s%s\n\n%s" % (
                    oname,
                    _inspect.formatargspec(*dargspec),
                    decorated.__doc__,
                )
        return wrapper
    return inner


def make_setarg(arg, func):
    """
    Find argument position and create arg setter:

    The signature of the setter function is::

        def setarg(args, kwargs, value_func):
            '''
            Set argument

            The argument is set only if the `value_func` function says so::

                def value_func(oldval):
                    '''
                    Determine argument value

                    :Parameters:
                      `oldval` : any
                        Value passed in

                    :Return: A tuple containing a boolean if the value is
                             new and should be set (vs. to leave the
                             passed-in value) and the final value
                    :Rtype: ``tuple``
                    '''

            :Parameters:
              `args` : sequence
                Positional arguments

              `kwargs` : ``dict``
                Keyword arguments

              `value_func` : ``callable``
                Value function

            :Return: A tuple containing `value_func`'s return value, the
                     new args and the new kwargs.
            :Rtype: ``tuple``
            '''

    :Parameters:
      `arg` : ``str``
        Argument name

      `func` : ``callable``
        Function to call

    :Return: arg setter function(args, kwargs, value_func)
    :Rtype: ``callable``
    """
    try:
        spec = _inspect.getargspec(func)
    except TypeError:
        try:
            if isinstance(func, type):
                func = func.__init__
            else:
                func = func.__call__
        except AttributeError:
            spec = None
        try:
            spec = _inspect.getargspec(func)
        except TypeError:
            spec = None

    if spec is not None and arg in spec[0]:
        idx = spec[0].index(arg)
    else:
        idx = None

    def setarg(args, kwargs, value_func):
        """
        Set argument

        The argument is set only if the `value_func` function says so::

            def value_func(oldval):
                '''
                Determine argument value

                :Parameters:
                  `oldval` : any
                    Value passed in

                :Return: A tuple containing a boolean if the value is new and
                         should be set (vs. to leave the passed-in value) and
                         the final value
                :Rtype: ``tuple``
                '''

        :Parameters:
          `args` : sequence
            Positional arguments

          `kwargs` : ``dict``
            Keyword arguments

          `value_func` : ``callable``
            Value function

        :Return: A tuple containing `value_func`'s return value, the new args
                 and the new kwargs.
        :Rtype: ``tuple``
        """
        if idx is None or idx >= len(args):
            kwargs = kwargs.copy()
            created, value = value_func(kwargs.get(arg))
            if created:
                kwargs[arg] = value
        else:
            created, value = value_func(args[idx])
            if created:
                args = list(args)
                args[idx] = value
                args = tuple(args)
        return (created, value), args, kwargs

    return setarg


def load_dotted(name):
    """
    Load a dotted name

    The dotted name can be anything, which is passively resolvable
    (i.e. without the invocation of a class to get their attributes or
    the like). For example, `name` could be 'wtf.util.load_dotted'
    and would return this very function. It's assumed that the first
    part of the `name` is always is a module.

    :Parameters:
     - `name`: The dotted name to load

    :Types:
     - `name`: ``str``

    :return: The loaded object
    :rtype: any

    :Exceptions:
     - `ImportError`: A module in the path could not be loaded
    """
    components = name.split('.')
    path = [components.pop(0)]
    obj = __import__(path[0])
    while components:
        comp = components.pop(0)
        path.append(comp)
        try:
            obj = getattr(obj, comp)
        except AttributeError:
            __import__('.'.join(path))
            try:
                obj = getattr(obj, comp)
            except AttributeError:
                raise ImportError('.'.join(path))

    return obj


def make_dotted(name):
    """
    Generate a dotted module

    :Parameters:
     - `name`: Fully qualified module name (like `wtf.services`)

    :Types:
     - `name`: ``str``

    :return: The module object of the last part and the information whether
             the last part was newly added (``(module, bool)``)
    :rtype: ``tuple``

    :Exceptions:
     - `ImportError`: The module name was horribly invalid
    """
    sofar, parts = [], name.split('.')
    oldmod = None
    for part in parts:
        if not part:
            raise ImportError("Invalid module name %r" % (name,))
        partname = ".".join(sofar + [part])
        try:
            fresh, mod = False, load_dotted(partname)
        except ImportError:
            mod = _imp.new_module(partname)
            mod.__path__ = []
            fresh = mod == _sys.modules.setdefault(partname, mod)
        if oldmod is not None:
            setattr(oldmod, part, mod)
        oldmod = mod
        sofar.append(part)

    return mod, fresh


def walk_package(package, errors='ignore'):
    """
    Collect all modules and subpackages of `package` recursively

    :Parameters:
     - `package`: The package to inspect, if it's a string the string
       is interpreted as a python package name and imported first. A failed
       import of this package cannot be suppressed.
     - `errors`: What should happen on ``ImportError``s during the crawling
       process? The following values are recognized:
       ``ignore``, ``warn``, ``error``

    :Types:
     - `package`: ``module`` or ``str``
     - `errors`: ``str``

    :return: Iterator over the modules/packages (including the root package)
    :rtype: ``iterable``

    :Exceptions:
     - `ImportError`: some import failed
     - `ValueError`: The `errors` value could nto be recognized
     - `OSError`: Something bad happened while accessing the file system
    """
    # pylint: disable = E0102, E1101, R0912

    self = walk_package

    if isinstance(package, basestring):
        package = load_dotted(package)

    if errors == 'ignore':
        errors = lambda: None
    elif errors == 'warn':
        def errors():
            """ Emit an import warning """
            _warnings.warn(''.join(
                _traceback.format_exception_only(*_sys.exc_info()[:2]),
                category=ImportWarning
            ))
    elif errors == 'error':
        def errors():
            """ raise the import error """
            raise
    else:
        raise ValueError("`errors` value not recognized")

    modre, pkgre = self.matchers
    exts = [item[0] for item in _imp.get_suffixes()][::-1]
    seen = set()
    def collect(package):
        """ Collect the package recursively alphabetically """
        try:
            paths = package.__path__
        except AttributeError:
            try:
                paths = [_os.path.dirname(package.__file__)]
            except AttributeError:
                paths = []
        yield package

        for basedir in paths:
            for name in sorted(_os.listdir(basedir)):
                fullname = _os.path.join(basedir, name)

                # Found a package?
                if _os.path.isdir(fullname):
                    match = pkgre(name)
                    if not match:
                        continue
                    pkgname = "%s.%s" % (
                        package.__name__, match.group('name'))
                    if pkgname in seen:
                        continue
                    seen.add(pkgname)
                    # prevent __init__ to be considered a dedicated module
                    seen.add('%s.__init__' % pkgname)
                    try:
                        _imp.find_module('__init__', [fullname])
                    except ImportError:
                        # no package at all, so no error here
                        continue
                    else:
                        try:
                            pkg = __import__(pkgname, {}, {}, ['*'])
                        except ImportError:
                            errors()
                            continue
                        else:
                            for item in collect(pkg):
                                yield item

                # Found a module?
                elif _os.path.isfile(fullname):
                    match = modre(name)
                    if match:
                        modname = match.group('name')
                        for ext in exts:
                            if modname.endswith(ext):
                                modname = "%s.%s" % (
                                    package.__name__, modname[:-len(ext)]
                                )
                                break
                        else:
                            continue
                        if modname in seen:
                            continue
                        seen.add(modname)
                        try:
                            mod = __import__(modname, {}, {}, ['*'])
                        except ImportError:
                            errors()
                            continue
                        else:
                            yield mod
    return collect(package)
walk_package.matchers = ( # pylint: disable = W0612
    _re.compile(
        r'(?P<name>[a-zA-Z_][a-zA-Z\d_]*(?:\.[^.]+)?)$'
    ).match,
    _re.compile(r'(?P<name>[a-zA-Z_][a-zA-Z\d_]*)$').match,
)


hpre = (
    _re.compile(ur'(?P<ip>[^:]+|\[[^\]]+])(?::(?P<port>\d+))?$').match,
    _re.compile(ur'(?:(?P<ip>[^:]+|\[[^\]]+]|\*):)?(?P<port>\d+)$').match,
    _re.compile(ur'(?P<ip>[^:]+|\[[^\]]+]|\*)(?::(?P<port>\d+))?$').match,
)
def parse_socket_spec(spec, default_port=None, any=False, _hpre=hpre):
    """
    Parse a socket specification

    This is either ``u'host:port'`` or ``u'/foo/bar'``. The latter (`spec`
    containing a slash) specifies a UNIX domain socket and will be
    transformed to a string according to the inherited locale setting.
    It may be a string initially, too.

    For internet sockets, the port is optional (will be `default_port` then).
    If `any` is true, the host may point to ``ANY``. That is: the host is
    ``u'*'`` or the port stands completely alone (e.g. ``u'80'``).
    Hostnames will be IDNA encoded.

    :Parameters:
     - `spec`: The socket spec
     - `default_port`: The default port to apply
     - `any`: Allow host resolve to ``ANY``?

    :Types:
     - `spec`: ``basestring``
     - `default_port`: ``int``
     - `any`: ``bool``

    :return: The determined spec. It may be a string (for UNIX sockets) or a
             tuple of host and port for internet sockets. (``('host', port)``)
    :rtype: ``tuple`` or ``str``

    :Exceptions:
     - `ValueError`: Unparsable spec
    """
    # pylint: disable = W0622

    if isinstance(spec, str):
        if '/' in spec:
            return spec
        spec = spec.decode('ascii')
    elif u'/' in spec:
        encoding = _sys.getfilesystemencoding() or 'utf-8'
        return spec.encode(encoding)

    match = _hpre[bool(any)](spec)
    if match is None and any:
        match = _hpre[2](spec)
    if match is None:
        raise ValueError("Unrecognized socket spec: %r" % (spec,))
    host, port = match.group('ip', 'port')
    if any:
        if not host or host == u'*':
            host = None
    if host is not None:
        host = host.encode('idna')
        if host.startswith('[') and host.endswith(']'): # IPv6
            host = host[1:-1]
    if not port:
        port = default_port
    else:
        port = int(port)
    return (host, port)

del hpre


class BaseDecorator(object):
    """
    Base decorator class

    Implement the `__call__` method in order to add some action.

    :IVariables:
     - `_func`: The decorated function
     - `__name__`: The "official" name of the function with decorator
     - `__doc__`: Function's doc string

    :Types:
     - `_func`: ``callable``
     - `__name__`: ``str``
     - `__doc__`: ``basestring``
    """

    def __init__(self, func):
        """
        Initialization

        :Parameters:
         - `func`: The callable to decorate

        :Types:
         - `func`: ``callable``
        """
        self._func = func
        try:
            name = func.__name__
        except AttributeError:
            name = repr(func)
        self.__name__ = "@%s(%s)" % (self.__class__.__name__, name)
        self.__doc__ = func.__doc__

    def __get__(self, inst, owner):
        """
        Generic attribute getter (descriptor protocol)

        :Parameters:
         - `inst`: Object instance
         - `owner`: Object owner

        :Types:
         - `inst`: ``object``
         - `owner`: ``type``

        :return: Proxy function which acts for the wrapped method
        :rtype: ``callable``
        """
        def proxy(*args, **kwargs):
            """ Method proxy """
            return self(inst, *args, **kwargs)
        proxy.__name__ = self.__name__ # pylint: disable = W0622
        proxy.__dict__ = self._func.__dict__
        try:
            proxy.__doc__ = self._func.__doc__ # pylint: disable = W0622
        except AttributeError:
            pass
        return proxy

    def __getattr__(self, name):
        """
        Pass attribute requests to the function

        :Parameters:
         - `name`: The name of the attribute

        :Types:
         - `name`: ``str``

        :return: The function attribute
        :rtype: any

        :Exceptions:
         - `AttributeError`: The attribute was not found
        """
        return getattr(self._func, name)

    def __call__(self, *args, **kwargs):
        """
        Actual decorating entry point

        :Parameters:
         - `args`: Positioned parameters
         - `kwargs`: named parameters

        :Types:
         - `args`: ``tuple``
         - `kwargs`: ``dict``

        :return: The return value of the decorated function (maybe modified
                 or replaced by the decorator)
        :rtype: any
        """
        raise NotImplementedError()


class PooledInterface(object):
    """ Interface for pooled objects """

    def destroy(self):
        """
        Destroy the object

         The method has to advise the pool to forget it. It should call the
         ``del_obj`` method of the pool for that purpose. In order to achieve
         that the object needs to store a reference to pool internally. In
         order to avoid circular references it is wise to store the pool as
         a weak reference (see ``weakref`` module).
        """


class BasePool(object):
    """
    Abstract pool of arbitrary objects

    :CVariables:
     - `_LOCK`: Locking class. By default this is ``threading.Lock``. However,
       if the pooled object's initializer or destructor (``.destroy``) are
       calling back into get_conn or put_conn, it should be ``RLock``.
     - `_FORK_PROTECT`: Clear the pool, when the PID changes?

    :IVariables:
     - `_not_empty`: "not empty" condition
     - `_not_full`: "not full" condition
     - `_pool`: actual object pool
     - `_maxout`: Hard maximum number of pooled objects to be handed out
     - `_maxcached`: Maximum number of pooled objects to be cached
     - `_obj`: References to handed out objects, Note that the objects need to
       be hashable
     - `_pid`: PID of currently handed out and cached objects

    :Types:
     - `_LOCK`: ``NoneType``
     - `_FORK_PROTECT`: ``bool``
     - `_not_empty`: ``threading.Condition``
     - `_not_full`: ``threading.Condition``
     - `_pool`: ``collections.deque``
     - `_maxout`: ``int``
     - `_maxcached`: ``int``
     - `_obj`: ``dict``
     - `_pid`: ``int``
    """
    _LOCK = None
    _FORK_PROTECT, _pid = False, None

    def __init__(self, maxout, maxcached):
        """ Initialization """
        import collections as _collections
        import threading as _threading

        if self._LOCK is None:
            lock = _threading.Lock()
        else:
            lock = self._LOCK() # pylint: disable = E1102
        self._not_empty = _threading.Condition(lock)
        self._not_full = _threading.Condition(lock)
        self._pool = _collections.deque()
        maxout = max(0, int(maxout))
        if maxout:
            self._maxout = max(1, maxout)
            self._maxcached = max(0, min(self._maxout, int(maxcached)))
        else:
            self._maxout = maxout
            self._maxcached = max(0, int(maxcached))
        self._obj = {}
        if self._FORK_PROTECT:
            self._pid = _os.getpid()
        else:
            self._fork_protect = lambda: None

    def __del__(self):
        """ Destruction """
        self.shutdown()

    def _create(self):
        """
        Create a pooled object

        This method must be implemented by subclasses.

        :return: A new object
        :rtype: ``PooledInterface``
        """
        # pylint: disable = E0202

        raise NotImplementedError()

    def get_obj(self):
        """
        Get a object from the pool

        :return: The new object. If no objects are available in the pool, a
                 new one is created (by calling `_create`). If no object
                 can be created (because of limits), the method blocks.
        :rtype: `PooledInterface`
        """
        self._not_empty.acquire()
        try:
            self._fork_protect()
            while not self._pool:
                if not self._maxout or len(self._obj) < self._maxout:
                    obj = self._create() # pylint: disable = E1111
                    try:
                        proxy = _weakref.proxy(obj)
                    except TypeError:
                        proxy = obj
                    self._obj[id(obj)] = proxy
                    break
                self._not_empty.wait()
            else:
                obj = self._pool.pop()
            self._not_full.notify()
            return obj
        finally:
            self._not_empty.release()

    def put_obj(self, obj):
        """
        Put an object back into the pool

        If the pool is full, the object is destroyed instead. If the object
        does not come from this pool, it is an error (``assert``).

        :Parameters:
         - `obj`: The object to put back

        :Types:
         - `obj`: `PooledInterface`
        """
        self._not_full.acquire()
        try:
            self._fork_protect()
            if id(obj) in self._obj:
                if len(self._pool) >= self._maxcached:
                    obj.destroy()
                else:
                    self._pool.appendleft(obj)
                self._not_empty.notify()
            else:
                obj.destroy()
        finally:
            self._not_full.release()

    def del_obj(self, obj):
        """
        Remove object from pool

        If the object original came not from this pool, this is not an error.

        :Parameters:
         - `obj`: The object to remove

        :Types:
         - `obj`: `PooledInterface`
        """
        try:
            del self._obj[id(obj)]
        except KeyError:
            pass

    def clear(self):
        """
        Clear the currently cached connections

        Connections handed out are not affected. This just empties the cached
        ones.
        """
        self._not_empty.acquire()
        try:
            while self._pool:
                self._pool.pop().destroy()
        finally:
            self._not_empty.release()

    def shutdown(self):
        """
        Shutdown this pool

        The queue will be emptied and all objects destroyed. No more
        objects will be created in this pool. Waiting consumers of the pool
        will get an ``AssertionError``, because they shouldn't consume anymore
        anyway.
        """
        self._not_full.acquire()
        try:
            self._maxcached = 0
            def create():
                """ Raise error for new consumers """
                raise AssertionError("Shutdown in progress")
            self._create = create
            self._pool.clear()
            self._obj, obj = {}, self._obj.values()
            while obj:
                obj.pop().destroy()
            self._not_empty.notifyAll()
        finally:
            self._not_full.release()

    def _fork_protect(self): # pylint: disable = E0202
        """
        Check if the current PID differs from the stored one

        If they actually differed, we forked and clear the pool. This
        function should only be called within a locked environment.
        """
        pid = _os.getpid()
        if pid != self._pid:
            while self._pool:
                self._pool.pop().destroy()
            self._obj.clear()
            self._pid = pid


def hash32(s):
    """
    Replacement for ``str.__hash__``

    The function is supposed to give identical results on 32 and 64 bit
    systems.

    :Parameters:
     - `s`: The string to hash

    :Types:
     - `s`: ``str``

    :return: The hash value
    :rtype: ``int``
    """
    # pylint: disable = W0613, C0103

    raise NotImplementedError()


def Property(func): # pylint: disable = C0103
    """
    Property with improved docs handling

    :Parameters:
      `func` : ``callable``
        The function providing the property parameters. It takes no arguments
        as returns a dict containing the keyword arguments to be defined for
        ``property``. The documentation is taken out the function by default,
        but can be overridden in the returned dict.

    :Return: The requested property
    :Rtype: ``property``
    """
    kwargs = func()
    kwargs.setdefault('doc', func.__doc__)
    kwargs = kwargs.get
    return property(
        fget=kwargs('fget'),
        fset=kwargs('fset'),
        fdel=kwargs('fdel'),
        doc=kwargs('doc'),
    )


def find_public(space):
    """
    Determine all public names in space

    :Parameters:
      `space` : ``dict``
        Name space to inspect

    :Return: List of public names
    :Rtype: ``list``
    """
    if space.has_key('__all__'):
        return list(space['__all__'])
    return [key for key in space.keys() if not key.startswith('_')]


class Version(tuple):
    """
    Represents the package version

    :IVariables:
      `major` : ``int``
        The major version number

      `minor` : ``int``
        The minor version number

      `patch` : ``int``
        The patch level version number

      `is_dev` : ``bool``
        Is it a development version?

      `revision` : ``int``
        SVN Revision
    """

    def __new__(cls, versionstring, is_dev, revision):
        """
        Construction

        :Parameters:
          `versionstring` : ``str``
            The numbered version string (like ``"1.1.0"``)
            It should contain at least three dot separated numbers

          `is_dev` : ``bool``
            Is it a development version?

          `revision` : ``int``
            SVN Revision

        :Return: New version instance
        :Rtype: `version`
        """
        # pylint: disable = W0613

        tup = []
        versionstring = versionstring.strip()
        if versionstring:
            for item in versionstring.split('.'):
                try:
                    item = int(item)
                except ValueError:
                    pass
                tup.append(item)
        while len(tup) < 3:
            tup.append(0)
        return tuple.__new__(cls, tup)

    def __init__(self, versionstring, is_dev, revision):
        """
        Initialization

        :Parameters:
          `versionstring` : ``str``
            The numbered version string (like ``1.1.0``)
            It should contain at least three dot separated numbers

          `is_dev` : ``bool``
            Is it a development version?

          `revision` : ``int``
            SVN Revision
        """
        # pylint: disable = W0613

        super(Version, self).__init__()
        self.major, self.minor, self.patch = self[:3]
        self.is_dev = bool(is_dev)
        self.revision = int(revision)

    def __repr__(self):
        """
        Create a development string representation

        :Return: The string representation
        :Rtype: ``str``
        """
        return "%s.%s(%r, is_dev=%r, revision=%r)" % (
            self.__class__.__module__,
            self.__class__.__name__,
            ".".join(map(str, self)),
            self.is_dev,
            self.revision,
        )

    def __str__(self):
        """
        Create a version like string representation

        :Return: The string representation
        :Rtype: ``str``
        """
        return "%s%s" % (
            ".".join(map(str, self)),
            ("", "-dev-r%d" % self.revision)[self.is_dev],
        )

    def __unicode__(self):
        """
        Create a version like unicode representation

        :Return: The unicode representation
        :Rtype: ``unicode``
        """
        return str(self).decode('ascii')


from wtf import c_override
cimpl = c_override('_wtf_cutil')
if cimpl is not None:
    # pylint: disable = E1103
    hash32 = cimpl.hash32
del c_override, cimpl
