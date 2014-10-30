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
Config service
==============

This service provides global access to the configuration object.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import services as _services


class ConfigService(object):
    """
    Config service

    This service provides global access to the configuration.
    """
    __implements__ = [_services.ServiceInterface]

    def __init__(self, config, opts, args):
        """ :See: `wtf.services.ServiceInterface.__init__` """
        self.config = config

    def shutdown(self):
        """ :See: `wtf.services.ServiceInterface.shutdown` """
        pass

    def global_service(self):
        """ :See: `wtf.services.ServiceInterface.global_service` """
        return 'wtf.config', self.config

    def middleware(self, func):
        """ :See: `wtf.services.ServiceInterface.middleware` """
        return func
