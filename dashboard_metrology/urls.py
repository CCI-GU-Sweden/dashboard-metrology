from django.urls import path

from . import views

urlpatterns = [
    path("metrology/", views.home, name="metrology_home"),
    path("metrology/review/", views.failures, name="metrology_failures"),
    path("metrology/review/<int:run_id>/redo/", views.redo_failed, name="metrology_redo_failed"),
    path("metrology/thresholds/", views.thresholds, name="metrology_thresholds"),
    path("metrology/thresholds/<int:measurement_id>/", views.threshold_save, name="metrology_threshold_save"),
    path("metrology/measurements/", views.measurements, name="metrology_measurements"),
    path("metrology/redo/", views.redo_queue, name="metrology_redo_queue"),
    path("metrology/measurements/<int:measurement_id>/redo/", views.redo, name="metrology_redo"),
    path("metrology/attachments/<int:artifact_id>/", views.attachment, name="metrology_attachment"),
    path("metrology/microscopes/<int:microscope_id>/figures/", views.figures, name="metrology_figures"),
    path("metrology/microscopes/<int:microscope_id>/", views.microscope, name="metrology_microscope"),
    path("metrology/microscopes/<int:microscope_id>/history/", views.history, name="metrology_history"),
]
