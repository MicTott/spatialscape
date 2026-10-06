import numpy as np

from spatialscape.outlines import _rdp, compute_outlines


def test_rdp_keeps_endpoints_and_corners():
    pts = np.array([[0, 0], [1, 0.01], [2, 0], [2, 1], [2, 2]], dtype=float)
    out = _rdp(pts, 0.1)
    assert out[0].tolist() == [0, 0] and out[-1].tolist() == [2, 2]
    assert len(out) == 3  # the near-collinear middle point is dropped, the corner kept


def test_outlines_trace_two_regions():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 1000, size=(6000, 2))
    codes = (xy[:, 0] > 500).astype(np.uint16)  # left = 0, right = 1
    d = compute_outlines(xy, codes, 2, min_cells=10)
    assert d["bin"] > 0
    cs = {p["c"] for p in d["paths"]}
    assert cs == {0, 1}
    # the region boundary should sit near x = 500 for the left region's right edge
    left = max((p for p in d["paths"] if p["c"] == 0), key=lambda p: len(p["p"]))
    xs = np.array(left["p"])[:, 0]
    assert abs(xs.max() - 500) < 40
    assert xs.min() < 40
