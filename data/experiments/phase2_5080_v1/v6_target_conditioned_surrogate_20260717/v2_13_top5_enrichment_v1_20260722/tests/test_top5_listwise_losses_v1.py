from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


PKG=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("v214_listwise_losses_test",PKG/"src/top5_listwise_losses_v1.py");assert spec and spec.loader
MOD=importlib.util.module_from_spec(spec);sys.modules[spec.name]=MOD;spec.loader.exec_module(MOD)


def batch():
    truth=torch.tensor([[.9,.85],[.8,.75],[.7,.65],[.6,.55],[.5,.45],[.4,.35],[.3,.25],[.2,.15]],dtype=torch.float32)
    return {"targets":truth,"truth_percentile":torch.tensor([.99,.95,.85,.75,.65,.55,.45,.35])}


def output(values):
    x=torch.tensor(values,dtype=torch.float32,requires_grad=True)
    return {"receptor_predictions":torch.column_stack([x,x+.01])}


class ListwiseLossTests(unittest.TestCase):
    def test_listmle_prefers_correct_order(self):
        good=MOD.top_weighted_listmle_loss(output([.9,.8,.7,.6,.5,.4,.3,.2]),batch(),softmin_tau=.02,score_temperature=.1,top_strength=3.,top_center=.9,top_scale=.05)
        bad=MOD.top_weighted_listmle_loss(output([.2,.3,.4,.5,.6,.7,.8,.9]),batch(),softmin_tau=.02,score_temperature=.1,top_strength=3.,top_center=.9,top_scale=.05)
        self.assertLess(float(good.detach()),float(bad.detach()))

    def test_soft_topk_prefers_correct_top(self):
        kwargs=dict(softmin_tau=.02,score_temperature=.1,rank_temperature=.5,top_k=2,positive_percentile=.9,false_positive_weight=.25,occupancy_weight=.1)
        good=MOD.soft_topk_recall_loss(output([.9,.8,.7,.6,.5,.4,.3,.2]),batch(),**kwargs)
        bad=MOD.soft_topk_recall_loss(output([.2,.3,.4,.5,.6,.7,.8,.9]),batch(),**kwargs)
        self.assertLess(float(good.detach()),float(bad.detach()))

    def test_combined_loss_has_finite_gradient(self):
        out=output([.4,.3,.7,.2,.8,.1,.6,.5])
        out["receptor_predictions"].retain_grad()
        config={"listmle_weight":.2,"soft_topk_weight":.4,"softmin_tau":.02,"score_temperature":.1,"rank_temperature":.5,"top_k":2,"positive_percentile":.9,"false_positive_weight":.25,"occupancy_weight":.1,"top_strength":3.,"top_center":.9,"top_scale":.05}
        loss,parts=MOD.combined_listwise_loss(out,batch(),config);loss.backward()
        self.assertTrue(torch.isfinite(loss));self.assertIsNotNone(out["receptor_predictions"].grad);self.assertTrue(torch.isfinite(out["receptor_predictions"].grad).all())
        self.assertEqual(set(parts),{"listmle","soft_topk","weighted_listwise_total"})


if __name__=="__main__":unittest.main()
