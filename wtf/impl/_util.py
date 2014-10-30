# -*- coding: ascii -*-
#
# Copyright 2006-2012
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
Implementation utilities
========================
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import stream as _stream


class ContentLengthReader(object):
    """
    Emulate EOF condition after Content length is reached

    :IVariables:
     - `_stream`: Stream to read from
     - `_left`: Octets that still can be read

    :Types:
     - `_stream`: ``file``
     - `_left`: ``int``
    """

    def __init__(self, stream, clen):
        """
        Initialization

        :Parameters:
         - `stream`: The stream to read from
         - `clen`: The length of the stream

        :Types:
         - `stream`: ``file``
         - `clen`: ``int``
        """
        self._stream, self._left = stream, int(clen)

    def read(self, size):
        """
        Read (at max) `size` bytes

        :Parameters:
         - `size`: Maximum number of octets to read

        :Types:
         - `size`: ``int``

        :return: The bytes read (empty on EOF)
        :rtype: ``str``
        """
        if self._left > 0:
            size = min(size, self._left)
            result = _stream.read_exact(self._stream, size)
            self._left -= len(result)
            return result
        return ""
