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
Request object
==============

This module implements a request object.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import binascii as _binascii
import codecs as _codecs
import cgi as _cgi
import encodings as _encodings
import re as _re
import urlparse as _urlparse
import weakref as _weakref

from wtf import webutil as _webutil
from wtf.util import Property


class Uploads(object):
    """
    Container for uploaded files

    :IVariables:
     - `_pairs`: Dict of form names and file objects

    :Types:
     - `_pairs`: ``dict``
    """

    def __init__(self, uploads):
        """
        Initialization

        :Parameters:
         - `uploads`: Dict of form names and file objects

        :Types:
         - `uploads`: ``dict``
        """
        self._pairs = uploads

    def __getitem__(self, name):
        """
        Return a single value for that name

        :Parameters:
         - `name`: The form name

        :Types:
         - `name`: ``str``

        :return: File object
        :rtype: ``file``

        :Exceptions:
         - `KeyError`: The name does not exist
        """
        return self._pairs[name][0]

    def __iter__(self):
        """
        Return an iterator over the regular keys
        """
        return self._pairs.iterkeys()

    def __contains__(self, name):
        """
        Determines whether a certain key exists

        :Parameters:
         - `name`: The key to check

        :Types:
         - `name`: ``str``

        :return: Does the key exist?
        :rtype: ``bool``
        """
        return name in self._pairs

    def keys(self):
        """
        Determine the list of available keys

        :return: The key list
        :rtype: ``list``
        """
        return self._pairs.keys()

    def multi(self, name):
        """
        Return a list of all values under that name

        :Parameters:
         - `name`: The name to look up

        :Types:
         - `name`: ``str``

        :return: List of files belonging to this key
        :rtype: ``tuple``
        """
        return tuple(self._pairs.get(name, ()))


class ParameterWrapper(object):
    """
    Wrapper around cgi.FieldStorage

    This wrapper provides a better interface and unicode awareness
    """

    def __init__(self, request):
        """
        Initialization

        :Parameters:
         - `request`: request object

        :Types:
         - `request`: `Request`
        """
        env = request.env
        try:
            store = _cgi.FieldStorage(
                fp=env['wsgi.input'], environ=env, keep_blank_values=True
            )
            if store.list is None:
                raise ValueError()
        except ValueError:
            self._encoding = 'utf-8'
            self._uploads = Uploads({})
            self._pairs = {}
        else:
            encoding = self._determine_encoding(store)

            uploads = {}
            regular = {}
            for key in store:
                values = store[key]
                if type(values) is not list:
                    values = [values]
                for value in values:
                    if value.filename:
                        uploads.setdefault(key, []).append(value)
                    else:
                        try:
                            value = value.value.decode(encoding)
                        except UnicodeError:
                            value = value.value.decode('cp1252')
                        regular.setdefault(key, []).append(value)

            self._encoding = encoding
            self._uploads = Uploads(uploads)
            self._pairs = regular

    @Property
    def encoding():
        """
        Assumed encoding of the request

        :Type: ``str``
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            return self._encoding
        return locals()

    @Property
    def uploads():
        """
        Upload container

        :Type: `Uploads`
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            return self._uploads
        return locals()

    def __setitem__(self, name, value):
        """
        Set a single item value

        :Parameters:
         - `name`: The name to set
         - `value`: The value to assign

        :Types:
         - `name`: ``str``
         - `value`: ``unicode``
        """
        try:
            iter(value)
        except TypeError:
            value = [unicode(value)]
        else:
            if isinstance(value, basestring):
                value = [unicode(value)]
            else:
                value = map(unicode, value)
        self._pairs[name] = value

    def __getitem__(self, name):
        """ Return a single value for that name """
        return (self._pairs.get(name) or [u''])[0]

    def __iter__(self):
        """ Return an iterator over the regular keys """
        return self._pairs.iterkeys()

    def __contains__(self, name):
        """
        Determines whether a certain key exists

        :Parameters:
         - `name`: The key to check

        :Types:
         - `name`: ``str``

        :return: Does the key exist?
        :rtype: ``bool``
        """
        return name in self._pairs
    has_key = __contains__

    def keys(self):
        """
        Determine the list of available keys

        :return: The key list
        :rtype: ``list``
        """
        return self._pairs.keys()

    def multi(self, name):
        """ Return a list of all values under that name """
        return tuple(self._pairs.get(name, ()))

    @staticmethod
    def _determine_encoding(store):
        """ Guess encoding of the request parameters """
        # try simple method first...
        encoding = store.getfirst('_charset_')
        if not encoding:
            # peek is assumed to be '\xe4', i.e. &#228;
            encoding = {
                '\xc3\xa4': 'utf-8',
                None      : 'utf-8',
                ''        : 'utf-8',
                '\x84'    : 'cp437', # default lynx on dos
            }.get(store.getfirst('_peek_'), 'cp1252')
        encoding = _encodings.normalize_encoding(encoding)

        # fix known browser bug, but it doesn't exactly hurt:
        if encoding.replace('_', '').decode('latin-1').lower() == u'iso88591':
            encoding = 'cp1252'
        else:
            try:
                _codecs.lookup(encoding)
            except LookupError:
                # doh!
                encoding = 'cp1252'
        return encoding


class CookieCollection(object):
    """
    Cookies parsed out of the request

    :IVariables:
      `_cookies` : ``dict``
        Cookie mapping (``{'name': ['value', ...], ...}``)

      `_cookiestring` : ``str``
        Initial cookie string
    """
    #: Split iterator
    #:
    #: :Type: ``callable``
    _SPLIT_ITER = _re.compile(r"""(
        (?:
            \s*
            (?P<key> [^"=\s;,]+ )
            (?:
                \s* = \s*
                (?P<val> " [^\\"]* (?:\\. [^\\"]* )* " | [^",;\s]+ )
            )?
        )+
    )""", _re.X).finditer

    def __init__(self, cookiestring, codec=None):
        """
        Initialization

        :Parameters:
         - `cookiestring`: Cookie string out of the request
         - `codec`: Cookie en-/decoder; if ``None``, an identity decoder
           is used.

        :Types:
         - `cookiestring`: ``str``
         - `codec`: `CookieCodecInterface`
        """
        pairs, cookies = [item.group('key', 'val') for item in
            self._SPLIT_ITER(cookiestring)], {}
        if codec is None:
            decode = lambda x: x
        else:
            decode = codec.decode
        for key, value in pairs:
            if value is not None and not key.startswith('$'):
                try:
                    cookies.setdefault(key, []).append(decode(value))
                except ValueError:
                    continue # ignore the unreadable
        self._cookies = cookies
        self._cookiestring = cookiestring

    def __call__(self, codec):
        """
        Create a cookie collection with a particular codec

        :Parameters:
         - `codec`: The codec to aplpy

        :Types:
         - `codec`: `CookieCodecInterface`

        :return: New CookieCollection instance
        :rtype: `CookieCollection`
        """
        return self.__class__(self._cookiestring, codec)

    def __getitem__(self, name):
        """
        Determine the value of a cookie

        :Parameters:
         - `name`: The cookie name

        :Types:
         - `name`: ``str``

        :return: The cookie value
        :rtype: ``unicode``

        :Exceptions:
         - `KeyError`: The cookie name does not exist
        """
        return self._cookies[name][0]

    def __iter__(self):
        """
        Create an iterator over the available cookie names

        :return: Iterator over the names
        :rtype: ``iterable``
        """
        return self._cookies.iterkeys()

    def __contains__(self, name):
        """
        Determine whether a particular cookie name was submitted

        :Parameters:
         - `name`: The cookie name to look up

        :Types:
         - `name`: ``str``

        :return: Is the name available?
        :rtype: ``bool``
        """
        return name in self._cookies
    has_key = __contains__

    def keys(self):
        """
        Determine the list of all available cookie names

        :return: The cookie name list (``['name', ...]``)
        :rtype: ``list``
        """
        return self._cookies.keys()

    def multi(self, name):
        """
        Determine a list of all cookies under that name

        :Parameters:
         - `name`: Name of the cookie(s)

        :Types:
         - `name`: ``str``

        :return: Tuple of cookie values (``(u'value', ...)``); maybe empty
        :rtype: ``tuple``
        """
        return tuple(self._cookies.get(name, ()))


class Request(object):
    """
    Request object passed to the application

    :CVariables:
     - `_PORTS`: Default port mapping accessor for http and https
     - `_PORTMATCH`: Host:port matching function

    :IVariables:
     - `_param`: Request parameter store
     - `env`: WSGI environment
     - `match`: URL regex match or ``None``, filled from outside

    :Types:
     - `_PORTS`: ``callable``
     - `_PORTMATCH`: ``callable``
     - `_param`: `ParameterWrapper`
     - `env`: ``dict``
     - `match`: regex match
    """
    _param, _cookie, match, _PORTS = None, None, None, {
        'http': 80,
        'https': 443,
    }.get
    _PORTMATCH = _re.compile(r'(?P<host>.+):(?P<port>\d+)$').match

    def __init__(self, environ):
        """
        Initialization

        :Parameters:
         - `environ`: WSGI environment

        :Types:
         - `environ`: ``dict``
        """
        self.env = environ
        self.url = self.abs_uri(_webutil.URL.fromcomponents(_urlparse.urljoin(
            '/',
            ''.join((environ['SCRIPT_NAME'], environ.get('PATH_INFO', '')))
        ),  netloc=environ.get('HTTP_HOST'),
            query=_webutil.Query(environ.get('QUERY_STRING', ''))
        ))

    def __getattr__(self, name):
        """
        Resolve unknown attributes

        We're looking for special env variables inserted by the middleware
        stack: ``wtf.request.<name>``. These are expected to be factories,
        which are lazily initialized with the request object and return
        the actual attribute, which is cached in the request object for
        further use.

        :Parameters:
         - `name`: The name to look up

        :Types:
         - `name`: ``str``

        :return: The attribute in question
        :rtype: any

        :Exceptions:
         - `AttributeError`: Attribute could not be resolved
        """
        try:
            factory = self.env['wtf.request.%s' % name]
        except KeyError:
            pass
        else:
            setattr(self, name, factory(_weakref.proxy(self)))
        return super(Request, self).__getattribute__(name)

    @Property
    def param():
        """
        The request parameters (Query string or POST data)

        This property is lazily initialized on first request.

        :Type: `ParameterWrapper`
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            result = self._param
            if result is None:
                result = self._param = ParameterWrapper(self)
            return result
        return locals()

    @Property
    def cookie():
        """
        The cookies

        This property is lazily initialized on first request.

        :Type: `CookieCollection`
        """
        # pylint: disable = E0211, C0111, W0212, W0612

        def fget(self):
            result = self._cookie
            if result is None:
                result = self._cookie = CookieCollection(
                    self.env.get('HTTP_COOKIE', ''),
                    self.env.get('wtf.codec.cookie'),
                )
            return result
        return locals()

    @Property
    def basic_auth():
        """
        Credentials of HTTP basic authentication

        (username, password) tuple or (None, None)

        :Type: ``tuple``
        """
        # pylint: disable = E0211, C0111, W0612

        def fget(self):
            header = self.env.get('HTTP_AUTHORIZATION')
            if header is None:
                header = self.env.get('Authorization')
            if header is not None:
                header = header.strip().split()
                if len(header) == 2 and header[0].lower() == 'basic':
                    try:
                        header = header[1].decode('base64')
                    except (ValueError, _binascii.Error):
                        pass
                    else:
                        header = header.split(':', 1)
                        if len(header) == 1:
                            header = (header, None)
                        return header
            return None, None
        return locals()

    @Property
    def is_ssl():
        """
        Is the request is SSL enabled?

        :Type: ``bool``
        """
        # pylint: disable = E0211, C0111, W0612

        def fget(self):
            return self.env['wsgi.url_scheme'] == 'https'
        return locals()

    @Property
    def method():
        """
        The request method

        :Type: ``str``
        """
        # pylint: disable = E0211, C0111, W0612

        def fget(self):
            return self.env['REQUEST_METHOD']
        return locals()

    def remote_addr(self, check_proxy=False):
        """
        Determine the remote address

        :Parameters:
         - `check_proxy`: Check for ``X-Forwarded-For``?

        :Types:
         - `check_proxy`: ``bool``

        :return: The remote address
        :rtype: ``str``
        """
        addr = self.env['REMOTE_ADDR']
        if check_proxy:
            addr = self.env.get('HTTP_X_FORWARDED_FOR', addr
                ).split(',')[-1].strip()
        return addr

    def abs_uri(self, url, decode=None):
        """
        Determine absolute URI out of a (possibly) path only one

        :Parameters:
         - `url`: URL to expand

        :Types:
         - `url`: ``basestring`` or `wtf.webutil.URL`

        :return: The expanded URL
        :rtype: `wtf.webutil.URL`
        """
        env = self.env
        parsed = _webutil.URL(url, decode=decode)
        if not parsed.scheme:
            parsed.scheme = env['wsgi.url_scheme']
        if not parsed.netloc:
            parsed.netloc = env['SERVER_NAME']
            match = self._PORTMATCH(parsed.netloc)
            if not match and \
                    env['SERVER_PORT'] != str(self._PORTS(parsed.scheme)):
                parsed.netloc = "%s:%s" % (parsed.netloc, env['SERVER_PORT'])
        else:
            match = self._PORTMATCH(parsed.netloc)
            if match and \
                    match.group('port') == str(self._PORTS(parsed.scheme)):
                parsed.netloc = match.group('host')

        return parsed
