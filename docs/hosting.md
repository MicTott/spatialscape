# Hosting

The app is static (`npm run build` -> `app/dist`). The data is static. They can live on different hosts.

## Requirements for the data host

1. CORS: `Access-Control-Allow-Origin: *` (or your app origin), allow `GET, HEAD`, allow the `Range` request header, expose `Content-Range, Content-Length, Accept-Ranges, ETag`.
2. HTTP Range requests must return `206 Partial Content`. Sharded zarr relies on them.
3. Check with `spatialscape validate https://host/path/bundle`.

### Cloudflare R2 (recommended: free egress)

- Create a bucket, upload the bundle (`rclone copy bundle r2:bucket/dataset`), attach a custom domain (edge caching; `r2.dev` is rate-limited and uncached).
- CORS policy (bucket settings):

```json
[{"AllowedOrigins": ["*"], "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["Range", "Content-Type"],
  "ExposeHeaders": ["Content-Range", "Content-Length", "Accept-Ranges", "ETag"], "MaxAgeSeconds": 86400}]
```

### AWS S3 (+ CloudFront)

```bash
aws s3 sync bundle s3://BUCKET/dataset --acl public-read
aws s3api put-bucket-cors --bucket BUCKET --cors-configuration file://docs/cors-s3.json
```

With CloudFront, forward the `Range` and `Origin` headers (the "CORS-S3Origin" origin request policy plus "CORS-With-Preflight" response headers policy work).

### GitHub Pages

Fine for the app and for small demo bundles (this repo publishes `examples/synthetic`), not for real data: 1 GB site limit and no guaranteed Range support. Build with `--no-shard` for anything hosted there.

## App

`npm run build`, upload `app/dist` anywhere (GitHub Pages, Cloudflare Pages, Netlify). The app reads `?d=<bundle url>`; link datasets as `https://app-host/?d=https://data-host/dataset`.
