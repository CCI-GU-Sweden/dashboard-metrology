"""Extract METEOR inputs from OMERO image annotations and dimensions."""
import math


def extract_metadata(image):
    """Return annotation values with OMERO dimensions as the axis authority.

    Conflicting duplicate keys are rejected rather than depending on annotation
    iteration order. Physical sizes in METEOR annotations are in micrometres.
    """
    from omero.gateway import MapAnnotationWrapper

    metadata = {}
    for annotation in image.listAnnotations():
        if not isinstance(annotation, MapAnnotationWrapper):
            continue
        for key, value in annotation.getValue():
            if key in metadata and metadata[key] != value:
                raise ValueError(f"Conflicting OMERO annotation values for {key}")
            metadata[key] = value

    for axis in "XYZCT":
        metadata[f"Image Size {axis}"] = int(getattr(image, f"getSize{axis}")())
    # OMERO exposes CZI scenes as separate Image objects within the fileset.
    metadata["Image Size S"] = 1
    metadata["axis_order"] = "TCZYX"
    return metadata


def positive_number(metadata, key):
    """Read a finite positive annotation number; reject missing calibration."""
    try:
        value = float(metadata[key])
    except (KeyError, ValueError, TypeError):
        raise ValueError(f"Missing or invalid {key}") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Missing or invalid {key}")
    return value
