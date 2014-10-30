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
===============
 DB Exceptions
===============

DB Exceptions.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"
__all__ = [
    'DBError',
    'DBConfigurationError',
    'DBAPIError',

    'InterfaceError',
    'DatabaseError',
    'DataError',
    'OperationalError',
    'IntegrityError',
    'InternalError',
    'ProgrammingError',
    'NotSupportedError',
]

import sys as _sys

from wtf import Error


class DBError(Error):
    """ Base DB exception """

class DBConfigurationError(Error):
    """ DB configuration error """

class DBAPIError(DBError):
    """ DB API Error """

class InterfaceError(DBAPIError):
    """ Interface error """

class DatabaseError(DBAPIError):
    """ Database error """

class DataError(DatabaseError):
    """ Data error """

class OperationalError(DatabaseError):
    """ Operational error """

class IntegrityError(DatabaseError):
    """ Integrity error """

class InternalError(DatabaseError):
    """ Internal error """

class ProgrammingError(DatabaseError):
    """ Programming error """

class NotSupportedError(DatabaseError):
    """ Not supported error """


def translate(adapter):
    """
    Translate exception to wtf.ext DBAPI exception

    The new exception is raised.

    :Parameters:
      `adapter` : ``module``
        DBAPI module

    :Warning: This is a private function. Use
              ``wtf.ext.db.driver(dbname).translate_exception()``.
    """
    e = _sys.exc_info()
    try:
        try:
            raise
        except adapter.NotSupportedError:
            raise NotSupportedError, e[1], e[2]
        except adapter.ProgrammingError:
            raise ProgrammingError, e[1], e[2]
        except adapter.InternalError:
            raise InternalError, e[1], e[2]
        except adapter.IntegrityError:
            raise IntegrityError, e[1], e[2]
        except adapter.OperationalError:
            raise OperationalError, e[1], e[2]
        except adapter.DataError:
            raise DataError, e[1], e[2]
        except adapter.DatabaseError:
            raise DatabaseError, e[1], e[2]
        except adapter.InterfaceError:
            raise InterfaceError, e[1], e[2]
        except adapter.Error:
            raise DBAPIError, e[1], e[2]
    finally:
        del e
