# Hosting

The app is static and the data is static. They can live on different hosts, and the hosted viewer at `mictott.github.io/spatialscape` can open bundles from anywhere.

## What a data host must do

1. **CORS**: allow `GET` and `HEAD` from the viewer's origin (or `*`), allow the `Range` request header, and expose `Content-Range`, `Content-Length`, `Accept-Ranges` and `ETag`.
2. **HTTP Range requests** must return `206 Partial Content`. Sharded Zarr depends on them.
3. Serve `.json` as `application/json`; everything else can be `application/octet-stream`.

Check any host with:

```bash
spatialscape validate https://host/path/my_atlas
```

## Cloudflare R2 (recommended)

Free egress, so a popular dataset does not run up a bill; storage is about $0.015 per GB-month.

1. Create a bucket and upload: `rclone copy bundles/my_atlas r2:bucket/my_atlas`.
2. Attach a custom domain (the `r2.dev` endpoint is rate-limited and not cached).
3. Set the bucket CORS policy:

```json
[{"AllowedOrigins": ["*"], "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["Range", "Content-Type"],
  "ExposeHeaders": ["Content-Range", "Content-Length", "Accept-Ranges", "ETag"],
  "MaxAgeSeconds": 86400}]
```

## AWS S3 (+ CloudFront)

```bash
aws s3 sync bundles/my_atlas s3://BUCKET/my_atlas --acl public-read
aws s3api put-bucket-cors --bucket BUCKET --cors-configuration file://cors-s3.json
```

[`cors-s3.json`](/cors-s3.json) is the same policy in S3's wrapper. Egress is about $0.09 per GB direct, or free for the first terabyte per month through CloudFront; forward the `Range` and `Origin` headers in the CloudFront behavior. For public scientific data, the AWS Open Data Sponsorship Program covers storage and egress entirely.

## GitHub Pages

Fine for the app and for small demo bundles; not for real data (1 GB site limit, no guaranteed Range support). Build demo bundles with `--no-shard` so each gene is its own file.

## Your own server

Any static server that supports Range requests works (nginx, Apache, Caddy all do). Add the CORS headers above. `spatialscape serve` is a development server with both and is not meant for production traffic.

## Globus

Globus Connect Server v5 collections can expose files over HTTPS. A guest collection with anonymous access gives plain URLs that work for `curl` and, with CORS enabled on the collection, for the viewer as well. Useful when the authoritative copy already lives on institutional storage.

## Deploying the viewer

You do not need Node. `spatialscape site build` writes a folder with the viewer, a registry and your bundles
(or references to bundles on object storage); upload it as-is. The full walkthrough is in
[Publish your own site](./publish). Developers who change the app build it with `npm run build` and deploy
`app/dist`; the repository's Pages workflow does this for the demo and the docs.
