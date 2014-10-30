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
======================
 MySQL adpater driver
======================

MySQL adapter driver.

:Variables:
  `adapter` : ``module``
    The database adapter
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import MySQLdb as _mysql
from MySQLdb.constants import CLIENT as _mysql_flags

from wtf import util as _wtf_util
from wtf.ext.db import _exceptions

adapter = _mysql


def driver():
    """
    Get this module

    :Return: The module
    :Rtype: ``module``
    """
    return _wtf_util.load_dotted(__name__)


def is_unique_violation(e):
    """
    Is a particular integrity error a unique violation?

    :Parameters:
      `e` : `Exception`
        DB-API exception instance

    :Return: Is it?
    :Rtype: ``bool``
    """
    return isinstance(e, adapter.IntegrityError) and e.args[0] == 1062


def translate_exception():
    """
    Translate exception to wtf.ext DBAPI exception

    The new exception is raised.
    """
    _exceptions.translate(adapter)


def autocommit(connection, value):
    """
    Set autocommit

    :Parameters:
      `value` : ``bool``
        yes or no?
    """
    connection.autocommit(int(bool(value)))


def begin(connection):
    """
    Start transaction
    """
    cur = connection.cursor()
    try:
        cur.execute('START TRANSACTION')
    finally:
        cur.close()


def commit(connection):
    """
    Commit transaction
    """
    connection.commit()


def rollback(connection):
    """
    Rollback transaction
    """
    connection.rollback()


def connect(conf, kwargs):
    """
    Connect to database ``dbname``

    The following config options are recognized:

    ``host`` : ``str``
        DB host
    ``port`` : ``int``
        DB port
    ``user`` : ``str``
        Username for login
    ``passwd`` : ``str``
        Password for login
    ``db`` : ``str``
        Database to connect to

    The following keyword arguments are recognized:

    ``use_unicode`` : ``bool``
        Use unicode? Default: True.

    :Parameters:
      `conf` : ``dict``
        Connection options

      `kwargs` : ``dict``
        Additional parameters for the connect

    :Return: new connection
    :Rtype: DB-API connection

    :Exceptions:
      - `DBConfigurationError` : Configuration error
    """
    args = dict((key, conf[key])
        for key in ('host', 'port', 'user', 'passwd', 'db') if key in conf
    )
    args['client_flag'] = (
          _mysql_flags.MULTI_STATEMENTS
        | _mysql_flags.MULTI_RESULTS
        | _mysql_flags.FOUND_ROWS
    )
    args['use_unicode'] = bool(kwargs.get('use_unicode', True))
    args['charset'] = 'utf8'
    if 'port' in args:
        args['port'] = int(args['port'])
        if args['host'] == 'localhost':
            args['host'] = '127.0.0.1'
    if 'passwd' in args and callable(args['passwd']):
        args['passwd'] = args['passwd']()
    try:
        return _mysql.connect(**args)
    finally:
        args['passwd'] = 'XXXXX' # pylint: disable = W0511
