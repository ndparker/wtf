/*
 * Copyright 2006-2012
 * André Malo or his licensors, as applicable
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "cext.h"
EXT_INIT_FUNC;

#include <stdint.h>

#ifdef WTF_HAVE_INITGROUPS
#ifndef _BSD_SOURCE
#define _BSD_SOURCE
#endif
#include <unistd.h>
#include <sys/types.h>
#include <grp.h>
#endif

#include "util_private.h"

/* --------------------------BEGIN HELPER FUNCTIONS------------------------- */

static PyObject *
quote_internal(PyObject *string, PyObject *safe_obj, PyObject *encoding_obj,
               PyObject *errors_obj, int plus)
{
    unsigned char localmask[sizeof(wtf_charmask)];
    const unsigned char *safe;
    PyObject *result;
    char *encoding, *errors;
    Py_ssize_t j, slen, tlen;
    unsigned char c = '/';

    /* make it a string */
    if (PyUnicode_CheckExact(string) || PyUnicode_Check(string)) {
        if (encoding_obj) {
            if (!(encoding = PyString_AsString(encoding_obj)))
                return NULL;
            if (errors_obj) {
                if (!(errors = PyString_AsString(errors_obj)))
                    return NULL;
            }
            else {
                errors = "strict";
            }
            string = PyUnicode_AsEncodedString(string, encoding, errors);
            if (!string)
                return NULL;
        }
        else {
            if (!(string = PyUnicode_AsUTF8String(string)))
                return NULL;
        }
    }
    else if (!PyString_CheckExact(string)) {
        string = PyObject_Str(string);
    }
    else {
        Py_INCREF(string);
    }
    result = NULL;

    /* determine safe table */
    if (safe_obj) {
        if (!PyString_CheckExact(safe_obj)) {
            if (!(safe_obj = PyObject_Str(safe_obj))) {
                goto done;
            }
        }
        else
            Py_INCREF(safe_obj);
        slen = PyString_GET_SIZE(safe_obj);
        if (!slen)
            safe = wtf_charmask;

        /* encoding misuse, but we don't it anymore anyway */
        encoding = PyString_AS_STRING(safe_obj);
        memcpy(localmask, wtf_charmask, sizeof(localmask));
        for (j=0; j < slen; ++j)
            localmask[(unsigned char)encoding[j] & 0xFF] |= WTF_SAFE_CHAR;
        safe = localmask;
        Py_DECREF(safe_obj);
    }
    else {
        memcpy(localmask, wtf_charmask, sizeof(localmask));
        localmask[c & 0xFF] |= WTF_SAFE_CHAR;
        safe = localmask;
    }

    /* count target length */
    encoding = PyString_AS_STRING(string);
    slen = PyString_GET_SIZE(string);
    tlen = slen;
    for (j=0; j<slen; ++j) {
        c = encoding[j];
        if (!WTF_IS_SAFE_CHAR(safe, c) && !(plus && c == ' ')) {
            tlen += 2; /* c => %XX */
        }
    }
    if (slen == tlen && !plus) /* shortcut: nothing to quote */
        return string;

    /* generate result */
    if (!(result = PyString_FromStringAndSize(NULL, tlen)))
        goto done;
    /* errors variable misuse */
    errors = PyString_AS_STRING(result);

    for (j=0; j<slen; ++j) {
        c = encoding[j];
        if (WTF_IS_SAFE_CHAR(safe, c)) {
            *errors++ = encoding[j];
        }
        else if (plus && c == ' ') {
            *errors++ = '+';
        }
        else {
            *errors++ = '%';
            *errors++ = WTF_HEXDIGIT_HIGH(c);
            *errors++ = WTF_HEXDIGIT_LOW(c);
        }
    }

done:
    Py_DECREF(string);
    return result;
}


static PyObject *
unquote_internal_unicode(PyObject *string, int plus)
{
    PyObject *result;
    Py_UNICODE *su, *ru;
    Py_ssize_t j, slen, tlen, sentinel;

    if (!PyUnicode_CheckExact(string)) {
        if (!(string = PyObject_Unicode(string)))
            return NULL;
    }
    else
        Py_INCREF(string);

    su = PyUnicode_AS_UNICODE(string);
    slen = tlen = PyUnicode_GET_SIZE(string);
    
    for (j=0, sentinel=slen-2; j<sentinel; ++j) {
        if (   WTF_IS_LATIN1(su[j]) && (su[j] & 0xFF) == '%'
            && WTF_IS_LATIN1(su[j+1]) && WTF_IS_HEX_DIGIT(su[j+1])
            && WTF_IS_LATIN1(su[j+2]) && WTF_IS_HEX_DIGIT(su[j+2])) {
            tlen -= 2;
            j += 2;
        }
    }
    if (slen == tlen && !plus) /* shortcut: nothing to unquote */
        return string;

    if (!(result = PyUnicode_FromUnicode(NULL, tlen)))
        goto done;
    ru = PyUnicode_AS_UNICODE(result);
    for (j=0, sentinel=slen-2; j<slen; ++j) {
        if (   j < sentinel && WTF_IS_LATIN1(su[j]) && (su[j] & 0xFF) == '%'
            && WTF_IS_LATIN1(su[j+1]) && WTF_IS_HEX_DIGIT(su[j+1])
            && WTF_IS_LATIN1(su[j+2]) && WTF_IS_HEX_DIGIT(su[j+2])) {
            *ru++ =   (WTF_HEX_VALUE(su[j+1]) << 4)
                    + (WTF_HEX_VALUE(su[j+2]));
            j += 2;
        }
        else if (plus && su[j] == (unsigned char)'+') {
            *ru++ = (unsigned char)' ';
        }
        else {
            *ru++ = su[j];
        }
    }

done:
    Py_DECREF(string);
    return result;
}

static PyObject *
unquote_internal_str(PyObject *string, int plus)
{
    PyObject *result;
    char *result_c;
    const char *string_c, *tmp, *tmp2;
    Py_ssize_t j, slen, tlen;

    if (!PyString_CheckExact(string)) {
        if (!(string = PyObject_Str(string)))
            return NULL;
    }
    else
        Py_INCREF(string);

    string_c = tmp = PyString_AS_STRING(string);
    slen = tlen = PyString_GET_SIZE(string);
    j = slen - 2;
    while (j > 0) {
        if (!(tmp2 = memchr(tmp, '%', j)))
            break;
        j -= tmp2 - tmp;
        tmp = tmp2;
        if (WTF_IS_HEX_DIGIT(*++tmp) && WTF_IS_HEX_DIGIT(*++tmp)) {
            ++tmp;
            j -= 3;
            tlen -= 2;
        }
    }
    if (tlen == slen && !plus) /* shortcut: nothing to unquote */
        return string;

    if (!(result = PyString_FromStringAndSize(NULL, tlen)))
        goto done;
    result_c = PyString_AS_STRING(result);
    j = slen;
    while (j > 0) {
        --j;
        if (   j > 1 && *string_c == '%'
            && WTF_IS_HEX_DIGIT(string_c[1])
            && WTF_IS_HEX_DIGIT(string_c[2])) {
            *result_c++ =   (WTF_HEX_VALUE(string_c[1]) << 4)
                          + (WTF_HEX_VALUE(string_c[2]));
            string_c += 3;
            j -= 2;
        }
        else if (plus && *string_c == '+') {
            *result_c++ = ' ';
            ++string_c;
        }
        else {
            *result_c++ = *string_c++;
        }
    }

done:
    Py_DECREF(string);
    return result;
}

/* ---------------------------END HELPER FUNCTIONS-------------------------- */

/* ------------------------ BEGIN MODULE DEFINITION ------------------------ */

PyDoc_STRVAR(wtf_initgroups__doc__,
"initgroups(username, gid)\n\
\n\
Execute ``initgroups(3)``. If ``initgroups`` is not available on this\n\
system, this function is a no-op.\n\
\n\
:See: `HAVE_INITGROUPS`\n\
\n\
Parameters\n\
----------\n\
- ``username``: The user name\n\
- ``gid``: The group id\n\
\n\
Types\n\
-----\n\
- ``username``: ``str``\n\
- ``gid``: ``int``\n\
\n\
:Exceptions:\n\
 - `OSError`: initgroups() didn't succeed");

static PyObject *
wtf_initgroups(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"username", "gid", NULL};
    PyObject *group_object, *uname_object;
    char *username;
    gid_t group;
#ifdef WTF_HAVE_INITGROUPS
    int result;
#endif

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "SO", kwlist,
            &uname_object, &group_object))
        return NULL;

    if (!(username = PyString_AsString(uname_object)))
        return NULL;
    group = (gid_t)PyInt_AsLong(group_object);
    if (PyErr_Occurred())
        return NULL;

#ifdef WTF_HAVE_INITGROUPS
    result = initgroups(username, group);
    if (result != 0)
        return PyErr_SetFromErrno(PyExc_OSError);
#endif

    Py_RETURN_NONE;
}


PyDoc_STRVAR(wtf_quote__doc__,
"quote(s, safe='/', encoding='utf-8', errors='strict')\n\
\n\
Fast replacement for ``urllib.quote``, which also handles unicode.\n\
\n\
:Parameters:\n\
 - `s`: The string to quote\n\
 - `safe`: safe characters (not quoted)\n\
 - `encoding`: Encoding to apply in case `s` is unicode\n\
 - `errors`: Error handling in case `s` is unicode\n\
\n\
:Types:\n\
 - `s`: ``basestring``\n\
 - `safe`: ``str``\n\
 - `encoding`: ``str``\n\
 - `errors`: ``str``\n\
\n\
:return: The quoted string\n\
:rtype: ``str``\n\
\n\
:Exceptions:\n\
 - `UnicodeError`: Encoding error");

static PyObject *
wtf_quote(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"s", "safe", "encoding", "errors", NULL};
    PyObject *string, *safe=NULL, *encoding=NULL, *errors=NULL;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|SSS", kwlist,
                                     &string, &safe, &encoding, &errors))
        return NULL;

    return quote_internal(string, safe, encoding, errors, 0);
}


PyDoc_STRVAR(wtf_quote_plus__doc__,
"quote_plus(s, safe='/', encoding='utf-8', errors='strict')\n\
\n\
Fast replacement for ``urllib.quote_plus``, which also handles unicode.\n\
\n\
:Parameters:\n\
 - `s`: The string to quote\n\
 - `safe`: safe characters (not quoted)\n\
 - `encoding`: Encoding to apply in case `s` is unicode\n\
 - `errors`: Error handling in case `s` is unicode\n\
\n\
:Types:\n\
 - `s`: ``basestring``\n\
 - `safe`: ``str``\n\
 - `encoding`: ``str``\n\
 - `errors`: ``str``\n\
\n\
:return: The quoted string\n\
:rtype: ``str``\n\
\n\
:Exceptions:\n\
 - `UnicodeError`: Encoding error");

static PyObject *
wtf_quote_plus(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"s", "safe", "encoding", "errors", NULL};
    PyObject *string, *safe=NULL, *encoding=NULL, *errors=NULL;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|SSS", kwlist,
                                     &string, &safe, &encoding, &errors))
        return NULL;

    return quote_internal(string, safe, encoding, errors, 1);
}


PyDoc_STRVAR(wtf_unquote__doc__,
"unquote(s)\n\
\n\
Fast replacement for ``urllib.unquote``\n\
\n\
:Parameters:\n\
 - `s`: The string to quote\n\
\n\
:Types:\n\
 - `s`: ``basestring``\n\
\n\
:return: The unquoted string\n\
:rtype: ``basestring``");

static PyObject *
wtf_unquote(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"s", NULL};
    PyObject *string;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O", kwlist, &string))
        return NULL;

    if (PyUnicode_CheckExact(string) || PyUnicode_Check(string))
        return unquote_internal_unicode(string, 0);
    return unquote_internal_str(string, 0);
}


PyDoc_STRVAR(wtf_unquote_plus__doc__,
"unquote_plus(s)\n\
\n\
Fast replacement for ``urllib.unquote_plus``\n\
\n\
:Parameters:\n\
 - `s`: The string to unquote\n\
\n\
:Types:\n\
 - `s`: ``basestring``\n\
\n\
:return: The unquoted string\n\
:rtype: ``basestring``");

static PyObject *
wtf_unquote_plus(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"s", NULL};
    PyObject *string;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O", kwlist, &string))
        return NULL;

    if (PyUnicode_CheckExact(string) || PyUnicode_Check(string))
        return unquote_internal_unicode(string, 1);
    return unquote_internal_str(string, 1);
}


PyDoc_STRVAR(wtf_hash32__doc__,
"hash32(s)\n\
\n\
Replacement for ``str.__hash__``\n\
\n\
The function which is supposed to give identical results on 32 and 64 bit\n\
systems.\n\
\n\
:Parameters:\n\
 - `s`: The string to hash\n\
\n\
:Types:\n\
 - `s`: ``str``\n\
\n\
:return: The hash value\n\
:rtype: ``int``");

static PyObject *
wtf_hash32(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"s", NULL};
    PyObject *string;
    Py_ssize_t len;
    unsigned char *p;
    int32_t x;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O", kwlist, &string))
        return NULL;

    if (!(PyString_CheckExact(string))) {
        if (!(string = PyObject_Str(string)))
            return NULL;
    }
    else
        Py_INCREF(string);

	len = PyString_GET_SIZE(string);
	p = (unsigned char *)PyString_AS_STRING(string);
	x = *p << 7;
	while (--len >= 0)
		x = (1000003*x) ^ *p++;
	x ^= PyString_GET_SIZE(string);
	if (x == -1)
		x = -2;

    Py_DECREF(string);
	return PyInt_FromLong((long)x);
}


EXT_METHODS = {
    {"initgroups",
        (PyCFunction)wtf_initgroups, METH_KEYWORDS,
        wtf_initgroups__doc__},

    {"quote",
        (PyCFunction)wtf_quote, METH_KEYWORDS,
        wtf_quote__doc__},

    {"quote_plus",
        (PyCFunction)wtf_quote_plus, METH_KEYWORDS,
        wtf_quote_plus__doc__},

    {"unquote",
        (PyCFunction)wtf_unquote, METH_KEYWORDS,
        wtf_unquote__doc__},

    {"unquote_plus",
        (PyCFunction)wtf_unquote_plus, METH_KEYWORDS,
        wtf_unquote_plus__doc__},

    {"hash32",
        (PyCFunction)wtf_hash32, METH_KEYWORDS,
        wtf_hash32__doc__},

    {NULL}  /* Sentinel */
};

PyDoc_STRVAR(EXT_DOCS_VAR,
"C implementations of misc stuff\n\
===============================\n\
\n\
This module provides some misc util implementations for WTF.\n\
\n\
:Variables:\n\
 - `HAVE_INITGROUPS`: Is ``initgroups(3)`` on this system implemented?\n\
\n\
:Types:\n\
 - `HAVE_INITGROUPS`: ``bool``");


#define ADD_STRING(MODULE, NAME, STRING) do {                 \
    if (PyModule_AddStringConstant(MODULE, NAME, STRING) < 0) \
        return;                                               \
} while (0)

#define ADD_OBJECT(MODULE, NAME, VALUE) do {          \
    Py_INCREF(VALUE);                                 \
    if (!(PyModule_AddObject(MODULE, NAME, VALUE))) { \
        Py_DECREF(VALUE);                             \
        return;                                       \
    }                                                 \
} while (0)


EXT_INIT_FUNC {
    PyObject *m;

    /* Create the module and populate stuff */
    if (!(m = Py_InitModule3(EXT_MODULE_NAME, EXT_METHODS_VAR, EXT_DOCS_VAR)))
        return;

    ADD_STRING(m, "__author__", "André Malo");
    ADD_STRING(m, "__docformat__", "restructuredtext en");
#ifdef WTF_HAVE_INITGROUPS
    ADD_OBJECT(m, "HAVE_INITGROUPS", Py_True);
#else
    ADD_OBJECT(m, "HAVE_INITGROUPS", Py_False);
#endif
}

/* ------------------------- END MODULE DEFINITION ------------------------- */
