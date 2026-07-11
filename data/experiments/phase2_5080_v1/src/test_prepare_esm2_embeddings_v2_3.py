#!/usr/bin/env python3
"""Unit tests for strict V2.3 ESM2 embedding-cache preparation."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_esm2_embeddings_v2_3 import (  # noqa: E402
    SequenceRecord,
    apply_prefix_length_policy,
    append_sharded_embeddings,
    collect_unique_sequences,
    dynamic_attention_batches,
    load_existing_manifest,
    sequence_sha256,
    shard_records,
)


class PrepareEsm2EmbeddingsTests(unittest.TestCase):
    def test_collect_unique_sequences_from_strict_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            site = root / "site.csv"
            pair = root / "pair.csv"
            ranking = root / "ranking.csv"
            contact = root / "contact.jsonl"
            site.write_text("vhh_seq,antigen_seq\nACDE,FGHI\nACDE,KLMN\n", encoding="utf-8")
            pair.write_text("vhh_seq,antigen_seq\nQRST,FGHI\n", encoding="utf-8")
            ranking.write_text(
                "positive_vhh_seq,positive_antigen_seq,negative_vhh_seq,negative_antigen_seq\n"
                "ACDE,FGHI,QRST,NPQR\n",
                encoding="utf-8",
            )
            contact.write_text(json.dumps({"vhh_seq": "VWYA", "antigen_seq": "KLMN"}) + "\n", encoding="utf-8")

            records = collect_unique_sequences(site, pair, ranking, contact)
            by_seq = {record.sequence: record for record in records}

            self.assertEqual(set(by_seq), {"ACDE", "FGHI", "KLMN", "QRST", "NPQR", "VWYA"})
            self.assertEqual(by_seq["ACDE"].sequence_sha256, sequence_sha256("ACDE"))
            self.assertEqual(by_seq["ACDE"].chain_type, "vhh")
            self.assertEqual(by_seq["FGHI"].chain_type, "antigen")

    def test_sharding_writes_fp16_packed_files_and_manifest(self) -> None:
        records = [
            SequenceRecord(sequence_sha256("AAAA"), "AAAA", "vhh"),
            SequenceRecord(sequence_sha256("CC"), "CC", "antigen"),
            SequenceRecord(sequence_sha256("DDD"), "DDD", "antigen"),
        ]
        embeddings = {record.sequence_sha256: torch.ones((len(record.sequence), 5), dtype=torch.float32) for record in records}
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir)
            manifest = output / "manifest.csv"
            rows = append_sharded_embeddings(
                output,
                manifest,
                records,
                embeddings,
                model_path=Path("/frozen/esm2_8m"),
                model_sha256="modelhash",
                shard_size=2,
            )

            self.assertEqual(len(rows), 3)
            self.assertTrue((output / "shard_00000.pt").exists())
            self.assertTrue((output / "shard_00001.pt").exists())
            shard0 = torch.load(output / "shard_00000.pt", map_location="cpu")
            self.assertEqual(len(shard0), 2)
            self.assertTrue(all(tensor.dtype == torch.float16 for tensor in shard0.values()))
            with manifest.open("r", encoding="utf-8", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))
            self.assertEqual(len(manifest_rows), 3)
            self.assertEqual(manifest_rows[0]["model_sha256"], "modelhash")
            self.assertTrue(all(row["cached_length"] == row["sequence_length"] for row in manifest_rows))
            self.assertTrue(all(row["truncation_policy"] == "none" for row in manifest_rows))
            self.assertEqual(set(row["shard_key"] for row in manifest_rows), {record.sequence_sha256 for record in records})

    def test_resume_metadata_skips_existing_model_rows_with_present_shards(self) -> None:
        record = SequenceRecord(sequence_sha256("AAAA"), "AAAA", "vhh")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir)
            torch.save({record.sequence_sha256: torch.zeros((4, 2), dtype=torch.float16)}, output / "shard_00000.pt")
            manifest = output / "manifest.csv"
            manifest.write_text(
                "model_path,model_sha256,sequence_sha256,sequence_length,cached_length,truncation_policy,chain_type,shard_path,shard_key\n"
                f"/model,keep,{record.sequence_sha256},4,4,none,vhh,shard_00000.pt,{record.sequence_sha256}\n"
                f"/model,other,{sequence_sha256('CCCC')},4,4,none,vhh,shard_00001.pt,{sequence_sha256('CCCC')}\n",
                encoding="utf-8",
            )

            existing = load_existing_manifest(manifest, "keep")
            self.assertEqual(set(existing), {record.sequence_sha256})

            second = SequenceRecord(sequence_sha256("CC"), "CC", "antigen")
            rows = append_sharded_embeddings(
                output,
                manifest,
                [second],
                {second.sequence_sha256: torch.ones((2, 3))},
                model_path=Path("/model"),
                model_sha256="keep",
                existing_rows=existing,
                shard_size=10,
            )
            self.assertEqual(len(rows), 2)
            self.assertTrue((output / "shard_00001.pt").exists())
            reloaded = load_existing_manifest(manifest, "keep")
            self.assertEqual(set(reloaded), {record.sequence_sha256, second.sequence_sha256})

    def test_shard_records_rejects_invalid_size(self) -> None:
        with self.assertRaises(ValueError):
            shard_records([], 0)

    def test_prefix_policy_preserves_full_hash_and_original_length(self) -> None:
        full = "ACDEFGHIKL"
        record = SequenceRecord(sequence_sha256(full), full, "antigen")
        cached = apply_prefix_length_policy([record], 6)[0]
        self.assertEqual(cached.sequence_sha256, sequence_sha256(full))
        self.assertEqual(cached.sequence, full[:6])
        self.assertEqual(cached.source_length, len(full))

    def test_dynamic_batches_reduce_long_sequence_batch_size(self) -> None:
        records = [
            SequenceRecord(sequence_sha256("A" * length), "A" * length, "antigen")
            for length in (100, 100, 500, 500, 1024, 1024)
        ]
        batches = dynamic_attention_batches(records, max_batch_size=16, attention_budget=1_000_000)
        self.assertEqual([len(batch) for batch in batches], [4, 1, 1])
        self.assertTrue(all(len(batch) * max(len(record.sequence) for record in batch) ** 2 <= 1_000_000 or len(batch) == 1 for batch in batches))


if __name__ == "__main__":
    unittest.main()
