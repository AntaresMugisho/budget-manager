from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from budget.views import FrenchLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("connexion/", FrenchLoginView.as_view(), name="login"),
    path("deconnexion/", LogoutView.as_view(), name="logout"),
    path("", include("budget.urls")),
]
