"""Normalize METEOR results and produce durable output artifacts."""
import io
import json
import math

import numpy as np


def normalize_results(image_id, results):
    """Extract finite metrics and figures; never mark empty output successful."""
    import matplotlib.pyplot as plt

    measurements = []
    artifacts = []
    summaries = []
    for index, result in enumerate(results):
        status = str(result.get("status", "error"))
        if status.lower() in ("error", "failure", "failed"):
            raise ValueError(f"Analysis {index} failed: {result.get('extra_measurements', {}).get('error', status)}")
        figure = result.get("figure")
        if figure is not None:
            try:
                buffer = io.BytesIO()
                figure.savefig(buffer, format="png", dpi=150)
                artifacts.append((image_id, f"figure-{index}.png", "image/png", buffer.getvalue()))
            finally:
                plt.close(figure)
        tiff = result.get("tiff")
        if tiff and tiff.get("image") is not None:
            import tifffile
            pixels = tiff.get("upscaled_pixel_size", {})
            buffer = io.BytesIO()
            tifffile.imwrite(buffer, np.asarray(tiff["image"], dtype=np.float32), ome=True, photometric="minisblack",
                             metadata={"axes": "ZYX", "PhysicalSizeX": pixels.get("X"),
                                       "PhysicalSizeY": pixels.get("Y"), "PhysicalSizeZ": pixels.get("Z"),
                                       "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm", "PhysicalSizeZUnit": "µm"})
            artifacts.append((image_id, f"psf-{index}.ome.tif", "image/tiff", buffer.getvalue()))
        gif = result.get("gif")
        if gif and gif.get("frames") is not None:
            import imageio.v2 as imageio
            frames = np.asarray(gif["frames"])
            if frames.ndim != 4 or len(frames) == 0:
                raise ValueError("Invalid PSF evolution frames")
            indices = np.unique(np.linspace(0, len(frames) - 1, min(len(frames), 40), dtype=int))
            average = np.zeros(frames.shape[1:], dtype=np.float64)
            rendered = []
            next_frame = 0
            for i, bead in enumerate(frames):
                average += (bead - average) / (i + 1)
                if next_frame < len(indices) and i == indices[next_frame]:
                    plane = np.log1p(np.maximum(average[average.shape[0] // 2], 0))
                    peak = float(plane.max())
                    rendered.append(np.uint8(255 * plane / peak) if peak else np.zeros(plane.shape, dtype=np.uint8))
                    next_frame += 1
            buffer = io.BytesIO()
            imageio.mimsave(buffer, rendered, format="GIF", duration=0.1, loop=0)
            artifacts.append((image_id, f"psf-{index}.gif", "image/gif", buffer.getvalue()))
        for metric_index, metric in enumerate(result.get("measurements", [])):
            try:
                value = float(metric["value"])
                if not math.isfinite(value):
                    continue
                category, name = str(metric["category"]), str(metric["name"])
            except (KeyError, ValueError, TypeError):
                continue
            key = f"{image_id}:{index}:{metric_index}:{category}:{name}"
            measurements.append((key, category, name, value, str(metric.get("unit") or ""), status))
            summaries.append({"category": category, "name": name, "value": value,
                              "unit": metric.get("unit") or "", "status": status})
    if not measurements:
        raise ValueError("Analysis returned no finite measurements")
    payload = json.dumps({"image_id": image_id, "measurements": summaries}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    artifacts.append((image_id, "measurements.json", "application/json", payload))
    return measurements, artifacts
