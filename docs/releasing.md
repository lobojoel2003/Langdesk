# Releasing

Langdesk uses [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

- **Patch** (`1.0.1`): bug fixes only.
- **Minor** (`1.1.0`): new features, backwards-compatible. Migrations run automatically.
- **Major** (`2.0.0`): changes that need someone to act when upgrading (settings, removed
  features). Explain them in the changelog.
- Pre-releases use a suffix: `1.1.0-rc.1`. They are published as GitHub pre-releases and are not
  tagged `latest`.

## Build numbers

Every image records the GitHub Actions run number that built it as its **build number**, along
with the commit and build time. You'll find them in the page footer, at `/healthz`, in the image
labels (`io.langdesk.build-number`, `org.opencontainers.image.revision`,
`org.opencontainers.image.created`) and in the extra image tag `X.Y.Z-build.N`.

Images built from `main` are tagged `edge`, `sha-<commit>` and `<version>-build.<N>`, so you can
always trace a running container back to a workflow run.

## Cutting a release

1. Move the **Unreleased** notes in `CHANGELOG.md` under a new heading,
   `## [X.Y.Z] - YYYY-MM-DD`, and update the comparison links at the bottom.
2. Set `__version__ = "X.Y.Z"` in `langdesk/version.py`.
3. Commit (`Release X.Y.Z`), merge to `main`, and wait for CI to pass.
4. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "Langdesk X.Y.Z"
   ```

   ```bash
   git push origin vX.Y.Z
   ```

The **Release** workflow then:

1. checks that the tag matches `langdesk/version.py` and that the changelog has a section for it;
2. runs the full CI suite again;
3. builds the wheel and sdist;
4. builds `linux/amd64` and `linux/arm64` images, pushes them to
   `ghcr.io/lobojoel2003/langdesk` as `X.Y.Z`, `X.Y`, `X`, `latest` and `X.Y.Z-build.N`, with an
   SBOM and signed build provenance;
5. publishes the GitHub release with the changelog notes, the Python packages,
   `docker-compose.yml`, `env.example` and `SHA256SUMS.txt`.

You can also run the workflow by hand from the Actions tab (**Release → Run workflow**) with the
version number. It creates the tag on the selected commit.

## Verifying a release

```bash
docker pull ghcr.io/lobojoel2003/langdesk:X.Y.Z
```

```bash
gh attestation verify oci://ghcr.io/lobojoel2003/langdesk:X.Y.Z --owner lobojoel2003
```

```bash
sha256sum -c SHA256SUMS.txt
```
