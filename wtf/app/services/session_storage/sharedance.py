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
Sharedance session storage
==========================

This storage uses sharedance_ as session storage.

.. _sharedance: http://sharedance.pureftpd.org/project/sharedance
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import datetime as _datetime
import os as _os
import sys as _sys
try:
    import cPickle as _pickle
except ImportError:
    import pickle as _pickle

from wtf import Error
from wtf import httputil as _httputil
from wtf import util as _util
from wtf.app.services import session as _session
from wtf.ext import sharedance as _sharedance


class SharedanceError(Error):
    """ Sharedance communication error """


class SessionCookieCodec(object):
    """ Session ID storing cookie """
    __implements__ = [_httputil.CookieCodecInterface]

    def __init__(self, signkey):
        """
        Initialization

        :Parameters:
         - `signkey`: Signation key (or ``None``)

        :Types:
         - `signkey`: ``str``
        """
        self._signkey = signkey

    def encode(self, value):
        """ Identity encoding (str->str) with signature """
        if self._signkey:
            from Crypto.Hash import HMAC
            value = _sharedance.escape(
                HMAC.new(self._signkey, value).digest()[:8]
            ) + value
        return value

    def decode(self, value):
        """ Identity decoding (str->str) with integrity checking """
        if self._signkey:
            sign, value = value[:11], value[11:] # 11 = 8 * 4/3 - padding
            from Crypto.Hash import HMAC
            if _sharedance.escape(
                    HMAC.new(self._signkey, value).digest()[:8]) != sign:
                raise ValueError()
        return value


class BoundSharedanceStorage(object):
    """
    Sharedance storage implementation

    :See: `wtf.app.services.session.StorageInterface`
    """
    _SIDLEN = 40

    __implements__ = [_session.StorageInterface]
    has_cookie, _need_cookie, _need_store = True, False, False
    _sid, _store = None, None

    def __init__(self, sharedance, cookie, refresh, init):
        """
        Initialization

        :Parameters:
         - `sharedance`: Sharedance object
         - `cookie`: Cookie configuration or ``None``
         - `init`: Initialization function (takes self as argument)

        :Types:
         - `sharedance`: `Sharedance`
         - `cookie`: ``dict``
         - `init`: ``callable``
        """
        self._sharedance = sharedance
        self.cookie = cookie.copy()
        self.codec = self.cookie['codec'] = \
            SessionCookieCodec(self.cookie.pop('sign'))

        init(self)

        key, now = '___next_cookie__', _datetime.datetime.utcnow()
        if key not in self._store or self._store[key] < now:
            self._need_store, self._store[key] = \
                True, now + _datetime.timedelta(seconds=refresh)
            if self.cookie['max_age']:
                self._need_cookie = True

    @classmethod
    def from_request(cls, sharedance, cookie, refresh, request):
        """ Create bound storage from request """
        def init(self):
            """ Load session from request """
            if request is not None:
                cookies = request.cookie(self.codec).multi(
                    self.cookie['name']
                )
                for sid in cookies:
                    if self.create_existing(sid):
                        return
            self.create_new()
        return cls(sharedance, cookie, refresh, init)

    @classmethod
    def from_sid(cls, sharedance, cookie, refresh, sid):
        """ Create bound storage from sid """
        def init(self):
            """ Load session from sid """
            if not self.create_existing(sid):
                self.create_new()
        return cls(sharedance, cookie, refresh, init)

    def create_existing(self, sid):
        """ Create session from existing one """
        data = None
        try:
            data = self._sharedance.fetch(sid)
        except KeyError:
            pass
        except _sharedance.SharedanceError, e:
            print >> _sys.stderr, "Sharedance: %s" % str(e)
        if data is None:
            return False

        try:
            store = _pickle.loads(data)
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            return False

        store['__id__'] = sid
        store['__is_new__'] = False
        self._sid, self._store = sid, store
        return True

    def create_new(self):
        """ Create new empty session """
        while True:
            sid = self._gensid()
            if 0:
                # Race condition here, but there's no better way :/
                try:
                    self._sharedance.fetch(sid)
                    continue
                except KeyError:
                    pass
                except _sharedance.SharedanceError, e:
                    print >> _sys.stderr, "Sharedance: %s" % str(e)
            break
        self._need_cookie, self._sid = True, sid
        self._store = {'__id__': sid, '__is_new__': True}

    def _gensid(self):
        """ Generate a random session ID """
        numbytes, rest = divmod(self._SIDLEN * 3, 4)
        numbytes += int(bool(rest))
        return _sharedance.escape(_os.urandom(numbytes))[:self._SIDLEN]

    def set(self, name, value):
        """ :See: `wtf.app.services.session.StorageInterface.set` """
        self._store[name] = value

    def get(self, name):
        """ :See: `wtf.app.services.session.StorageInterface.get` """
        return self._store[name]

    def delete(self, name):
        """ :See: `wtf.app.services.session.StorageInterface.delete` """
        del self._store[name]

    def contains(self, name):
        """ :See: `wtf.app.services.session.StorageInterface.contains` """
        return name in self._store

    def need_cookie(self):
        """ :See: `wtf.app.services.session.StorageInterface.need_cookie` """
        return self._need_cookie

    def need_store(self):
        """ :See: `wtf.app.services.session.StorageInterface.need_store` """
        return self._need_store

    def make_cookie(self):
        """ :See: `wtf.app.services.session.StorageInterface.make_cookie` """
        return _httputil.make_cookie(value=self._sid, **self.cookie)

    def store_back(self):
        """ :See: `wtf.app.services.session.StorageInterface.store_back` """
        try:
            store = self._store.copy()
            if '__id__' in store:
                del store['__id__']
            if '__is_new__' in store:
                del store['__is_new__']
            self._sharedance.store(self._sid, _pickle.dumps(store))
        except _sharedance.SharedanceError, e:
            print >> _sys.stderr, "Sharedance: %s" % str(e)

    def wipe(self):
        """ :See: `wtf.app.services.session.StorageInterface.wipe` """
        try:
            if '__new__' not in self._store:
                self._sharedance.delete(self._sid)
            return True
        except _sharedance.SharedanceError, e:
            print >> _sys.stderr, "Sharedance: %s" % str(e)
        return False


class SharedanceStorage(object):
    """
    Sharedance storage factory

    :See: `session.StorageFactoryInterface`

    :CVariables:
     - `_DEFAULT_HOST`: Default session server host
     - `_DEFAULT_TIMEOUT`: Default session server timeout

    :Types:
     - `_DEFAULT_HOST`: ``str``
     - `_DEFAULT_TIMEOUT`: ``float``
    """
    __implements__ = [_session.StorageFactoryInterface]
    _DEFAULT_HOST = 'localhost'
    _DEFAULT_TIMEOUT = 10.0

    def __init__(self, config, opts, args):
        """ :See: `session.StorageFactoryInterface.__init__` """
        # pylint: disable = E1103, R0912, R0915
        try:
            section = config['session:sharedance']
        except KeyError:
            section = dict()

        if 'timeout' in section:
            timeout = max(0.0, float(section.timeout))
        else:
            timeout = self._DEFAULT_TIMEOUT

        if 'weight' in section:
            weight = max(0, int(section.weight))
        else:
            weight = 1

        if 'compress_threshold' in section:
            compress_threshold = unicode(section.compress_threshold) and \
                int(section.compress_threshold) or None
        else:
            compress_threshold = 128

        if 'server' in section:
            servers = []
            for spec in section.server:
                key = 'session:sharedance %s' % spec
                spec = _util.parse_socket_spec(unicode(spec),
                    default_port=_sharedance.DEFAULT_PORT)
                if key in config:
                    subtimeout = \
                        max(0.0, float(config[key]('timeout', timeout)))
                    subweight = max(0, int(config[key]('weight', weight)))
                else:
                    subtimeout, subweight = timeout, weight
                servers.append(_sharedance.SharedanceConnector(
                    spec, compress_threshold=compress_threshold,
                    timeout=subtimeout, weight=subweight, magic=True
                ))
        else:
            servers = [_sharedance.SharedanceConnector(
                (self._DEFAULT_HOST, _sharedance.DEFAULT_PORT),
                compress_threshold=compress_threshold,
                timeout=timeout, weight=1, magic=True
            )]

        self._sd = _sharedance.Sharedance(servers)

        if 'refresh' in section:
            refresh = unicode(section.refresh)
        else:
            refresh = u'auto'
        if refresh == u'auto':
            self._refresh = 60
        else:
            self._refresh = int(refresh)

        if 'cookie' in section:
            cookie = section.cookie
        else:
            cookie = dict().get
        sign = cookie('sign', u'') or None
        if sign:
            sign = sign.encode('ascii').decode('base64')
        domain = cookie('domain', u'') or None
        if domain:
            if domain.startswith(u'.'):
                domain = (u'x' + domain).encode('idna')[1:]
            else:
                domain = domain.encode('idna')
        self._cookie = dict(
            name=cookie('name', u's').encode('ascii'),
            max_age=int(cookie('max_age', 0)) or None,
            path=unicode(cookie('path', u'/')).encode('ascii'),
            domain=domain,
            sign=sign,
        )

    def __call__(self, request):
        """ :See: `session.StorageFactoryInterface.__call__` """
        return BoundSharedanceStorage.from_request(
            self._sd, self._cookie, self._refresh, request
        )

    def from_sid(self, sid):
        """ :See: `session.StorageFactoryInterface.from_sid` """
        return BoundSharedanceStorage.from_sid(
            self._sd, self._cookie, self._refresh, sid
        )

    def status(self):
        """ :See: `session.StorageFactoryInterface.status` """
        checks = self._sd.check()
        for check in checks:
            check['time'] //= 1000
        return checks
