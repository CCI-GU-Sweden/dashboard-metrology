from django.urls import path

from . import views

urlpatterns = [
    path("metrology/", views.home, name="metrology_home"),
    path("metrology/review/", views.failures, name="metrology_failures"),
    path("metrology/measurements/", views.measurements, name="metrology_measurements"),
    path("metrology/attachments/<int:artifact_id>/", views.attachment, name="metrology_attachment"),
    path("metrology/microscopes/<int:microscope_id>/figures/", views.figures, name="metrology_figures"),
    path("metrology/microscopes/<int:microscope_id>/", views.microscope, name="metrology_microscope"),
    path("metrology/microscopes/<int:microscope_id>/history/", views.history, name="metrology_history"),
]
