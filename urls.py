from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('',
    url(r'^$', 'grid.views.main'),
    url(r'^link/$', 'grid.views.link'),
    url(r'^unlink/$', 'grid.views.unlink'),
    url(r'^generate/$', 'grid.views.generate'),
    url(r'^recent/$', 'grid.views.get_recent_media'),
    url(r'^stats/$', 'grid.views.stats'),
)
