"""OMERO acquisition and annotation helpers."""
import os
import tempfile

import numpy as np

from .metadata import extract_metadata

NAMESPACE = "org.openmicroscopy.dashboard.metrology.v1"


def connect():
    from omero.gateway import BlitzGateway

    connection = BlitzGateway(os.environ["OMERO_USER"], os.environ["OMERO_PASSWORD"],
                              host=os.environ["OMERO_HOST"], port=int(os.getenv("METROLOGY_OMERO_PORT", "4064")))
    if not connection.connect():
        raise RuntimeError("OMERO login failed")
    group_id = int(os.environ["OMERO_METROLOGY_GROUP_ID"])
    if group_id not in [group.getId() for group in connection.getGroupsMemberOf()]:
        connection.close()
        raise RuntimeError("Service account is not a member of the configured group")
    connection.setGroupForSession(group_id)
    return connection


def filesets(connection):
    """Return most recently imported filesets, with stable ID tie-breaking."""
    items = []
    for fileset in connection.getObjects("Fileset"):
        images = sorted(fileset.copyImages(), key=lambda image: image.getId())
        if not images:
            continue
        # Import event timestamps are used, not image acquisition dates.
        event = fileset.getDetails().getCreationEvent()
        imported = event.getTime() if event is not None else None
        items.append((fileset.getId(), imported, [image.getId() for image in images]))
    return sorted(items, key=lambda item: (item[1] is not None, item[1], item[0]), reverse=True)


def load_image(connection, image_id, max_bytes):
    image = connection.getObject("Image", image_id)
    if image is None:
        raise ValueError(f"Image {image_id} is not accessible")
    metadata = extract_metadata(image)
    sizes = [metadata[f"Image Size {axis}"] for axis in "TCZYX"]
    pixels = image.getPrimaryPixels()
    coords = [(z, c, t) for t in range(sizes[0]) for c in range(sizes[1]) for z in range(sizes[2])]
    planes = iter(pixels.getPlanes(coords))
    try:
        first = np.asarray(next(planes))
        required = int(np.prod(sizes, dtype=np.int64)) * first.dtype.itemsize
        if required > max_bytes:
            raise ValueError(f"Image {image_id} needs {required} bytes, over configured input limit")
        stack = np.empty(sizes, dtype=first.dtype)
        stack[0, 0, 0] = first
        for z, c, t in coords[1:]:
            stack[t, c, z] = next(planes)
    finally:
        if hasattr(planes, "close"):
            planes.close()
    return image, metadata, stack


def attach(connection, image_id, filename, mimetype, payload):
    """Reconcile already-linked module artifacts before creating an attachment."""
    from omero.gateway import FileAnnotationWrapper

    image = connection.getObject("Image", image_id)
    if image is None:
        raise RuntimeError(f"Image {image_id} is not accessible")
    for annotation in image.listAnnotations(ns=NAMESPACE):
        if isinstance(annotation, FileAnnotationWrapper) and annotation.getFile().getName() == filename:
            if b"".join(annotation.getFileInChunks()) != payload:
                raise RuntimeError("Existing attachment content differs from stored artifact")
            return annotation.getId()
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, filename)
        with open(path, "wb") as output:
            output.write(payload)
        annotation = connection.createFileAnnfromLocalFile(path, mimetype=mimetype, ns=NAMESPACE)
        image.linkAnnotation(annotation)
        return annotation.getId()
