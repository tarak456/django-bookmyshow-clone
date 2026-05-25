from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# ── Customize Django admin header ─────────────────────────────────────────────
admin.site.site_header  = 'BookMySeat Administration'
admin.site.site_title   = 'BookMySeat Admin'
admin.site.index_title  = 'Site Management'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path('movies/', include('movies.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
