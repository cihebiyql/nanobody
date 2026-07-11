# Frozen ESM2 Cache Validation V2.3

- Status: **PASS**
- Manifest rows / unique hashes: 4935 / 4935
- Validated tensor keys: 4935
- Shards: 21
- Embedding dimension: 320
- Dtypes: `{"torch.float16": 4935}`
- Chain types: `{"antigen": 2418, "mixed": 213, "vhh": 2304}`
- Truncation policies: `{"none": 4838, "prefix_1024": 97}`
- Orphan shard keys: 0
- Manifest SHA256: `6d931b1f3f9a42a673c1ad9ee3cb8920feef6060515a11e1a05da51398828060`

Every manifest row was resolved to a finite floating-point tensor with the declared cached length and the expected 320-dimensional ESM2 representation.
