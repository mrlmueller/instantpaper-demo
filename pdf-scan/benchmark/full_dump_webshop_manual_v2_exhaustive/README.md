# full_dump_webshop_manual_v2_exhaustive

This suite is an exhaustive benchmark for the current webshop decision-psychology chapter.

Judgment meaning:
- `label_0_to_3 = 0`: not useful
- `label_0_to_3 = 1`: weak or marginal
- `label_0_to_3 = 2`: useful support
- `label_0_to_3 = 3`: core or strong support

Role meaning:
- `core_evidence`: highly useful section that should strongly matter in evaluation
- `strong_support`: clearly useful section that broadens or grounds the chapter
- `optional_support`: somewhat useful but not essential
- `weak_context`: context or background with limited standalone value
- `low_value` / `not_useful`: should not materially count as a success

Artifacts:
- `judgments/`: exhaustive per-document judgments
- `manifests/`: document manifests plus suite manifest
- `review_packets/`: human-readable per-document review packets

Built from run `386e04657c41c805f8c1b974` and the source suite `full_dump_webshop_manual_v1`.
