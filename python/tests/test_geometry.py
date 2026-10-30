import numpy as np

from spatialscape.geometry import transform_image, transform_points


def test_points_and_image_transform_agree():
    # an image with a single bright pixel; the point at that pixel's centre must map to the same pixel
    h, w = 40, 60
    for flip in ("none", "x", "y"):
        for rot in (0, 90, 180, 270):
            img = np.zeros((1, h, w), dtype=np.uint8)
            py, px = 7, 50
            img[0, py, px] = 255
            out = transform_image(img, flip, rot)
            pt = transform_points(np.array([[px + 0.5, py + 0.5]]), w, h, flip, rot)[0]
            oy, ox = np.argwhere(out[0] == 255)[0]
            assert int(np.floor(pt[0])) == ox and int(np.floor(pt[1])) == oy, (flip, rot)
            assert out.shape[1:] == ((w, h) if rot in (90, 270) else (h, w))


def test_microns_error_names_the_platform_shortcuts():
    import pytest

    from spatialscape.config import MicronsSpec, SampleSpec
    from spatialscape.geometry import microns_per_unit
    from spatialscape.readers import SampleInput

    spec = SampleSpec(id="s", platform="other", path="x.h5ad", microns=MicronsSpec())
    import anndata as ad

    sinput = SampleInput(adata=ad.AnnData(np.zeros((3, 1), dtype=np.float32)), coords=np.zeros((3, 2)), gene_names=np.array(["G"]))
    with pytest.raises(ValueError, match=r"`platform: xenium` / `merfish`.*already_microns: true.*Visium HD"):
        microns_per_unit(spec, sinput)


def test_spot_spacing_rule_is_visium_only():
    """`spot_nn_spacing_level0_px` in uns gives the scale for a Visium array; a Visium HD object carrying the same key
    must not get the 100 um rule (its neighbour spacing is the bin pitch, not 100 um)."""
    import anndata as ad
    import pytest

    from spatialscape.config import MicronsSpec, SampleSpec
    from spatialscape.geometry import microns_per_unit
    from spatialscape.readers import SampleInput

    def sinput():
        return SampleInput(adata=ad.AnnData(np.zeros((3, 1), dtype=np.float32)), coords=np.zeros((3, 2)), gene_names=np.array(["G"]), uns={"spot_nn_spacing_level0_px": 200.0})

    assert microns_per_unit(SampleSpec(id="v", platform="visium", path="x.h5ad", microns=MicronsSpec()), sinput()) == 0.5
    assert microns_per_unit(SampleSpec(id="o", platform="other", path="x.h5ad", microns=MicronsSpec()), sinput()) == 0.5  # an object shown from a notebook
    with pytest.raises(ValueError, match="Visium HD"):
        microns_per_unit(SampleSpec(id="hd", platform="visium_hd", path="x.h5ad", microns=MicronsSpec()), sinput())
