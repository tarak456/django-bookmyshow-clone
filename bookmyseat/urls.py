from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

admin.site.site_header  = 'BookMySeat Administration'
admin.site.site_title   = 'BookMySeat Admin'
admin.site.index_title  = 'Site Management'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path('movies/', include('movies.urls')),

    # Serve media files in ALL environments (dev + production).
    # Django's static() helper only works when DEBUG=True, so in production
    # uploaded images would return 404.  This pattern serves them always.
    # For high-traffic production use S3/Cloudinary instead.
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
