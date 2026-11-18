"""Construct METEOR inputs and run classified acquisitions."""
import numpy as np

from .omero_io import load_image
from .routing import analyze, validate_metadata
from .results import normalize_results


def analyze_fileset(connection, image_ids, overrides, max_bytes):
    from METEOR_core.classification import classify_image

    outputs = []
    visited = set()
    for image_id in image_ids:
        if image_id in visited:
            continue
        image, metadata, stack = load_image(connection, image_id, max_bytes)
        validate_metadata(metadata)
        override = overrides.get(image_id)
        decision = classify_image(stack, metadata, image.getName(), override=override)
        if decision["requires_review"]:
            raise ValueError(f"Image {image_id} requires classification review")
        category = decision["category"]
        validate_metadata(metadata, category)
        if category == "Plastic_Field_Uniformity" and len(image_ids) > 1:
            planes = [stack[0, 0, 0]]
            for other_id in image_ids:
                if other_id == image_id:
                    continue
                if overrides.get(other_id) not in (None, category):
                    raise ValueError("Conflicting overrides in multi-image plastic fileset")
                _, other_metadata, other = load_image(connection, other_id, max_bytes)
                validate_metadata(other_metadata, category)
                planes.append(other[0, 0, 0])
            stack = np.stack(planes)[None, None, :, :, :]
            metadata.update({"Image Size Z": len(planes), "Image Size C": 1, "Image Size T": 1})
            metadata["contributing_image_ids"] = list(image_ids)
            visited.update(image_ids)
        elif category != "Argo_2D_Rings_Analysis":
            stack = stack[:, :1]
            metadata["Image Size C"] = 1
        results = analyze(stack, image.getName(), metadata, category)
        measurements, artifacts = normalize_results(image_id, results)
        outputs.append((image_id, image.getName(), metadata, measurements, artifacts, decision))
        visited.add(image_id)
    return outputs
