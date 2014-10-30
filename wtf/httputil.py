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
HTTP utilities
==============

This module implements various common HTTP utilities.

:Variables:
 - `CR`: ASCII CR byte (\\r)
 - `LF`: ASCII LF byte (\\n)
 - `CRLF`: ASCII CRLF sequence (\\r\\n)

:Types:
 - `CR`: ``str``
 - `LF`: ``str``
 - `CRLF`: ``str``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import re as _re

from wtf import Error

CR = "\x0D"
LF = "\x0A"
CRLF = CR + LF


class HeaderError(Error):
    """ Base header parse error """

class InvalidHeaderLine(HeaderError):
    """ A header line is invalid """

class IncompleteHeaders(HeaderError):
    """ The headers are incomplete """


def make_date(stamp=None, cookie=False):
    """
    Make a HTTP date

    :Parameters:
     - `stamp`: The UTC timestamp to process. If omitted or ``None``, the
       current time is taken

    :Types:
     - `stamp`: ``datetime.datetime``

    :return: The HTTP date string
    :rtype: ``str``
    """
    self = make_date
    if stamp is None:
        stamp = _datetime.datetime.utcnow()
    return stamp.strftime(
        "%%(wday)s, %d%%(sep)s%%(month)s%%(sep)s%Y %H:%M:%S GMT"
    ) % {
        'wday': self.wdays[stamp.weekday()], # pylint: disable = E1101
        'month': self.months[stamp.month], # pylint: disable = E1101
        'sep': [' ', '-'][bool(cookie)],
    }
make_date.wdays = ( # pylint: disable = W0612
    'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'
)
make_date.months = (None, # pylint: disable = W0612
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
)


def read_headers(stream):
    """
    Read MIME headers from stream

    :Parameters:
     - `stream`: The stream to read from

    :Types:
     - `stream`: ``file``

    :return: Dictionary of lists of headers (``{'name': ['val', ...], ...}``)
    :rtype: ``dict``

    :Exceptions:
     - `httputil.InvalidHeaderLine`: Unparsable header line
     - `httputil.IncompleteHeaders`: Stream ended before the final empty line
    """
    headers = {}
    self, name, values = read_headers, None, None
    while True:
        line = stream.readline()
        if not line:
            raise IncompleteHeaders("Headers not completed")
        line = line[:-1 - line.endswith(CRLF)]
        if self.CONT_MATCH(line): # pylint: disable = E1101
            if name is None:
                raise InvalidHeaderLine(
                    "Continuation line without line to continue")
            values.append(line.lstrip())
            continue
        elif name is not None:
            headers.setdefault(name.lower(), []
                ).append(" ".join(values))
        if not line: # empty separator line, finished reading
            break
        match = self.HEADER_MATCH(line) # pylint: disable = E1101
        if not match:
            raise InvalidHeaderLine("Invalid header line format")
        name, value = match.group('name', 'value')
        values = [value]
    return headers

read_headers.CONT_MATCH = _re.compile(r'\s').match # pylint: disable = W0612
# token chars from rfc 2616:
#    ''.join(c for c in map(chr, range(33, 127))
#    if c not in '()<>@,;:\\"/[]?={}')
read_headers.HEADER_MATCH = _re.compile( # pylint: disable = W0612
    r'''(?P<name>[-!#$%&'*+.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'''
    r'''^_`abcdefghijklmnopqrstuvwxyz|~]+)\s*:\s*(?P<value>.*)$''',
_re.X).match


class CookieCodecInterface(object):
    """ Interface for Cookie codecs """

    def encode(self, value):
        """
        Encode the cookie value to a 7bit US-ASCII string

        This method is also responsible for quoting the value if necessary.

        :Parameters:
         - `value`: The value to encode

        :Types:
         - `value`: any

        :return: The encoded value
        :rtype: ``str``
        """

    def decode(self, value):
        """
        Decode the cookie value from 7bit US-ASCII string

        :Parameters:
         - `value`: The cookie string (as submitted)

        :Types:
         - `value`: ``str``

        :return: The decoded value
        :rtype: any

        :Exceptions:
         - `ValueError`: The value could not be decoded properly
        """


class CookieMaker(object):
    """
    Cookie maker helper class

    :CVariables:
     - `UNSAFE_SEARCH`: Unsafe character search function
     - `_ATTR`: Attribute spelling and type getter
     - `KEYS`: Valid attribute keys

    :IVariables:
     - `_encode`: Value encoder

    :Types:
     - `UNSAFE_SEARCH`: ``callable``
     - `_ATTR`: ``callable``
     - `KEYS`: ``tuple``
     - `_encode`: ``callable``
    """
    UNSAFE_SEARCH = _re.compile(r"[^a-zA-Z\d!#$%&'*+.^_`|~-]").search
    _ATTR = dict(
        expires=("expires", 'date'),
        path=   ("Path",    'ustring'),
        comment=("Comment", 'string'),
        domain= ("Domain",  'ustring'),
        max_age=("Max-Age", 'int'),
        secure= ("secure",  'bool'),
        version=("Version", 'string'),
    )
    KEYS = tuple(sorted(_ATTR.keys()))
    _ATTR = _ATTR.get

    def __init__(self, codec=None):
        """
        Initialization

        :Parameters:
         - `codec`: Cookie codec to apply. If unset or ``None``, an identity
           codec is applied (leaving 8bit chars as-is)

        :Types:
         - `codec`: `CookieCodecInterface`
        """
        if codec is None:
            encode = lambda x: x
        else:
            encode = codec.encode
        self._encode = encode

    def __call__(self, name, value, **kwargs):
        """
        Create the cookie string

        Cookie parameters are given in kwargs. Valid keys are listed in
        `KEYS`. ``None``-values are ignored. Here are short descriptions of
        the valid parameters:

        ``comment``
          Cookie comment (``str``)
        ``domain``
          Valid domain (``str``)
        ``expires``
          Expire time of the cookie (``datetime.datetime``). If unset
          or ``None`` the cookie is dropped when the browser is closed.
          See also the ``max_age`` keyword.
        ``max_age``
          Max age of the cookie in seconds (``int``). If set, make sure it
          matches the expiry time. The difference is that expires will be
          transformed to a HTTP date, while max-age will stay an integer.
          The expires parameter is the older one and better understood by
          the clients out there. For that reason if you set max_age only,
          expires will be set automatically to ``now + max_age``. If unset
          or ``None`` the cookie will be dropped when the browser is closed.
        ``path``
          Valid URL base path for the cookie. It should always be set to a
          reasonable path (at least ``/``), otherwise the cookie will only
          be valid for the current URL and below.
        ``secure``
          Whether this is an SSL-only cookie or not (``bool``)
        ``version``
          Cookie spec version (``int``). See `RFC 2965`_
        
        .. _RFC 2965: http://www.ietf.org/rfc/rfc2965.txt

        :Parameters:
         - `name`: Cookie name
         - `value`: Cookie value (if a codec was given, the type should be
           applicable for the codec encoder).
         - `kwargs`: Cookie parameters

        :Types:
         - `name`: ``str``
         - `value`: ``str``
         - `kwargs`: ``dict``

        :return: The cookie string
        :rtype: ``str``

        :Exceptions:
         - `ValueError`: Invalid name or values given
         - `TypeError`: Unrecognized attributes given
        """
        if self.UNSAFE_SEARCH(name):
            raise ValueError("%r is unsafe as key" % (name,))
        elif name.lower().replace('-', '_') in self.KEYS:
            raise ValueError("%s is a reserved attribute and cannot be used "
                "as name" % (name,))
        items = ["%s=%s" % (str(name), str(self._encode(value)))]
        if kwargs.get('max_age') is not None:
            kwargs['max_age'] = max(0, kwargs['max_age'])
            if kwargs.get('expires') is None:
                kwargs['expires'] = (
                    _datetime.datetime.utcnow() +
                    _datetime.timedelta(seconds=kwargs['max_age'])
                )

        for key in self.KEYS:
            if key in kwargs:
                val = kwargs.pop(key)
                if val is not None:
                    key, translator = self._ATTR(key)
                    value = getattr(self, '_' + translator)(key, val)
                    if value is not None:
                        items.append(str(value))
        if kwargs:
            raise TypeError("Unrecognized keywords: %r" % (kwargs.keys(),))
        return "; ".join(item for item in items if item is not None)

    @staticmethod
    def _date(key, value):
        """ Date translator """
        return "%s=%s" % (key, make_date(value, cookie=True))

    @staticmethod
    def _int(key, value):
        """ Integer translator """
        return "%s=%d" % (key, int(value))

    @staticmethod
    def _bool(key, value):
        """ Boolean translator """
        if value:
            return key
        return None

    def _string(self, key, value):
        """ String translator """
        return "%s=%s" % (key, self._encode(value))

    @staticmethod
    def _ustring(key, value):
        """ Unquoted string translator """
        return "%s=%s" % (key, value)


def make_cookie(name, value, codec=None, **kwargs):
    """
    Make a cookie

    The is a simple interface to the `CookieMaker` class. See there for
    detailed information.

    :Parameters:
     - `name`: Cookie name
     - `value`: Cookie value
     - `codec`: Value codec. If unset or ``None``, the identity codec is
       applied.
     - `kwargs`: Cookie attributes

    :Types:
     - `name`: ``str``
     - `value`: ``str``
     - `codec`: `CookieCodecInterface`
     - `kwargs`: ``dict``

    :return: The cookie string
    :rtype: ``str``

    :Exceptions:
     - `ValueError`: Invalid name or values given
     - `TypeError`: Unrecognized attributes given
    """
    return CookieMaker(codec)(name, value, **kwargs)
