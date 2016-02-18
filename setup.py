#!/usr/bin/env python
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

from _setup import run, ext


def make_util_private_h(cfile):
    """ Create util_private.h """
    import urllib, posixpath
    hfile = posixpath.join(posixpath.dirname(cfile), 'util_private.h')
    fp = file(hfile, 'w')
    try:
        print >> fp, """/*
 * XXX This file is autogenerated by setup.py, don't edit XXX
 */
#ifndef WTF_UTIL_PRIVATE_H
#define WTF_UTIL_PRIVATE_H

#define WTF_SAFE_CHAR (1 << 0)
#define WTF_HEX_DIGIT (1 << 1)


#define WTF_IS_SAFE_CHAR(table, c) \\
    ((table)[(unsigned char)(c) & 0xFF] & WTF_SAFE_CHAR)

#define WTF_IS_HEX_DIGIT(c) \\
    (wtf_charmask[(unsigned char)(c) & 0xFF] & WTF_HEX_DIGIT)

#define WTF_HEX_VALUE(c) (wtf_hextable[(unsigned char)c & 0xFF])

#define WTF_IS_LATIN1(u) (!((u) & ~((Py_UNICODE)0xFF)))

static const char *wtf_hex_digits = "0123456789ABCDEF";

#define WTF_HEXDIGIT_HIGH(c) \\
    (wtf_hex_digits[((((unsigned char)c) & 0xF0) >> 4)])
#define WTF_HEXDIGIT_LOW(c) (wtf_hex_digits[((unsigned char)c) & 0xF])

static const unsigned char wtf_charmask[256] = {"""
        for x in range(16):
            line = []
            for y in range(16):
                mask = int(chr(x * 16 + y) in urllib.always_safe)
                if chr(x*16 + y) in 'abcdefABCDEF0123456789':
                    mask |= 2
                if mask < 10:
                    mask = ' ' + str(mask)
                line.append(str(mask))
            line.append('')
            print >> fp, ', '.join(line)
        print >> fp, """};

static const unsigned char wtf_hextable[256] = {"""
        for x in range(16):
            line = []
            for y in range(16):
                c = chr(x*16 + y)
                if c in 'abcdef':
                    line.append(str('abcdef'.index(c) + 10))
                elif c in 'ABCDEF':
                    line.append(str('ABCDEF'.index(c) + 10))
                elif c in '0123456789':
                    line.append(' ' + str(int(c)))
                else:
                    line.append(' 0')
            line.append('')
            print >> fp, ', '.join(line)
        print >> fp, """};

#endif"""
    finally:
        fp.close()


class UtilExtension(ext.Extension):
    """ Check and create header file for util extension """

    def cached_check_prerequisites(self, build):
        """ Check for prereq """
        conftest = ext.ConfTest(build, """
#define _BSD_SOURCE
#define _DEFAULT_SOURCE
#include <unistd.h>
#include <sys/types.h>
#include <grp.h>
int main(int argc, char **argv)
{
    return !!initgroups("foo", 0);
}
        """)
        try:
            if conftest.compile() and conftest.link():
                self.define_macros.append(('WTF_HAVE_INITGROUPS', None))
        finally:
            conftest.destroy()
        make_util_private_h(self.sources[0])
        return False


def setup(args=None, _manifest=0):
    """ Main setup function """
    return run(
        ext=[
            UtilExtension('wtf._wtf_cutil', [
                'wtf/util.c'
            ], depends=['wtf/util_private.h', '_setup/include/cext.h']),

            ext.Extension('wtf._wtf_cstream', [
                'wtf/stream.c'
            ], depends=['_setup/include/cext.h']),
        ],
        script_args=args,
        manifest_only=_manifest,
    )


def manifest():
    """ Create List of packaged files """
    return setup((), _manifest=1)


if __name__ == '__main__':
    setup()
