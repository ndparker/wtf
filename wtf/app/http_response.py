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
Response codes
==============

This module stores HTTP response codes.

:Variables:
 - `classes`: Mapping status code -> HTTPResponse
   (``{status: HTTPResponse, ...}``)
 - `reasons`: Mapping status code -> reason phrase
   (``{status: 'reason', ...}``)

:Types:
 - `classes`: ``dict``
 - `reasons`: ``dict``
"""
__author__ = u"Andr\xe9 Malo"
__docformat__ = "restructuredtext en"

from wtf import webutil as _webutil


class HTTPResponse(SystemExit):
    """
    Base HTTP error response exception class

    The exception is derived from `SystemExit` on purpose - that way it
    should wind up the whole try-except stack (if well-written: nobody should
    swallow `SystemExit`) until explicitly caught.

    :CVariables:
     - `_FRAME`: Frame around the actual message
     - `status`: HTTP response status
     - `reason`: HTTP response reason phrase

    :IVariables:
     - `message`: Message template
     - `param`: Additional parameters for response template fill-in
     - `_escaped`: Already escaped parameters
     - `_content_type`: Content-Type
     - `_replace`: Replace parameters in message?

    :Types:
     - `_FRAME`: ``str``
     - `status`: ``int``
     - `reason`: ``str``
     - `message`: ``str``
     - `param`: ``dict``
     - `_escaped`: ``dict``
     - `_content_type`: ``str``
     - `_replace`: ``bool``
    """
    status, reason, message = None, None, None
    _FRAME = """
<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>%%(status)s %%(reason)s</title>
</head><body>
<h1>%%(reason)s</h1>
%s
</body></html>
    """.strip()

    def __init__(self, request, message=None,
                 content_type='text/html; charset=us-ascii', replace=True,
                 **param):
        """
        Initialization

        :Parameters:
         - `request`: Request object
         - `message`: message template
         - `content_type`: Response content type
         - `replace`: Replace parameters in message?
         - `param`: Additional parameters for response template fill-in

        :Types:
         - `request`: `wtf.app.request.Request`
         - `message`: ``str``
         - `content_type`: ``str``
         - `replace`: ``bool``
         - `param`: ``dict``
        """
        SystemExit.__init__(self, 0)
        if message is not None:
            self.message = message
        elif self.message is not None:
            self.message = self._FRAME % self.message
        self._content_type = content_type
        self._replace = bool(replace)
        self._request = request
        self.param, self._escaped = self.init(**param)
        url = request.url.copy()
        url.scheme, url.netloc = u'', u''
        self.param.setdefault('url', str(url))
        self.param.setdefault('method', str(request.method))

    def init(self):
        """
        Custom initializer and easy check for required parameters

        :return: tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        return {}, {}

    def headers(self, collection):
        """ Modify response headers """
        collection.set('content-type', self._content_type)

    def body(self):
        """
        Compute the response body

        :return: The response body
        :rtype: ``str``
        """
        if self.message is None:
            return ""
        elif not self._replace:
            return self.message
        param = dict(self.param)
        param.update({'status': str(self.status), 'reason': str(self.reason)})
        param = dict((key, _webutil.escape_html(str(val)))
            for key, val in param.iteritems())
        param.update(self._escaped)
        return self.message % param


class Continue(HTTPResponse):
    """ 100 Continue (RFC 2616) """
    status, reason, message = 100, "Continue", None


class SwitchingProtocols(HTTPResponse):
    """ 101 Switching Protocols (RFC 2616) """
    status, reason, message = 101, "Switching Protocols", None


class Processing(HTTPResponse):
    """ 102 Processing (RFC 2518) """
    status, reason, message = 102, "Processing", None


class OK(HTTPResponse):
    """ 200 OK (RFC 2616) """
    status, reason, message = 200, "OK", None


# pylint: disable = W0221

class Created(HTTPResponse):
    """ 201 Created (RFC 2616) """
    status, reason = 201, "Created"
    message = """
<p>A new resource has been created and is available under the following
URI(s):</p>
<ul>
<li><a href="%(location)s">%(location)s</a></li>
%(uris)s
</ul>
    """.strip()

    def init(self, location, additional=()):
        """
        Add main location and (optional) less significant URIs

        :Parameters:
         - `location`: Main location of the created resource
         - `additional`: List of additional (less significant) locations
           (``('uri', ...)``)

        :Types:
         - `location`: ``str``
         - `additional`: ``iterable``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        urilist = "\n".join("<li><a href=\"%(uri)s\">%(uri)s</a></li>" %
            _webutil.escape_html(uri) for uri in additional)
        return dict(location=location, uris=additional), dict(uris=urilist)

    def headers(self, collection):
        """ Modify response headers """
        HTTPResponse.headers(self, collection)
        collection.set('location', self.param['location'])


class Accepted(HTTPResponse):
    """ 202 Accepted (RFC 2616) """
    status, reason = 202, "Accepted"
    message = """
<p>Your request has been accepted and may be processed later.</p>
    """.strip()


class NonAuthoritativeInformation(HTTPResponse):
    """ 203 Non-Authoritative Information (RFC 2616) """
    status, reason, message = 203, "Non-Authoritative Information", None


class NoContent(HTTPResponse):
    """ 204 No Content (RFC 2616) """
    status, reason, message = 204, "No Content", None


class ResetContent(HTTPResponse):
    """ 205 Reset Content (RFC 2616) """
    status, reason, message = 205, "Reset Content", None


class PartialContent(HTTPResponse):
    """ 206 Partial Content (RFC 2616) """
    status, reason, message = 206, "Partial Content", None


class MultiStatus(HTTPResponse):
    """ 207 Multi-Status (RFC 2518) """
    status, reason, message = 207, "Multi-Status", None


class MultipleChoices(HTTPResponse):
    """ 300 Multiple Choices (RFC 2616) """
    status, reason = 300, "Multiple Choices"
    message = """
<p>Multiple representations available:</p>
<ul>
%(variants)s
</ul>
    """.strip()

    def init(self, variants):
        """
        Add list of variants

        :Parameters:
         - `variants`: List of choosable variants (``('uri', ...)``)

        :Types:
         - `variants`: ``iterable``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        variantlist = "\n".join("<li>%(variant)s</li>" %
            _webutil.escape_html(variant) for variant in variants)
        return dict(variants=variants), dict(variants=variantlist)


class _BaseRedirect(HTTPResponse):
    """ Base redirect class """
    message = """
<p>The document has moved <a href="%(location)s">here</a>.</p>
    """.strip()

    def init(self, location):
        """
        Ensure location parameter

        :Parameters:
         - `location`: New location

        :Types:
         - `location`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        return dict(location=location), {}

    def headers(self, collection):
        """ Modify response headers """
        HTTPResponse.headers(self, collection)
        collection.set('location', self.param['location'])


class HTTPRedirectResponse(_BaseRedirect):
    """ Subclass for type identification of automatic redirects """


class MovedPermanently(HTTPRedirectResponse):
    """ 301 Moved Permanently (RFC 2616) """
    status, reason = 301, "Moved Permanently"


class Found(HTTPRedirectResponse):
    """ 302 Found (RFC 2616) """
    status, reason = 302, "Found"


class SeeOther(HTTPRedirectResponse):
    """ 303 See Other (RFC 2616) """
    status, reason = 303, "See Other"
    message = """
<p>The answer to your request is located <a href="%(location)s">here</a>.</p>
    """.strip()


class NotModified(HTTPResponse):
    """ 304 Not Modified (RFC 2616) """
    status, reason, message = 304, "Not Modified", None


class UseProxy(_BaseRedirect):
    """ 305 Use Proxy (RFC 2616) """
    status, reason = 305, "Use Proxy"
    message = """
<p>This resource is only accessible through the proxy
%(location)s<br>
You will need to configure your client to use that proxy.</p>
    """.strip()


class Unused306(HTTPResponse):
    """ 306 (Unused) (RFC 2616) """
    status, reason, message = 306, "Unused", "<p>Unused Status Code</p>"


class TemporaryRedirect(HTTPRedirectResponse):
    """ 307 Temporary Redirect (RFC 2616) """
    status, reason = 307, "Temporary Redirect"


class BadRequest(HTTPResponse):
    """ 400 Bad Request (RFC 2616) """
    status, reason = 400, "Bad Request"
    message = """
<p>Your browser sent a request that this server could not understand.<br>
%(hint)s</p>
    """.strip()

    def init(self, hint=None):
        """
        Add an error hint

        :Parameters:
         - `hint`: Optional hint describing the error (unescaped HTML)

        :Types:
         - `hint`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        hint_esc = hint and _webutil.escape_html(hint) or ""
        return dict(hint=hint), dict(hint=hint_esc)


class AuthorizationRequired(HTTPResponse):
    """ 401 Authorization Required (RFC 2616) """
    status, reason = 401, "Authorization Required"
    message = """
<p>This server could not verify that you
are authorized to access the document
requested.  Either you supplied the wrong
credentials (e.g., bad password), or your
browser doesn't understand how to supply
the credentials required.</p>
    """.strip()

    def init(self, auth_type, realm):
        """
        Add auth type and realm

        :Parameters:
         - `auth_type`: Authentication Type (like 'Basic', see RFC 2617)
         - `realm`: Authentication realm

        :Types:
         - `auth_type`: ``str``
         - `realm`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        assert auth_type.lower() == 'basic', \
            'Only basic authentication supported yet'
        return dict(auth_type=auth_type, realm=realm), {}

    def headers(self, collection):
        """ Modify response headers """
        HTTPResponse.headers(self, collection)
        collection.set('WWW-Authenticate', '%s realm="%s"' % (
            self.param['auth_type'], self.param['realm'].replace('"', '\\"')
        ))


class PaymentRequired(HTTPResponse):
    """ 402 Payment Required (RFC 2616) """
    status, reason = 402, "Payment Required"
    message = """
<p>This resource requires payment.</p>
    """.strip()


class Forbidden(HTTPResponse):
    """ 403 Forbidden (RFC 2616) """
    status, reason = 403, "Forbidden"
    message = """
<p>You don't have permission to access %(url)s
non this server.</p>
    """.strip()


class NotFound(HTTPResponse):
    """ 404 Not Found (RFC 2616) """
    status, reason = 404, "Not Found"
    message = """
<p>The requested URL %(url)s was not found on this server.</p>
    """.strip()


class MethodNotAllowed(HTTPResponse):
    """ 405 Method Not Allowed """
    status, reason = 405, "Method Not Allowed"
    message = """
<p>The requested method %(method)s is not allowed for the URL %(url)s.</p>
    """.strip()

    def init(self, allowed):
        """
        Add the allowed method list

        :Parameters:
         - `allowed`: List of allowed methods (``('method', ...)``)

        :Types:
         - `allowed`: ``iterable``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        allowed = list(sorted(set(allowed)))
        allowed_esc = '\n'.join("<li>%s</li>" % _webutil.escape_html(method)
            for method in allowed)
        return dict(allowed=allowed), dict(allowed=allowed_esc)

    def headers(self, collection):
        """ Modify response headers """
        HTTPResponse.headers(self, collection)
        collection.set('allow', ', '.join(self.param['allowed']))


class NotAcceptable(HTTPResponse):
    """ 406 Not Acceptable (RFC 2616) """
    status, reason = 406, "Not Acceptable"
    message = """
<p>An appropriate representation of the requested resource %(url)s
could not be found on this server.</p>
Available variants:
<ul>
%(variants)s
</ul>
    """.strip()

    def init(self, variants, descriptions=None):
        """
        Add the variant list

        :Parameters:
         - `variants`: The variant URLs
         - `descriptions`: variant descriptions, the url is the key

        :Types:
         - `variants`: ``iterable``
         - `descriptions`: ``dict``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        if descriptions is None:
            descriptions = {}
        variants_esc = '\n'.join(
            '<li><a href="%(var)s">%(var)s</a>%(desc)s</li>' % dict(
            var=_webutil.escape_html(var),
            desc=descriptions.get(var) and
                (", " + _webutil.escape_html(descriptions[var])) or "",
        ) for var in variants)
        return (
            dict(variants=variants, descriptions=descriptions),
            dict(variants=variants_esc, descriptions="")
        )


class ProxyAuthenticationRequired(AuthorizationRequired):
    """ 407 Proxy Authentication Required (RFC 2616) """
    status, reason = 407, "Proxy Authentication Required"


class RequestTimeout(HTTPResponse):
    """ 408 Request Timeout (RFC 2616) """
    status, reason = 408, "Request Timeout"
    message = """
<p>Server timeout waiting for the HTTP request from the client.</p>
    """.strip()


class Conflict(HTTPResponse):
    """ 409 Conflict (RFC 2616) """
    status, reason = 409, "Conflict"
    message = """
<p>The request could not be completed due to a conflict with the current
state of the resource.</p>%(desc)s
    """.strip()

    def init(self, desc=None):
        """
        Optionally add a conflict description

        :Parameters:
         - `desc`: Optional conflict description

        :Types:
         - `desc`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        desc_esc = desc and "\n<p>%s</p>" % _webutil.escape_html(desc) or ""
        return dict(desc=desc), dict(desc=desc_esc)


class Gone(HTTPResponse):
    """ 410 Gone (RFC 2616) """
    status, reason = 410, "Gone"
    message = """
<p>The requested resource<br>%(url)s<br>
is no longer available on this server and there is no forwarding address.
Please remove all references to this resource.</p>
    """.strip()


class LengthRequired(HTTPResponse):
    """ 411 Length Required (RFC 2616) """
    status, reason = 411, "Length Required"
    message = """
<p>A request of the requested method %(method)s requires a valid
Content-length.%(desc)s</p>
    """.strip()

    def init(self, desc=None):
        """
        Add optional description

        :Parameters:
         - `desc`: Optional additional description

        :Types:
         - `desc`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        desc_esc = desc and ("<br>\n" + _webutil.escape_html(desc)) or ""
        return dict(desc=desc), dict(desc=desc_esc)


class PreconditionFailed(HTTPResponse):
    """ 412 Precondition Failed (RFC 2616) """
    status, reason = 412, "Precondition Failed"
    message = """
<p>The precondition on the request for the URL %(url)s evaluated to false.</p>
    """.strip()


class RequestEntityTooLarge(HTTPResponse):
    """ 413 Request Entity Too Large (RFC 2616) """
    status, reason = 413, "Request Entity Too Large"
    message = """
<p>The requested resource<br>%(url)s<br>
does not allow request data with %(method)s requests, or the amount of data
provided in the request exceeds the capacity limit.</p>
    """.strip()


class RequestURITooLong(HTTPResponse):
    """ 414 Request-URI Too Long (RFC 2616) """
    status, reason = 414, "Request-URI Too Long"
    message = """
<p>The requested URL's length exceeds the capacity
limit for this server.%(desc)s</p>
    """.strip()

    def init(self, desc=None):
        """
        Optionally add a error description

        :Parameters:
         - `desc`: Optional error description

        :Types:
         - `desc`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        desc_esc = desc and "<br>\n%s" % _webutil.escape_html(desc) or ""
        return dict(desc=desc), dict(desc=desc_esc)


class UnsupportedMediaType(HTTPResponse):
    """ 415 Unsupported Media Type (RFC 2616) """
    status, reason = 415, "Unsupported Media Type"
    message = """
<p>The supplied request data is not in a format
acceptable for processing by this resource.</p>
    """.strip()


class RequestRangeNotSatisfiable(HTTPResponse):
    """ 416 Request Range Not Satisfiable (RFC 2616) """
    status, reason = 416, "Request Range Not Satisfiable"
    message = """
<p>None of the range-specifier values in the Range
request-header field overlap the current extent
of the selected resource.</p>
    """.strip()


class ExpectationFailed(HTTPResponse):
    """ 417 Expectation Failed (RFC 2616) """
    status, reason = 417, "Expectation Failed"
    message = """
<p>The expectation given in an Expect request-header field could not be met
by this server.</p>
    """.strip()


class UnprocessableEntity(HTTPResponse):
    """ 422 Unprocessable Entity (RFC 2518) """
    status, reason = 422, "Unprocessable Entity"
    message = """
<p>The server understands the media type of the
request entity, but was unable to process the
contained instructions.</p>
    """.strip()


class Locked(HTTPResponse):
    """ 423 Locked (RFC 2518) """
    status, reason = 423, "Locked"
    message = """
<p>The requested resource is currently locked.
The lock must be released or proper identification
given before the method can be applied.</p>
    """.strip()


class FailedDependency(HTTPResponse):
    """ 424 Failed Dependency (RFC 2518) """
    status, reason = 424, "Failed Dependency"
    message = """
<p>The method could not be performed on the resource
because the requested action depended on another
action and that other action failed.</p>
    """.strip()


class UpgradeRequired(HTTPResponse):
    """ 426 Upgrade Required (RFC 2817) """
    status, reason = 426, "Upgrade Required"
    message = """
<p>The requested resource can only be retrieved
using SSL.  The server is willing to upgrade the current
connection to SSL, but your client doesn't support it.
Either upgrade your client, or try requesting the page
using https://.</p>
    """.strip()

    def init(self, tokens):
        """
        Add upgrade tokens

        :Parameters:
         - `tokens`: List of upgrade tokens to advertise

        :Types:
         - `tokens`: ``iterable``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        tokens_esc = _webutil.escape_html(", ".join(tokens))
        return dict(tokens=tokens), dict(tokens=tokens_esc)

    def headers(self, collection):
        """ Modify response headers """
        HTTPResponse.headers(self, collection)
        collection.add('connection', 'upgrade')
        collection.set('upgrade', ', '.join(self.param['tokens']))


class InternalServerError(HTTPResponse):
    """ 500 Internal Server Error (RFC 2616) """
    status, reason = 500, "Internal Server Error"
    message = """
<p>The server encountered an internal error or
misconfiguration and was unable to complete
your request.</p>
<p>Please contact the server administrator,%(admin)s and inform them of the
time the error occurred,
and anything you might have done that may have
caused the error.</p>
<p>More information about this error may be available
in the server error log.</p>
    """.strip()

    def init(self, admin=None):
        """
        Add optional admin address

        :Parameters:
         - `admin`: The optional admin contact address

        :Types:
         - `admin`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        admin_esc = admin and (" " + _webutil.escape_html(admin)) or ""
        return dict(admin=admin), dict(admin=admin_esc)


class NotImplemented(HTTPResponse): # pylint: disable = W0622
    """ 501 Not Implemented (RFC 2616) """
    status, reason = 501, "Not Implemented"
    message = """
<p>%(method)s to %(url)s not supported.<br>
%(desc)s</p>
    """.strip()

    def init(self, desc=None):
        """
        Add optional description

        :Parameters:
         - `desc`: Optional error description

        :Types:
         - `desc`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        desc_esc = desc and _webutil.escape_html(desc) or ""
        return dict(desc=desc), dict(desc=desc_esc)


class BadGateway(HTTPResponse):
    """ 502 Bad Gateway (RFC 2616) """
    status, reason = 502, "Bad Gateway"
    message = """
<p>The proxy server received an invalid
response from an upstream server.<br>%(desc)s</p>
    """.strip()

    def init(self, desc=None):
        """
        Optionally add a error description

        :Parameters:
         - `desc`: Optional error description

        :Types:
         - `desc`: ``str``

        :return: Tuple of unescaped and escaped parameters (``(dict, dict)``)
        :rtype: ``tuple``
        """
        desc_esc = desc and _webutil.escape_html(desc) or ""
        return dict(desc=desc), dict(desc=desc_esc)


class ServiceUnavailable(HTTPResponse):
    """ 503 Service Unavailable (RFC 2616) """
    status, reason = 503, "Service Unavailable"
    message = """
<p>The server is temporarily unable to service your
request due to maintenance downtime or capacity
problems. Please try again later.</p>
    """.strip()


class GatewayTimeout(HTTPResponse):
    """ 504 Gateway Timeout (RFC 2616) """
    status, reason = 504, "Gateway Timeout"
    message = """
<p>The proxy server did not receive a timely response
from the upstream server.</p>
    """.strip()


class HTTPVersionNotSupported(HTTPResponse):
    """ 505 HTTP Version Not Supported (RFC 2616) """
    status, reason = 505, "HTTP Version Not Supported"
    message = """
<p>The HTTP version used in the request is not suppored.</p>
    """.strip()


class VariantAlsoNegotiates(HTTPResponse):
    """ 506 Variant Also Negotiates (RFC 2295) """
    status, reason = 506, "Variant Also Negotiates"
    message = """
<p>A variant for the requested resource %(url)s is itself a negotiable
resource. This indicates a configuration error.</p>
    """.strip()


class InsufficientStorage(HTTPResponse):
    """ 507 Insufficient Storage (RFC 2518) """
    status, reason = 507, "Insufficient Storage"
    message = """
<p>The method could not be performed on the resource
because the server is unable to store the
representation needed to successfully complete the
request.  There is insufficient free space left in
your storage allocation.</p>
    """.strip()


class NotExtended(HTTPResponse):
    """ 510 Not Extended (RFC 2774) """
    status, reason = 510, "Not Extended"
    message = """
<p>A mandatory extension policy in the request is not
accepted by the server for this resource.</p>
    """.strip()


def classes(space):
    """
    Compute the mapping status code -> status class

    :Parameters:
     - `space`: Namespace to inspect

    :Types:
     - `space`: ``dict``

    :return: The mapping (``{status: HTTPResponse, ...}``)
    :rtype: ``dict``
    """
    def _issubclass(inner, outer):
        """ Determine subclassness """
        try:
            return issubclass(inner, outer)
        except TypeError:
            return False
    return dict((cls.status, cls) for cls in space.values()
        if _issubclass(cls, HTTPResponse) and cls.status)
classes = classes(globals())


def reasons():
    """
    Compute the mapping status code -> reason phrase

    :return: The mapping (``{status: 'reason', ...}``)
    :rtype: ``dict``
    """
    return dict((status, cls.reason)
        for status, cls in classes.iteritems())
reasons = reasons()
