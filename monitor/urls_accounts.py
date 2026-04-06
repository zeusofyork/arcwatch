from django.urls import path
from monitor.views.settings_views import accept_invite

urlpatterns = [
    path('accept-invite/<uuid:token>/', accept_invite, name='accept_invite'),
]
