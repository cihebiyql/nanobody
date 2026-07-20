# V2 to V3 migration

V2 failed at scoring because `score_pose.py` requires `reports/reference_normalization_summary.json`. V3 adds that file and closes the aggregation imports. Stop V2 before copying mutable output directories. Preserve job IDs, hashes and protocol hashes; do not relabel scoring failures as biological negatives.
