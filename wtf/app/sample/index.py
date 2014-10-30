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
Sample application package
==========================

This package contains a sample application.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf.app.decorators import Method
from wtf import webutil as _webutil

from __svc__.wtf import static as _static


@Method('GET')
def hello_world(request, response):
    """ Hello world output """
    if request.match is not None:
        name = request.match.group('name')
    else:
        name = u'World'
    name = name.encode('utf-8')
    salutation = (request.param['s'] or u'Hello!').encode('utf-8')
    response.content_type(charset='utf-8')
    response.cache(0)

    return ["""
<html>
<head>
    <title>Hi</title>
    <link rel="stylesheet" type="text/css" href="/static/layout.css" />
</head>
<body><h1>%s</h1><p>%s</p></body>
</html>
""".strip() % tuple(map(_webutil.escape_html, [salutation, name]))]


__staticmap__ = {
    '/': hello_world,
    #'/layout.css': _static.controller('static'),
}
__dynamicmap__ = [
    (r'/(?P<name>[^./]+)\.html$', hello_world),
    (r'/static/(?P<filename>.+)', _static.controller('static', 'filename')),
]
