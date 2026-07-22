#!/usr/bin/env python3
"""Validate CPU smoke predictions against the frozen Node1 reference."""

import argparse
import csv
import json
from pathlib import Path

from scipy.stats import pearsonr, spearmanr


def table(path, id_choices, score_choices):
    rows=list(csv.DictReader(path.open()))
    if not rows: raise ValueError(f"empty {path}")
    fields=rows[0].keys()
    id_col=next(x for x in id_choices if x in fields)
    score_col=next(x for x in score_choices if x in fields)
    return {r[id_col]:float(r[score_col]) for r in rows}


def compare(actual, expected):
    if actual.keys()!=expected.keys():
        raise ValueError(f"ID mismatch actual={sorted(actual)} expected={sorted(expected)}")
    diffs={k:abs(actual[k]-expected[k]) for k in actual}
    keys=list(actual)
    observed=[actual[k] for k in keys]
    reference=[expected[k] for k in keys]
    return {
        'max_abs_diff':max(diffs.values(),default=0.0),
        'mean_abs_diff':sum(diffs.values())/len(diffs) if diffs else 0.0,
        'pearson':float(pearsonr(observed,reference).statistic),
        'spearman':float(spearmanr(observed,reference).statistic),
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument('deep_actual',type=Path); p.add_argument('nano_actual',type=Path)
    p.add_argument('deep_expected',type=Path); p.add_argument('nano_expected',type=Path)
    p.add_argument('-o','--output',type=Path,required=True); args=p.parse_args()
    deep_cols=(('Nanobody ID','Nanobody-ID','nanobody_id'),('Prediction','prediction','probability'))
    nano_cols=(('nanobody_id','Nanobody ID'),('probability','Prediction'))
    da=table(args.deep_actual,*deep_cols); de=table(args.deep_expected,*deep_cols)
    na=table(args.nano_actual,*nano_cols); ne=table(args.nano_expected,*nano_cols)
    deep=compare(da,de); nano=compare(na,ne)
    nano_classes_agree=all((na[k] >= 0.5) == (ne[k] >= 0.5) for k in na)
    # Frozen Node1 references were produced with CUDA/PyTorch 2.6, while bxcpu uses
    # CPU/PyTorch 2.1.  Exact floating-point identity is not expected.  Gate both
    # absolute drift and ranking/scale agreement so a model or input mismatch still
    # fails closed.
    gates={
        'deepnano_max_abs_diff':deep['max_abs_diff'] <= 5e-3,
        'deepnano_mean_abs_diff':deep['mean_abs_diff'] <= 2e-3,
        'deepnano_pearson':deep['pearson'] >= 0.999,
        'deepnano_spearman':deep['spearman'] >= 0.98,
        'nanobind_max_abs_diff':nano['max_abs_diff'] <= 1e-3,
        'nanobind_pearson':nano['pearson'] >= 0.999,
        'nanobind_class_agreement':nano_classes_agree,
    }
    status='PASS' if all(gates.values()) else 'FAIL'
    payload={'status':status,'records':len(da),'deepnano':deep,'nanobind':nano,
             'nanobind_class_agreement':nano_classes_agree,'gates':gates,
             'scientific_boundary':'CPU/GPU implementation equivalence for weak binding priors; not Kd, IC50, or blocking validation'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(json.dumps(payload,sort_keys=True))
    return 0 if status=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
