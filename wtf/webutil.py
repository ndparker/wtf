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

:Variables:
 - `PIXEL`: Transparent 1x1 pixel GIF. Can be used for delivering webbugs etc.
   Usage: ``response.content_type('image/gif'); return [PIXEL]``

:Types:
 - `PIXEL`: ``str``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import re as _re
import urlparse as _urlparse

PIXEL = 'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!' \
        '\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01' \
        '\x00\x00\x02\x01D\x00;'


def escape_html(toescape, quotes=True):
    """
    Escape a string for HTML output

    :Parameters:
     - `toescape`: The string to escape
     - `quotes`: Escape quotes, too?

    :Types:
     - `toescape`: ``basestring``
     - `quotes`: ``bool``

    :return: The escaped string
    :rtype: ``basestring``
    """
    if isinstance(toescape, unicode):
        xquote, result = (u'"', u'&quot;'), toescape.replace(u'&', u'&amp;'
            ).replace(u'<', u'&lt;').replace(u'>', u'&gt;')
    else:
        xquote, result = ('"', '&quot;'), str(toescape).replace('&', '&amp;'
            ).replace('<', '&lt;').replace('>', '&gt;')
    if quotes:
        result = result.replace(*xquote)
    return result


def escape_js(toescape):
    """
    Escape a string for JS output (to be inserted into a JS string)

    The output is always of type ``str``.

    :Parameters:
      `toescape` : ``basestring``
        The string to escape

    :Return: The escaped string
    :Rtype: ``str``
    """
    if isinstance(toescape, unicode):
        result = toescape.replace(u'\\', u'\\\\').encode('unicode_escape')
    else:
        result = str(toescape).replace('\\', '\\\\').encode('string_escape')
    return result.replace("'", "\\'").replace('"', '\\"').replace('/', '\\/')


def decode_simple(value):
    """
    Return unicode version of value

    Simple heuristics: Try UTF-8 first, cp1252 then

    :Parameters:
     - `value`: The value to decode

    :Types:
     - `value`: ``str``

    :return: The decoded value
    :rtype: ``unicode``
    """
    try:
        return value.decode('utf-8')
    except UnicodeError:
        return value.decode('cp1252')


class URL(object):
    """
    URL abstraction (RFC 1738)

    :CVariables:
     - `_PARTS`: ordered list of known URL parts (available via instance
       attributes)

    :IVariables:
     - `scheme`: The URL scheme
     - `netloc`: The net location if available (or ``''``)
     - `path`: The unescaped path if available, for non-path-based schemes
       this contains the unescaped non-path ;-) (or ``''``)
     - `params`: optional unescaped path parameters (or ``''``)
     - `query`: query object
     - `fragment`: optional fragment. Strictly spoken this isn't part of URLs
       but of URL references. But who cares. (or ``''``)

    :Types:
     - `_PARTS`: ``tuple``
     - `scheme`: ``str``
     - `netloc`: ``unicode``
     - `path`: ``unicode``
     - `params`: ``unicode``
     - `query`: `Query`
     - `fragment`: ``unicode``
    """
    scheme, netloc, path, params, query, fragment = [''] * 6
    _PARTS = ('scheme', 'netloc', 'path', 'params', 'query', 'fragment')
    _PATH_SAFE = '/()=~'
    _unicode = False

    def __init__(self, url, decode=None):
        """
        Initialization

        :Parameters:
         - `url`: The url to parse. If it's an instance of this class, the
           parameters will be copied
         - `decode`: Decoder of parsed octet data

        :Types:
         - `url`: ``basestring`` or `URL`
         - `decode`: ``callable``
        """
        if isinstance(url, URL):
            for key in self._PARTS:
                setattr(self, key, getattr(url, key))
            self.query = Query(url.query)
            self._unicode = url._unicode # pylint: disable = W0212
        else:
            if decode is None:
                decode = decode_simple
            if decode:
                self._unicode = True
                if not isinstance(url, unicode):
                    url = decode(url)
            if self._unicode:
                url = url.encode('utf-8')
            for key, value in zip(self._PARTS, _urlparse.urlparse(url)):
                setattr(self, key, value)
            if not isinstance(self.netloc, unicode):
                self.netloc = decode_simple(self.netloc)
            self.netloc = self.netloc.encode('idna')
            if self._unicode:
                self.netloc = self.netloc.decode('idna')
                self.path = decode(unquote(self.path))
                self.params = decode(unquote(self.params))
                self.fragment = decode(self.fragment)
            self.query = Query(self.query, decode=decode)

    def __str__(self):
        """
        String representation, hostname idna encoded

        :return: The string representation
        :rtype: ``str``
        """
        if self._unicode:
            encode = lambda x, enc = 'utf-8': x.encode(enc)
        else:
            encode = lambda x, enc = 'utf-8': x

        return _urlparse.urlunparse((
            self.scheme,
            encode(self.netloc, 'idna'),
            quote(encode(self.path), self._PATH_SAFE),
            quote(encode(self.params), self._PATH_SAFE),
            str(self.query),
            encode(self.fragment),
        ))

    def __repr__(self):
        """
        Debug representation

        :return: The debug representation
        :rtype: ``str``
        """
        return "%s(%r)" % (self.__class__.__name__, str(self))

    def __unicode__(self):
        """
        Unicode representation, hostname as unicode (vs. idna)

        :return: The unicode representation
        :rtype: ``unicode``
        """
        if self._unicode:
            encode = lambda x, enc = 'utf-8': x.encode(enc)
            decode = lambda x: x.decode('utf-8')
        else:
            encode = lambda x, enc = 'utf-8': x
            decode = decode_simple

        return decode(_urlparse.urlunparse((
            self.scheme,
            encode(self.netloc),
            quote(encode(self.path), self._PATH_SAFE),
            quote(encode(self.params), self._PATH_SAFE),
            str(self.query),
            encode(self.fragment),
        )))

    @classmethod
    def fromcomponents(cls, path, scheme=None, netloc=None, query=None):
        """
        Create URL object from **unescaped** path

        For convenience you can optionally add query, scheme and netloc.

        :Parameters:
         - `path`: The path to create the URL from
         - `scheme`: Optional URL scheme (like ``http``)
         - `netloc`: Optional net location (like ``example.com``)
         - `query`: Optional query string (encoded) or `Query` object

        :Types:
         - `path`: ``basestring``
         - `scheme`: ``str``
         - `netloc`: ``basestring``
         - `query`: ``str``

        :return: New URL object
        :rtype: `URL`
        """
        if not isinstance(path, unicode):
            path = decode_simple(path)
        path = path.encode('utf-8')
        self = cls(quote(path, cls._PATH_SAFE))
        if scheme is not None:
            self.scheme = str(scheme)
        if netloc is not None:
            if not isinstance(netloc, unicode):
                netloc = decode_simple(netloc)
            self.netloc = netloc.encode('idna')
        if query is not None:
            self.query = Query(query)
        return self

    def copy(self):
        """
        Copy the URL

        :return: a new `URL` instance
        :rtype: `URL`
        """
        return self.__class__(self)


class Query(object):
    """
    Class for query string parsing and modification
    (stolen from svnmailer)

    :CVariables:
     - `_QUERYRE`: Regex for splitting a query string
       on possible delimiters (``&`` and ``;``)

    :Ivariables:
     - `_query_dict`: Dictionary of key->valuelist pairs
       (``{'key': ['val1', 'val2'], ...}``)
     - `_keyorder`: Original order of the keys (``['key', ...]``)
     - `_delim`: The delimiter to use for reconstructing the query string

    :Types:
     - `_QUERYRE`: ``_sre.SRE_Pattern``
     - `_query_dict`: ``dict``
     - `_keyorder`: ``list``
     - `_delim`: ``unicode``
    """
    _QUERYRE = _re.compile(r'[&;]')
    _unicode = False

    def __init__(self, query=u'', delim='&', decode=None):
        """
        Initialization

        :Parameters:
         - `query`: The query string to store
         - `delim`: The delimiter for reconstructing the query
         - `decode`: Parameter decoder

        :Types:
         - `query`: ``unicode`` or `Query`
         - `delim`: ``unicode``
         - `decode`: ``callable``
        """
        if not query:
            if decode is None or decode:
                self._unicode = True
            query_dict = {}
            keyorder = []
        elif isinstance(query, Query):
            # pylint: disable = E1103, W0212
            query_dict = dict([(key, list(val))
                for key, val in query._query_dict.items()
            ])
            keyorder = list(query._keyorder)
            self._unicode = query._unicode
        else:
            query_dict = {}
            keyorder = []
            if decode is None:
                decode = decode_simple
            if decode:
                self._unicode = True
                if not isinstance(query, unicode):
                    query = decode(query)
                query = query.encode('utf-8')
            if not decode:
                decode = lambda x: x
            for tup in [pair.split('=', 1)
                    for pair in self._QUERYRE.split(query)]:
                if len(tup) == 1:
                    key, val = decode(unquote_plus(tup[0])), None
                else:
                    key, val = map(decode, map(unquote_plus, tup))
                query_dict.setdefault(key, []).append(val)
                keyorder.append(key)

        self._keyorder = keyorder
        self._query_dict = query_dict
        self._delim = delim

    def __str__(self):
        """
        Returns the query as string again

        :return: The query as string (type depends on the input)
        :rtype: ``str``
        """
        result = []
        qdict = dict((key, list(reversed(val)))
            for key, val in self._query_dict.iteritems())
        for key in self._keyorder:
            val = qdict[key].pop()
            if self._unicode:
                key = key.encode('utf-8')
            key = quote_plus(key)
            if val is None:
                result.append(key)
            else:
                if isinstance(val, unicode):
                    val = val.encode('utf-8')
                val = quote_plus(val)
                result.append("%s=%s" % (key, val))

        return self._delim.join(result)

    def __unicode__(self):
        """ Unicode representation (just ascii decoded str() value) """
        return decode_simple(str(self))

    def __contains__(self, key):
        """
        Returns whether `key` occurs in the query as parameter name

        :Parameters:
         - `key`: The key to lookup

        :Types:
         - `key`: ``unicode``

        :return: Does `key` occur?
        :rtype: ``bool``
        """
        if self._unicode:
            key = unicode(key)
        return key in self._query_dict

    def __getitem__(self, key):
        """
        Returns the value list for parameter named `key`

        Don't modify the returned list without adjusting `_keyorder`,
        too. At best don't modify it directly at all :)

        :Parameters:
         - `key`: The key to lookup

        :Types:
         - `key`: ``unicode``

        :return: The value list (``['val1', 'val2', ...]``)
        :rtype: ``list``

        :exception KeyError: The key does not exist
        """
        if self._unicode:
            key = unicode(key)
        return tuple(self._query_dict[key])

    def __setitem__(self, key, value):
        """
        Replace all occurences of `key` with the new one

        :Parameters:
         - `key`: key to replace
         - `value`: value to set

        :Types:
         - `key`: ``unicode``
         - `value`: ``unicode``
        """
        self.remove([key])
        self.add([(key, value)])

    def replace(self, **kwargs):
        """
        Conveniently replace multiple key value pairs at once

        :Parameters:
         - `kwargs`: key value pairs (unicode/unicode)

        :Types:
         - `kwargs`: ``dict``
        """
        self.remove(kwargs.iterkeys())
        self.add(kwargs.iteritems())

    def remove(self, keys):
        """
        Removes certain parameters from the query if present

        Non-present parameters are silently ignored

        :Parameters:
         - `keys`: The names of the parameters to remove

        :Types:
         - `keys`: sequence
        """
        if self._unicode:
            keys = map(unicode, keys)
        for key in keys:
            if key in self._query_dict:
                del self._query_dict[key]
                self._keyorder = [
                    nkey for nkey in self._keyorder if nkey != key
                ]

    def add(self, toadd):
        """
        Adds certain key value pairs to the query

        :Parameters:
         - `toadd`: A sequence of key-value-pairs
           (``((u'key', u'value), ...)``)

        :Types:
         - `toadd`: ``iterable``
        """
        for key, val in toadd:
            if self._unicode:
                key = unicode(key)
            if val is not None:
                if self._unicode:
                    try:
                        val = unicode(val)
                    except ValueError:
                        pass
            self._query_dict.setdefault(key, []).append(val)
            self._keyorder.append(key)

    def modify(self, remove=None, add=None, replace=None):
        """
        Summarizes certain query modification methods

        `replace` is a convenience parameter, it's actually a combination
        of `remove` and `add`. The order of processing is:

        1. append the `replace` parameters to `remove` and `add`
        2. apply `remove`
        3. apply `add`

        :Parameters:
         - `remove`: parameters to remove (see `Query.remove`
           method)
         - `add`: parameters to add (see `Query.add` method)
         - `replace`: parameters to override (see `Query.add` for the
           format)

        :Types:
         - `remove`: sequence
         - `add`: sequence
         - `replace`: sequence
        """
        remove = list(remove or [])
        add = list(add or [])
        replace = list(replace or [])

        # append replace list to remove and add
        remove.extend([tup[0] for tup in replace])
        add.extend(replace)

        self.remove(remove)
        self.add(add)


from wtf import c_override
cimpl = c_override('_wtf_cutil')
if cimpl is not None:
    # pylint: disable = E1103
    quote = cimpl.quote
    quote_plus = cimpl.quote_plus
    unquote = cimpl.unquote
    unquote_plus = cimpl.unquote_plus
else:
    import urllib as _urllib

    def quote(s, safe='/', encoding='utf-8', errors='strict',
              _orig=_urllib.quote):
        """
        Replacement for ``urllib.quote``, which also handles unicode.

        :Parameters:
         - `s`: The string to quote
         - `safe`: safe characters (not quoted)
         - `encoding`: Encoding to apply in case `s` is unicode
         - `errors`: Error handling in case `s` is unicode

        :Types:
         - `s`: ``basestring``
         - `safe`: ``str``
         - `encoding`: ``str``
         - `errors`: ``str``

        :return: The quoted string
        :rtype: ``str``

        :Exceptions:
         - `UnicodeError`: Encoding error
        """
        # pylint: disable = C0103

        if isinstance(s, unicode):
            s = s.encode(encoding, errors)
        else:
            s = str(s)
        return _orig(s, safe)


    def quote_plus(s, safe='/', encoding='utf-8', errors='strict',
                   _orig =_urllib.quote_plus):
        """
        Replacement for ``urllib.quote_plus``, which also handles unicode.

        :Parameters:
         - `s`: The string to quote
         - `safe`: safe characters (not quoted)
         - `encoding`: Encoding to apply in case `s` is unicode
         - `errors`: Error handling in case `s` is unicode

        :Types:
         - `s`: ``basestring``
         - `safe`: ``str``
         - `encoding`: ``str``
         - `errors`: ``str``

        :return: The quoted string
        :rtype: ``str``

        :Exceptions:
         - `UnicodeError`: Encoding error
        """
        # pylint: disable = C0103

        if isinstance(s, unicode):
            s = s.encode(encoding, errors)
        else:
            s = str(s)
        return _orig(s, safe)

    unquote = _urllib.unquote
    unquote_plus = _urllib.unquote_plus

del c_override, cimpl
