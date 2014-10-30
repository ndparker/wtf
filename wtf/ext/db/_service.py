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
============
 DB service
============

This service configures database connections.

Configuration
~~~~~~~~~~~~~

::

  [db]
  # conf = /path/to/db.conf
  dbs = master slave

  [db:master]
  db = web@master

  [db:slave]
  db = web@localhost
"""
__docformat__ = "restructuredtext en"
__author__ = u"Andr\xe9 Malo"

from wtf import services as _services
from wtf.ext.db import _connection
from wtf.ext.db import _tagged


class DBService(object):
    """ DB Service """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """ Initialization """
        # pylint: disable = W0613
        if 'conf' in config.db:
            conf = unicode(config.db.conf).encode('utf-8')
            if conf:
                _connection.configure(conf)
        for tag in config.db.dbs:
            section = config[u'db:%s' % tag]
            _tagged.register_connection_tag(tag, section.db)

    def shutdown(self):
        """ :See: ``wtf.services.ServiceInterface.shutdown`` """
        pass

    def global_service(self):
        """ :See: ``wtf.services.ServiceInterface.global_service`` """
        return None

    def middleware(self, func):
        """ :See: ``wtf.services.ServiceInterface.middleware`` """
        return func
