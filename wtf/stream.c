/*
 * Copyright 2007-2012
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

/* ------------------------ BEGIN COMMON DEFINITIONS ----------------------- */

/*
 * Constants
 */
#ifndef WTF_DEFAULT_CHUNK_SIZE
#define WTF_DEFAULT_CHUNK_SIZE (8192) /* Must be > 1 */
#endif

#ifndef WTF_MAX_CACHED_BUFITEMS
#define WTF_MAX_CACHED_BUFITEMS (1024)
#endif

/*
 * Linked list item for buffer chains
 */
typedef struct bufitem {
    struct bufitem *next;  /* Next item. Just in case you're wondering:
                            * For write buffers, this points to the right.
                            * For read buffers, this points to the left. */
    PyObject *load;        /* Item load (a python string) */
} bufitem;

/*
 * Object structure for GenericStreamType
 */
typedef struct {
    PyObject_HEAD

    PyObject *ostream;      /* The stream to actually read/write */
    PyObject *read;         /* The stream's reader */
    PyObject *write;        /* The stream's writer */
    PyObject *flush;        /* The stream's flusher */
    bufitem *wbuf;          /* Current write buffer */
    bufitem *rbuf;          /* Current read buffer */
    bufitem *rbuf_last;     /* Last read buffer item */
    Py_ssize_t chunk_size;  /* Chunk size to use */
    Py_ssize_t blockiter;   /* Block iteration size */
    Py_ssize_t wbuf_size;   /* Current write buffer size */
    Py_ssize_t rbuf_size;   /* Current read buffer size */
    int flags;              /* Flags */
} genericstreamobject;

/* generic stream flags */
#define GENERIC_STREAM_SOFTSPACE (1 << 0)  /* softspace flag */
#define GENERIC_STREAM_CLOSED    (1 << 1)  /* closed flag */
#define GENERIC_STREAM_EOF       (1 << 2)  /* EOF flag (for read()) */
#define GENERIC_STREAM_EXACT     (1 << 3)  /* Read maximum bytes? */

/*
 * Object structure for MinimalSocketStreamType
 */
typedef struct {
    PyObject_HEAD

    PyObject *recv;      /* Receiving function */
    PyObject *send;      /* Sending function */
    PyObject *sock;      /* Socket reference */
    PyObject *exc;       /* socket.error */
    PyObject *enotconn;  /* ENOTCONN */
    int shutdown;        /* Shutdown value, -1 if unset */
} sockstreamobject;

/*
 * Static objects (allocated once at module init time)
 */
static PyObject *emptystring;       /* empty string */
static PyObject *nameproperty;      /* "name" property name */
static PyObject *filenoproperty;    /* "fileno" property name */
static PyObject *isattyproperty;    /* "isatty" property name */
static PyObject *flushproperty;     /* "flush" property name */
static PyObject *closeproperty;     /* "close" property name */
static PyObject *shutdownproperty;  /* "close" property name */
static PyObject *sockstreamname;    /* socket stream name (<socket>) */

/*
 * Object cache
 */
static bufitem  *llcache;   /* Cache for bufitems */
static size_t    llcached;  /* Number of cached bufitems */

/*
 * Forward declarations of this module's type objects
 */
static PyTypeObject GenericStreamType;
static PyTypeObject MinimalSocketStreamType;

/* ------------------------- END COMMON DEFINITIONS ------------------------ */

/* -------------------- BEGIN CUSTOM STRUCT CONSTRUCTORS ------------------- */

static bufitem *
bufitem_new(void)
{
    bufitem *result;

    if (llcache) {
        result = llcache;
        llcache = llcache->next;
        --llcached;
    }
    else if (!(result = PyMem_Malloc(sizeof *result)))
        return (bufitem *)PyErr_NoMemory();

    result->load = NULL;
    return result;
}

static bufitem *
bufitem_del(bufitem *item)
{
    bufitem *oldnext;

    Py_CLEAR(item->load);

    oldnext = item->next;
    if (llcached >= WTF_MAX_CACHED_BUFITEMS)
        PyMem_Free(item);
    else {
        item->next = llcache;
        llcache = item;
        ++llcached;
    }

    return oldnext;
}

/* --------------------- END CUSTOM STRUCT CONSTRUCTORS -------------------- */

/* ------------------- BEGIN GenericStream IMPLEMENTATION ------------------ */

/* Make an argument list out of a read size */
static PyObject *
size2py(Py_ssize_t size)
{
    PyObject *sizeobj, *result;

    if (!(sizeobj = PyInt_FromSsize_t(size)))
        return NULL;
    if (!(result = PyTuple_New(1))) {
        Py_DECREF(sizeobj);
        return NULL;
    }

    PyTuple_SET_ITEM(result, 0, sizeobj);
    return result;
}


/* Determine optimal chunk size for next read */
static PyObject *
optimal_chunk_size(genericstreamobject *self, Py_ssize_t size)
{
    Py_ssize_t chunk_size;
    
    chunk_size = self->chunk_size < 2 ?
        WTF_DEFAULT_CHUNK_SIZE : self->chunk_size;
    if (size > 0) {
        size = size - self->rbuf_size;
        if (size < chunk_size)
            chunk_size = size;
    }

    return size2py(chunk_size);
}


/* Alien reader wrapper */
static PyObject *
alien_read(void *reader_, Py_ssize_t size)
{
    PyObject *sizeobj, *result, *reader=reader_;

    if (!(sizeobj = size2py(size)))
        return NULL;

    result = PyObject_CallObject((PyObject *)reader, sizeobj);
    Py_DECREF(sizeobj);

    if (result) {
        if (!PyString_CheckExact(result)) {
            sizeobj = PyObject_Str(result); /* variable misuse */
            Py_DECREF(result);
            result = sizeobj;
        }
        if (!PyString_GET_SIZE(result)) {
            Py_DECREF(result);
            result = NULL;
        }
    }

    return result;
}


/* Generic exact reader */
static PyObject *
generic_read_exact(PyObject *(*reader)(void *, Py_ssize_t), void *ctx,
                   Py_ssize_t size)
{
    PyObject *result;
    bufitem *start, *item, *newitem;
    char *buf;
    Py_ssize_t vlen;

    if (size < 0)
        return reader(ctx, size);

    /* ok then... fetch the stuff */
    start = item = NULL;
    vlen = 0;
    while (vlen < size) {
        result = reader(ctx, size-vlen);
        if (!result) {
            if (PyErr_Occurred())
                goto error;
            break;
        }
        if (PyString_GET_SIZE(result) > 0) {
            if ((vlen + PyString_GET_SIZE(result)) < vlen) {
                Py_DECREF(result);
                PyErr_SetString(PyExc_OverflowError,
                                "Result buffer got too big");
                goto error;
            }
            if (!(newitem = bufitem_new())) {
                Py_DECREF(result);
                goto error;
            }
            vlen += PyString_GET_SIZE(result);
            newitem->next = NULL;
            newitem->load = result;
            if (!item) {
                start = item = newitem;
            }
            else {
                item->next = newitem;
                item = newitem;
            }
        }
    }

    /* ...and assemble the result */
    if (vlen > 0) {
        if (!(result = PyString_FromStringAndSize(NULL, vlen)))
            goto error;
        buf = PyString_AS_STRING(result);
        while (start) {
            (void)memcpy(buf, PyString_AS_STRING(start->load),
                         (size_t)PyString_GET_SIZE(start->load));
            buf += PyString_GET_SIZE(start->load);
            start = bufitem_del(start);
        }
        return result;
    }

error:
    while (start)
        start = bufitem_del(start);
    return NULL;
}


/* buffer-read a block (return NULL on eof) */
static PyObject *
generic_read(void *self_, Py_ssize_t size)
{
    PyObject *tmp, *result, *sizeobj = NULL;
    bufitem *item;
    genericstreamobject *self=self_;
    char *jptr, *sentinel;
    Py_ssize_t cursize, rsize;

    if (!self->read) {
        PyErr_SetString(PyExc_AttributeError,
            "This stream does not provide a read function"
        );
        return NULL;
    }

    /* return a bufitem */
    if (size == 0) {
        if ((item = self->rbuf_last)) {
            result = item->load;
            Py_INCREF(result);
            if (!(self->rbuf_last = item->next)) {
                self->rbuf = NULL;
                self->rbuf_size = 0;
            }
            else
                self->rbuf_size -= PyString_GET_SIZE(result);
            (void)bufitem_del(item);
            return result;
        }
        else if (self->flags & GENERIC_STREAM_EOF)
            return NULL;
        /* else */
        size = self->chunk_size;
    }

    /* read up to size bytes */
    if (   !(self->flags & GENERIC_STREAM_EOF)
           && (size > 0) && (size > self->rbuf_size)) {
        if (!(sizeobj = optimal_chunk_size(self, size)))
            return NULL;
        if (!(tmp = PyObject_CallObject(self->read, sizeobj)))
            goto error;
        if (PyString_CheckExact(tmp))
            result = tmp;
        else {
            result = PyObject_Str(tmp);
            Py_DECREF(tmp);
            if (!result)
                goto error;
        }

        rsize = PyString_GET_SIZE(result);
        if (rsize > 0) {
            if ((self->rbuf_size + rsize) < self->rbuf_size) {
                PyErr_SetString(PyExc_OverflowError, "Buffer became too big");
                Py_DECREF(result);
                goto error;
            }
            if (!(item = bufitem_new())) {
                Py_DECREF(result);
                goto error;
            }
            item->next = NULL;
            item->load = result;
            if (self->rbuf) {
                self->rbuf->next = item; /* Note to self:         */
                self->rbuf = item;       /* this code is correct. */
                self->rbuf_size += rsize;
            }
            else {
                self->rbuf = self->rbuf_last = item;
                self->rbuf_size = rsize;
            }
        }
        else {
            Py_DECREF(result);
            self->flags |= GENERIC_STREAM_EOF;
        }
    }

    /* slurp it all */
    else if (!(self->flags & GENERIC_STREAM_EOF) && (size < 0)) {
        if (!(sizeobj = optimal_chunk_size(self, size)))
            return NULL;
        while (1) {
            if (!(tmp = PyObject_CallObject(self->read, sizeobj)))
                goto error;
            if (PyString_CheckExact(tmp))
                result = tmp;
            else {
                result = PyObject_Str(tmp);
                Py_DECREF(tmp);
                if (!result)
                    goto error;
            }
            rsize = PyString_GET_SIZE(result);
            if (rsize > 0) {
                if ((self->rbuf_size + rsize) < self->rbuf_size) {
                    PyErr_SetString(PyExc_OverflowError,
                                    "Buffer became too big");
                    Py_DECREF(result);
                    goto error;
                }
                if (!(item = bufitem_new())) {
                    Py_DECREF(result);
                    goto error;
                }
                item->next = NULL;
                item->load = result;
                if (self->rbuf) {
                    self->rbuf->next = item; /* Note to self:         */
                    self->rbuf = item;       /* this code is correct. */
                    self->rbuf_size += rsize;
                }
                else {
                    self->rbuf = self->rbuf_last = item;
                    self->rbuf_size = rsize;
                }
            }
            else {
                Py_DECREF(result);
                self->flags |= GENERIC_STREAM_EOF;
                break;
            }
        }
        size = self->rbuf_size;
    }
    Py_XDECREF(sizeobj);

    if (!self->rbuf_size) {
        self->flags |= GENERIC_STREAM_EOF;
        return NULL;
    }

    /* flatten the bufitems into the result string */
    rsize = size <= self->rbuf_size ? size : self->rbuf_size;
    if (!(result = PyString_FromStringAndSize(NULL, rsize)))
        return NULL;
    jptr = PyString_AS_STRING(result);
    sentinel = jptr + rsize;
    while (jptr < sentinel && (item = self->rbuf_last)) {
        cursize = PyString_GET_SIZE(item->load);
        if (jptr + cursize > sentinel) { /* need to split */
            bufitem *newitem;
            
            if (!(newitem = bufitem_new())) {
                Py_DECREF(result);
                return NULL;
            }
            newitem->next = item->next;
            newitem->load = PyString_FromStringAndSize(
                PyString_AS_STRING(item->load) + (size_t)(sentinel - jptr),
                (cursize - (Py_ssize_t)(sentinel - jptr))
            );
            if (!newitem->load) {
                (void)bufitem_del(newitem);
                Py_DECREF(result);
                return NULL;
            }
            item->next = newitem;
            if (self->rbuf == item)
                self->rbuf = newitem;
            cursize = (Py_ssize_t)(sentinel - jptr);
        }
        (void)memcpy(jptr, PyString_AS_STRING(item->load),
                     (size_t)cursize);
        jptr += cursize;
        self->rbuf_size -= cursize;
        if (self->rbuf == item)
            self->rbuf = NULL;
        self->rbuf_last = bufitem_del(item);
    }

    return result;

error:
    Py_XDECREF(sizeobj);
    return NULL;
}


/* read a line (return NULL on eof) */
static PyObject *
generic_readline(genericstreamobject *self, Py_ssize_t size)
{
    bufitem *linebuf, *item;
    PyObject *result;
    char *jptr;
    const char *newline;
    Py_ssize_t cursize, leftsize, readsize;

    if (size < 0)
        size = 0; /* read default chunks */

    if (!(result = generic_read(self, size))) /* maybe just EOF */
        return NULL;
    if (!(linebuf = bufitem_new())) {
        Py_DECREF(result);
        return NULL;
    }
    linebuf->next = NULL;
    linebuf->load = result;
    item = linebuf;
    readsize = 0;
    for (;;) {
        jptr = PyString_AS_STRING(item->load);
        cursize = PyString_GET_SIZE(item->load);
        if ((readsize + cursize) < readsize) {
            PyErr_SetString(PyExc_OverflowError, "Buffer became too big");
            goto error;
        }
        readsize += cursize;
        leftsize = cursize -
            ((size > 0) && (size < readsize) ? readsize - size: 0);
        if (   (leftsize > 0)
            && (newline = memchr(jptr, '\n', (size_t)leftsize))) {
            /* split at newline */
            size = readsize - cursize + ((Py_ssize_t)(newline - jptr) + 1);
            break;
        }
        else if ((size > 0) && (readsize >= size))
            /* cut it here and now */
            break;

        /* read next chunk, if any */
        result = generic_read(self, size - ((size > 0) ? readsize: 0));
        if (!result) {
            if (PyErr_Occurred())
                goto error;
            /* else */
            size = readsize;
            break;
        }
        if (!(item->next = bufitem_new())) {
            Py_DECREF(result);
            goto error;
        }
        item = item->next;
        item->next = NULL;
        item->load = result;
    }

    /* flatten the buffer chain */
    if (size == 0)
        size = readsize; /* > 0 by definition */
    if (!(result = PyString_FromStringAndSize(NULL, size)))
        goto error;
    jptr = PyString_AS_STRING(result);
    newline = jptr + (size_t)size;
    while (linebuf && (jptr < newline)) {
        cursize = PyString_GET_SIZE(linebuf->load);
        if ((jptr + cursize) > newline) { /* need to split */
            if (!(item = bufitem_new())) {
                Py_DECREF(result);
                goto error;
            }
            item->next = linebuf->next;
            item->load = PyString_FromStringAndSize(
                PyString_AS_STRING(linebuf->load) + (size_t)(newline - jptr),
                (cursize - (Py_ssize_t)(newline - jptr))
            );
            if (!item->load) {
                (void)bufitem_del(item);
                Py_DECREF(result);
                goto error;
            }
            linebuf->next = item;
            cursize = (Py_ssize_t)(newline - jptr);
        }
        (void)memcpy(jptr, PyString_AS_STRING(linebuf->load),
                     (size_t)cursize);
        jptr += cursize;
        linebuf = bufitem_del(linebuf);
    }
    /* push back unused data */
    if (linebuf) {
        item = linebuf;
        readsize = PyString_GET_SIZE(item->load);
        while (item->next) {
            item = item->next;
            readsize += PyString_GET_SIZE(item->load);
        }
        if (self->rbuf_last) {
            item->next = self->rbuf_last;
            self->rbuf_last = linebuf;
            self->rbuf_size += readsize; /* just read from it, need no check */
        }
        else {
            self->rbuf = item;
            self->rbuf_last = linebuf;
            self->rbuf_size = readsize;
        }
    }

    return result;

error:
    item = linebuf;
    while ((item = bufitem_del(item)))
        ;
    return NULL;
}


/* flush the write buffer */
static int
generic_flush(genericstreamobject *self, int passdown)
{
    bufitem *current;
    PyObject *joined, *result;
    char *jptr;
    Py_ssize_t size;

    if (!self->write) {
        PyErr_SetString(PyExc_AttributeError,
            "This stream does not provide a write function"
        );
        return -1;
    }

    if (self->wbuf && self->wbuf_size > 0) {
        joined = PyString_FromStringAndSize(NULL, self->wbuf_size);
        jptr = PyString_AS_STRING(joined) + self->wbuf_size;
        current = self->wbuf;
        self->wbuf = NULL;
        self->wbuf_size = 0;
        while (current) {
            size = PyString_GET_SIZE(current->load);
            jptr -= size;
            (void)memcpy(jptr, PyString_AS_STRING(current->load),
                         (size_t)size);
            current = bufitem_del(current);
        }
        result = PyObject_CallFunction(self->write, "(O)", joined);
        Py_DECREF(joined);
        if (!result)
            return -1;
        Py_DECREF(result);
    }

    if (passdown) {
        if (!self->flush) {
            if (!(result = PyObject_GetAttr(self->ostream, flushproperty))) {
                if (!PyErr_ExceptionMatches(PyExc_AttributeError))
                    return -1;
                PyErr_Clear();
                Py_INCREF(Py_None);
                self->flush = Py_None;
            }
            else
                self->flush = result;
        }
        if (    (self->flush != Py_None)
            && !(result = PyObject_CallObject(self->flush, NULL)))
            return -1;
    }

    return 0;
}


/* Write stuff to the write buffer (possibly flush it) */
static int
generic_write(genericstreamobject *self, PyObject *data)
{
    PyObject *datastr;
    bufitem *item;
    Py_ssize_t size;

    if (!(datastr = PyObject_Str(data)))
        return -1;
    if (!(item = bufitem_new()))
        goto error;

    size = self->wbuf_size + PyString_GET_SIZE(datastr);
    if ((size < self->wbuf_size) && (generic_flush(self, 0) == -1))
        goto error_item;
    item->load = datastr;
    item->next = self->wbuf;
    self->wbuf_size += PyString_GET_SIZE(datastr);
    self->wbuf = item;
    if ((self->wbuf_size > self->chunk_size) && (generic_flush(self, 0) == -1))
        return -1;

    return 0;

error_item:
    (void)bufitem_del(item);
error:
    Py_DECREF(datastr);
    return -1;
}


/* Close the stream */
static int
generic_close(genericstreamobject *self)
{
    PyObject *tmp, *closefn;
    PyObject *ptype = NULL, *pvalue, *ptraceback;

    if (!(self->flags & GENERIC_STREAM_CLOSED)) {
        if (generic_flush(self, 0) == -1) {
            if (PyErr_ExceptionMatches(PyExc_AttributeError)) {
                PyErr_Clear();
            }
            else {
                PyErr_Fetch(&ptype, &pvalue, &ptraceback);
                PyErr_Clear();
            }
        }
        self->flags |= GENERIC_STREAM_CLOSED;

        if (!(closefn = PyObject_GetAttr(self->ostream, closeproperty))) {
            if (!PyErr_ExceptionMatches(PyExc_AttributeError))
                goto error;
            PyErr_Clear();
        }
        else {
            tmp = PyObject_CallObject(closefn, NULL);
            Py_DECREF(closefn);
            if (!tmp)
                goto error;
            Py_DECREF(tmp);
        }

        if (ptype)
            goto error;
    }
    return 0;

error:
    if (PyErr_Occurred()) {
        if (ptype) {
            Py_DECREF(ptype);
            Py_DECREF(pvalue);
            Py_DECREF(ptraceback);
        }
    }
    else {
        PyErr_Restore(ptype, pvalue, ptraceback);
    }
    return -1;
}

/* -------------------- END GenericStream IMPLEMENTATION ------------------- */

/* ------------------- BEGIN GenericStreamType DEFINITION ------------------ */

static PyObject *
GenericStreamType_getname(genericstreamobject *self, void *closure)
{
    return PyObject_GetAttr(self->ostream, nameproperty);
}

static PyObject *
GenericStreamType_getclosed(genericstreamobject *self, void *closure)
{
    if (self->flags & GENERIC_STREAM_CLOSED)
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
GenericStreamType_getsoftspace(genericstreamobject *self, void *closure)
{
    if (self->flags & GENERIC_STREAM_SOFTSPACE)
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static int
GenericStreamType_setsoftspace(genericstreamobject *self, PyObject *value,
                               void *closure)
{
    int bval;

    if ((bval = PyObject_IsTrue(value)) == -1)
        return -1;

    if (bval)
        self->flags |= GENERIC_STREAM_SOFTSPACE;
    else
        self->flags &= ~GENERIC_STREAM_SOFTSPACE;

    return 0;
}

static PyGetSetDef GenericStreamType_getset[] = {
    {"name",
     (getter)GenericStreamType_getname,
     NULL,
     NULL, NULL},

    {"closed",
     (getter)GenericStreamType_getclosed,
     NULL,
     NULL, NULL},

    {"softspace",
     (getter)GenericStreamType_getsoftspace,
     (setter)GenericStreamType_setsoftspace,
     NULL, NULL},

    {NULL}  /* Sentinel */
};

PyDoc_STRVAR(GenericStreamType_read__doc__,
"``s.read([size]) -> str``\n\
\n\
Reads a specified amount of bytes (at max) from the stream\n\
\n\
Parameters\n\
----------\n\
- ``size``: The maximum number of bytes to read (``< 0`` means\n\
  to slurp the whole stream; ``== 0`` means to return the current\n\
  buffer or the next buffer it the current buffer is empty)\n\
\n\
Types\n\
-----\n\
- ``size``: ``int``\n\
\n\
:return: The read bytes; if empty you've hit EOF\n\
:rtype: ``str``\n\
\n\
:Exceptions:\n\
 - `ValueError`: The stream is closed");

static PyObject *
GenericStreamType_read(genericstreamobject *self, PyObject *args)
{
    PyObject *blob = NULL;
    Py_ssize_t size = -1;

    if (!PyArg_ParseTuple(args, "|O", &blob))
        return NULL;

    if (blob) {
        size = PyInt_AsSsize_t(blob);
        if (PyErr_Occurred())
            return NULL;
    }
    if (self->flags & GENERIC_STREAM_EXACT)
        blob = generic_read_exact(generic_read, self, size);
    else
        blob = generic_read(self, size);

    if (!blob && !PyErr_Occurred())
        return Py_INCREF(emptystring), emptystring;
    return blob;
}

PyDoc_STRVAR(GenericStreamType_read_exact__doc__,
"``s.read_exact([size]) -> str``\n\
\n\
Read exactly size bytes from stream, except on EOF\n\
\n\
Parameters\n\
----------\n\
- ``size``: The maximum number of bytes to read (``< 0`` means\n\
  to slurp the whole stream; ``== 0`` means to return the current\n\
  buffer or the next buffer it the current buffer is empty)\n\
\n\
Types\n\
-----\n\
- ``size``: ``int``\n\
\n\
:return: The read bytes; if empty you've hit EOF\n\
:rtype: ``str``\n\
\n\
:Exceptions:\n\
 - `ValueError`: The stream is closed");

static PyObject *
GenericStreamType_read_exact(genericstreamobject *self, PyObject *args)
{
    PyObject *blob = NULL;
    Py_ssize_t size = -1;

    if (!PyArg_ParseTuple(args, "|O", &blob))
        return NULL;

    if (blob) {
        size = PyInt_AsSsize_t(blob);
        if (PyErr_Occurred())
            return NULL;
    }

    blob = generic_read_exact(generic_read, self, size);
    if (!blob && !PyErr_Occurred())
        return Py_INCREF(emptystring), emptystring;
    return blob;
}

PyDoc_STRVAR(GenericStreamType_readline__doc__,
"``s.readline([size]) -> line``\n\
\n\
Read a line from the stream\n\
\n\
Parameters\n\
----------\n\
- ``size``: The maximum number of bytes to read (``<= 0`` means\n\
  to read until the next newline or EOF, which is the default\n\
  behaviour)\n\
\n\
Types\n\
-----\n\
- ``size``: ``int``\n\
\n\
:return: The read bytes including the newline; if empty you've hit\n\
         EOF\n\
:rtype: ``str``");

static PyObject *
GenericStreamType_readline(genericstreamobject *self, PyObject *args)
{
    PyObject *line = NULL;
    Py_ssize_t size = 0;

    if (!(PyArg_ParseTuple(args, "|O", &line)))
        return NULL;

    if (line) {
        size = PyInt_AsSsize_t(line);
        if (PyErr_Occurred())
            return NULL;
    }
    if (!(line = generic_readline(self, size)) && !PyErr_Occurred())
        return Py_INCREF(emptystring), emptystring;
    return line;
}

PyDoc_STRVAR(GenericStreamType_readlines__doc__,
"``s.readlines([size]) -> [line, ...]``\n\
\n\
Read all lines from the stream\n\
\n\
Parameters\n\
----------\n\
- ``size``: The maximum number of bytes to read per line (``<= 0`` means\n\
  to read until the next newline or EOF, which is the default\n\
  behaviour)\n\
\n\
Types\n\
-----\n\
- ``size``: ``int``\n\
\n\
:return: The list of lines\n\
:rtype: ``list``");

static PyObject *
GenericStreamType_readlines(genericstreamobject *self, PyObject *args)
{
    PyObject *lines, *line = NULL;
    Py_ssize_t size = 0;

    if (!(PyArg_ParseTuple(args, "|O", &line)))
        return NULL;

    if (line) {
        size = PyInt_AsSsize_t(line);
        if (PyErr_Occurred())
            return NULL;
        if (size < 0)
            size = 0;
    }
    if (!(lines = PyList_New(0)))
        return NULL;
    while ((line = generic_readline(self, size))) {
        if (PyList_Append(lines, line) == -1)
            goto error;
        Py_DECREF(line);
    }
    if (PyErr_Occurred())
        goto error;

    return lines;

error:
    Py_DECREF(lines);
    return NULL;
}

PyDoc_STRVAR(GenericStreamType_xreadlines__doc__,
"``s.xreadlines()``\n\
\n\
Iterator of the lines\n\
\n\
:Depreciated: Use the iterator API instead");

static PyObject *
GenericStreamType_xreadlines(PyObject *self, PyObject *args)
{
    return Py_INCREF(self), self;
}

PyDoc_STRVAR(GenericStreamType_write__doc__,
"``s.write(data)``\n\
\n\
Write data into the stream\n\
\n\
Parameters\n\
----------\n\
- ``data``: The data to write\n\
\n\
Types\n\
-----\n\
- ``data``: ``str``");

static PyObject *
GenericStreamType_write(genericstreamobject *self, PyObject *args)
{
    PyObject *data;

    if (!PyArg_ParseTuple(args, "O", &data))
        return NULL;

    if (generic_write(self, data) == -1)
        return NULL;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(GenericStreamType_writelines__doc__,
"``s.writelines(lines)``\n\
\n\
Write lines to the stream\n\
\n\
Parameters\n\
----------\n\
- ``lines``: The list of lines to write\n\
\n\
Types\n\
-----\n\
- ``lines``: ``iterable``");

static PyObject *
GenericStreamType_writelines(genericstreamobject *self, PyObject *args)
{
    PyObject *line, *iter;
    int result;

    if (!PyArg_ParseTuple(args, "O", &line))
        return NULL;
    if (!(iter = PyObject_GetIter(line)))
        return NULL;

    while ((line = PyIter_Next(iter))) {
        result = generic_write(self, line);
        Py_DECREF(line);
        if (result == -1)
            goto error;
    }
    if (PyErr_Occurred())
        goto error;

    Py_DECREF(iter);
    Py_RETURN_NONE;

error:
    Py_DECREF(iter);
    return NULL;
}

PyDoc_STRVAR(GenericStreamType_close__doc__,
"``s.close()``\n\
\n\
Close the stream\n\
\n\
The call is passed to the underlying octet stream.");

static PyObject *
GenericStreamType_close(genericstreamobject *self, PyObject *args)
{
    if (generic_close(self) == -1)
        return NULL;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(GenericStreamType_flush__doc__,
"``s.flush()``\n\
\n\
Flush the write buffer");

static PyObject *
GenericStreamType_flush(genericstreamobject *self, PyObject *args)
{
    if (generic_flush(self, 1) == -1)
        return NULL;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(GenericStreamType_fileno__doc__,
"``s.fileno()``\n\
\n\
Determine underlying fileno");

static PyObject *
GenericStreamType_fileno(genericstreamobject *self, PyObject *args)
{
    return PyObject_CallMethodObjArgs(self->ostream, filenoproperty, NULL);
}

PyDoc_STRVAR(GenericStreamType_isatty__doc__,
"``s.isatty()``\n\
\n\
Does the stream refer to a tty?\n\
\n\
:return: Does the stream refer to a tty?\n\
:rtype: ``bool``");

static PyObject *
GenericStreamType_isatty(genericstreamobject *self, PyObject *args)
{
    PyObject *func, *result;

    func = PyObject_GetAttr(self->ostream, isattyproperty);
    if (!func) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError))
            return NULL;
        Py_RETURN_FALSE;
    }
    result = PyObject_CallObject(func, NULL);
    Py_DECREF(func);
    return result;
}

static PyObject *
GenericStreamType__del__(genericstreamobject *self, PyObject *args)
{
    if (generic_close(self) == -1)
        return NULL;
    Py_RETURN_NONE;
}

static struct PyMethodDef GenericStreamType_methods[] = {
    {"__del__",
     (PyCFunction)GenericStreamType__del__,      METH_NOARGS,
     NULL},

    {"read",
     (PyCFunction)GenericStreamType_read,        METH_VARARGS,
     GenericStreamType_read__doc__},

    {"read_exact",
     (PyCFunction)GenericStreamType_read_exact,  METH_VARARGS,
     GenericStreamType_read_exact__doc__},

    {"readline",
     (PyCFunction)GenericStreamType_readline,    METH_VARARGS,
     GenericStreamType_readline__doc__},

    {"readlines",
     (PyCFunction)GenericStreamType_readlines,   METH_VARARGS,
     GenericStreamType_readlines__doc__},

    {"xreadlines",
     (PyCFunction)GenericStreamType_xreadlines,  METH_NOARGS,
     GenericStreamType_xreadlines__doc__},

    {"write",
     (PyCFunction)GenericStreamType_write,       METH_VARARGS,
     GenericStreamType_write__doc__},

    {"writelines",
     (PyCFunction)GenericStreamType_writelines,  METH_VARARGS,
     GenericStreamType_writelines__doc__},

    {"close",
     (PyCFunction)GenericStreamType_close,       METH_NOARGS,
     GenericStreamType_close__doc__},

    {"flush",
     (PyCFunction)GenericStreamType_flush,       METH_NOARGS,
     GenericStreamType_flush__doc__},

    {"fileno",
     (PyCFunction)GenericStreamType_fileno,      METH_NOARGS,
     GenericStreamType_fileno__doc__},

    {"isatty",
     (PyCFunction)GenericStreamType_isatty,      METH_NOARGS,
     GenericStreamType_isatty__doc__},

    {NULL, NULL}  /* Sentinel */
};

static PyObject *
GenericStreamType_iter(PyObject *self)
{
    return Py_INCREF(self), self;
}

static PyObject *
GenericStreamType_iternext(genericstreamobject *self)
{
    if (self->blockiter == 1)
        return generic_readline(self, 0);

    return generic_read(self, self->blockiter);
}

static void
GenericStreamType_dealloc(genericstreamobject *self)
{
    bufitem *item;

    for (item = self->rbuf; item; item = bufitem_del(item))
        ;
    for (item = self->wbuf; item; item = bufitem_del(item))
        ;
    Py_CLEAR(self->flush);
    Py_CLEAR(self->write);
    Py_CLEAR(self->read);
    Py_CLEAR(self->ostream);

    ((PyObject *)self)->ob_type->tp_free(self);
}

static PyObject *
GenericStreamType_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"stream", "buffering", "blockiter", "read_exact",
                             NULL};
    PyObject *ostream, *buffering=NULL, *blockiter=NULL, *read_exact=NULL;
    genericstreamobject *self;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|OOO", kwlist,
                                     &ostream, &buffering, &blockiter,
                                     &read_exact))
        return NULL;

    if (!(self = (genericstreamobject *)type->tp_alloc(type, 0)))
        return NULL;

    self->read = NULL;
    self->write = NULL;
    self->flush = NULL;
    self->wbuf = NULL;
    self->rbuf = NULL;
    self->rbuf_last = NULL;
    self->rbuf_size = 0;
    self->wbuf_size = 0;
    self->flags = 0;

    Py_INCREF(ostream);
    self->ostream = ostream;
    if (!(self->read = PyObject_GetAttrString(ostream, "read")))
        PyErr_Clear();
    if (!(self->write = PyObject_GetAttrString(ostream, "write")))
        PyErr_Clear();

    if (!buffering)
        self->chunk_size = WTF_DEFAULT_CHUNK_SIZE;
    else {
        Py_ssize_t chunk_size;

        chunk_size = PyInt_AsSsize_t(buffering);
        if (PyErr_Occurred())
            goto error;
        if (chunk_size < 0)
            self->chunk_size = WTF_DEFAULT_CHUNK_SIZE;
        else if (chunk_size == 0)
            self->chunk_size = 1;
        else
            self->chunk_size = chunk_size;
    }

    if (!blockiter)
        self->blockiter = 1;
    else {
        Py_ssize_t bsize;

        bsize = PyInt_AsSsize_t(blockiter);
        if (PyErr_Occurred())
            goto error;
        if (bsize <= 0)
            self->blockiter = WTF_DEFAULT_CHUNK_SIZE;
        else if (bsize == 1)
            self->blockiter = 1;
        else
            self->blockiter = bsize;
    }

    if (read_exact) {
        int read_exact_bool = PyObject_IsTrue(read_exact);
        if (read_exact_bool == -1)
            goto error;
        else if (read_exact_bool)
            self->flags |= GENERIC_STREAM_EXACT;
    }

    return (PyObject *)self;

error:
    Py_DECREF(self);
    return NULL;
}

PyDoc_STRVAR(GenericStreamType__doc__,
"``GenericStream(stream[, buffering])``\n\
\n\
Represents a buffered stream");

static PyTypeObject GenericStreamType = {
    PyObject_HEAD_INIT(NULL)
    0,                                                  /* ob_size */
    EXT_MODULE_PATH ".GenericStream",                   /* tp_name */
    sizeof(genericstreamobject),                        /* tp_basicsize */
    0,                                                  /* tp_itemsize */
    (destructor)GenericStreamType_dealloc,              /* tp_dealloc */
    0,                                                  /* tp_print */
    0,                                                  /* tp_getattr */
    0,                                                  /* tp_setattr */
    0,                                                  /* tp_compare */
    0,                                                  /* tp_repr */
    0,                                                  /* tp_as_number */
    0,                                                  /* tp_as_sequence */
    0,                                                  /* tp_as_mapping */
    0,                                                  /* tp_hash */
    0,                                                  /* tp_call */
    0,                                                  /* tp_str */
    0,                                                  /* tp_getattro */
    0,                                                  /* tp_setattro */
    0,                                                  /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT                                  /* tp_flags */
    | Py_TPFLAGS_BASETYPE,
    GenericStreamType__doc__,                           /* tp_doc */
    0,                                                  /* tp_traverse */
    0,                                                  /* tp_clear */
    0,                                                  /* tp_richcompare */
    0,                                                  /* tp_weaklistoffset */
    (getiterfunc)GenericStreamType_iter,                /* tp_iter */
    (iternextfunc)GenericStreamType_iternext,           /* tp_iternext */
    GenericStreamType_methods,                          /* tp_methods */
    0,                                                  /* tp_members */
    GenericStreamType_getset,                           /* tp_getset */
    0,                                                  /* tp_base */
    0,                                                  /* tp_dict */
    0,                                                  /* tp_descr_get */
    0,                                                  /* tp_descr_set */
    0,                                                  /* tp_dictoffset */
    0,                                                  /* tp_init */
    0,                                                  /* tp_alloc */
    GenericStreamType_new,                              /* tp_new */
};

/* -------------------- END GenericStreamType DEFINITION ------------------- */

/* ---------------- BEGIN MinimalSocketStreamType DEFINITION --------------- */

static PyObject *
MinimalSocketStreamType_getname(sockstreamobject *self, void *closure)
{
    Py_INCREF(sockstreamname);
    return sockstreamname;
}

static PyObject *
MinimalSocketStreamType_getclosed(sockstreamobject *self, void *closure)
{
    if (self->send && self->recv && self->sock)
        Py_RETURN_FALSE;

    Py_RETURN_TRUE;
}

static PyGetSetDef MinimalSocketStreamType_getset[] = {
    {"name",
     (getter)MinimalSocketStreamType_getname,
     NULL,
     NULL, NULL},

    {"closed",
     (getter)MinimalSocketStreamType_getclosed,
     NULL,
     NULL, NULL},

    {NULL}  /* Sentinel */
};


PyDoc_STRVAR(MinimalSocketStreamType_read__doc__,
"``s.read(size)`` -> bytes\n\
\n\
Read ``size`` bytes (or less) from the socket\n\
\n\
Parameters\n\
----------\n\
- ``size``: The number of bytes to read (``> 0``)\n\
\n\
Types\n\
-----\n\
- ``size``: ``int``\n\
\n\
:return: The bytes read\n\
:rtype: ``str``\n\
\n\
:Exceptions:\n\
 - `ValueError`: The stream is closed\n\
 - `socket.error`: Something happened to the socket");

static PyObject *
MinimalSocketStreamType_read(sockstreamobject *self, PyObject *args)
{
    if (!self->recv) {
        PyErr_SetString(PyExc_ValueError, "I/O operation on closed stream");
        return NULL;
    }
    return PyObject_CallObject(self->recv, args);
}

PyDoc_STRVAR(MinimalSocketStreamType_write__doc__,
"``s.write(data)``\n\
\n\
Write data to the socket\n\
\n\
Parameters\n\
----------\n\
- ``data``: The data to write\n\
\n\
Types\n\
-----\n\
- ``data``: ``str``\n\
\n\
:Exceptions:\n\
 - `ValueError`: The stream is closed\n\
 - `socket.error`: Something happened to the socket");

static PyObject *
MinimalSocketStreamType_write(sockstreamobject *self, PyObject *args)
{
    if (!self->send) {
        PyErr_SetString(PyExc_ValueError, "I/O operation on closed stream");
        return NULL;
    }
    return PyObject_CallObject(self->send, args);
}

/*
 * Shutdown socket
 *
 * Steals sock reference
 */
static int
sock_shutdown(PyObject *sock, int shutdown, PyObject *exc, PyObject *enotconn)
{
    PyObject *func, *tmp;
    PyObject *ptype, *pvalue, *ptb;
    int cmp;

    func = PyObject_GetAttr(sock, shutdownproperty);
    Py_DECREF(sock);
    if (!func) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError))
            return -1;
        PyErr_Clear();
        return 0;
    }
    tmp = PyObject_CallFunction(func, "(i)", shutdown);
    Py_DECREF(func);
    if (tmp) {
        Py_DECREF(tmp);
        return 0;
    }

    if (!PyErr_ExceptionMatches(exc))
        return -1;
    PyErr_Fetch(&ptype, &pvalue, &ptb);
    if (!pvalue) {
        PyErr_Restore(ptype, pvalue, ptb);
        return -1;
    }
    if (!(tmp = PyLong_FromLong(0))) {
        PyErr_Restore(ptype, pvalue, ptb);
        return -1;
    }
    func = PyObject_GetItem(pvalue, tmp);
    Py_DECREF(tmp);
    if (!func) {
        Py_DECREF(ptype);
        Py_DECREF(pvalue);
        Py_DECREF(ptb);
        return -1;
    }
    cmp = PyObject_Compare(func, enotconn);
    Py_DECREF(func);
    if (PyErr_Occurred()) {
        Py_DECREF(ptype);
        Py_DECREF(pvalue);
        Py_DECREF(ptb);
        return -1;
    }
    if (cmp != 0) {
        PyErr_Restore(ptype, pvalue, ptb);
        return -1;
    }
    Py_DECREF(ptype);
    Py_DECREF(pvalue);
    Py_DECREF(ptb);

    return 0;
}

static int
sock_close(PyObject *sock, int shutdown, PyObject *exc, PyObject *enotconn)
{
    PyObject *func, *tmp;

    if  (shutdown >= 0) {
        if (sock_shutdown(sock, shutdown, exc, enotconn) == -1)
            return -1;
    }
    else {
        func = PyObject_GetAttr(sock, closeproperty);
        Py_DECREF(sock);
        if (!func) {
            if (!PyErr_ExceptionMatches(PyExc_AttributeError))
                return -1;
            PyErr_Clear();
        }
        else {
            tmp = PyObject_CallObject(func, NULL);
            Py_DECREF(func);
            if (!tmp)
                return -1;
            Py_DECREF(tmp);
        }
    }

    return 0;
}


PyDoc_STRVAR(MinimalSocketStreamType_close__doc__,
"``s.close()``\n\
\n\
Close the stream (not necessarily the socket)");

static PyObject *
MinimalSocketStreamType_close(sockstreamobject *self, PyObject *args)
{
    PyObject *tmp;

    Py_CLEAR(self->send);
    Py_CLEAR(self->recv);
    if (self->sock) {
        tmp = self->sock;
        self->sock = NULL;
        if (sock_close(tmp, self->shutdown, self->exc, self->enotconn) == -1)
            return NULL;
    }
    Py_RETURN_NONE;
}


static struct PyMethodDef MinimalSocketStreamType_methods[] = {
    {"read",
     (PyCFunction)MinimalSocketStreamType_read,     METH_VARARGS,
     MinimalSocketStreamType_read__doc__},

    {"write",
     (PyCFunction)MinimalSocketStreamType_write,    METH_VARARGS,
     MinimalSocketStreamType_write__doc__},

    {"close",
     (PyCFunction)MinimalSocketStreamType_close,    METH_NOARGS,
     MinimalSocketStreamType_close__doc__},

    {NULL, NULL}  /* Sentinel */
};

static PyObject *
MinimalSocketStreamType_getattro(sockstreamobject *self, PyObject *name)
{
    PyObject *tmp;

    if (!(self->sock)) {
        PyErr_SetObject(PyExc_AttributeError, name);
        return NULL;
    }
    if (!(tmp = PyObject_GenericGetAttr((PyObject *)self, name))) {
        if (!self->sock || !PyErr_ExceptionMatches(PyExc_AttributeError))
            return NULL;
        PyErr_Clear();
    }
    else
        return tmp;

    return PyObject_GetAttr(self->sock, name);
}

static void
MinimalSocketStreamType_dealloc(sockstreamobject *self)
{
    PyObject *tmp;

    Py_CLEAR(self->send);
    Py_CLEAR(self->recv);
    tmp = self->sock;
    self->sock = NULL;
    if (tmp)
        if (sock_close(tmp, self->shutdown, self->exc, self->enotconn) == -1)
            PyErr_Clear();
    Py_CLEAR(self->exc);
    Py_CLEAR(self->enotconn);

    PyObject_Del(self);
}

static PyObject *
MinimalSocketStreamType_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"sock", "shutdown", NULL};
    PyObject *sock;
    sockstreamobject *self;
    int shutdown = -1;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|i", kwlist,
                                     &sock, &shutdown))
        return NULL;

    if (!(self = PyObject_New(sockstreamobject, &MinimalSocketStreamType)))
        return NULL;

    Py_INCREF(sock);
    self->sock = sock;
    self->send = NULL;
    self->exc = NULL;
    self->enotconn = NULL;
    self->shutdown = -1;

    if (!(self->recv = PyObject_GetAttrString(sock, "recv")))
        goto error;
    if (!(self->send = PyObject_GetAttrString(sock, "sendall")))
        goto error;

    if (!(sock = PyImport_ImportModule("socket")))
        goto error;
    self->exc = PyObject_GetAttrString(sock, "error");
    Py_DECREF(sock);
    if (!self->exc)
        goto error;

    if (!(sock = PyImport_ImportModule("errno")))
        goto error;
    self->enotconn = PyObject_GetAttrString(sock, "ENOTCONN");
    Py_DECREF(sock);
    if (!self->enotconn)
        goto error;

    if (shutdown <= -1)
        self->shutdown = -1;
    else
        self->shutdown = shutdown;

    return (PyObject *)self;

error:
    Py_DECREF(self);
    return NULL;
}

PyDoc_STRVAR(MinimalSocketStreamType__doc__,
"``MinimalSocketStream(sock)``\n\
\n\
Minimal stream out of a socket\n\
\n\
This effectively maps ``recv`` to ``read`` and ``sendall`` to ``write``.\n\
\n\
:See: `GenericStream`");

static PyTypeObject MinimalSocketStreamType = {
    PyObject_HEAD_INIT(NULL)
    0,                                                  /* ob_size */
    EXT_MODULE_PATH ".MinimalSocketStream",             /* tp_name */
    sizeof(sockstreamobject),                           /* tp_basicsize */
    0,                                                  /* tp_itemsize */
    (destructor)MinimalSocketStreamType_dealloc,        /* tp_dealloc */
    0,                                                  /* tp_print */
    0,                                                  /* tp_getattr */
    0,                                                  /* tp_setattr */
    0,                                                  /* tp_compare */
    0,                                                  /* tp_repr */
    0,                                                  /* tp_as_number */
    0,                                                  /* tp_as_sequence */
    0,                                                  /* tp_as_mapping */
    0,                                                  /* tp_hash */
    0,                                                  /* tp_call */
    0,                                                  /* tp_str */
    (getattrofunc)MinimalSocketStreamType_getattro,     /* tp_getattro */
    0,                                                  /* tp_setattro */
    0,                                                  /* tp_as_buffer */
    Py_TPFLAGS_HAVE_WEAKREFS                            /* tp_flags */
    | Py_TPFLAGS_HAVE_CLASS
    | Py_TPFLAGS_BASETYPE,
    MinimalSocketStreamType__doc__,                     /* tp_doc */
    0,                                                  /* tp_traverse */
    0,                                                  /* tp_clear */
    0,                                                  /* tp_richcompare */
    0,                                                  /* tp_weaklistoffset */
    0,                                                  /* tp_iter */
    0,                                                  /* tp_iternext */
    MinimalSocketStreamType_methods,                    /* tp_methods */
    0,                                                  /* tp_members */
    MinimalSocketStreamType_getset,                     /* tp_getset */
    0,                                                  /* tp_base */
    0,                                                  /* tp_dict */
    0,                                                  /* tp_descr_get */
    0,                                                  /* tp_descr_set */
    0,                                                  /* tp_dictoffset */
    0,                                                  /* tp_init */
    0,                                                  /* tp_alloc */
    MinimalSocketStreamType_new,                        /* tp_new */
};

/* ----------------- END MinimalSocketStreamType DEFINITION ---------------- */

/* ------------------------- BEGIN GLOBAL FUNCTIONS ------------------------ */

PyDoc_STRVAR(wtf_read_exact__doc__,
"read_exact(stream, size)\n\
\n\
Read exactly size bytes from stream, except on EOF\n\
\n\
:Parameters:\n\
 - `stream`: The stream to read from.\n\
 - `size`: expected number of bytes\n\
\n\
:Types:\n\
 - `stream`: ``file``\n\
 - `size`: ``int``\n\
\n\
:return: The read bytes\n\
:rtype: ``str``");

static PyObject *
wtf_read_exact(PyObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"stream", "size", NULL};
    PyObject *stream, *size_, *reader;
    Py_ssize_t size;
    int eof;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "OO", kwlist,
                                     &stream, &size_))
        return NULL;

    if (!(reader = PyObject_GetAttrString(stream, "read")))
        return NULL;

    size = PyInt_AsSsize_t(size_);
    if (PyErr_Occurred())
        return NULL;

    eof = (   !(stream = generic_read_exact(alien_read, reader, size))
           && !PyErr_Occurred());
    Py_DECREF(reader);

    if (eof)
        return Py_INCREF(emptystring), emptystring;
    return stream;
}

/* -------------------------- END GLOBAL FUNCTIONS ------------------------- */

/* ------------------------ BEGIN MODULE DEFINITION ------------------------ */

EXT_METHODS = {
    {"read_exact",
        (PyCFunction)wtf_read_exact, METH_KEYWORDS,
        wtf_read_exact__doc__},

    {NULL}  /* Sentinel */
};

PyDoc_STRVAR(EXT_DOCS_VAR,
"C implementations of stream wrappers\n\
=====================================\n\
\n\
This module provides some speedy stream wrappers for WTF.");


#define INIT_TYPE(TYPE) do {    \
    if (PyType_Ready(TYPE) < 0) \
        return;                 \
} while (0)

#define INIT_PYSTRING(NAME, VALUE) do {                \
    if (!NAME && !(NAME = PyString_FromString(VALUE))) \
        return;                                        \
} while (0)

#define ADD_STRING(MODULE, NAME, STRING) do {                 \
    if (PyModule_AddStringConstant(MODULE, NAME, STRING) < 0) \
        return;                                               \
} while (0)

#define ADD_TYPE(MODULE, NAME, TYPE) do {                         \
    Py_INCREF(TYPE);                                              \
    if (PyModule_AddObject(MODULE, NAME, (PyObject *)(TYPE)) < 0) \
        return;                                                   \
} while (0)

EXT_INIT_FUNC {
    PyObject *m;

    /* Init static objects */
    INIT_TYPE(&GenericStreamType);
    INIT_TYPE(&MinimalSocketStreamType);

    INIT_PYSTRING(emptystring, "");
    INIT_PYSTRING(nameproperty, "name");
    INIT_PYSTRING(filenoproperty, "fileno");
    INIT_PYSTRING(isattyproperty, "isatty");
    INIT_PYSTRING(flushproperty, "flush");
    INIT_PYSTRING(closeproperty, "close");
    INIT_PYSTRING(shutdownproperty, "shutdown");
    INIT_PYSTRING(sockstreamname, "<socket>");

    /* Create the module and populate stuff */
    if (!(m = Py_InitModule3(EXT_MODULE_NAME, EXT_METHODS_VAR, EXT_DOCS_VAR)))
        return;

    ADD_STRING(m, "__author__", "André Malo");
    ADD_STRING(m, "__docformat__", "restructuredtext en");

    /* add user concerning types */
    ADD_TYPE(m, "GenericStream", &GenericStreamType);
    ADD_TYPE(m, "MinimalSocketStream", &MinimalSocketStreamType);
}

/* ------------------------- END MODULE DEFINITION ------------------------- */
