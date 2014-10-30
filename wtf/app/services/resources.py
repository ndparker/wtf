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
Resource Resolver
=================

This service provides global access to resources on disk, set up in
the configuration.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import errno as _errno
import os as _os
import sys as _sys

from wtf.config import ConfigurationError
from wtf import services as _services
from wtf import stream as _stream
from wtf import util as _util


class BuiltinModuleError(ConfigurationError):
    """ A builtin module was specified for relative reference """


class GlobalResources(object):
    """
    Globally visible resource service object

    :IVariables:
     - `__resources`: Resource mapping (``{'name': Resource}``)

    :Types:
     - `__resources`: ``dict``
    """

    def __init__(self, locator, resources):
        """
        Initialization

        :Parameters:
         - `resources`: Resource mapping (``{'name': Resource}``)

        :Types:
         - `resources`: ``dict``
        """
        self.__locate = locator
        self.__resources = resources

    def __call__(self, *args, **kwargs):
        return self.__locate(*args, **kwargs)

    def __getitem__(self, name):
        """
        Dict like resource getter

        :Parameters:
         - `name`: Name to look up

        :Types:
         - `name`: ``str``

        :Exceptions:
         - `KeyError`: Resource not found
        """
        return self.__resources[name]

    def __getattr__(self, name):
        """
        Attribute like resource getter

        :Parameters:
         - `name`: Name to look up

        :Types:
         - `name`: ``str``

        :Exceptions:
         - `AttributeError`: Resource not found
        """
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __contains__(self, name):
        """
        Check for availability of resource `name`

        :Parameters:
         - `name`: The resource name to look up

        :Types:
         - `name`: ``str``

        :return: Is the resource available (aka configured)?
        :rtype: ``bool``
        """
        return name in self.__resources


class ResourceService(object):
    """
    Resource Resolver

    This service provides global access to resources on disk.
    """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """
        Initialization

        :See: `wtf.services.ServiceInterface.__init__`
        """
        self._locate = Locator(config)
        self._rsc = dict((key, [self._locate(item) for item in value])
            for key, value in config.resources)

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.resource', GlobalResources(self._locate, self._rsc)

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return func


class Locator(object):
    """
    Resource locator

    :IVariables:
     - `_config`: Configuration

    :Types:
     - `_config`: `wtf.config.Config`
    """

    def __init__(self, config):
        """
        Initialization

        :Parameters:
         - `config`: Configuration

        :Types:
         - `config`: `wtf.config.Config`
        """
        self._config = config

    def __call__(self, spec, isfile=False):
        """
        Locate a particular resource

        :Parameters:
         - `spec`: The specification
         - `isfile`: Does spec refer to a file?

        :Types:
         - `spec`: ``str``
         - `isfile`: ``bool``

        :return: A resource Container
        :rtype: `Resource`
        """
        if spec.startswith('pkg:') or spec.startswith('mod:'):
            rsc = Resource.frommodule(spec[4:], isfile)
        elif spec.startswith('dir:'):
            rsc = Resource(spec[4:], self._config.ROOT, isfile)
        else:
            try:
                rsc = Resource.frommodule(spec, isfile)
            except (IOError, ImportError):
                rsc = Resource(spec, self._config.ROOT, isfile)
        return rsc


class Resource(object):
    """
    Base resource container

    :IVariables:
     - `_base`: Base directory which is represented by this object

    :Types:
     - `_base`: ``unicode``
    """
    _encoding = _sys.getfilesystemencoding() or 'latin-1'

    def __new__(cls, base, root=None, isfile=False):
        """
        Construction

        :Parameters:
         - `base`: Base directory to represent
         - `root`: Root directory in case that `base` is relative. If it's
           ``None``, the current working directory is taken.
         - `isfile`: Does it refer to a file?

        :Types:
         - `base`: ``unicode``
         - `root`: ``str``
         - `isfile`: ``bool``

        :Exceptions:
         - `IOError`: path not found
        """
        if root is None:
            root = _os.getcwd().decode(cls._encoding)
        base = base.encode('utf-8')
        base = _os.path.normpath(
            _os.path.join(root.encode('utf-8'), base.encode('utf-8'))
        ).decode('utf-8')
        if isfile:
            basename = _os.path.basename(base)
            base = _os.path.normpath(_os.path.dirname(base))
        if not _os.path.isdir(base):
            raise IOError(_errno.ENOENT, base)

        self = super(Resource, cls).__new__(cls)
        self._base = base

        if isfile:
            return self.resolve(basename)
        return self

    @classmethod
    def frommodule(cls, base, isfile=False):
        """ 
        Determine a resource relative to a module

        :Parameters:
         - `base`: The combined module and path. Like:
           ``wtf.app.sample:static``. This resolves to the static subdirectory
           of the wtf.app.sample package. If the last part is a module, the
           directory is treated as parallel to the module, Like:
           ``wtf.app.sample.index:static`` resolves to the static subdir of
           wtf.app.sample, too; parallel to index.py.
         - `isfile`: Does it refer to a file?

        :Types:
         - `base`: ``unicode``
         - `isfile`: Does it refer to a file?

        :return: New resource instance
        :rtype: `Resource`

        :Exceptions:
         - `ImportError`: Module could not be imported
         - `BuiltinModuleError`: Module doesn't have a __file__ attribute
         - `UnicodeError`: Recoding according to the locale failed.
        """
        base = unicode(base)
        tup = base.split(u':', 1)
        if len(tup) == 1:
            modname, reldir = base, None
        else:
            modname, reldir = tup

        modname = modname.encode('ascii')
        mod = _util.load_dotted(modname)
        try:
            modfile = mod.__file__
        except AttributeError:
            raise BuiltinModuleError(
                "Cannot take builtin module %r as relative path reference" %
                (modname,)
            )

        tup = [_os.path.normpath(_os.path.dirname(
            modfile.decode(cls._encoding).encode('utf-8')))]
        if reldir is not None:
            reldir = _os.path.normpath(reldir.encode('utf-8'))
            root = _os.path.normpath('/')
            while reldir.startswith(root):
                reldir = reldir[1:]
            tup.append(reldir)
        return cls(_os.path.join(*tup).decode('utf-8'), isfile=isfile)

    def list(self):
        """
        List the directory

        :return: List of strings (as returned by ``os.listdir``)
        :rtype: ``list``
        """
        # pylint: disable = E1101

        return _os.listdir(self._base.encode(self._encoding))

    def resolve(self, name):
        """
        Resolve a filename relative to this directory

        :Parameters:
         - `name`: filename to resolve

        :Types:
         - `name`: ``unicode``

        :return: resolved filename in system encoding
        :rtype: ``str``

        :Exceptions:
         - `UnicodeError`: Recoding failed
        """
        # pylint: disable = E1101

        root = _os.path.normpath('/')
        resolved = _os.path.splitdrive(_os.path.normpath(
            _os.path.join(root, unicode(name).encode('utf-8'))
        ))[1]
        while resolved.startswith(root):
            resolved = resolved[1:]
        resolved = _os.path.normpath(
            _os.path.join(self._base, resolved)
        ).decode('utf-8')
        return FileResource(self, name, resolved.encode(self._encoding))

    def open(self, name, mode='rb', buffering=-1, blockiter=1):
        """
        Open a file relative to this directory

        :Parameters:
         - `name`: relative filename
         - `mode`: File open mode
         - `buffering`: buffer spec (``-1`` == default, ``0`` == unbuffered)
         - `blockiter`: Iterator mode
           (``<= 0: Default block size, 1: line, > 1: This block size``)

        :Types:
         - `name`: ``unicode``
         - `mode`: ``str``
         - `buffering`: ``int``
         - `blockiter`: ``int``

        :return: open stream
        :rtype: `ResourceStream`

        :Exceptions:
         - `IOError`: Error opening file
        """
        return self.resolve(name).open(mode, buffering, blockiter)


class FileResource(object):
    """
    Resource representing a file

    :IVariables:
     - `directory`: The directory resource
     - `resource`: The file resource name
     - `filename`: The full file name

    :Types:
     - `directory`: `Resource`
     - `resource`: ``unicode``
     - `filename`: ``str``
    """
    def __init__(self, directory, resource, filename):
        """
        Initialization

        :Parameters:
         - `directory`: The directory resource
         - `resource`: The file resource name
         - `filename`: The full file name

        :Types:
         - `directory`: `Resource`
         - `resource`: ``unicode``
         - `filename`: ``str``
        """
        self.directory = directory
        self.resource = resource
        self.filename = filename

    def open(self, mode='rb', buffering=-1, blockiter=1):
        """
        Open the file

        :Parameters:
         - `mode`: The opening mode
         - `buffering`: Buffering spec
         - `blockiter`: Iterator mode
           (``1: Line, <= 0: Default chunk size, > 1: This chunk size``)

        :Types:
         - `mode`: ``str``
         - `buffering`: ``int``
         - `blockiter`: ``int``

        :return: The open stream
        :rtype: `ResourceStream`
        """
        return ResourceStream(
            self.resource, self.filename, mode, buffering, blockiter
        )


class ResourceStream(_stream.GenericStream):
    """
    Extended generic stream, which provides more info about the resource

    :IVariables:
     - `_length`: Resource size in bytes. Retrieve it via len``(r)``
     - `resource`: The name, which the resource was resolved from
     - `last_modified`: Last modification time

    :Types:
     - `_length`: ``int``
     - `resource`: ``str``
     - `last_modified`: ``datetime.datetime``
    """

    def __new__(cls, resource, fullname, mode, buffering, blockiter):
        """
        Initialization

        :Parameters:
         - `resource`: Resource name (just for making it available)
         - `fullname`: Full name of the file to open
         - `mode`: File opening mode
         - `buffering`: Buffering spec
         - `blockiter`: Iterator mode

        :Types:
         - `resource`: ``str``
         - `fullname`: ``str``
         - `mode`: ``str``
         - `buffering`: ``int``
         - `blockiter`: ``int``
        """
        # pylint: disable = W0221

        stream = file(fullname, mode)
        self = super(ResourceStream, cls).__new__(
            cls, stream, buffering, blockiter, read_exact=True
        )
        self.resource = resource
        stres = _os.fstat(stream.fileno())
        self.last_modified = _datetime.datetime.utcfromtimestamp(
            stres.st_mtime
        )
        self._length = stres.st_size
        return self

    def __len__(self):
        """
        Determine the size of the resource in bytes

        :return: The resource size
        :rtype: ``int``
        """
        return self._length # pylint: disable = E1101
