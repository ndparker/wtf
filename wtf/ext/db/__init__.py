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

# pylint: disable = W0611
from wtf.ext.db import _config
from wtf.ext.db import _connection
from wtf.ext.db import _tagged as tagged
from wtf.ext.db._decorators import connection, transaction
from wtf.ext.db._exceptions import __all__
from wtf.ext.db._exceptions import * # pylint: disable = W0401, W0614
from wtf.ext.db._service import DBService
__all__ = __all__ + [
    'driver', 'connect', 'configure', 'connection', 'transaction', 'tagged',
    'DBService',
]


def driver(dbname):
    """
    Determine driver module

    :Parameters:
      `dbname` : ``str``
        DB name (section token in db.conf)

    :Return: Driver module
    :Rtype: ``module``

    :Exceptions:
      - `DBConfigurationError` : DB not configured
      - `KeyError` : DB name not found
      - `ImportError` : Driver not found
    """
    return _connection.driver(dbname)


def connect(dbname, **kwargs):
    """
    Connect to database

    :Parameters:
      `dbname` : ``str``
        DB name (section token in db.conf)

      `kwargs` : ``dict``
        Additional parameters for adapter connect() call

    :Return: new connection
    :Rtype: connection object (DBAPI 2)

    :Exceptions:
      - `DBConfigurationError` : DB not configured
      - `KeyError` : DB name not found
      - `ImportError` : Driver not found
    """
    return _connection.connect(dbname, **kwargs)


def configure(dbconf=None, unpack_password=None):
    """
    Configure the databases

    :Parameters:
      `dbconf` : ``str``
        Config file name. If omitted or ``None``, the environment variable
        ``WTF_EXT_DB_CONF`` is queried. If that's unset, too, it defaults to
        ``%r``.

      `unpack_password` : callable
        Password unpacker. If omitted or ``None``, no password unpacker is
        applied.

    :Exceptions:
      - `DBConfigurationError` : Configuration failed (file missing or
        something)
    """
    _connection.configure(dbconf, unpack_password)
if configure.__doc__:
    # pylint: disable = W0622
    configure.__doc__ = configure.__doc__ % (_config.DEFAULT_CONF,)


try:
    configure()
except DBConfigurationError:
    pass # ignore for autoconfiguration
