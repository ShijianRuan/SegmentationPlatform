# Segmentation Platform Utility Scripts

> Status: current minimal utilities for the file-package stage. These scripts are helpers around the current Case Package draft, not the platform architecture itself.

This directory now keeps the smallest tool-agnostic utilities that are already aligned with the current Case Package contract.

## Current Scripts

| Script | Purpose | Extra Dependencies |
|---|---|---|
| `hash_package.py` | Generate `checksums.sha256` for a package directory | None |
| `check_case_package.py` | Preflight validator for the current Case Package draft | None |

## Planned Scripts

| Script | Purpose | Extra Dependencies |
|---|---|---|
| `split_multilabel_to_masks.py` | Split a multilabel NIfTI into per-organ binary masks | `numpy`, `nibabel`, `PyYAML` |
| `merge_masks_to_multilabel.py` | Merge per-organ binary masks into one multilabel NIfTI | `numpy`, `nibabel`, `PyYAML` |
| `check_geometry.py` | Compare image and label shape/affine/spacing | `numpy`, `nibabel` |

## Scope boundary

```bash
# These scripts support file-package validation only.
# They do not replace Data Registry, Dataset Snapshot, or Tool Adapter logic.
```

The current contract reference is `docs/domains/labeling/case_package_contract.md`.
