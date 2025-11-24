# SiFli Mirror Sync

SiFli is used for synchronizing with domestic mirroring tools for internal use.

Currently based on Tencent Cloud's COS.

## Inputs

- `secret_id` (required): Tencent Cloud SecretId.
- `secret_key` (required): Tencent Cloud SecretKey.
- `region` (required): COS region (e.g. `ap-nanjing`).
- `bucket` (required): COS bucket name (e.g. `my-bucket-123456`).
- `prefix` (required): Remote prefix/folder to upload into (trailing slash added automatically).
- `artifacts` (required): Comma/newline-separated paths or globs; directories upload recursively. All matches are staged into one temp folder before upload.
- `delete_remote` (optional, default `false`): If `true`, remote files under `prefix` that are not in the staged content are deleted.
- `flush_url` (optional): CDN path to purge; when empty, purge step is skipped.
- `working_directory` (optional): If set, the action `cd`s into this path before resolving globs, so staged paths are relative to it.

## Example

```yaml
jobs:
  sync-cos:
    if: startsWith(github.ref, 'refs/tags/') && github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - name: Download build artifacts
        uses: actions/download-artifact@v4
        with:
          pattern: sftool-*
          path: artifacts
          merge-multiple: true

      - name: Upload to COS and optional CDN purge
        uses: OpenSiFli/SiFliMirrorSync@v1
        with:
          secret_id: ${{ secrets.COS_DOCS_SECRET_ID }}
          secret_key: ${{ secrets.COS_DOCS_SECRET_KEY }}
          region: ${{ secrets.COS_DOWNLOAD_REGION }}
          bucket: ${{ secrets.COS_DOWNLOAD_BUCKET }}
          prefix: github_assets/OpenSiFli/sftool/releases/download/${{ github.ref_name }}/
          artifacts: artifacts/
          delete_remote: true
          flush_url: https://downloads.sifli.com/github_assets/OpenSiFli/sftool/releases/download/
```

## Notes

- Staging keeps each matched path’s relative location (e.g., `artifacts/foo/bar.zip` stays under `artifacts/foo/bar.zip` in COS). Avoid name collisions across globs; the action errors if a collision occurs.
- `delete_remote` mirrors coscmd `--delete` against the staged view. Use with care.
- `flush_url` triggers `tccli cdn PurgePathCache`. Leave empty to skip CDN purge.
- Upload flow: first attempts with regional endpoint; on failure, reconfigures coscmd to use `cos.accelerate.myqcloud.com` and retries once. If the second attempt fails, the action fails.
