                                                        -*- coding: utf-8 -*-
TABLE OF CONTENTS
=================

1. Introduction
2. Copyright and License
3. System Requirements
4. Installation
5. Documentation
6. Bugs
7. Author Information


INTRODUCTION
============

WTF (WSGI Tackling Framework) is a WSGI based meta-framework written in python
with optional speedup code written in C.

WSGI is described here: <http://www.python.org/dev/peps/pep-0333/>
Meta-framework means, that the package helps you build your own framework
out of it.


COPYRIGHT AND LICENSE
=====================

Copyright 2006-2012
André Malo or his licensors, as applicable.

The whole package is distributed under the Apache License Version 2.0.
You'll find a copy in the root directory of the distribution or online
at: <http://www.apache.org/licenses/LICENSE-2.0>.


SYSTEM REQUIREMENTS
===================

You need python 2 (>= 2.4). Python 3 is NOT supported yet.


INSTALLATION
============

WTF is set up using the standard python distutils. So you can install
it using the usual command:

$ python setup.py install

The command above will install a new "wtf" package into python's
library path.

Additionally it will install the documentation. On unices it will be
installed by default into <prefix>/share/doc/wtf.

For customization options please study the output of

$ python setup.py --help


DOCUMENTATION
=============

You'll find a user documentation in the docs/userdoc/ directory of the
distribution package. It is installed by default under <prefix>/share/doc/wtf
(e.g. /usr/share/doc/wtf). Further, there's the code documentation, generated
by epydoc (<http://epydoc.sourceforge.net/>), which can be found in the
docs/apidoc/ subdirectory.

The latest documentation is also available online at
<http://opensource.perlig.de/wtf/>.


BUGS
====

No bugs, of course. ;-)
But if you've found one or have an idea how to improve the WTF, feel free
to send a pull request on `github <https://github.com/ndparker/wtf>`_
or send a mail to <wtf-bugs@perlig.de>.


AUTHOR INFORMATION
==================

André "nd" Malo <nd@perlig.de>
GPG: 0x8103A37E


If God intended people to be naked, they would be born that way.
                                                 -- Oscar Wilde
