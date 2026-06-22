# Custom Importer Examples

This directory contains templates for L4 dataset importers.

Use a custom importer only when `sp ingest scan` and `sp ingest from-description`
cannot express the dataset layout safely. A custom importer must still output
standard `case_package_request.v1` files and standard reports; it must not write
the Registry directly.

Expected output:

```text
import_runs/{dataset_id}_{run_id}/
  requests/
  reports/
    import_summary.json
    import_issues.csv
    importer_manifest.json
  derived/
  logs/
```

Read the full contract before copying the template:

```text
docs/architecture/custom_importer_contract.md
```

The template is intentionally conservative. It provides report writers and
stable issue fields, but dataset-specific discovery must be implemented by the
developer who understands the source dataset.
