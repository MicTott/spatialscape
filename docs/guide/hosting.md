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

1. Create a bucket and upload one bundle folder at a time: `rclone copy bundles/my_atlas r2:bucket/my_atlas` (not `bundles/` itself, whose `.cache/` sibling is local only).
2. Attach a custom domain (the `r2.dev` endpoint is rate-limited and not cached).
3. Set the bucket CORS policy:

```json
[{"AllowedOrigins": ["*"], "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["Range", "Content-Type"],
  "ExposeHeaders": ["Content-Range", "Content-Length", "Accept-Ranges", "ETag"],
  "MaxAgeSeconds": 86400}]
```

## AWS S3 + CloudFront

A private bucket read by a CloudFront distribution: free egress up to a terabyte a month, byte ranges served
natively, and a CORS policy applied by CloudFront so cached responses always carry the headers. Five calls
with the AWS CLI set up the bucket and the two policies (`BUCKET` is a name you choose; export it first):

```bash
aws s3api create-bucket --bucket $BUCKET --region us-east-1
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-cors --bucket $BUCKET --cors-configuration '{"CORSRules":[{"AllowedOrigins":["*"],"AllowedMethods":["GET","HEAD"],"AllowedHeaders":["Range","Content-Type","Origin"],"ExposeHeaders":["Content-Range","Content-Length","Accept-Ranges","ETag"],"MaxAgeSeconds":86400}]}'
OAC=$(aws cloudfront create-origin-access-control --origin-access-control-config "Name=$BUCKET,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" --query OriginAccessControl.Id --output text)
RHP=$(aws cloudfront create-response-headers-policy --response-headers-policy-config '{"Name":"spatialscape-cors-range","CorsConfig":{"AccessControlAllowOrigins":{"Quantity":1,"Items":["*"]},"AccessControlAllowHeaders":{"Quantity":3,"Items":["Range","Content-Type","Origin"]},"AccessControlAllowMethods":{"Quantity":3,"Items":["GET","HEAD","OPTIONS"]},"AccessControlAllowCredentials":false,"AccessControlExposeHeaders":{"Quantity":4,"Items":["Content-Range","Content-Length","Accept-Ranges","ETag"]},"AccessControlMaxAgeSec":86400,"OriginOverride":true}}' --query ResponseHeadersPolicy.Id --output text)
```

Then create the distribution in the console (the CLI needs a long JSON for this): origin
`$BUCKET.s3.us-east-1.amazonaws.com` with the origin access control `$OAC`, the managed `CachingOptimized`
cache policy, the managed `CORS-S3Origin` origin request policy, the response headers policy
`spatialscape-cors-range`, `GET, HEAD, OPTIONS` allowed, and `index.html` as the default root object. Note
its id and domain, then let it read the bucket:

```bash
export ID=<the distribution id, E1ABC...>
export DISTRIBUTION=$(aws cloudfront get-distribution --id $ID --query Distribution.DomainName --output text)   # dxxxx.cloudfront.net
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3api put-bucket-policy --bucket $BUCKET --policy "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"cloudfront.amazonaws.com\"},\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\",\"Condition\":{\"StringEquals\":{\"AWS:SourceArn\":\"arn:aws:cloudfront::$ACCOUNT:distribution/$ID\"}}}]}"
```

Upload each bundle folder (not `bundles/` itself: its `.cache/` sibling stays home) and the site, built with
`data_url` set to the distribution's domain:

```bash
aws s3 sync bundles/my_atlas s3://$BUCKET/my_atlas --exclude "*/build.json" --exclude "build-info.json"
spatialscape site build site.yaml -o site && aws s3 sync site s3://$BUCKET/      # site.yaml: data_url: https://dxxxx.cloudfront.net
spatialscape validate https://$DISTRIBUTION/my_atlas
```

CloudFront caches for a day; after re-uploading a changed bundle, invalidate its paths
(`aws cloudfront create-invalidation --distribution-id $ID --paths "/my_atlas/*"`). The same `datasets.json`
can be served from the distribution root and from a GitHub Pages copy of the viewer: the data is reached
cross-origin either way. For public scientific data, the AWS Open Data Sponsorship Program covers storage
and egress entirely.

## GitHub Pages

Fine for the app and for bundles that fit the 1 GB site limit; it does not guarantee Range support, so the bundles must be unsharded (`sharded: false` in the dataset yaml, or `build --no-shard`), which makes each gene its own file. [Publish your own site](./publish#under-1-gb-github-pages-start-to-finish) has the branch-and-push route; `site build` writes the `.nojekyll` file Pages needs.

## Your own server

Any static server that supports Range requests works (nginx, Apache, Caddy all do). Add the CORS headers above. `spatialscape serve` is a development server with both and is not meant for production traffic.

## Globus

Globus Connect Server v5 collections can expose files over HTTPS. A guest collection with anonymous access gives plain URLs that work for `curl` and, with CORS enabled on the collection, for the viewer as well. Useful when the authoritative copy already lives on institutional storage.

## Deploying the viewer

You do not need Node. `spatialscape site build` writes a folder with the viewer, a registry and your bundles
(or references to bundles on object storage); upload it as-is. The full walkthrough is in
[Publish your own site](./publish). Developers who change the app build it with `npm run build` and deploy
`app/dist`; the repository's Pages workflow does this for the demo and the docs.
