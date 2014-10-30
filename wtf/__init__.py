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
===============================
 WSGI Tackling Framework (WTF)
===============================

WSGI Tackling Framework (WTF).
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"
__license__ = "Apache License, Version 2.0"
__version__ = ('0.8.22', False, 4268)


class Error(Exception):
    """ Base exception for this package """
    pass

class WtfWarning(Warning):
    """ Base warning for this package """

    @classmethod
    def emit(cls, message, stacklevel=1):
        """ Emit a warning of this very category """
        import warnings as _warnings
        _warnings.warn(message, cls, max(1, stacklevel) + 1)


def _extendquotes(envkey=None):
    """ Extend _urllib.quote and _urllib.quote_plus

    :Parameters:
     - `envkey`: The environment key to lookup. If this key is set and ``1``
       the charset definition won't be fixed and this function is a no-op.
       If unset or ``None``, no lookup is made.

    :Types:
     - `envkey`: ``str``
    """
    import os
    if envkey is not None and os.environ.get(envkey) == '1':
        return

    import urllib
    from wtf import webutil
    urllib.quote = webutil.quote
    urllib.quote_plus = webutil.quote_plus
    urllib.unquote = webutil.unquote
    urllib.unquote_plus = webutil.unquote_plus


def _fixcp1252(envkey=None):
    """
    Fixup cp1252 codec in order to use it as a real superset of latin-1

    :Parameters:
     - `envkey`: The environment key to lookup. If this key is set and ``1``
       the charset definition won't be fixed and this function is a no-op.
       If unset or ``None``, no lookup is made.

    :Types:
     - `envkey`: ``str``
    """
    import os
    if envkey is not None and os.environ.get(envkey) == '1':
        return

    import codecs
    from encodings import cp1252

    try:
        dmap = cp1252.decoding_map # pylint: disable = E1101
    except AttributeError:
        dtable = list(cp1252.decoding_table)
        codepoint = 0
        try:
            while True:
                codepoint = dtable.index(u'\ufffe', codepoint)
                dtable[codepoint] = unichr(codepoint)
        except ValueError:
            # no more undefined points there
            pass
        dtable = u''.join(dtable)
        cp1252.decoding_table = dtable
        cp1252.encoding_table = codecs.charmap_build(dtable)
    else:
        # Python 2.4
        for key, value in dmap.iteritems():
            if value is None:
                dmap[key] = key
        cp1252.encoding_map = codecs.make_encoding_map(dmap)


def _register_defaults(envkey=None):
    """
    Register default

    :Parameters:
     - `envkey`: The environment key to lookup. If this environment variable
       is set and ``1`` nothing will be registered and and this function
       is a no-op. If unset or ``None``, no lookup is made.

    :Types:
     - `envkey`: ``str``
    """
    import os
    if envkey is not None and os.environ.get(envkey) == '1':
        return

    from wtf.opi import register, daemon
    register('daemon', daemon.DaemonOPI)

    from wtf.opi.worker import register, threaded, single
    register('threaded', threaded.ThreadedWorker)
    register('single', single.SingleWorker)

    from wtf.impl import register, scgi, http
    register('scgi', scgi.SCGIServer)
    register('http', http.HTTPServer)


def c_override(envkey=None):
    """
    Factory for creating a module factory

    :Parameters:
     - `envkey`: Name of the environment variable which has to be "1" in
       order to disable the C override.

    :Types:
     - `envkey`: ``str``

    :return: Module factory function
    :rtype: ``callable``
    """
    import os
    enabled = envkey is None or os.environ.get(envkey) != '1'
    if enabled:
        def module_factory(modname):
            """
            Module factory

            :Parameters:
             - `modname`: dotted module name relative to the wtf package

            :Types:
             - `modname`: ``str``

            :return: The imported module or ``None`` on import disabled or
                     error
            :rtype: ``module``
            """
            try:
                mod = __import__(
                    'wtf.%s' % modname, globals(), locals(), ['*']
                )
            except ImportError:
                mod = None
            return mod
    else:
        def module_factory(modname):
            """
            Module factory

            :Parameters:
             - `modname`: dotted module name relative to the wtf package

            :Types:
             - `modname`: ``str``

            :return: The imported module or ``None`` on import disabled or
                     error
            :rtype: ``module``
            """
            # pylint: disable = W0613

            return None
    module_factory.enabled = enabled # pylint: disable = W0612
    return module_factory


c_override = c_override('WTF_NO_C_OVERRIDE')
_fixcp1252('WTF_NO_CP1252_OVERRIDE')
_extendquotes('WTF_NO_QUOTE_OVERRIDE')
_register_defaults('WTF_NO_REGISTER_DEFAULT')

from wtf import util as _util

#: Version of the package
#:
#: :Type: `wtf.util.Version`
version = _util.Version(*__version__)

__all__ = _util.find_public(globals())
del _util
