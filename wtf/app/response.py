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
Response object
===============

This module implements a response object.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import weakref as _weakref

from wtf.app import http_response as http
from wtf import httputil as _httputil


class Done(http.HTTPResponse):
    """
    Request Done exception

    Use this is cases where return is not applicable (e.g. decorators).
    """


class HeaderCollection(object):
    """
    Response header collection representation

    Note that all header names are treated case insensitive (by lowering them)

    :IVariables:
     - `_headers`: The headers (``{'name': ['value', ...], ...}``)

    :Types:
     - `_headers`: ``dict``
    """

    def __init__(self):
        """ Initialization """
        self._headers = {}

    def __contains__(self, name):
        """
        Check if header is already set

        :Parameters:
         - `name`: Header name

        :Types:
         - `name`: ``str``

        :return: Does the header already exist?
        :rtype: ``bool``
        """
        return name.lower() in self._headers

    def __iter__(self):
        """ Header tuple iterator """
        for name, values in self._headers.iteritems():
            for value in values:
                yield (name, value)

    def get(self, name):
        """
        Determine the value list of a header

        :Parameters:
         - `name`: The header name

        :Types:
         - `name`: ``str``

        :return: The value list or ``None``
        :rtype: ``list``
        """
        return self._headers.get(name.lower())

    def set(self, name, *values):
        """
        Set a header, replacing any same-named header previously set

        :Parameters:
         - `name`: The header name
         - `values`: List of values (``('value', ...)``)

        :Types:
         - `name`: ``str``
         - `values`: ``tuple``
        """
        self._headers[name.lower()] = list(values)

    def add(self, name, *values):
        """
        Add a value list to a header

        The old values are preserved

        :Parameters:
         - `name`: Header name
         - `values`: Values to add (``('value', ...)``)

        :Types:
         - `name`: ``str``
         - `values`: ``tuple``
        """
        self._headers.setdefault(name.lower(), []).extend(list(values))

    def remove(self, name, value=None):
        """
        Remove a header by name (plus optionally by value)

        If the header does not exist alrady, it is not an error.

        :Parameters:
         - `name`: Header name
         - `value`: Particular value to remove

        :Types:
         - `name`: ``str``
         - `value`: ``str``
        """
        name = name.lower()
        if name in self._headers:
            if value is None:
                del self._headers[name]
            else:
                try:
                    while True:
                        self._headers[name].remove(value)
                except ValueError:
                    pass


class Response(object):
    """
    Main response object

    :IVariables:
     - `write`: Response body writer. You are not forced to use it. In fact,
       it's recommended to not use it but return an iterator over the
       response body instead (as WSGI takes it)
     - `headers`: Response header collection. The headers are flushed
       autmatically before the fist `write` call or the returned iterable
       is passed to the WSGI layer below. The headers can't be changed
       anymore after that (the collection object will emit a warning
       in case you attempt to do that)
     - `_status`: Tuple of status and reason phrase (``(int, 'reason')``)

    :Types:
     - `write`: ``callable``
     - `headers`: `HeaderCollection`
     - `_status`: ``tuple``
    """
    _status = None

    def __init__(self, request, start_response):
        """
        Initialization

        :Parameters:
         - `request`: Request object
         - `start_response`: WSGI start_response callable

        :Types:
         - `request`: `wtf.app.request.Request`
         - `start_response`: ``callable``
        """
        self.request = _weakref.proxy(request)
        self.http = http
        self.status(200)
        self.headers = HeaderCollection()
        self.content_type('text/html')
        def first_write(towrite):
            """ First write flushes all """
            # ensure to do the right thing[tm] in case someone stored
            # a reference to the write method
            if self.write == first_write:
                resp_code = "%03d %s" % self._status
                headers = list(self.headers)
                self.write = start_response(resp_code, headers)
            return self.write(towrite)
        self.write = first_write

    def __getattr__(self, name):
        """
        Resolve unknown attributes

        We're looking for special env variables inserted by the middleware
        stack: ``wtf.response.<name>``. These are expected to be factories,
        which are lazily initialized with the response object and return
        the actual attribute, which is cached in the response object for
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
            factory = self.request.env['wtf.response.%s' % name]
        except KeyError:
            pass
        else:
            setattr(self, name, factory(_weakref.proxy(self)))
        return super(Response, self).__getattribute__(name)

    def status(self, status=None, reason=None):
        """
        Set/get response status

        :Parameters:
         - `status`: Response status code
         - `reason`: Reason phrase

        :Types:
         - `status`: ``int``
         - `reason`: ``str``

        :return: Tuple of previous status and reason phrase
                 (``(int, 'reason')``)
        :rtype: ``tuple``
        """
        oldstatus = self._status
        if status is not None:
            if reason is None:
                reason = http.reasons.get(status) or "Status %d" % status
            status = int(status), reason
        elif reason is not None:
            status = oldstatus[0], reason
        self._status = status
        return oldstatus

    def cookie(self, name, value, path='/', expires=None, max_age=None,
               domain=None, secure=None, comment=None, version=None,
               codec=None):
        """
        Set response cookie

        :Parameters:
         - `name`: Cookie name
         - `value`: Cookie value (if a codec is given, the type should be
           applicable for the codec encoder).
         - `path`: Valid URL base path for the cookie. It should always be set
           to a reasonable path (at least ``/``), otherwise the cookie will
           only be valid for the current URL and below.
         - `expires`: Expire time of the cookie. If unset or ``None`` the
           cookie is dropped when the browser is closed. See also the
           `max_age` parameter.
         - `max_age`: Max age of the cookie in seconds. If set, make sure it
           matches the expiry time. The difference is that expires will be
           transformed to a HTTP date, while max-age will stay an integer.
           The expires parameter is the older one and better understood by
           the clients out there. For that reason if you set max_age only,
           expires will be set automatically to ``now + max_age``. If unset
           or ``None`` the cookie will be dropped when the browser is closed.
         - `domain`: Valid domain
         - `secure`: Whether this is an SSL-only cookie or not
         - `comment`: Cookie comment
         - `version`: Cookie spec version. See `RFC 2965`_
         - `codec`: Cookie codec to apply. If unset or ``None``, the codec
           specified in the application configuration is applied.

        .. _RFC 2965: http://www.ietf.org/rfc/rfc2965.txt

        :Types:
         - `name`: ``str``
         - `value`: ``str``
         - `path`: ``str``
         - `expires`: ``datetime.datetime``
         - `max_age`: ``int``
         - `domain`: ``str``
         - `secure`: ``bool``
         - `comment`: ``str``
         - `version`: ``int``
         - `codec`: `CookieCodecInterface`
        """
        # pylint: disable = R0913

        if codec is None:
            codec = self.request.env.get('wtf.codec.cookie')
        cstring = _httputil.make_cookie(name, value, codec,
            path=path,
            expires=expires,
            max_age=max_age,
            domain=domain,
            secure=secure,
            comment=comment,
            version=version
        )
        self.headers.add('Set-Cookie', cstring)

    def content_type(self, ctype=None, charset=None):
        """
        Set/get response content type

        :Parameters:
         - `ctype`: Content-Type
         - `charset`: Charset

        :Types:
         - `ctype`: ``str``
         - `charset`: ``str``

        :return: Full previous content type header (maybe ``None``)
        :rtype: ``str``
        """
        oldtype = (self.headers.get('content-type') or [None])[0]
        if charset is not None:
            charset = '"%s"' % charset.replace('"', '\\"')
            if ctype is None:
                ctype = oldtype or 'text/plain'
                pos = ctype.find(';')
                if pos > 0:
                    ctype = ctype[:pos]
                ctype = ctype.strip()
            ctype = "%s; charset=%s" % (ctype, charset)
        if ctype is not None:
            self.headers.set('content-type', ctype)
        return oldtype

    def content_length(self, length):
        """
        Add content length information

        :Parameters:
         - `length`: The expected length in octets

        :Types:
         - `length`: ``int``
        """
        self.headers.set('Content-Length', str(length))

    def last_modified(self, last_modified):
        """
        Add last-modified information

        :Parameters:
         - `last_modified`: Last modification date (UTC)

        :Types:
         - `last_modified`: ``datetime.datetime``
        """
        self.headers.set('Last-Modified', _httputil.make_date(last_modified))

    def cache(self, expiry, audience=None):
        """
        Add cache information

        :Parameters:
         - `expiry`: Expiry time in seconds from now
         - `audience`: Caching audience; ``private`` or ``public``

        :Types:
         - `expiry`: ``int``
         - `audience`: ``str``
        """
        expiry = max(0, expiry)
        self.headers.set('Expires', _httputil.make_date(
            _datetime.datetime.utcnow() + _datetime.timedelta(seconds=expiry)
        ))
        fields = ['max-age=%s' % expiry]
        if audience in ('private', 'public'):
            fields.append(audience)
        self.headers.set('Cache-Control', ', '.join(fields))
        if expiry == 0:
            self.headers.set('Pragma', 'no-cache')

    def raise_error(self, status, **param):
        """
        Raise an HTTP error

        :Parameters:
         - `status`: Status code
         - `param`: Additional parameters for the accompanying class in
           `http_response`. The request object is passed automagically.

        :Types:
         - `status`: ``int``
         - `param`: ``dict``

        :Exceptions:
         - `KeyError`: The status code is not available
         - `HTTPResponse`: The requested HTTP exception
        """
        cls = http.classes[status]
        raise cls(self.request, **param)

    def raise_redirect(self, location, status=302):
        """
        Raise HTTP redirect

        :Parameters:
         - `location`: URL to redirect to
         - `status`: Response code

        :Types:
         - `location`: ``str``
         - `status`: ``int``

        :Exceptions:
         - `http.HTTPRedirectResponse`: The redirect exception
        """
        cls = http.classes[status]
        assert issubclass(cls, http.HTTPRedirectResponse)
        raise cls(self.request, location=location)

    def raise_basic_auth(self, realm, message=None):
        """
        Raise a 401 error for HTTP Basic authentication

        :Parameters:
         - `realm`: The realm to authenticate
         - `message`: Optional default overriding message

        :Types:
         - `realm`: ``str``
         - `message`: ``str``
        
        :Exceptions:
         - `http.AuthorizationRequired`: The 401 exception
        """
        self.raise_error(401, message=message, auth_type='Basic', realm=realm)
