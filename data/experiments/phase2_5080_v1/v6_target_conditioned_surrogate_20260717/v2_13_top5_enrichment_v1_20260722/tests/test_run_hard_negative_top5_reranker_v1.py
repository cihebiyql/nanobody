from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


PKG=Path(__file__).resolve().parents[1]


def load_module():
    path=PKG/"src/run_hard_negative_top5_reranker_v1.py"
    spec=importlib.util.spec_from_file_location("v213_hard_negative_test",path);assert spec and spec.loader
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module


MOD=load_module();CORE=MOD.CORE


def dataset()->CORE.Dataset:
    rng=np.random.default_rng(917);count=500
    parents=[f"P{i//50:02d}" for i in range(count)];folds=np.asarray([(i//50)%5 for i in range(count)])
    signal=rng.uniform(.1,.9,count);truth=np.column_stack([signal+rng.normal(0,.02,count),signal+rng.normal(0,.02,count)])
    bases={name:truth+rng.normal(0,scale,truth.shape) for name,scale in {"S0":.09,"M2":.07,"C2":.1,"B":.08}.items()}
    return CORE.Dataset([f"C{i:04d}" for i in range(count)],[f"{i:064x}" for i in range(count)],parents,folds,truth,bases,rng.uniform(0,.03,count),rng.uniform(0,1,count),CORE.exact_min(bases["B"]))


CONTRACT={
 "hgb":{"max_depth":2,"max_iter":16,"learning_rate":.05,"min_samples_leaf":16,"l2_regularization":5.0},
 "extra_trees":{"n_estimators":32,"max_depth":5,"min_samples_leaf":8,"max_features":.75,"n_jobs":2},
 "logistic":{"C":.1},
 "promotion_gate":{"minimum_ef5_increment":.1,"maximum_ef10_decrement":.1,"minimum_folds_with_delta_at_least_minus_0p5":4,"minimum_single_fold_delta":-1.0},
}


class HardNegativeTests(unittest.TestCase):
    def test_union_pool_exceeds_top5_budget(self):
        data=dataset();index=np.arange(500);mask=MOD.pool_mask(data,index,.2)
        self.assertGreaterEqual(int(mask.sum()),25)
        self.assertLess(int(mask.sum()),500)

    def test_expanded_features_are_36_and_finite(self):
        data=dataset();index=np.arange(400);sorted_dual=[np.sort(CORE.exact_min(data.bases[name][index])) for name in CORE.BASES]
        values=MOD.expanded_raw(data,index,sorted_dual)
        self.assertEqual(values.shape,(400,36));self.assertTrue(np.isfinite(values).all())

    def test_complete_whole_parent_oof(self):
        data=dataset();scores,audit,models=MOD.oof(data,CONTRACT)
        self.assertEqual(set(scores),set(MOD.METHODS));self.assertEqual(set(audit),set(map(str,range(5))));self.assertEqual(set(models),set(map(str,range(5))))
        for score in scores.values():self.assertEqual(score.shape,(500,));self.assertTrue(np.isfinite(score).all())

    def test_no_increment_falls_back(self):
        base={"pooled_ef5":3.,"pooled_ef10":2.,"binary_ndcg_true_top10_at_budget5":.4,"spearman":.5,"fold_ef5":[3.]*5,"median_fold_ef5":3.,"worst_fold_ef5":3.}
        observed={name:dict(base) for name in MOD.METHODS};selected,audit=MOD.select(observed,CONTRACT)
        self.assertEqual(selected,"H0_EQUAL_RANK4");self.assertTrue(all(not x["eligible"] for x in audit.values()))


if __name__=="__main__":unittest.main()
