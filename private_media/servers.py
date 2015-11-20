# -*- coding: utf-8 -*-
import mimetypes
import os
import stat
from django.conf import settings
from django.http import HttpResponse, Http404, HttpResponseNotModified
from django.utils.encoding import smart_str
from django.utils.http import http_date
from django.views.static import was_modified_since


class BasePrivateMediaServer(object):
    INTERNAL_URL = None
    ROOT = None
    FORCE_DOWNLOAD = True

    def get_url(self, relative_path):
        return os.path.join(self.INTERNAL_URL or settings.PRIVATE_MEDIA_INTERNAL_URL, relative_path).encode('utf-8')

    def get_full_path(self, relative_path):
        return os.path.join(self.ROOT or settings.PRIVATE_MEDIA_ROOT, relative_path)

    def get_mimetype(self, relative_path):
        return mimetypes.guess_type(self.get_full_path(relative_path))[0] or 'application/octet-stream'

    def get_force_download(self, overwrite=None):
        if overwrite is not None:
            return overwrite
        else:
            return getattr(settings, 'PRIVATE_MEDIA_FORCE_DOWNLOAD', self.FORCE_DOWNLOAD)

    def get_filename(self, relative_path):
        return os.path.basename(self.get_full_path(relative_path))

    def add_attachment_header(self, response, relative_path):
        """
        Add header to force the browser to save the file instead of possibly displaying it.
        """
        filename = self.get_filename(relative_path)
        response['Content-Disposition'] = smart_str('attachment; filename={0}'.format(filename))
        return response

    def prepare_response(self, request, response, relative_path):
        if self.get_force_download():
            response = self.add_attachment_header(response, relative_path)
        return response

    def serve(self, request, relative_path):
        response = HttpResponse()
        response = self.prepare_response(request, response, relative_path)
        return response


class LocalDevelopmentServer(BasePrivateMediaServer):
    """
    Serve static files from the local filesystem through django.
    This is a bad idea for most situations other than testing.

    This will only work for files that can be accessed in the local filesystem.
    """

    def serve(self, request, relative_path):
        # the following code is largely borrowed from `django.views.static.serve`
        # and django-filetransfers: filetransfers.backends.default

        full_path = self.get_full_path(relative_path)

        if not os.path.exists(full_path):
            raise Http404('"{0}" does not exist'.format(full_path))

        # Respect the If-Modified-Since header.
        content_type = self.get_mimetype(relative_path)
        statobj = os.stat(full_path)

        if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'),
                                  statobj[stat.ST_MTIME],
                                  statobj[stat.ST_SIZE]):
            response = HttpResponseNotModified(content_type=content_type)
        else:
            response = HttpResponse(open(full_path, 'rb').read(), content_type=content_type)
            response["Last-Modified"] = http_date(statobj[stat.ST_MTIME])
            response = self.prepare_response(request, response, relative_path)

        return response


class ApacheXSendfileServer(BasePrivateMediaServer):
    def prepare_response(self, request, response, relative_path):
        # Apache need a 'X-Sendfile' header an the full filesystem path
        response['X-Sendfile'] = self.get_full_path(request, relative_path)

        # From django-filer (https://github.com/stefanfoulis/django-filer/):
        # This is needed for lighttpd, hopefully this will
        # not be needed after this is fixed:
        # http://redmine.lighttpd.net/issues/2076
        response['Content-Type'] = self.get_mimetype(relative_path)
        return response


class NginxXAccelRedirectServer(BasePrivateMediaServer):
    def prepare_response(self, request, response, relative_path):
        # Nginx expects a 'X-Accel-Redirect' header to a private url;
        # the actual filesystem path is set in the nginx configuration.
        response['X-Accel-Redirect'] = self.get_url(relative_path)
        response['Content-Type'] = self.get_mimetype(relative_path)
        return response
