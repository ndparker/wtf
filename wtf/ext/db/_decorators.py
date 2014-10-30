# -*- coding: ascii -*-
#
# Copyright 2010-2012
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
==========
 DB stuff
==========

DB stuff.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import sys as _sys

from wtf import util as _wtf_util
from wtf.ext.db import _connection


class WTFConnection(object):
    """ Connection wrapper """
    # pylint: disable = W0212, C0111
    def __init__(self, dbname, conn):
        in_transaction = False
        self.__next_broken = None
        while isinstance(conn, WTFConnection):
            dbname = conn.__dbname
            in_transaction = conn.__in_transaction
            if not self.__next_broken:
                self.__next_broken = conn.__mark_broken
            conn = conn.__conn
        self.__conn = conn
        self.__dbname = dbname
        self.__in_transaction = in_transaction
        self.__initiated_transaction = False
        self.__broken = False
    def __getattr__(self, name):
        return getattr(self.__conn, name)
    def __mark_broken(self, how, who=None):
        if who is None:
            who = set()
        if id(self) not in who:
            who.add(id(self))
            self.__broken = bool(how)
            if self.__next_broken:
                self.__next_broken(how, who)
    def begin(self):
        if not self.__in_transaction:
            _connection.driver(self.__dbname).begin(self.__conn)
            self.__mark_broken(False)
            self.__initiated_transaction = True
        return self
    def commit(self):
        if self.__initiated_transaction and not self.__broken:
            _connection.driver(self.__dbname).commit(self.__conn)
            _connection.driver(self.__dbname).autocommit(self.__conn, True)
    def rollback(self):
        if self.__in_transaction:
            self.__mark_broken(True)
            _connection.driver(self.__dbname).rollback(self.__conn)
            _connection.driver(self.__dbname).autocommit(self.__conn, False)


def connection(dbname, arg=None, translate_exceptions=True):
    """
    Create decorator to inject SA connection into function

    :Parameters:
      `dbname` : ``str``
        DB name

      `arg` : ``str``
        Argument name. If omitted or ``None``, ``'db'`` is used.

      `translate_exceptions` : ``bool``
        Translate adapter exceptions to our ones?

    :Return: Decorator function
    :Rtype: ``callable``
    """
    if arg is None:
        arg = 'db'
    def con(oldval):
        """ Create connection """
        if oldval is None:
            this_con = _connection.connect(dbname)
            _connection.driver(dbname).autocommit(this_con, True)
            return True, WTFConnection(dbname, this_con)
        return False, WTFConnection(dbname, oldval)

    def inner(func):
        """
        Actual decorator

        :Parameters:
          `func` : ``callable``
            Function to decorate

        :Return: Decorated function
        :Rtype: ``callable``
        """
        setarg = _wtf_util.make_setarg(arg, func)

        @_wtf_util.decorating(func)
        def proxy(*args, **kwargs):
            """ Proxy """
            drv = _connection.driver(dbname)
            try:
                (created, opened), args, kwargs = setarg(args, kwargs, con)
                try:
                    return func(*args, **kwargs)
                finally:
                    if created:
                        opened.close()
            except drv.adapter.Error:
                if translate_exceptions:
                    drv.translate_exception()
                raise
        return proxy
    return inner


def transaction(arg=None):
    """
    Create decorator to wrap a connection into a transaction

    :Parameters:
      `arg` : ``str``
        Argument name. If omitted or ``None``, ``'db'`` is used.

    :Return: Decorator function
    :Rtype: ``callable``
    """
    if arg is None:
        func, arg = None, 'db'
    elif callable(arg):
        func, arg = arg, 'db'
    else:
        func = None

    def make_trans(oldval):
        """ Create transaction """
        return False, oldval.begin()

    def inner(func):
        """
        Actual decorator

        :Parameters:
          `func` : ``callable``
            Function to decorate

        :Return: Decorated function
        :Rtype: ``callable``
        """
        setarg = _wtf_util.make_setarg(arg, func)

        @_wtf_util.decorating(func)
        def proxy(*args, **kwargs):
            """ Proxy """
            (_, trans), args, kwargs = setarg(args, kwargs, make_trans)
            try:
                res = func(*args, **kwargs)
            except: # pylint: disable = W0702
                e = _sys.exc_info()
                try:
                    trans.rollback()
                finally:
                    try:
                        raise e[0], e[1], e[2]
                    finally:
                        del e
            trans.commit()
            return res
        return proxy

    if func is not None:
        return inner(func)
    return inner
