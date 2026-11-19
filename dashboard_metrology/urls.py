from django.urls import path

from . import views

urlpatterns = [
    path("metrology/", views.home, name="metrology_home"),
    path("metrology/microscopes/<int:microscope_id>/", views.microscope, name="metrology_microscope"),
]
