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
==============
 Memcache API
==============

This module implements a memcache API implementation and connector.

:Variables:
 - `DEFAULT_PORT`: Memcache default port
 - `CRLF`: CRLF sequence, which finishs most of memcache's commands
 - `STATE_GRACE`: Dead state "grace"
 - `STATE_RETRY`: Dead state "retry"
 - `FLAG_COMPRESSED`: Flag for compressed storage
 - `FLAG_PADDED`: Flag for padded storage
 - `FLAG_SPLIT`: Flag for split storage
 - `NO_FLAGS`: Bit mask for checking invalid flag bits
 - `TYPEMAP`: Type map (id -> codec)

:Types:
 - `DEFAULT_PORT`: ``int``
 - `CRLF`: ``str``
 - `STATE_GRACE`: ``int``
 - `STATE_RETRY`: ``int``
 - `FLAG_COMPRESSED`: ``int``
 - `FLAG_PADDED`: ``int``
 - `FLAG_SPLIT`: ``int``
 - `NO_FLAGS`: ``int``
 - `TYPEMAP`: ``dict``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

try:
    import cPickle as _pickle
except ImportError:
    import pickle as _pickle
import itertools as _it
try:
    import hashlib as _md5
except ImportError:
    import md5 as _md5
import os as _os
import socket as _socket
import threading as _threading
import time as _time
import weakref as _weakref
try:
    import zlib as _zlib
except ImportError:
    _zlib = None

from wtf import Error
from wtf import osutil as _osutil
from wtf import stream as _stream
from wtf import util as _util

DEFAULT_PORT = 11211
CRLF = "\r\n"
STATE_GRACE, STATE_RETRY = xrange(2)

# python hash() differs between 32bit and 64bit!
hashfunc = _util.hash32


# 8 bits for the type
# 8 bits for the flags
#
# ...RNING WARNING WARNING WARNING WARNING WARNING WARNING WARNING WARN...
#   Do not change the order of the types - otherwise already stored stuff
#   from a memcache will result in crap. New types (up to 255) can be
#   added at the end of the list.
#
#   The first one is the fallback (pickle).
#
# ...ING WARNING WARNING WARNING WARNING WARNING WARNING WARNING WARNIN...
TYPEMAP = dict(enumerate((
    # name, encoder, decoder
    (None, lambda x: _pickle.dumps(x, -1), _pickle.loads),
    (unicode,
        lambda x: x.encode('utf-8'),
        lambda x: x.decode('utf-8'),
    ),
    (str, str, str),
    (bool,
        lambda x: x and "1" or "",
        bool,
    ),
    (int, str, int),
    (long, str, long),
)))

FLAG_COMPRESSED = 256 # 2 **  8
FLAG_PADDED = 512     # 2 **  9
FLAG_SPLIT = 1024     # 2 ** 10
NO_FLAGS = ~(FLAG_COMPRESSED | FLAG_PADDED | FLAG_SPLIT)


class MemcacheError(Error):
    """ Memcache communication error """

class MemcacheConnectError(MemcacheError):
    """ Memcache connect error """

class CommandError(MemcacheError):
    """ Unrecognized command """

class ClientError(MemcacheError):
    """ Invalid command line """

class ServerError(MemcacheError):
    """ Server error """

class UnknownError(MemcacheError):
    """ Unknown error from the server """


class Memcache(object):
    """
    Memcache cluster proxy

    :CVariables:
     - `DEFAULT_GRACE_TIME`: Default grace time in seconds. See `__init__` for
       further details.
     - `DEFAULT_RETRY_TIME`: Default retry time in seconds. See `__init__` for
       details.
     - `DEFAULT_COMPRESS_THRESHOLD`: Default minimum size for compressing
       values
     - `DEFAULT_PADDED`: Default padding behavior
     - `DEFAULT_SPLIT`: Default splitting behaviour
     - `DEFAULT_LARGEST_SLAB`: Default maximum slab size
     - `_TYPEMAP`: typemap

    :IVariables:
     - `_pools`: List of available pools
     - `_weighted`: Weighted list of available pools
     - `_grace_time`: Grace time for this instance
     - `_retry_time`: Retry time for this instance
     - `_compress_threshold`: Minimal size for compression
     - `_padded`: Pad small values (<16 byte)?
     - `_split`: Allow large value splitting?
     - `_prefix`: Key prefix to use
     - `_largest_slab`: Largest SLAB size

    :Types:
     - `DEFAULT_GRACE_TIME`: ``int``
     - `DEFAULT_RETRY_TIME`: ``int``
     - `DEFAULT_COMPRESS_THRESHOLD`: ``int``
     - `DEFAULT_PADDED`: ``bool``
     - `DEFAULT_SPLIT`: ``bool``
     - `DEFAULT_LARGEST_SLAB`: ``int``
     - `_TYPEMAP`: ``dict``
     - `_pools`: ``tuple``
     - `_weighted`: ``tuple``
     - `_grace_time`: ``int``
     - `_retry_time`: ``int``
     - `_compress_threshold`: ``int``
     - `_padded`: ``bool``
     - `_split`: ``bool``
     - `_prefix`: ``str``
     - `_largest_slab`: ``int``
    """
    DEFAULT_GRACE_TIME = 30
    DEFAULT_RETRY_TIME = 60
    DEFAULT_COMPRESS_THRESHOLD = 128
    DEFAULT_PADDED = True
    DEFAULT_SPLIT = True
    DEFAULT_LARGEST_SLAB = 1048576 # POWER_BLOCK in slabs.c
    _TYPEMAP = TYPEMAP

    def __init__(self, pools, prepare=None, grace_time=None, retry_time=None,
                 compress_threshold=None, padded=None, split=None,
                 prefix=None, largest_slab=None):
        """
        Initialization

        `grace_time` and `retry_time` describe the behaviour of
        the dispatcher in case one or more dead pools. The algorithm works
        as follows:

        If a server is detected to be unreachable, it is marked dead. Now the
        grace counter starts to run. Now if the server stays dead until
        `grace_time` is reached requests for the server (read and write) are
        discarded. This gives short memcache outages (like restarts)
        a chance to recover without adding load to the other caches
        of the cluster. However, when the grace time threshold is reached,
        the server is considered completely dead and the requests are
        dispatched to the other ones. The now completely-declared-dead
        server will be retried every `retry_time` seconds from now on until
        it's vivified again.

        :Parameters:
         - `pools`: List of memcache connection pools
           (``[MemcacheConnectionPool, ...]``)
         - `prepare`: Key preparation function
         - `grace_time`: Grace time in seconds
         - `retry_time`: Retry time in seconds
         - `compress_threshold`: Minimum size for compression. If omitted or
           ``None``, `DEFAULT_COMPRESS_THRESHOLD` is applied.
         - `padded`: Pad small values (< 16 byte)? If omitted or ``None``,
           `DEFAULT_PADDED` is applied
         - `split`: Split large values? If omitted or ``None``,
           `DEFAULT_SPLIT` is applied
         - `prefix`: Prefix for keys. Empty by default
         - `largest_slab`: Largest SLAB item size of the server, if omitted or
           ``None``, `DEFAULT_LARGEST_SLAB` is applied.

        :Types:
         - `pools`: ``iterable``
         - `prepare`: ``callable``
         - `grace_time`: ``int``
         - `retry_time`: ``int``
         - `compress_threshold`: ``int``
         - `padded`: ``bool``
         - `split`: ``bool``
         - `prefix`: ``str``
         - `largest_slab`: ``int``
        """
        # Key config
        if prepare is None:
            if prefix:
                prepare = lambda x: prefix + x
            else:
                prepare = lambda x: x
        elif prefix:
            _prepare = prepare
            prepare = lambda x: prefix + _prepare(x)
        self._prepare_key = prepare

        # Value config
        if compress_threshold is None:
            compress_threshold = self.DEFAULT_COMPRESS_THRESHOLD
        self._compress_threshold = compress_threshold
        self._padded = padded
        self._split = split
        self._largest_slab = \
            [largest_slab, self.DEFAULT_LARGEST_SLAB][largest_slab is None]

        # Pool config
        self._pools = tuple(pools)
        self._weighted = tuple(_it.chain(*[[pool] * pool.weight
            for pool in self._pools]))
        self._grace_time = int(
            [grace_time, self.DEFAULT_GRACE_TIME][grace_time is None])
        self._retry_time = int(
            [retry_time, self.DEFAULT_RETRY_TIME][retry_time is None])

    def delete(self, key, block_time=None, all_pools=False):
        """
        Delete a key/value pair from the cache

        :Parameters:
         - `key`: The key to identify the item to delete
         - `block_time`: Time to block add and replace requests for this key
           in seconds. If omitted or ``None``, the blocking time is ``0``.
         - `all_pools`: Issue delete to each pool? This may be useful to
           enforce the deletion on backup pools, too. However, it won't
           delete the key from currently dead pools. So, it might be not
           that useful after all, but it's the best we can do from this
           side of the ocean.

        :Types:
         - `key`: ``str``
         - `block_time`: ``int``
         - `all_pools`: ``bool``

        :return: Whether it was really deleted from the main pool (or the
                 current backup pool) of this key (i.e. whether it existed
                 before)
        :rtype: ``bool``
        """
        result = False
        key = self._prepare_key(key)
        block_time = max(0, int(block_time or 0))
        mainpool = None
        try:
            conns = self._get_conn(key)
            if conns is not None:
                try:
                    conn = conns.keys()[0]
                    mainpool = conn.pool
                    conn.write("delete %s %s%s" % (key, block_time, CRLF))
                    conn.flush()
                    line = self._error(conn.readline())
                finally:
                    conns = conns.keys()
                    while conns:
                        conns.pop().close()
                result = line == "DELETED"
        except _socket.error:
            pass

        if all_pools:
            for pool in self._pools:
                if pool == mainpool or pool.dead:
                    continue
                try:
                    conn = pool.get_conn()
                    try:
                        conn.write("delete %s %s%s" % (key, block_time, CRLF))
                        conn.flush()
                        conn.readline() # don't care about the response
                    finally:
                        conn.close()
                except _socket.error:
                    pass
        return result

    def get(self, *keys):
        """
        Get a list of key/value pairs from the cache (if applicable)

        The returned dict contains all pairs it could get. But keys maybe
        missing or the dict might be completely empty (of course).

        :Parameters:
         - `keys`: The keys to fetch

        :Types:
         - `keys`: ``tuple``

        :return: The dict of key/value pairs
        :rtype: ``dict``
        """
        # pylint: disable = R0912, R0915

        result = {}
        if not keys:
            return result
        keymap = dict((self._prepare_key(key), key) for key in keys)
        try:
            conns = self._get_conn(*keymap.keys())
            if not conns:
                return result
            conns = conns.items()
            try:
                while conns:
                    conn, keys = conns.pop()
                    try:
                        conn.write("get %s%s" % (" ".join(keys), CRLF))
                        conn.flush()
                        while True:
                            line = self._error(conn.readline())
                            if line == "END":
                                break
                            elif line.startswith("VALUE "):
                                _, key, flags, length = line.split()
                                flags, length = int(flags), int(length)
                                value = _stream.read_exact(conn, length)
                                if _stream.read_exact(conn, 2) != CRLF:
                                    # sync error?
                                    conn, _ = None, conn.destroy()
                                    return {}
                                try:
                                    result[keymap[key]] = \
                                        self._decode_value(flags, value)
                                except (TypeError, ValueError):
                                    pass # wrong flags or something
                                except KeyError:
                                    raise KeyError('%r, %s: %r' % (
                                        line, key, keymap
                                    ))
                                except (SystemExit, KeyboardInterrupt):
                                    raise
                                except:
                                    import sys
                                    e = sys.exc_info()
                                    try:
                                        msg = "%s:: %r, %s, %r" % (
                                            str(e[1]), line, flags, value
                                        )
                                        e = (e[0], msg, e[2])
                                    finally:
                                        try:
                                            raise e[0], e[1], e[2]
                                        finally:
                                            del e
                            else:
                                # something else we don't know. Better close
                                # the connection.
                                conn, _ = None, conn.destroy()
                                return {}
                    finally:
                        if conn is not None:
                            conn.close()
            finally:
                while conns:
                    conns.pop()[0].close()
        except _socket.error:
            pass
        return result

    def set(self, key, value, max_age):
        """
        Set a key/value pair unconditionally

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        return self.store("set", key, value, max_age)

    def add(self, key, value, max_age):
        """
        Set a key/value pair if the key does not exist yet

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        return self.store("add", key, value, max_age)

    def replace(self, key, value, max_age):
        """
        Set a key/value pair only if the key does exist already

        :Parameters:
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Maximum age in seconds

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        return self.store("replace", key, value, max_age)

    def store(self, method, key, value, max_age, compress=True):
        """
        Store the value under the given key expiring now + expiry

        :Parameters:
         - `method`: Actual method to call (``set``, ``add`` or ``replace``)
         - `key`: The key to store under
         - `value`: The value to store (should be picklable)
         - `max_age`: Max age of the entry in seconds
         - `compress`: Compress the value?

        :Types:
         - `method`: ``str``
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``
         - `compress`: ``bool``

        :return: Stored successfully?
        :rtype: ``bool``
        """
        conn = None
        key = self._prepare_key(key)
        try:
            try:
                flags, value = self._encode_value(
                    key, value, max_age, compress
                )
                conns = self._get_conn(key)
                if not conns:
                    return False
                conn, conns = conns.keys()[0], None
                expiry = int(_time.time()) + max_age - conn.pool.timediff
                cmd = "%(cmd)s %(key)s %(flags)s %(exp)s %(len)s%(nl)s" % \
                dict(
                    cmd=method,
                    key=key,
                    flags=flags,
                    exp=expiry,
                    len=len(value),
                    nl=CRLF,
                )
                conn.write(cmd)
                conn.write(value)
                conn.write(CRLF)
                conn.flush()
                return self._error(conn.readline()) == "STORED"
            except _socket.error:
                conn, _ = None, conn.destroy()
                return False
        finally:
            if conn is not None:
                conn.close()

    def _error(self, line):
        """
        Convert a response line into an error or pass it through

        :Parameters:
         - `line`: The response line to inspect

        :Types:
         - `line`: ``str``

        :return: The stripped response line
        :rtype: ``str``

        :Exceptions:
         - `CommandError`: Command error
         - `ClientError`: Client error
         - `ServerError`: Server error
        """
        line = line.strip()
        if "ERROR" in line:
            if line == "ERROR":
                raise CommandError()
            elif line.startswith("CLIENT_ERROR "):
                raise ClientError(line[13:])
            elif line.startswith("SERVER_ERROR "):
                raise ServerError(line[13:])
            else:
                pos = line.find(' ')
                if pos > 0:
                    raise UnknownError(line[pos + 1:])
                raise UnknownError()
        return line

    def _encode_value(self, key, value, max_age, compress):
        """
        Encode a value for the memcache

        :Parameters:
         - `key`: The store key
         - `value`: The value to encode
         - `max_age`: Maxc age of this item
         - `compress`: Allow value compression?

        :Types:
         - `key`: ``str``
         - `value`: any
         - `max_age`: ``int``
         - `compress`: ``bool``

        :return: The flags and the encoded value (``(int, str)``)
        :rtype: ``tuple``
        """
        flags, vtype = 0, type(value)
        for type_id, (kind, encoder, _) in self._TYPEMAP.iteritems():
            if type_id == 0:
                continue
            if vtype is kind:
                flags, value = type_id, encoder(value)
                break
        else:
            value = self._TYPEMAP[0][1](value)
        if compress and \
                len(value) >= self._compress_threshold and _zlib is not None:
            value = _zlib.compress(value, 9)
            flags |= FLAG_COMPRESSED
        if self._padded and len(value) < 16:
            value = value + "\0" * 16
            flags |= FLAG_PADDED
        if (len(value) + len(key) + 100) > self._largest_slab:
            tpl = "split:%s:%s-%%s" % (
                _md5.md5(_os.urandom(20)).hexdigest(), key
            )
            blocklen = self._largest_slab - len(tpl) - 100
            skeys, idx = [], 0
            while value:
                skey = tpl % idx
                skeys.append(skey)
                idx += 1
                buf, value = value[:blocklen], value[blocklen:]
                self.store("set", skey, buf, max_age, compress=False)
            flags |= FLAG_SPLIT
            value = ' '.join(skeys)
        return flags, value

    def _decode_value(self, flags, value):
        """
        Decode a value depending on its flags

        :Parameters:
         - `flags`: Flag bit field
         - `value`: Value to decode

        :Types:
         - `flags`: ``int``
         - `value`: ``str``

        :return: The decoded value
        :rtype: any

        :Exceptions:
         - `ValueError`: Bad flags or bad value
        """
        type_id = flags & 255
        flags = flags & 65280
        if type_id not in self._TYPEMAP or flags & NO_FLAGS:
            raise ValueError()

        if flags & FLAG_SPLIT:
            keys = str(value).split()
            value = self.get(*keys)
            try:
                value = ''.join([value[key] for key in keys])
            except KeyError:
                raise ValueError()
        if flags & FLAG_PADDED:
            if len(value) < 16:
                raise ValueError()
            value = value[:-16]
        if flags & FLAG_COMPRESSED:
            if _zlib is None:
                raise ValueError()
            try:
                value = _zlib.decompress(value)
            except _zlib.error, e:
                raise ValueError(str(e))
        value = self._TYPEMAP[type_id][2](value)
        return value

    def _get_conn(self, key, *keys):
        """
        Retrieve memcache connection

        The actual memcache connection is selected by the key.
        The algorithm is a simple
        ``hashfunc(key) % weighted_selectable_pools``

        :Parameters:
         - `key`: The key to use for selection

        :Types:
         - `key`: ``str``

        :return: The connection or ``None``
        :rtype: `MemcacheConnection`
        """
        pools, conns, seen = self._weighted, {}, {}
        for key in (key,) + keys:
            conn, hashed = None, int(abs(hashfunc(key)))
            while conn is None and pools:
                pool = pools[hashed % len(pools)]
                if pool in seen:
                    conns[seen[pool]].append(key)
                    break
                state, retry = pool.state
                if state == STATE_RETRY and not retry:
                    pools = pool.backup
                    continue

                try:
                    conn = pool.get_conn()
                except MemcacheConnectError:
                    if state == STATE_RETRY:
                        pools = pool.backup
                        continue
                    elif state != STATE_GRACE:
                        pool.mark_dead(
                            self._grace_time, self._retry_time, self._pools
                        )
                    break
                else:
                    if pool.dead:
                        pool.mark_alive()
                    seen[pool] = conn
                    conns.setdefault(conn, []).append(key)
                break
        return conns


class MemcacheConnection(object):
    """
    Memcache connection representation

    :IVariables:
     - `pool`: Weak reference to the pool
     - `_conn`: Underlying connection stream

    :Types:
     - `pool`: `MemcacheConnectionPool`
     - `_conn`: `stream.GenericStream`
    """
    __implements__ = [_util.PooledInterface]
    pool, _conn = None, None

    def __init__(self, pool, spec, timeout=None):
        """
        Initialization

        :Parameters:
         - `pool`: Pool reference
         - `spec`: Connection spec
         - `timeout`: Communication timeout

        :Types:
         - `pool`: `MemcacheConnectionPool`
         - `spec`: ``tuple``
         - `timeout`: ``float``
        """
        self.pool = _weakref.proxy(pool)
        try:
            sock = _osutil.connect(spec, timeout=timeout, cache=3600)
        except _osutil.SocketError, e:
            raise MemcacheConnectError(str(e))
        if sock is None:
            raise MemcacheConnectError("No connectable address found")
        self._conn = _stream.GenericStream(
            _stream.MinimalSocketStream(sock), read_exact=True
        )

    def __del__(self):
        """ Destruction """
        self.destroy()

    def __getattr__(self, name):
        """
        Delegate unknown requests to the underlying connection

        :Parameters:
         - `name`: The name to lookup

        :Types:
         - `name`: ``str``

        :return: The looked up name
        :rtype: any

        :Exceptions:
         - `AttributeError`: The symbol could be resolved
        """
        return getattr(self._conn, name)

    def close(self):
        """ Close connection """
        self.pool.put_conn(self)

    def destroy(self):
        """ :See: `wtf.util.PooledInterface.destroy` """
        if self.pool is not None:
            try:
                self.pool.del_conn(self)
            finally:
                try:
                    if self._conn is not None:
                        self._conn.close()
                except (_socket.error, ValueError, IOError):
                    pass


class MemcacheConnectionPool(_util.BasePool):
    """
    Memcache connection pool

    :IVariables:
     - `spec`: Connection spec
     - `weight`: Relative pool weight
     - `timeout`: Communication timeout
     - `timediff`: Time difference between client and server in seconds. The
       value is determined after each real connect (``c_time - s_time``)
     - `backup`: The weighted backup pools used in retry state
     - `_dead`: dead state and recovery information during dead time. If the
       pool is alive the value is ``None``. If it's dead it's a tuple
       containing the retry time and the pool list. (``(int, tuple)``)
     - `get_conn`: Connection getter
     - `del_conn`: Connection deleter
     - `_stamp`: Timestamp when the next event should happen. That is either
       the switch from grace state to retry state or the next retry.
     - `_state`: The current state of the pool during dead time (`STATE_GRACE`
       or `STATE_RETRY`)
     - `_deadlock`: Lock for dead state access

    :Types:
     - `spec`: ``tuple``
     - `weight`: ``int``
     - `timeout`: ``float``
     - `timediff`: ``int``
     - `backup`: ``tuple``
     - `get_conn`: ``callable``
     - `del_conn`: ``callable``
     - `_dead`: ``tuple``
     - `_stamp`: ``int``
     - `_state`: ``int``
     - `_deadlock`: ``threading.RLock``
    """
    _FORK_PROTECT = True
    timediff, _dead, _stamp, backup, _state = 0, False, None, (), None

    def __init__(self, maxconn, maxcached, spec, weight=None, timeout=None):
        """
        Initialization

        :Parameters:
         - `maxconn`: Hard maximum of connections to hand out
         - `maxcached`: Maximum number of connections to cache
         - `spec`: Memcache location spec (``('host', port)``)
         - `weight`: Relative pool weight (defaults to ``1``)
         - `timeout`: Memcache timeout (defaults to ``None`` - no timeout)

        :Types:
         - `maxconn`: ``int``
         - `maxcached`: ``int``
         - `spec`: ``tuple``
         - `weight`: ``int``
         - `timeout`: ``float``
        """
        super(MemcacheConnectionPool, self).__init__(maxconn, maxcached)
        if weight is None:
            weight = 1
        self.spec, self.weight, self.timeout = spec, int(weight), timeout
        self.get_conn = self.get_obj
        self.del_conn = self.del_obj
        self._deadlock = _threading.RLock()

    def _create(self): # pylint: disable = E0202
        """ :See: `BasePool._create` """
        conn = MemcacheConnection(self, self.spec, timeout=self.timeout)
        try:
            conn.write("stats" + CRLF)
            conn.flush()
            ctime = int(_time.time())
            stime = None
            while True:
                line = conn.readline().strip()
                if line == "END":
                    break
                if line.startswith('STAT time '):
                    stime = int(line[10:])
            if stime is not None:
                self.timediff = ctime - stime
        except (TypeError, ValueError, _socket.error):
            pass
        return conn

    def put_conn(self, conn):
        """
        Put back connection, but only if not dead

        :Parameters:
         - `conn`: The connection to put back. If the pool is marked dead,
           the connection is just destroyed

        :Types:
         - `conn`: `MemcacheConnection`
        """
        lock = self._deadlock
        lock.acquire()
        try:
            if self._dead:
                conn.destroy()
            else:
                self.put_obj(conn)
        finally:
            lock.release()

    def mark_dead(self, grace_time, retry_time, pools):
        """
        Mark this pool dead

        :Parameters:
         - `grace_time`: Grace time
         - `retry_time`: Retry time
         - `pools`: List of available pools

        :Types:
         - `grace_time`: ``int``
         - `retry_time`: ``int``
         - `pools`: ``tuple``
        """
        lock = self._deadlock
        lock.acquire()
        try:
            self._dead = (retry_time, pools)
            self._state = STATE_GRACE
            self._stamp = int(_time.time()) + grace_time
            self.clear()
        finally:
            lock.release()

    def mark_alive(self):
        """
        Mark this pool alive

        The method unconditionally removes the backup pool list and the dead
        status.
        """
        lock = self._deadlock
        lock.acquire()
        try:
            self._dead, self.backup = None, ()
        finally:
            lock.release()

    def dead(self):
        """
        Determine dead state of the pool

        :return: Is it dead?
        :rtype: ``bool``
        """
        lock = self._deadlock
        lock.acquire()
        try:
            return bool(self._dead)
        finally:
            lock.release()
    dead = property(dead, doc=""" (bool) The current dead state """)

    def state(self):
        """
        Determine the pool's state

        :return: The state (``(state, retry?)``)
        :rtype: ``tuple``
        """
        lock = self._deadlock
        lock.acquire()
        try:
            dead = self._dead
            if dead:
                retry, state, now = False, self._state, int(_time.time())
                if state == STATE_GRACE:
                    if self._stamp < now:
                        state = self._state = STATE_RETRY
                        self._stamp = now + dead[0]
                        self.backup = tuple(_it.chain(*[
                            [pool] * pool.weight for pool in dead[1]
                            if not pool.dead
                        ]))
                elif state == STATE_RETRY and self._stamp < now:
                    self._stamp = now + dead[0]
                    retry = True
                return state, retry
            return None, None
        finally:
            lock.release()
    state = property(state, doc="""
        (tuple) The pool's state.

        The first item is the dead state (`STATE_GRACE` or `STATE_RETRY`) or
        ``None`` if the pool is not dead. The second item is only useful in
        retry state. Then it's a boolean answering the question whether we
        hit a retry point or not.
    """)
