# Papyrus marketing site

The standalone public marketing site for `papyrus.anth.us`.

The Papyrus CMS and its demo publication remain separate: the demo reader is
served at `p.apyr.us`.

## Development

```bash
npm install
npm run dev
```

The site runs at `http://127.0.0.1:3012` and builds as a static export in
`out/`.

## Current scope

The sales page includes the Papyrus product story, open-source ownership
positioning, setup and management pricing, FAQ, and the wait-list interface.
The wait-list form is deliberately a design-only preview for now: it prevents
submission and does not send or store visitor data until a backend is added.

## Deployment

The site is exported to static files and served from a private, versioned S3
bucket through CloudFront. `infra/cloudformation.yml` owns only the isolated
marketing bucket, distribution, TLS certificate, and the `papyrus.anth.us`
Route 53 records. It does not modify any other `anth.us` record.

Run `scripts/deploy.sh` from the `marketing` directory to build, synchronize,
and invalidate the public site.
