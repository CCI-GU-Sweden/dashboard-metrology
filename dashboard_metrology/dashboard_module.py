"""Dashboard module descriptor."""
from accounts.permissions import operational_access
from dashboard.modules import DashboardModule

from .data import summary, microscopes
from .overdue import is_overdue


def overview_metrics(user):
    data = summary()
    return [
        {"label": "Microscopes", "value": str(data["microscopes"])},
        {"label": "Measurements", "value": str(data["measurements"])},
        {"label": "Overdue microscopes", "value": str(sum(is_overdue(item["last_measurement"]) for item in microscopes()))},
        {"label": "Filesets needing attention", "value": str(data["failures"])},
    ]


module = DashboardModule(
    key="metrology", name="Metrology", eyebrow="Microscope health", icon="🔬",
    url_name="metrology_home", urlconf="dashboard_metrology.urls",
    can_view=operational_access, get_metrics=overview_metrics,
)
