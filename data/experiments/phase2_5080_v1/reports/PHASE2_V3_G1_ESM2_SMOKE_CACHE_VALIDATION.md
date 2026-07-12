# Frozen ESM2 Cache Validation V2.3

- Status: **PASS**
- Manifest rows / unique hashes: 10556 / 10556
- Validated tensor keys: 10556
- Shards: 32
- Embedding dimension: 320
- Dtypes: `{"torch.float16": 10556}`
- Chain types: `{"antigen": 2430, "mixed": 213, "vhh": 7913}`
- Truncation policies: `{"none": 10454, "prefix_1024": 102}`
- Orphan shard keys: 0
- Manifest SHA256: `372f7582ec15227f95a48c13d36691e0b56bbde45f15714198ac48ced01e725b`

Every manifest row was resolved to a finite floating-point tensor with the declared cached length and the expected 320-dimensional ESM2 representation.
