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
============================
 Tagged connection creation
============================

Tagged connection creation.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf.ext.db import _connection
from wtf.ext.db import _decorators


#: Global tag mapping
#:
#: :Type: ``dict``
_connection_tags = {}


def dbname(tag):
    """
    Determine dbname from tag

    :Parameters:
      `tag` : ``str``
        Connection tag

    :Return: DB name
    :Rtype: ``str``
    """
    return _connection_tags[tag]


def driver(tag):
    """
    Determine driver module

    :Parameters:
      `tag` : ``str``
        Connection tag

    :Return: Driver module
    :Rtype: ``module``

    :Exceptions:
      - `DBConfigurationError` : DB not configured
      - `KeyError` : DB name not found
      - `ImportError` : Driver not found
    """
    return _connection.driver(dbname(tag))


def connect(tag, **kwargs):
    """
    Connect and create a connection

    :Parameters:
      `tag` : ``str``
        Connection tag

    :Return: connection
    :Rtype: ``Connection``
    """
    return _connection.connect(dbname(tag), **kwargs)


def connection(tag, arg=None, translate_exceptions=True):
    """
    Create decorator to inject connection into function

    :Parameters:
      `tag` : ``str``
        Connection tag

      `arg` : ``str``
        Argument name. If omitted or ``None``, ``'db'`` is used.

      `translate_exceptions` : ``bool``
        Translate adapter exceptions to our ones?

    :Return: Decorator function
    :Rtype: ``callable``
    """
    return _decorators.connection(dbname(tag), arg, translate_exceptions)


def transaction(arg=None):
    """
    Create decorator to wrap a connection into a transaction

    :Parameters:
      `arg` : ``str``
        Argument name. If omitted or ``None``, ``'db'`` is used.

    :Return: Decorator function
    :Rtype: ``callable``
    """
    return _decorators.transaction(arg)


def register_connection_tag(tag, dbname):
    """
    Register a connection tag

    :Parameters:
      `tag` : ``str``
        Tag name

      `dbname` : ``str``
        DB name string

    :Exceptions:
      - `ValueError` : Tag already defined with a different value
    """
    # pylint: disable = W0621
    if tag in _connection_tags and _connection_tags[tag] != dbname:
        raise ValueError("Tag %r (=%r) redefined as %r" % (
            tag, _connection_tags[tag], dbname
        ))
    _connection_tags[tag] = dbname
