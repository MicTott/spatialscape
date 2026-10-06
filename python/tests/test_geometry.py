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
