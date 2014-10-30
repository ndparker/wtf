# -*- coding: utf-8 -*-
"""
Debugging output heavily based on colubrid.debug
(http://trac.pocoo.org/repos/colubrid/trunk/colubrid/debug.py@2791)

colubrid.debug is copyright 2006 by Armin Ronacher, Benjamin Wiegand,
Georg Brandl and licensed under the `BSD License`_

.. _BSD License: http://www.opensource.org/licenses/bsd-license.php
"""
__docformat__ = 'restructuredtext en'

try:
    import cStringIO as _string_io
except ImportError:
    import StringIO as _string_io
import inspect as _inspect
import keyword as _keyword
import os as _os
import pprint as _pprint
import re as _re
import sys as _sys
import token as _token
import tokenize as _tokenize
import traceback as _traceback
from xml.sax.saxutils import escape as _escape


JAVASCRIPT = r'''
function toggleBlock(handler) {
    if (handler.nodeName == 'H3') {
        var table = handler;
        do {
            table = table.nextSibling;
            if (typeof table == 'undefined') {
                return;
            }
        }
        while (table.nodeName != 'TABLE');
    }
    
    else if (handler.nodeName == 'DT') {
        var parent = handler.parentNode;
        var table = parent.getElementsByTagName('TABLE')[0];
    }
    
    var lines = table.getElementsByTagName("TR");
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (line.className == 'pre' || line.className == 'post' ||
                line.parentNode.parentNode.className == 'vars') {
            line.style.display = (line.style.display == 'none') ? '' : 'none';
        }
    }
}

function initTB() {
    var tb = document.getElementById('wsgi-traceback');
    var handlers = tb.getElementsByTagName('H3');
    for (var i = 0; i < handlers.length; i++) {
        toggleBlock(handlers[i]);
        handlers[i].setAttribute('onclick', 'toggleBlock(this)');
    }
    handlers = tb.getElementsByTagName('DT');
    for (var i = 0; i < handlers.length; i++) {
        toggleBlock(handlers[i]);
        handlers[i].setAttribute('onclick', 'toggleBlock(this)');
    }
}

function change_tb() {
    interactive = document.getElementById('interactive');
    plain = document.getElementById('plain');
    interactive.style.display = ((interactive.style.display == 'block') | (interactive.style.display == '')) ? 'none' : 'block';
    plain.style.display = (plain.style.display == 'block') ? 'none' : 'block';
}
'''

STYLESHEET = '''
body {
  font-size:0.9em;
  margin: 0;
  padding: 1.3em;
}

* {
  margin:0;
  padding:0;
}

#wsgi-traceback {
  margin: 1em;
  border: 1px solid #5F9CC4;
  background-color: #F6F6F6;
}

h1 {
  background-color: #3F7CA4;
  font-size:1.2em;
  color:#FFFFFF;
  padding:0.3em;
  margin:0 0 0.2em 0;
}

h2 {
  background-color:#5F9CC4;
  font-size:1em;
  color:#FFFFFF;
  padding:0.3em;
  margin:0.4em 0 0.2em 0;
}

h2.tb {
  cursor:pointer;
}

h3 {
  font-size:1em;
  cursor:pointer;
}

h3.fn {
  margin-top: 0.5em;
  padding: 0.3em;
}

h3.fn:hover {
  color: #777;
}

h3.indent {
  margin:0 0.7em 0 0.7em;
  font-weight:normal;
}

p.text {
  padding:0.1em 0.5em 0.1em 0.5em;
}

p.errormsg {
  padding:0.1em 0.5em 0.1em 0.5em;
}

p.errorline {
  padding:0.1em 0.5em 0.1em 2em;
  font-size: 0.9em;
}

div.frame {
  margin: 0 2em 0 1em;
}

table.code {
  margin: 0.4em 0 0 0.5em;
  background-color:#E0E0E0;
  width:100%;
  font-family: monospace;
  font-size:13px;
  border:1px solid #C9C9C9;
  border-collapse:collapse;
}

table.code td.lineno {
  width:42px;
  text-align:right;
  padding:0 5px 0 0;
  color:#444444;
  font-weight:bold;
  border-right:1px solid #888888;
}

table.code td.code {
  background-color:#EFEFEF;
  padding:1px 0 1px 5px;
  white-space:pre;
}

table.code tr.cur td.code {
  background-color: #fff;
  border-top: 1px solid #ccc;
  border-bottom: 1px solid #ccc;
  white-space: pre;
}

pre.plain {
  margin:0.5em 1em 1em 1em;
  padding:0.5em;
  border:1px solid #999999;
  background-color: #FFFFFF;
  font-family: monospace;
  font-size: 13px;
}

table.vars {
  margin:0 1.5em 0 1.5em;
  border-collapse:collapse;
  font-size: 0.9em;
}

table.vars td {
  font-family: 'Bitstream Vera Sans Mono', 'Courier New', monospace;
  padding: 0.3em;
  border: 1px solid #ddd;
  vertical-align: top;
  background-color: white;
}

table.vars .name {
  font-style: italic;
}

table.vars .value {
  color: #555;
}

table.vars th {
  padding: 0.2em;
  border: 1px solid #ddd;
  background-color: #f2f2f2;
  text-align: left;
}

#plain {
  display: none;
}

dl dt {
  padding: 0.2em 0 0.2em 1em;
  font-weight: bold;
  cursor: pointer;
  background-color: #ddd;
}

dl dt:hover {
  background-color: #bbb; color: white;
}

dl dd {
  padding: 0 0 0 2em;
  background-color: #eee;
}

span.p-kw {
  font-weight: bold;
  color: #008800;
}

span.p-cmt {
  color: #888888;
}

span.p-str {
  color: #dd2200;
  background-color: #fff0f0;
}

span.p-num {
  color: #0000DD;
  font-weight: bold;
}

span.p-op {
  color: black;
}
'''


def get_frame_info(tb, context_lines=7):
    """
    Return a dict of information about a given traceback.
    """
    # line numbers / function / variables
    lineno = tb.tb_lineno
    function = tb.tb_frame.f_code.co_name
    variables = tb.tb_frame.f_locals

    # get filename
    fn = tb.tb_frame.f_globals.get('__file__')
    if not fn:
        fn = _os.path.realpath(
            _inspect.getsourcefile(tb) or _inspect.getfile(tb)
        )
    if fn[-4:] in ('.pyc', '.pyo'):
        fn = fn[:-1]

    # module name
    modname = tb.tb_frame.f_globals.get('__name__')

    # get loader
    loader = tb.tb_frame.f_globals.get('__loader__')

    # sourcecode
    try:
        if not loader is None:
            source = loader.get_source(modname)
        else:
            source = file(fn).read()
    except (SystemExit, KeyboardInterrupt):
        raise
    except:
        source = ''
        pre_context, post_context = [], []
        context_line, context_lineno = None, None
    else:
        parser = PythonParser(source)
        parser.parse()
        parsed_source = parser.get_html_output()
        lbound = max(0, lineno - context_lines - 1)
        ubound = lineno + context_lines
        try:
            context_line = parsed_source[lineno - 1]
            pre_context = parsed_source[lbound:lineno - 1]
            post_context = parsed_source[lineno:ubound]
        except IndexError:
            context_line = None
            pre_context = post_context = [], []
        context_lineno = lbound

    return {
        'tb':               tb,
        'filename':         fn,
        'loader':           loader,
        'function':         function,
        'lineno':           lineno,
        'vars':             variables,
        'pre_context':      pre_context,
        'context_line':     context_line,
        'post_context':     post_context,
        'context_lineno':   context_lineno,
        'source':           source
    }


def debug_context(exc_info):
    exception_type, exception_value, tb = exc_info
    # skip first internal frame
    if tb.tb_next is not None:
        tb = tb.tb_next
    plaintb = ''.join(_traceback.format_exception(*exc_info))

    # load frames
    frames = []

    # walk through frames and collect information
    while tb is not None:
        frames.append(get_frame_info(tb))
        tb = tb.tb_next

    # guard for string exceptions
    if isinstance(exception_type, str):
        extypestr = "string exception"
        exception_value = exception_type
    elif exception_type.__module__ == "exceptions":
        extypestr = exception_type.__name__
    else:
        extypestr = str(exception_type)

    return Namespace(
        exception_type=extypestr,
        exception_value=str(exception_value),
        frames=frames,
        last_frame=frames[-1],
        plaintb=plaintb,
    )


def debug_info(environ, exc_info):
    """
    Return debug info for the request
    """
    context = debug_context(exc_info)
    context.req_vars = sorted(environ.iteritems())
    return DebugRender(context).render()


class Namespace(object):
    def __init__(self, **kwds):
        self.__dict__.update(kwds)


class PythonParser(object):
    """
    Simple python sourcecode highlighter.
    Usage::

        p = PythonParser(source)
        p.parse()
        for line in p.get_html_output():
            print line
    """

    _KEYWORD = _token.NT_OFFSET + 1
    _TEXT    = _token.NT_OFFSET + 2
    _classes = {
        _token.NUMBER:       'num',
        _token.OP:           'op',
        _token.STRING:       'str',
        _tokenize.COMMENT:   'cmt',
        _token.NAME:         'id',
        _token.ERRORTOKEN:   'error',
        _KEYWORD:            'kw',
        _TEXT:               'txt',
    }

    def __init__(self, raw):
        self.raw = raw.expandtabs(8).strip()
        self.out = _string_io.StringIO()

    def parse(self):
        self.lines = [0, 0]
        pos = 0
        while 1:
            pos = self.raw.find('\n', pos) + 1
            if not pos: break
            self.lines.append(pos)
        self.lines.append(len(self.raw))

        self.pos = 0
        text = _string_io.StringIO(self.raw)
        try:
            _tokenize.tokenize(text.readline, self)
        except _tokenize.TokenError:
            pass

    def get_html_output(self):
        """ Return line generator. """
        def html_splitlines(lines):
            # this cool function was taken from trac.
            # http://projects.edgewall.com/trac/
            open_tag_re = _re.compile(r'<(\w+)(\s.*)?[^/]?>')
            close_tag_re = _re.compile(r'</(\w+)>')
            open_tags = []
            for line in lines:
                for tag in open_tags:
                    line = tag.group(0) + line
                open_tags = []
                for tag in open_tag_re.finditer(line):
                    open_tags.append(tag)
                open_tags.reverse()
                for ctag in close_tag_re.finditer(line):
                    for otag in open_tags:
                        if otag.group(1) == ctag.group(1):
                            open_tags.remove(otag)
                            break
                for tag in open_tags:
                    line += '</%s>' % tag.group(1)
                yield line
                
        return list(html_splitlines(self.out.getvalue().splitlines()))
            
    def __call__(self, toktype, toktext, (srow,scol), (erow,ecol), line):
        oldpos = self.pos
        newpos = self.lines[srow] + scol
        self.pos = newpos + len(toktext)

        if toktype in [_token.NEWLINE, _tokenize.NL]:
            self.out.write('\n')
            return

        if newpos > oldpos:
            self.out.write(self.raw[oldpos:newpos])

        if toktype in [_token.INDENT, _token.DEDENT]:
            self.pos = newpos
            return

        if _token.LPAR <= toktype and toktype <= _token.OP:
            toktype = _token.OP
        elif toktype == _token.NAME and _keyword.iskeyword(toktext):
            toktype = self._KEYWORD
        clsname = self._classes.get(toktype, 'txt')

        self.out.write('<span class="code-item p-%s">' % clsname)
        self.out.write(_escape(toktext))
        self.out.write('</span>')


class DebugRender(object):

    def __init__(self, context):
        self.c = context

    def render(self):
        return '\n'.join([
            self.header(),
            self.traceback(),
            self.request_information(),
            self.footer()
        ])
        
    def header(self):
        data = [
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
                '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>',
            '<title>Python Traceback</title>',
            '<script type="text/javascript">%s</script>' % JAVASCRIPT,
            '<style type="text/css">%s</style>' % STYLESHEET,
            '</head><body>',
            '<div id="wsgi-traceback">'
        ]
        
        if hasattr(self.c, 'exception_type'):
            title = _escape(self.c.exception_type)
            exc = _escape(self.c.exception_value)
            data += [
                '<h1>%s</h1>' % title,
                '<p class="errormsg">%s</p>' % exc
            ]

        if hasattr(self.c, 'last_frame'):
            data += [
                '<p class="errorline">%s in %s, line %s</p>' % (
                self.c.last_frame['filename'], self.c.last_frame['function'],
                self.c.last_frame['lineno'])
            ]

        return '\n'.join(data)

    def render_code(self, frame):
        def render_line(mode, lineno, code):
            return ''.join([
                '<tr class="%s">' % mode,
                '<td class="lineno">%i</td>' % lineno,
                '<td class="code">%s</td></tr>' % code
            ])

        tmp = ['<table class="code">']
        lineno = frame['context_lineno']
        if not lineno is None:
            lineno += 1
            for l in frame['pre_context']:
                tmp.append(render_line('pre', lineno, l))
                lineno += 1
            tmp.append(render_line('cur', lineno, frame['context_line']))
            lineno += 1
            for l in frame['post_context']:
                tmp.append(render_line('post', lineno, l))
                lineno += 1
        else:
            tmp.append(render_line('cur', 1, 'Sourcecode not available'))
        tmp.append('</table>')
        
        return '\n'.join(tmp)
        
    def var_table(self, var):
        # simple data types
        if isinstance(var, basestring) or isinstance(var, float)\
           or isinstance(var, int) or isinstance(var, long):
            return ('<table class="vars"><tr><td class="value">%r'
                    '</td></tr></table>' % _escape(repr(var)))
        
        # dicts
        if isinstance(var, dict) or hasattr(var, 'items'):
            items = var.items()
            items.sort()

            # empty dict
            if not items:
                return ('<table class="vars"><tr><th>no data given'
                        '</th></tr></table>')
        
            result = ['<table class="vars"><tr><th>Name'
                      '</th><th>Value</th></tr>']
            for key, value in items:
                try:
                    val = _escape(_pprint.pformat(value))
                except (SystemExit, KeyboardInterrupt):
                    raise
                except:
                    val = '?'
                result.append('<tr><td class="name">%s</td><td class="value">%s'
                              '</td></tr>' % (_escape(repr(key)), val))
            result.append('</table>')
            return '\n'.join(result)

        # lists
        if isinstance(var, list):
            # empty list
            if not var:
                return ('<table class="vars"><tr><th>no data given'
                        '</th></tr></table>')

            result = ['<table class="vars">']
            for line in var:
                try:
                    val = _escape(_pprint.pformat(line))
                except (SystemExit, KeyboardInterrupt):
                    raise
                except:
                    val = '?'
                result.append('<tr><td class="value">%s</td></tr>' % (val))
            result.append('</table>')
            return '\n'.join(result)
        
        # unknown things
        try:
            value = _escape(repr(var))
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            value = '?'
        return '<table class="vars"><tr><th>%s</th></tr></table>' % value

    def traceback(self):
        if not hasattr(self.c, 'frames'):
            return ''

        result = ['<h2 onclick="change_tb()" class="tb">Traceback (click to switch to raw view)</h2>']
        result.append('<div id="interactive"><p class="text">A problem occurred in your Python WSGI'
        ' application. Here is the sequence of function calls leading up to'
        ' the error, in the order they occurred. Click on a header to show'
        ' context lines.</p>')
        
        for num, frame in enumerate(self.c.frames):
            line = [
                '<div class="frame" id="frame-%i">' % num,
                '<h3 class="fn">%s in %s</h3>' % (frame['function'],
                                                  frame['filename']),
                self.render_code(frame),
            ]
                
            if frame['vars']:
                line.append('\n'.join([
                    '<h3 class="indent">▸ local variables</h3>',
                    self.var_table(frame['vars'])
                ]))

            line.append('</div>')
            result.append(''.join(line))
        result.append('\n'.join([
            '</div>',
            self.plain()
        ]))
        return '\n'.join(result)

    def plain(self):
        if not hasattr(self.c, 'plaintb'):
            return ''
        return '''
        <div id="plain">
        <p class="text">Here is the plain Python traceback for copy and paste:</p>
        <pre class="plain">\n%s</pre>
        </div>
        ''' % self.c.plaintb
        
    def request_information(self):
        result = [
            '<h2>Request Environment</h2>',
            '<p class="text">The following list contains all environment',
            'variables. Click on a header to expand the list.</p>'
        ]

        if not hasattr(self.c, 'frames'):
            del result[0]
        
        for key, info in self.c.req_vars:
            result.append('<dl><dt>%s</dt><dd>%s</dd></dl>' % (
                _escape(key), self.var_table(info)
            ))
        
        return '\n'.join(result)
        
    def footer(self):
        return '\n'.join([
            '<script type="text/javascript">initTB();</script>',
            '</div>',
            hasattr(self.c, 'plaintb')
                and ('<!-- Plain traceback:\n\n%s-->' % self.c.plaintb)
                or '',
            '</body></html>',
        ])
