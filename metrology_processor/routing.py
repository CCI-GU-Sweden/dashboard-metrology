"""Routing shared by the processor and future administrative interface."""

from .metadata import positive_number

CATEGORIES = (
    "Argo_2D_Rings_Analysis",
    "Argo_Intensity_Linearity",
    "Psf_Measure",
    "Plastic_Field_Uniformity",
    "3D_Crossing_Stairs",
    "star_resolution",
)


def analyze(image, name, metadata, override=None):
    """Invoke METEOR-core's content classifier and optional explicit override."""
    if override is not None and override not in CATEGORIES:
        raise ValueError(f"Unsupported metrology category: {override}")
    from METEOR_core.metrology import metrology_splitter

    results = metrology_splitter(image, name, metadata, category_override=override)
    if not isinstance(results, list) or not results:
        raise ValueError("Analysis failed or requires classification review")
    return results


def validate_metadata(metadata, category=None):
    """Reject absent calibration rather than accepting core's unit defaults."""
    for axis in ("X", "Y"):
        positive_number(metadata, f"Physical pixel size {axis}")
    if category in ("Psf_Measure", "3D_Crossing_Stairs") and int(metadata.get("Image Size Z", 1)) > 1:
        positive_number(metadata, "Physical pixel size Z")
    if category == "Psf_Measure":
        positive_number(metadata, "Lens NA")
