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
Request object
==============

This module implements a request object.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import itertools as _it
import re as _re

from wtf import httputil as _httputil


class CookieCodecFactoryInterface(object):
    """ Interface for cookie codec factories """

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

    def __call__(self):
        """
        Create the codec instance (doesn't have to be a new one)

        :return: The codec instance
        :rtype: `CookieCodecInterface`
        """


class BaseCookieCodec(object):
    """
    Base class for some codecs

    :CVariables:
     - `_UNSAFE_SEARCH`: Unsafe char detection function

    :Types:
     - `_UNSAFE_SEARCH`: ``callable``
    """
    __implements__ = [
        CookieCodecFactoryInterface, _httputil.CookieCodecInterface
    ]
    UNSAFE_SEARCH = _httputil.CookieMaker.UNSAFE_SEARCH

    def __init__(self, config, opts, args):
        """ Initialization """
        pass

    def __call__(self):
        """ Determine codec instance """
        return self

    def quote(self, value):
        """
        Quote a value if necessary

        :Parameters:
         - `value`: The value to inspect

        :Types:
         - `value`: ``str``

        :return: The quoted value (or the original if no quoting is needed)
        :rtype: ``str``
        """
        if self.UNSAFE_SEARCH(value):
            return '"%s"' % value.replace('"', '\\"')
        return value

    def unquote(self, value):
        """
        Unquote a value if applicable

        :Parameters:
         - `value`: The value to inspect

        :Types:
         - `value`: ``str``

        :return: The unquoted value (or the original if no unquoting is needed)
        :rtype: ``str``
        """
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1].replace('\\"', '"')
        return value

    def encode(self, value):
        """ Encode the cookie value """
        raise NotImplementedError()

    def decode(self, value):
        """ Decode the cookie value """
        raise NotImplementedError()


class DefaultCookie(BaseCookieCodec):
    """
    Standard python behaviour

    :CVariables:
     - `_TRANS`: Translation getter
     - `_UNTRANS`: Untranslation substituter

    :Types:
     - `_TRANS`: ``callable``
     - `_UNTRANS`: ``callable``
    """
    _TRANS = dict([('\\', '\\\\')] + [(chr(_key), "\\%03o" % _key)
        for _key in _it.chain(xrange(32), xrange(127, 256))
    ]).get
    _UNTRANS = _re.compile(r'\\([0-3][0-7][0-7])').sub
    del _key # pylint: disable = W0631

    def encode(self, value):
        """ Encode a cookie value """
        if self.UNSAFE_SEARCH(value):
            value = ''.join(map(self._TRANS, value, value))
        return self.quote(value)

    def decode(self, value):
        """ Decode a cookie value """
        return self._UNTRANS(self._untranssub, self.unquote(value))

    @staticmethod
    def _untranssub(match):
        """ Translate octal string back to number to char """
        return chr(int(match.group(1), 8))


class UnicodeCookie(BaseCookieCodec):
    """
    Unicode cookies

    The codecs takes and gives unicode, translates them using the
    ``unicode_escape`` codec.
    """

    def encode(self, value):
        """ Encode a cookie value """
        return self.quote(unicode(value).encode('unicode_escape'))

    def decode(self, value):
        """ Decode a cookie value """
        return self.unquote(value).decode('unicode_escape')
