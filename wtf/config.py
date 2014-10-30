# -*- coding: ascii -*-
#
# Copyright 2005-2013
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
Configuration Handling
======================

This modules handles configuration loading and provides an easy API
for accessing it.
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

import os as _os
import re as _re
import sys as _sys

from wtf import Error


class ConfigurationError(Error):
    """ Configuration error """

class ConfigurationIOError(ConfigurationError):
    """ Config file IO error """

class ParseError(ConfigurationError):
    """
    Parse error

    :CVariables:
     - `_MESSAGE`: The message format string

    :IVariables:
     - `filename`: The name of the file where the error occured
     - `lineno`: The line number of the error

    :Types:
     - `_MESSAGE`: ``str``
     - `filename`: ``basestring``
     - `lineno`: ``int``
    """
    _MESSAGE = "Parse error in %(filename)r, line %(lineno)s"

    def __init__(self, filename, lineno):
        """
        Initialization

        :Parameters:
         - `filename`: The name of the file, where the error occured
         - `lineno`: The erroneous line number

        :Types:
         - `filename`: ``basestring``
         - `lineno`: ``int``
        """
        ConfigurationError.__init__(self, filename, lineno)
        self.filename = filename
        self.lineno = lineno
        self._param = dict(filename=filename, lineno=lineno)

    def __str__(self):
        """ Returns a string representation of the Exception """
        return self._MESSAGE % self._param

class ContinuationError(ParseError):
    """ A line continuation without a previous option line occured """
    _MESSAGE = "Invalid line continuation in %(filename)r, line %(lineno)s"

class OptionSyntaxError(ParseError):
    """ A option line could not be parsed """
    _MESSAGE = "Option syntax error in %(filename)r, line %(lineno)s"

class RecursiveIncludeError(ParseError):
    """ Recursive Include Detected """
    _MESSAGE = "Recursive include detected in %(filename)r, line " \
        "%(lineno)d: %(included)r"

    def __init__(self, filename, lineno, included):
        """
        Initialization

        :Parameters:
         - `filename`: The name of the file, where the error occured
         - `lineno`: The erroneous line number
         - `included`: recursively included file

        :Types:
         - `filename`: ``basestring``
         - `lineno`: ``int``
         - `included`: ``basestring``
        """
        ParseError.__init__(self, filename, lineno)
        self.included = included
        self._param['included'] = included

class OptionTypeError(ParseError):
    """ An option type could not be recognized """
    _MESSAGE = "Failed option type conversion"


class Parser(object):
    """
    Simplified config file parser

    The ``ConfigParser`` module does too much magic (partially
    not even documented). Further we don't need all the set and
    save stuff here, so we write our own - clean - variant.
    This variant just reads the stuff and does not apply any
    typing or transformation. It also uses a better design...

    :IVariables:
     - `_config`: Config instance to feed
     - `_charset`: Default config charset

    :Types:
     - `_config`: `Config`
     - `_charset`: ``str``
    """

    def __init__(self, config, charset='latin-1'):
        """
        Initialization

        :Parameters:
         - `config`: Config instance
         - `charset`: Default config charset

        :Types:
         - `config`: `Config`
         - `charset`: ``str``
        """
        self._config, self._charset = config, charset

    def parse(self, fp, filename, _included=None):
        """
        Reads from `fp` until EOF and parses line by line

        :Parameters:
         - `fp`: The stream to read from
         - `filename`: The filename used for relative includes and
           error messages
         - `_included`: Set of already included filenames for recursion check

        :Types:
         - `fp`: ``file``
         - `filename`: ``basestring``
         - `_included`: ``set``

        :Exceptions:
         - `ContinuationError`: An invalid line continuation occured
         - `OptionSyntaxError`: An option line could not be parsed
         - `IOError`: An I/O error occured while reading the stream
        """
        # pylint: disable = R0912, R0914, R0915

        lineno, section, option = 0, None, None
        root_section, charset, includes = None, self._charset, ()

        # speed / readability enhancements
        config = self._config
        readline = fp.readline
        is_comment = self._is_comment
        try_section = self._try_section
        parse = self._parse_option
        make_section = self._make_section

        def handle_root(root_section):
            """ Handle root section """
            if root_section is None:
                return charset, includes, None
            self._cast(root_section)
            _charset, _includes = charset, []
            if u'charset' in root_section:
                _charset = list(root_section.charset)
                if len(_charset) != 1:
                    raise ContinuationError("Invalid charset declaration")
                _charset = _charset[0].encode('ascii')
            if u'include' in root_section:
                _includes = list(root_section.include)
            return _charset, _includes, None

        while True:
            line = readline()
            if not line:
                break
            line = line.decode(charset)
            lineno += 1

            # skip blank lines and comments
            if line.strip() and not is_comment(line):
                # section header?
                header = try_section(line)
                if header is not None:
                    charset, includes, root_section = \
                        handle_root(root_section)
                    option = None # reset for the next continuation line
                    header = header.strip()
                    if header in config:
                        section = config[header]
                    else:
                        config[header] = section = make_section()

                # line continuation?
                elif line[0].isspace():
                    if option is None:
                        raise ContinuationError(filename, lineno)
                    option.append(line.strip())

                # must be a new option
                else:
                    name, value = parse(line)
                    name = name.strip()
                    if not name:
                        raise OptionSyntaxError(filename, lineno)
                    option = [value]
                    if section is None:
                        if root_section is None:
                            root_section = make_section()
                        section = root_section
                    section[name] = option

        charset, includes, root_section = handle_root(root_section)
        basedir = _os.path.abspath(_os.path.dirname(filename))
        # recode includes to updated charset
        includes = [item.encode(self._charset).decode(charset)
            for item in includes]
        if not isinstance(basedir, unicode):
            fsenc = _sys.getfilesystemencoding()
            includes = [item.encode(fsenc) for item in includes]
        oldseen = _included
        if oldseen is None:
            oldseen = set()
        seen = set()
        for fname in includes:
            fname = _os.path.normpath(_os.path.join(basedir, fname))
            rpath = _os.path.realpath(fname)
            if rpath in oldseen:
                raise RecursiveIncludeError(filename, lineno, fname)
            elif rpath not in seen:
                seen.add(rpath)
                fp = file(fname, 'rb')
                try:
                    self.parse(fp, fname, oldseen | seen)
                finally:
                    fp.close()

        if _included is None:
            for _, section in config:
                self._cast(section)

    def _cast(self, section):
        """
        Cast the options of a section to python types

        :Parameters:
         - `section`: The section to process

        :Types:
         - `section`: `Section`
        """
        # pylint: disable = R0912

        tokre = _re.compile(ur'''
              [;#]?"[^"\\]*(\\.[^"\\]*)*"
            | [;#]?'[^'\\]*(\\.[^'\\]*)*'
            | \S+
        ''', _re.X).finditer
        escsub = _re.compile(ur'''(\\(?:
              x[\da-fA-F]{2}
            | u[\da-fA-F]{4}
            | U[\da-fA-F]{8}
        ))''', _re.X).sub
        def escsubber(match):
            """ Substitution function """
            return match.group(1).encode('ascii').decode('unicode_escape')

        make_option, make_section = self._make_option, self._make_section

        for name, value in section:
            newvalue = []
            for match in tokre(u' '.join(value)):
                val = match.group(0)
                if val.startswith('#'):
                    continue
                if (val.startswith(u'"') and val.endswith(u'"')) or \
                        (val.startswith(u"'") and val.endswith(u"'")):
                    val = escsub(escsubber, val[1:-1])
                else:
                    try:
                        val = human_bool(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            #raise OptionTypeError(val)
                            pass
                newvalue.append(val)
            option = make_option(newvalue)

            # nest dotted options
            if u'.' in name:
                parts, sect = name.split(u'.'), section
                parts.reverse()
                while parts:
                    part = parts.pop()
                    if parts:
                        if part not in sect:
                            sect[part] = make_section()
                        sect = sect[part]
                    else:
                        sect[part] = option
                del section[name]
            else:
                section[name] = option

    def _is_comment(self, line):
        """
        Decide if `line` is comment

        :Parameters:
         - `line`: The line to inspect

        :Types:
         - `line`: ``str``

        :return: Is `line` is comment line?
        :rtype: ``bool``
        """
        return line.startswith(u'#') or line.startswith(u';')

    def _try_section(self, line):
        """
        Try to extract a section header from `line`

        :Parameters:
         - `line`: The line to process

        :Types:
         - `line`: ``str``

        :return: The section header name or ``None``
        :rtype: ``str``
        """
        if line.startswith(u'['):
            pos = line.find(u']')
            if pos > 1: # one name char minimum
                return line[1:pos]
        return None

    def _parse_option(self, line):
        """
        Parse `line` as option (``name [:=] value``)

        :Parameters:
         - `line`: The line to process

        :Types:
         - `line`: ``str``

        :return: The name and the value (both ``None`` if an error occured)
        :rtype: ``tuple``
        """
        pose = line.find('=')
        posc = line.find(':')
        pos = min(pose, posc)
        if pos < 0:
            pos = max(pose, posc)
        if pos > 0: # name must not be empty
            return (line[:pos], line[pos + 1:])
        return (None, None)

    def _make_section(self):
        """
        Make a new `Section` instance

        :return: The new `Section` instance
        :rtype: `Section`
        """
        return Section()

    def _make_option(self, valuelist):
        """
        Make a new option value

        The function will do the right thing[tm] in order to determine
        the correct option type based on `valuelist`.

        :Parameters:
         - `valuelist`: List of values of that option

        :Types:
         - `valuelist`: ``list``

        :return: Option type appropriate for the valuelist
        :rtype: any
        """
        if not valuelist:
            valuelist = [None]
        if len(valuelist) > 1:
            return valuelist
        else:
            return TypedIterOption(valuelist[0])


class TypedIterOption(object):
    """ Option, typed dynamically

        Provides an iterator of the single value list
    """

    def __new__(cls, value):
        """
        Create the final option type

        This gives the type a new name, inherits from the original type
        (where possible) and adds an ``__iter__`` method in order to
        be able to iterate over the one-value-list.

        The following type conversions are done:

        ``bool``
          Will be converted to ``int``

        :Parameters:
         - `value`: The value to decorate

        :Types:
         - `value`: any

        :return: subclass of ``type(value)``
        :rtype: any
        """
        space = {}
        if value is None:
            newcls = unicode
            value = u''
            def itermethod(self):
                """ Single value list iteration method """
                # pylint: disable = W0613

                return iter([])
        else:
            newcls = type(value)
            def itermethod(self):
                """ Single value list iteration method """
                # pylint: disable = W0613

                yield value
        if newcls is bool:
            newcls = int
        def reducemethod(self, _cls=cls):
            """ Mixed Pickles """
            # pylint: disable = W0613
            return (_cls, (value,))

        space = dict(
            __module__=cls.__module__,
            __iter__=itermethod,
            __reduce__=reducemethod,
        )
        cls = type(cls.__name__, (newcls,), space)
        return cls(value)


class Config(object):
    """
    Config access class

    :IVariables:
     - `ROOT`: The current working directory at startup time

    :Types:
     - `ROOT`: ``str``
    """

    def __init__(self, root):
        """
        Initialization

        :Parameters:
         - `root`: The current working directory at startup time

        :Types:
         - `root`: ``str``
        """
        self.ROOT = root
        self.__config_sections__ = {}

    def __iter__(self):
        """ Return (sectionname, section) tuples of parsed sections """
        return iter(self.__config_sections__.items())

    def __setitem__(self, name, value):
        """
        Set a section

        :Parameters:
         - `name`: Section name
         - `value`: Section instance

        :Types:
         - `name`: ``unicode``
         - `value`: `Section`
        """
        self.__config_sections__[unicode(name)] = value

    def __getitem__(self, name):
        """
        Get section by key

        :Parameters:
         - `name`: The section name

        :Types:
         - `name`: ``basestring``

        :return: Section object
        :rtype: `Section`

        :Exceptions:
         - `KeyError`: section not found
        """
        return self.__config_sections__[unicode(name)]

    def __contains__(self, name):
        """
        Determine if a section named `name` exists

        :Parameters:
         - `name`: The section name

        :Types:
         - `name`: ``unicode``

        :return: Does the section exist?
        :rtype: ``bool``
        """
        return unicode(name) in self.__config_sections__

    def __getattr__(self, name):
        """
        Return section by dotted notation

        :Parameters:
         - `name`: The section name

        :Types:
         - `name`: ``str``

        :return: Section object
        :rtype: `Section`

        :Exceptions:
         - `AttributeError`: section not found
        """
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class Section(object):
    """
    Config section container

    :IVariables:
     - `__section_options__`: Option dict

    :Types:
     - `__section_options__`: ``dict``
    """

    def __init__(self):
        """ Initialization """
        self.__section_options__ = {}

    def __iter__(self):
        """ (Name, Value) tuple iterator """
        return iter(self.__section_options__.items())

    def __setitem__(self, name, value):
        """
        Set a new option

        :Parameters:
         - `name`: Option name
         - `value`: Option value

        :Types:
         - `name`: ``unicode``
         - `value`: any
        """
        self.__section_options__[unicode(name)] = value

    def __getitem__(self, name):
        """
        Return a config option by key

        :Parameters:
         - `name`: The key to look up

        :Types:
         - `name`: ``unicode``

        :return: The value of the option
        :rtype: any

        :Exceptions:
         - `KeyError`: No suitable option could be found
        """
        return self.__section_options__[unicode(name)]

    def __delitem__(self, name):
        """
        Delete option

        :Parameters:
         - `name`: Option key to process

        :Types:
         - `name`: ``unicode``

        :Exceptions:
         - `KeyError`: Option did not exist
        """
        del self.__section_options__[unicode(name)]

    def __getattr__(self, name):
        """
        Get option in dotted notation

        :Parameters:
         - `name`: Option key to look up

        :Types:
         - `name`: ``str``

        :return: The value of the option
        :rtype: any

        :Exceptions:
         - `AttributeError`: No suitable option could be found
        """
        try:
            return self[unicode(name)]
        except KeyError:
            raise AttributeError(name)

    def __call__(self, name, default=None):
        """
        Get option or default value

        :Parameters:
         - `name`: The option key to look up
         - `default`: Default value

        :Types:
         - `name`: ``unicode``
         - `default`: any

        :return: The value of the option
        :rtype: any
        """
        try:
            return self[unicode(name)]
        except KeyError:
            return default

    def __contains__(self, name):
        """
        Determine whether `name` is an available option key

        :Parameters:
         - `name`: The option key to look up

        :Types:
         - `name`: ``unicode``

        :return: Is `name` an available option?
        :rtype: ``bool``
        """
        return unicode(name) in self.__section_options__


def merge_sections(*sections):
    """
    Merge sections together

    :Parameters:
      `sections` : ``tuple``
        The sections to merge, later sections take more priority

    :Return: The merged section
    :Rtype: `Section`

    :Exceptions:
      - `TypeError`: Either one of the section was not a section or the
        sections contained unmergable attributes (subsections vs. plain
        values)
    """
    result = Section()
    for section in sections:
        if not isinstance(section, Section):
            raise TypeError("Expected Section, found %r" % (section,))
        for key, value in dict(section).iteritems():
            if isinstance(value, Section) and key in result:
                value = merge_sections(result[key], value)
            result[key] = value
    return result


def human_bool(value):
    """
    Interpret human readable boolean value

    ``True``
      ``yes``, ``true``, ``on``, any number other than ``0``
    ``False``
      ``no``, ``false``, ``off``, ``0``, empty, ``none``

    The return value is not a boolean on purpose. It's a number, so you
    can pass more than just boolean values (by passing a number)

    :Parameters:
     - `value`: The value to interpret

    :Types:
     - `value`: ``str``

    :return: ``number``
    :rtype: ``int``
    """
    if not value:
        value = 0
    else:
        self = human_bool
        value = str(value).lower()
        if value in self.yes: # pylint: disable = E1101
            value = 1
        elif value in self.no: # pylint: disable = E1101
            value = 0
        else:
            value = int(value)
    return value
# pylint: disable = W0612
human_bool.yes = dict.fromkeys("yes true on 1".split())
human_bool.no = dict.fromkeys("no false off 0 none".split())
# pylint: enable = W0612


def dump(config, stream=None):
    """
    Dump config object

    :Parameters:
      `stream` : ``file``
        The stream to dump to. If omitted or ``None``, it's dumped to
        ``sys.stdout``.
    """
    # pylint: disable = R0912

    def subsection(basename, section):
        """ Determine option list from subsection """
        opts = []
        if basename is None:
            make_base = lambda s: s
        else:
            make_base = lambda s: ".".join((basename, s))
        for opt_name, opt_value in section:
            opt_name = make_base(opt_name)
            if isinstance(opt_value, Section):
                opts.extend(subsection(opt_name, opt_value))
            else:
                opts.append((opt_name, opt_value))
        return opts

    def pretty(name, value):
        """ Pretty format a value list """
        value = tuple(value)
        if len(value) == 0:
            return u''
        elif len(value) == 1:
            return cast(value[0])
        result = u" ".join(cast(item) for item in value)
        if len(u"%s = %s" % (name, result)) < 80:
            return result
        return u"\n    " + u"\n    ".join(cast(item) for item in value)

    def cast(value):
        """ Format output by type """
        if isinstance(value, float):
            return unicode(value)
        elif isinstance(value, unicode):
            return u"'%s'" % value.replace(u'\\', u'\\\\').encode(
                'unicode_escape').decode(
                'ascii').replace(
                u"'", u"\\'"
            )
        return repr(value).decode('ascii')

    if stream is None:
        stream = _sys.stdout

    print >> stream, "# ----8<------- WTF config dump -------------"
    print >> stream, "# This is, what the WTF systems gets to see"
    print >> stream, "# after loading and merging all config files."
    print >> stream
    print >> stream, "charset = %r" % 'utf-8'

    for section_name, section in sorted(config):
        if section_name is None:
            continue

        print >> stream
        print >> stream, (u"[%s]" % section_name).encode('utf-8')
        for opt_name, opt_value in sorted(subsection(None, section)):
            print >> stream, u"%s = %s" % (
                opt_name, pretty(opt_name, opt_value)
            )

    print >> stream
    print >> stream, "# ------------- WTF config dump ------->8----"


def load(name, charset='latin-1'):
    """
    Load configuration

    It is not a failure if the file does not exist.

    :Parameters:
     - `name`: The name of the file
     - `charset`: Default charset of config files

    :Types:
     - `name`: ``basestring``
     - `charset`: ``str``

    :return: A config object
    :rtype: `Config`
    """
    config = Config(_os.path.normpath(_os.path.abspath(_os.getcwd())))
    parser = Parser(config, charset)
    try:
        fp = file(name, 'rb')
        try:
            parser.parse(fp, name)
        finally:
            fp.close()
    except IOError:
        e = _sys.exc_info()
        try:
            raise ConfigurationIOError, e[1], e[2]
        finally:
            del e
    return config
