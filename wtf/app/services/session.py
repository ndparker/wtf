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
Session service
===============

This service provides an API and a basic cookie based storage. The
storage is exchangable, though.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import services as _services
from wtf import util as _util


class StorageInterface(object):
    """
    Interface for storage classes

    :IVariables:
     - `has_cookie`: Is a cookie involved by this storage?

    :Types:
     - `has_cookie`: ``bool``
    """

    def set(self, name, value):
        """
        Set an attribute

        :Parameters:
         - `name`: Attribute name
         - `value`: Attribute value

        :Types:
         - `name`: ``str``
         - `value`: any
        """

    def get(self, name):
        """
        Retrieve attribute

        :Parameters:
         - `name`: Attribute name

        :Types:
         - `name`: ``str``

        :return: Attribute value
        :rtype: any

        :Exceptions:
         - `KeyError`: Attribute not found
        """

    def delete(self, name):
        """
        Delete attribute

        :Parameters:
         - `name`: Attribute name

        :Types:
         - `name`: ``str``

        :Exceptions:
         - `KeyError`: Attribute not found
        """

    def contains(self, name):
        """
        Determine whether an attribute exists

        :Parameters:
         - `name`: Attribute name to check

        :Types:
         - `name`: ``str``

        :return: Does it exist?
        :rtype: ``bool``
        """

    def need_cookie(self):
        """
        Determine whether the storage needs a cookie to be set

        :return: Does it need one?
        :rtype: ``bool``
        """

    def need_store(self):
        """
        Determine whether the storage needs a store back

        :return: Does it?
        :rtype: ``bool``
        """

    def make_cookie(self):
        """
        Create a cookie for the session

        :return: The cookie string
        :rtype: ``str``
        """

    def store_back(self):
        """ Persist the session data """

    def wipe(self):
        """ Wipe out session data """


class StorageFactoryInterface(object):
    """ Interface for storage factories """

    def __init__(self, config, opts, args):
        """
        Initialization

        :Parameters:
         - `config`: Configuration
         - `opts`: Command line options
         - `args`: Positional command line arguments

        :Types:
         - `config`: `wtf.config.Config`
         - `opts`: ``optparse.OptionContainer``
         - `args`: ``list``
        """

    def __call__(self, request):
        """
        Factory function: Create request-bound storage object

        :Parameters:
         - `request`: Request object

        :Types:
         - `request`: `wtf.app.request.Request`

        :return: The new storage instance
        :rtype: `StorageInterface`
        """

    def from_sid(self, sid):
        """
        Factory function: Create sid-bound storage object

        :Parameters:
         - `sid`: Session ID

        :Types:
         - `sid`: ``str``

        :return: The new storage instance
        :rtype: `StorageInterface`
        """

    def status(self):
        """
        Fetch status information from storage factory

        :return: Status information, see specific implementation for
                 details
        :rtype: any
        """


class Session(object):
    """
    Session object

    :IVariables:
     - `_adapter`: Storage adapter

    :Types:
     - `_adapter`: `StorageAdapter`
    """
    __slots__ = ['__weakref__', '_adapter']

    def __init__(self, adapter):
        """
        Initialization

        :Parameters:
         - `adapter`: Storage adapter

        :Types:
         - `adapter`: `StorageAdapter`
        """
        self._adapter = adapter

    def __getattr__(self, name):
        """
        Resolve magic sesison attributes magically

        :Parameters:
         - `name`: The magic name to resolve

        :Types:
         - `name`: ``str``

        :return: The value of the magic attribute
        :rtype: any

        :Exceptions:
         - `AttributeError`: Attribute not found
        """
        name = "__%s__" % name
        if self._adapter.contains(name):
            return self._adapter.get(name)
        raise AttributeError(name)

    def __delitem__(self, name):
        """
        Delete a session attribute

        If the attribute did not exist before, this is not an error
        (just a no-op).

        :Parameters:
         - `name`: Name of the attribute

        :Types:
         - `name`: ``str``
        """
        self._adapter.delete(name)

    def __setitem__(self, name, value):
        """
        Set or replace a session attribute

        :Parameters:
         - `name`: Attribute name
         - `value`: Attribute value (must be picklable)

        :Types:
         - `name`: ``str``
         - `value`: any
        """
        self._adapter.set(name, value)

    def __getitem__(self, name):
        """
        Determine the value of an attribute

        :Parameters:
         - `name`: Attribute name

        :Types:
         - `name` ``str``

        :return: Attribute value
        :rtype: any

        :Exceptions:
         - `KeyError`: The attribute did not exist
        """
        return self._adapter.get(name)

    def get(self, name, default=None):
        """
        Determine the value of an attribute

        :Parameters:
         - `name`: The attribute name
         - `default`: Default value to return in case the attribute does not
           exist

        :Types:
         - `name`: ``str``
         - `default`: any
        """
        try:
            return self._adapter.get(name)
        except KeyError:
            return default

    def __contains__(self, name):
        """
        Determine if an attribute exists in the session

        :Parameters:
         - `name`: Attribute name to check

        :Types:
         - `name`: ``str``

        :return: Does it exist?
        :rtype: ``bool``
        """
        return self._adapter.contains(name)
    has_key = __contains__

    def new(self, **kwargs):
        """
        Create a new session

        :Parameters:
         - `kwargs`: Initial attributes (``{'name': value, ...}``)

        :Types:
         - `kwargs`: ``dict``
        """
        self._adapter.new()
        for key, val in kwargs.iteritems():
            self._adapter.set(key, val)

    def invalidate(self):
        """
        Invalidate the session

        The session is not cleared, but will be unusable with the next
        request. Call `new` if you need to create a fresh, empty session after
        invalidating.
        """
        self._adapter.set('__is_valid__', False)


class StorageAdapter(object):
    """
    Storage adapter

    This class acts a glue code between the session object, middleware and
    storage implementations. It provides all interfaces needed both by the
    public session object and the middleware. The lazyness of session
    initialization and store back are also implemented here.

    :IVariables:
     - `_dirty`: Is the session dirty (need store back)?
     - `_factory`: Tuple of storage factory and request object. When the
       storage is initialized, this attribute becomes ``None``
     - `_storage`: Lazily initialized storage instance (on first access)

    :Types:
     - `_dirty`: ``bool``
     - `_factory`: ``tuple``
     - `_storage`: ``StorageInterface``
    """
    _dirty, _stored = False, False

    def __init__(self, factory, request=None):
        """
        Initialization

        :Parameters:
         - `factory`: Storage factory
         - `request`: Request object

        :Types:
         - `factory`: `StorageFactoryInterface`
         - `request`: `wtf.app.request.Request`
        """
        self._factory = factory, request

    def __getattr__(self, name):
        """
        Resolve unknown attributes

        Effectively resolve the ``_storage`` attribute lazily. The attribute
        will be cached in the instance, so this method is called only once
        (for ``_storage``).

        :Parameters:
         - `name`: The attribute name to resolve

        :Types:
         - `name`: ``str``

        :return: The resolved attribute value
        :rtype: any

        :Exceptions:
         - `AttributeError`: Attribute not found
        """
        if name == '_storage':
            factory, request = self._factory
            self._stored, self._storage = True, factory(request)
            if self.contains('__is_valid__') and not self.get('__is_valid__'):
                self._storage = factory(None)
            self.set('__is_valid__', True)
        return super(StorageAdapter, self).__getattribute__(name)

    def new(self):
        """ Create a fresh session """
        # pylint: disable = W0201

        factory, _ = self._factory
        self._dirty, self._storage = True, factory(None)
        self.set('__is_valid__', True)

    def get(self, name):
        """
        Retrieve a attribute value

        :Parameters:
         - `name`: The attribute name to look up

        :Types:
         - `name`: ``str``

        :return: attribute value
        :rtype: any

        :Exceptions:
         - `KeyError`: Attribute not found
        """
        return self._storage.get(name)

    def contains(self, name):
        """
        Determine whether an attribute exists

        :Parameters:
         - `name`: The name to check

        :Types:
         - `name`: ``str``

        :return: Does the attribute exist?
        :rtype: ``bool``
        """
        return self._storage.contains(name)

    def set(self, name, value):
        """
        Set or replace an attribute

        :Parameters:
         - `name`: Attribute name
         - `value`: Attribute value (must be pickleable)

        :Types:
         - `name`: ``str``
         - `value`: any
        """
        self._dirty, _ = True, self._storage.set(name, value)

    def delete(self, name):
        """
        Delete an attribute

        :Parameters:
         - `name`: The name of the attribute to delete

        :Types:
         - `name`: ``str``
        """
        try:
            self._dirty, _ = True, self._storage.delete(name)
        except KeyError:
            pass

    def store_back(self):
        """
        Store back the session

        :Note: The session is only stored back, if it's marked dirty.
        """
        if self._dirty or (self._stored and self._storage.need_store()):
            return self._storage.store_back()

    def wipe(self):
        """ Wipe session in storage """
        return self._storage.wipe()

    def cookie(self):
        """
        Ask the storage for a cookie if necessary

        :return: The cookie string or ``None``
        :rtype: ``str``
        """
        if self._stored and self._storage.need_cookie():
            return self._storage.make_cookie()
        return None


class SessionFactory(object):
    """
    Intermediate session object factory

    :IVariables:
     - `_storage`: Storage factory (takes the request object)
     - `_start_response`: original WSGI start_response callable
     - `_adapter`: Storage adapter (maybe ``None`` if the session is
       not queried)

    :Types:
     - `_storage`: ``callable``
     - `_start_response`: ``callable``
     - `_adapter`: ``StorageAdapter``
    """
    _adapter = None

    def __init__(self, storage, start_response):
        """
        Initialization

        :Parameters:
         - `storage`: Storage factory (takes the request object)
         - `start_response`: Original start_response callable

        :Types:
         - `storage`: ``callable``
         - `start_response`: ``callable``
        """
        self._storage = storage
        self._start_response = start_response

    def __call__(self, request):
        """
        Factory function

        :Parameters:
         - `request`: The request object

        :Types:
         - `request`: `wtf.app.request.Request`

        :return: Session object
        :rtype: `Session`
        """
        self._adapter = StorageAdapter(self._storage, request)
        return Session(self._adapter)

    def start_response(self, status, response_headers, exc_info=None):
        """
        Session dealing start_response callable

        :See: `WSGI spec`_

        .. _WSGI spec: http://www.python.org/dev/peps/pep-0333/
        """
        adapter = self._adapter
        if adapter is not None:
            adapter.store_back()
            cookie = adapter.cookie()
            if cookie is not None:
                for idx, (name, value) in enumerate(response_headers):
                    if name.lower() == 'cache-control':
                        values = set(item.strip().replace('"', '').lower()
                            for item in value.split(','))
                        toadd = []
                        if 'no-cache=set-cookie' not in values:
                            toadd.append("no-cache=Set-Cookie")
                        if 'private' not in values:
                            toadd.append("private")
                        if toadd:
                            response_headers[idx] = (
                                name, ", ".join([value] + toadd)
                            )
                        break
                else:
                    response_headers.append((
                        'Cache-Control', 'private, no-cache=Set-Cookie'
                    ))
                response_headers.append(('Set-Cookie', cookie))
        return self._start_response(status, response_headers, exc_info)


class Middleware(object):
    """
    Session middleware

    :IVariables:
     - `_storage`: Storage factory
     - `_func`: Next WSGI handler

    :Types:
     - `_storage`: `StorageFactoryInterface`
     - `_func`: ``callable``
    """

    def __init__(self, storage, func):
        """
        Initialization

        :Parameters:
         - `storage`: Storage factory
         - `func`: WSGI callable to wrap

        :Types:
         - `storage`: `StorageFactoryInterface`
         - `func`: ``callable``
        """
        self._storage, self._func = storage, func

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
        factory = SessionFactory(self._storage, start_response)
        environ['wtf.request.session'] = factory
        return self._func(environ, factory.start_response)


class GlobalSession(object):
    """
    Global session service

    :IVariables:
     - `status`: Status requester

    :Types:
     - `status`: ``callable``
    """

    def __init__(self, storage):
        """
        Initialization

        :Parameters:
         - `storage`: Storage factory

        :Types:
         - `storage`: `StorageFactoryInterface`
        """
        self.status = storage.status


class SessionService(object):
    """
    Session service

    This service provides a middleware which automatically handles
    session persistance and APIs for the application.

    :IVariables:
     - `_storage`: Storage factory

    :Types:
     - `_storage`: `StorageFactoryInterface`
    """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """ :See: `wtf.services.ServiceInterface.__init__` """
        if 'session' in config and not config.session('enable', True):
            self._storage = None
        else:
            if 'session' in config and 'storage' in config.session:
                storage = config.session.storage
            else:
                storage = 'wtf.app.services.session_storage.cookie.Cookie'
            self._storage = _util.load_dotted(storage)(config, opts, args)

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        if self._storage is None:
            return None
        return 'wtf.session', GlobalSession(self._storage)

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        if self._storage is None:
            return func
        return Middleware(self._storage, func)
