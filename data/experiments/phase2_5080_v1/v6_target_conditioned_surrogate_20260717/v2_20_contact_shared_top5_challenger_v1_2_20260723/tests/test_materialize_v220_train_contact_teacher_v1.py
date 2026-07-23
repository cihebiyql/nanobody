#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve()
ROOT=HERE.parents[1]
MODULE_PATH=ROOT/'src/materialize_v220_train_contact_teacher_v1.py'
SPEC=importlib.util.spec_from_file_location('v220_materializer',MODULE_PATH)
assert SPEC and SPEC.loader
MOD=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=MOD;SPEC.loader.exec_module(MOD)


def pdb_atom(serial:int,atom:str,resname:str,chain:str,resnum:int,x:float,y:float,z:float)->str:
    return f"ATOM  {serial:5d} {atom:^4s} {resname:>3s} {chain}{resnum:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C  \n"


def tiny_pose()->bytes:
    text=''.join([
        pdb_atom(1,'CA','ALA','A',1,0,0,0),
        pdb_atom(2,'CA','CYS','A',2,20,0,0),
        pdb_atom(3,'CA','ALA','T',41,1,0,0),
    ])+'END\n'
    return gzip.compress(text.encode(),mtime=0)


class Phase0FourteenTests(unittest.TestCase):
    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)

    def tearDown(self)->None:self.tmp.cleanup()

    def test_01_split_allowlist_precedes_candidate_specific_access(self)->None:
        split=self.root/'split.json';split.write_text('{}\n')
        metadata=self.root/'meta.tsv';metadata.write_text('x\n1\n')
        guard=MOD.AccessGuard()
        with self.assertRaisesRegex(MOD.MaterializationError,'metadata_before_split'):
            guard.open_metadata(metadata,'early')
        guard.open_split(split);guard.open_metadata(metadata,'after');guard.freeze_allowlist({'TRAIN1'})
        self.assertEqual(guard.event_order[:3],['split_manifest_open','metadata_open:after','train_allowlist_frozen'])

    def test_02_train_only_guard_rejects_dev_frozen_quarantine_before_resolution_or_stat(self)->None:
        split=self.root/'split.json';split.write_text('{}\n');guard=MOD.AccessGuard();guard.open_split(split);guard.freeze_allowlist({'TRAIN1'})
        for cid,split_name in [('DEV1','development'),('TEST1','frozen_test'),('Q1','quarantine'),('UNKNOWN','train')]:
            with self.assertRaisesRegex(MOD.MaterializationError,'pose_resolution_forbidden'):
                guard.resolve_pose(candidate_id=cid,model_split=split_name,root=self.root,job_id='job',model='m.pdb.gz')
        audit=guard.audit();self.assertEqual(audit['train_pose_files_opened'],0);self.assertEqual(audit['development_pose_files_stat_hashed_opened'],0)
        self.assertEqual(audit['forbidden_pose_attempt_count'],4)

    def test_03_v29_top8_coordinate_hash_and_contact_closure(self)->None:
        cid='TRAIN1';seq='AC';job='job1';base=self.root/job/'haddock_run/6_seletopclusts';base.mkdir(parents=True)
        models=[]
        for i in range(1,9):
            name=f'cluster_{i}_model_1.pdb.gz';(base/name).write_bytes(tiny_pose());models.append(name)
        split=self.root/'split.json';split.write_text('{}\n');guard=MOD.AccessGuard();guard.open_split(split);guard.freeze_allowlist({cid})
        candidate={'candidate_id':cid,'sequence_sha256':MOD.sha256_bytes(seq.encode()),'sequence':seq,'parent_framework_cluster':'C1','regions':['framework','cdr1']}
        row={'job_id':job,'conformation':'8x6b','seed':'917','top8_model_ids':','.join(models)}
        result=MOD.process_v29_job({'candidate':candidate,'job':row},guard,self.root,{'8x6b':{41:(1,'A')}})
        self.assertEqual(len(result['inventory']),8);self.assertEqual(len({x['pose_sha256'] for x in result['inventory']}),1)
        self.assertAlmostEqual(result['pair'][(1,41)],1.0);self.assertAlmostEqual(result['marginal'][1],1.0)
        self.assertEqual(guard.audit()['train_pose_files_opened'],8)

    def test_04_seed917_included_multiseed_rule_rejects_1931_3253_only(self)->None:
        c={'candidate_id':'X','sequence_sha256':'a'*64,'sequence':'AC','parent_framework_cluster':'C1','regions':['framework','cdr1']}
        mk=lambda s:{'seed':s,'pair':{(1,41):0.5},'marginal':{1:0.5}}
        with self.assertRaisesRegex(MOD.MaterializationError,'v29_seed_rule'):
            MOD.aggregate_v29(c,'8x6b',[mk(1931),mk(3253)],{'8x6b':{41:(1,'A')}})
        p,m=MOD.aggregate_v29(c,'8x6b',[mk(917),mk(1931)],{'8x6b':{41:(1,'A')}})
        self.assertEqual(p[0]['observed_seed_ids'],'917,1931');self.assertEqual(len(m),2)

    def test_05_technical_na_is_masked_not_zero_negative(self)->None:
        self.assertIsNone(MOD.balanced_soft_bce([0,0],[0,0],[1,1],[0,0]))
        valid=MOD.balanced_soft_bce([0,0],[0,0],[1,1],[1,1])
        self.assertAlmostEqual(valid,math.log(2),places=12)

    def test_06_frozen_primary_join_count_and_source_contract(self)->None:
        self.assertEqual(MOD.EXPECTED,{'V4D':113,'V4H':320,'V29':305})
        self.assertEqual(sum(MOD.EXPECTED.values()),738);self.assertEqual(MOD.EXPECTED_PARENTS,53)
        contract=json.loads((ROOT/'PHASE0_TEACHER_MATERIALIZATION_CONTRACT_V1.json').read_text())
        self.assertEqual(contract['expected_train_teacher']['candidates'],738);self.assertEqual(contract['expected_train_teacher']['development_candidates'],0)

    def test_07_dense_universe_mapping_valid_absent_zero_and_invalid_mask_zero(self)->None:
        c={'candidate_id':'X','sequence_sha256':'a'*64,'sequence':'AC','parent_framework_cluster':'C1','regions':['framework','cdr1']}
        row={'receptor':'8x6b','vhh_sequence_index':'1','vhh_aa':'A','pvrig_uniprot_position':'41','pvrig_aa':'A','observed_seed_count':'2','seed_contact_values':'917:0.5;1931:0','contact_target_mean':'0.25','contact_target_variance':'0.0625','contact_uncertainty_weight':str(1/(1+4*0.0625)),'supporting_seed_count':'1'}
        out=MOD.normalize_pair(row,c,'V29',{'8x6b':{41:(1,'A')}})
        self.assertEqual(out['pvrig_node_index'],1);self.assertEqual(out['target_mask'],1)
        self.assertEqual(2*103,206) # sequence length x frozen 8X6B nodes
        self.assertIsNone(MOD.balanced_soft_bce([0],[0],[1],[0]))

    def test_08_contact_reduction_golden_both_single_class_and_unavailable(self)->None:
        both=MOD.balanced_soft_bce([0,0],[1,0],[1,1],[1,1]);self.assertAlmostEqual(both,math.log(2),places=12)
        pos=MOD.balanced_soft_bce([2],[1],[1],[1]);self.assertAlmostEqual(pos,math.log1p(math.exp(-2)),places=12)
        neg=MOD.balanced_soft_bce([-2],[0],[1],[1]);self.assertAlmostEqual(neg,math.log1p(math.exp(-2)),places=12)
        self.assertIsNone(MOD.balanced_soft_bce([1],[1],[1],[0]))

    def test_09_exact_v213_scalar_softmin_top_weight_contract(self)->None:
        pred=np.array([[0.5,0.6],[0.7,0.4]],dtype=float);truth=np.array([[0.55,0.58],[0.68,0.45]],dtype=float)
        weights=MOD.v213_top_weights([0.55,0.45],[1,1]);self.assertGreater(weights[0],weights[1])
        loss=MOD.v213_scalar_loss(pred,truth,weights);self.assertTrue(math.isfinite(loss) and loss>0)
        sm=MOD.v213_softmin(np.array([0.5]),np.array([0.6]))[0];self.assertLessEqual(sm,0.5+0.02*math.log(2)+1e-12)

    def test_10_batch_shuffle_remainder_and_pairing_contract(self)->None:
        a=MOD.v213_epoch_batches(19,43,0);b=MOD.v213_epoch_batches(19,43,0)
        self.assertEqual(a,b);self.assertEqual([len(x) for x in a],[8,8,3]);self.assertEqual(sorted(sum((list(x) for x in a),[])),list(range(19)))
        self.assertEqual(MOD.v213_remainder_gradient_scale(1),4);self.assertEqual(MOD.v213_remainder_gradient_scale(4),1)

    def test_11_five_fold_bindings_and_B0_hash_contract(self)->None:
        self.assertEqual(len(MOD.V213_FOLD_BINDINGS),5);self.assertEqual(len(MOD.B0_OOF_SHA256),64)
        for fold,train,score,digest in MOD.V213_FOLD_BINDINGS:
            self.assertEqual(train+score,9849);self.assertEqual(len(digest),64);int(digest,16);self.assertIn(fold,range(5))

    def test_12_C0_C1_full_state_initialization_hash_pairing(self)->None:
        state={'a':np.array([1,2],dtype=np.float32),'b':np.array([[3]],dtype=np.int64)}
        clone={k:v.copy() for k,v in state.items()};self.assertEqual(MOD.state_hash(state),MOD.state_hash(clone))
        clone['a'][0]=9;self.assertNotEqual(MOD.state_hash(state),MOD.state_hash(clone))

    def test_13_forward_firewall_gcontact_and_gradient_conflict_rule(self)->None:
        MOD.validate_forward_keys({'vhh_residue','target_graph'})
        with self.assertRaisesRegex(MOD.MaterializationError,'forbidden_forward_keys'):
            MOD.validate_forward_keys({'vhh_residue','teacher_source'})
        self.assertFalse(MOD.conflict_prelaunch_fails([-0.6,-0.6,0,0,0,0,0,0]));self.assertTrue(MOD.conflict_prelaunch_fails([-0.6,-0.6,-0.6,0,0,0,0,0]))
        contract=json.loads((ROOT/'PHASE0_TEACHER_MATERIALIZATION_CONTRACT_V1.json').read_text())
        self.assertEqual(contract['gradient_calibration_contract']['g_contact_exact'],'gradient_over_shared_parameters_of_(L_marginal + 0.5 * L_pair)_before_lambda_scaling')

    def test_14_target_node_position_baseline_and_ablation_movement_contract(self)->None:
        mapping=MOD.deterministic_derangement(['a','b','c','d']);self.assertEqual(MOD.movement_rate(mapping),1.0)
        contract=json.loads((ROOT/'PHASE0_TEACHER_MATERIALIZATION_CONTRACT_V1.json').read_text())
        baseline=contract['target_node_position_baseline_contract'];self.assertIn('pvrig_node_index',baseline['pair_baseline_key']);self.assertEqual(baseline['fit_data'],'outer_fit_parents_only')
        ab=contract['ablation_contract'];self.assertTrue(all(ab[k]['mode'].startswith('inference_perturbation') for k in ('target_residue_embedding_permutation','hotspot_mask_shuffle','conformer_swap')))
        shuffle=ab['contact_label_shuffle'];self.assertEqual(shuffle['mode'],'full_five_fold_retraining_from_C1_paired_initialization');self.assertEqual(shuffle['required_movement_rate_eligible'],1.0);self.assertGreaterEqual(shuffle['minimum_eligible_fraction_pooled'],0.70)


if __name__=='__main__':unittest.main(verbosity=2)
