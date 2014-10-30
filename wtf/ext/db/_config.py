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
==================
 DB access module
==================

DB access module.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import ConfigParser as _config_parser
import os as _os

from wtf.ext.db._exceptions import DBConfigurationError
from wtf import util as _wtf_util


#: Default conf file location
#:
#: :Type: ``str``
DEFAULT_CONF = '/etc/wtf/ext/db.conf'


def load_from_file(dbconf):
    """
    Load config

    :Parameters:
      `dbconf` : ``str``
        DB config filename

    :Return: Config dict
    :Rtype: ``dict``
    """
    parser = _config_parser.RawConfigParser()
    try:
        fp = open(dbconf, 'rb')
        try:
            parser.readfp(fp)
        finally:
            fp.close()
    except IOError, e:
        raise DBConfigurationError(str(e))

    config = dict((section, dict((opt, parser.get(section, opt))
        for opt in parser.options(section)
    )) for section in parser.sections())

    for _, opts in config.items():
        if 'alias' in opts:
            alias = opts['alias']
            opts.clear()
            opts.update(config[alias])

    return config


def configure(dbconf=None, unpack_password=None):
    """
    Configure the databases

    This function is called automatically at import time. But configuration
    errors are ignored this first time.

    :Parameters:
      `dbconf` : ``str``
        Config file name. If omitted or ``None``, the environment variable
        ``WTF_EXT_DB_CONF`` is queried. If that's unset, too, it defaults to
        `DEFAULT_CONF`.

      `unpack_password` : callable
        Password unpacker. If omitted or ``None``, no password unpacker is
        applied.

    :Exceptions:
      - `DBConfigurationError` : Config error
    """
    def resolve(arg, env, default):
        """ Resolve path """
        if arg is not None:
            return arg
        return _os.path.expanduser(_os.environ.get(env, default))

    dbconf = resolve(dbconf, 'WTF_EXT_DB_CONF', DEFAULT_CONF)
    config = load_from_file(dbconf)

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
        return _wtf_util.load_dotted(
            'wtf.ext.db._driver_%s' % config[dbname]['driver']
        )

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
        conf = config[dbname].copy()
        db_driver = driver(dbname)
        conf.pop('driver', None)
        if 'passwd' in conf and unpack_password is not None:
            passwd = conf['passwd']
            conf['passwd'] = lambda: unpack_password(passwd)
        return db_driver.connect(conf, kwargs)
    connect.config = config

    return driver, connect
