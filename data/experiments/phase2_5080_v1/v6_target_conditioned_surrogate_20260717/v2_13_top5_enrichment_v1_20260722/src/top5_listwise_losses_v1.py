"""Numerically stable listwise losses for V2.14 Top5 enrichment training."""

from __future__ import annotations

import math
from typing import Mapping

import torch
import torch.nn.functional as F
from torch import Tensor


class ListwiseLossError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ListwiseLossError(message)


def predicted_dual(output: Mapping[str, Tensor], softmin_tau: float) -> Tensor:
    require(softmin_tau > 0.0, "softmin_tau")
    predictions=output["receptor_predictions"].float()
    require(predictions.ndim==2 and predictions.shape[1]==2,"prediction_shape")
    return -softmin_tau*torch.logsumexp(-predictions/softmin_tau,dim=1)+softmin_tau*math.log(2.0)


def top_weighted_listmle_loss(
    output: Mapping[str,Tensor],
    batch: Mapping[str,Tensor],
    *,
    softmin_tau: float,
    score_temperature: float,
    top_strength: float,
    top_center: float,
    top_scale: float,
) -> Tensor:
    require(score_temperature>0 and top_strength>=0 and top_scale>0,"listmle_config")
    score=predicted_dual(output,softmin_tau)/score_temperature
    targets=batch["targets"].to(score.device,dtype=torch.float32)
    percentiles=batch["truth_percentile"].to(score.device,dtype=torch.float32)
    truth=torch.minimum(targets[:,0],targets[:,1])
    order=torch.argsort(truth,descending=True,stable=True)
    ordered_score=score[order];ordered_percentile=percentiles[order]
    suffix_logsumexp=torch.logcumsumexp(torch.flip(ordered_score,dims=(0,)),dim=0).flip(0)
    terms=suffix_logsumexp-ordered_score
    weights=1.0+top_strength*torch.sigmoid((ordered_percentile-top_center)/top_scale)
    loss=(weights*terms).sum()/weights.sum().clamp_min(1e-12)
    require(bool(torch.isfinite(loss)),"listmle_nonfinite")
    return loss


def soft_topk_recall_loss(
    output: Mapping[str,Tensor],
    batch: Mapping[str,Tensor],
    *,
    softmin_tau: float,
    score_temperature: float,
    rank_temperature: float,
    top_k: int,
    positive_percentile: float,
    false_positive_weight: float,
    occupancy_weight: float,
) -> Tensor:
    require(score_temperature>0 and rank_temperature>0 and top_k>0,"soft_topk_config")
    score=predicted_dual(output,softmin_tau)/score_temperature
    require(top_k<len(score),"soft_topk_k")
    percentile=batch["truth_percentile"].to(score.device,dtype=torch.float32)
    labels=(percentile>=positive_percentile).float()
    require(bool(labels.sum()>0) and bool(labels.sum()<len(labels)),"soft_topk_class_balance")
    # rank_i = 1 + number of candidates with a higher score; subtract the self 0.5 term.
    higher=torch.sigmoid((score[None,:]-score[:,None])/rank_temperature)
    soft_rank=1.0+higher.sum(dim=1)-0.5
    membership=torch.sigmoid((float(top_k)+0.5-soft_rank)/rank_temperature)
    recall= (membership*labels).sum()/labels.sum().clamp_min(1e-12)
    false_positive=(membership*(1.0-labels)).sum()/membership.sum().clamp_min(1e-12)
    occupancy=((membership.sum()-float(top_k))/float(top_k)).square()
    loss=1.0-recall+false_positive_weight*false_positive+occupancy_weight*occupancy
    require(bool(torch.isfinite(loss)),"soft_topk_nonfinite")
    return loss


def combined_listwise_loss(
    output: Mapping[str,Tensor],
    batch: Mapping[str,Tensor],
    config: Mapping[str,float|int],
) -> tuple[Tensor,dict[str,Tensor]]:
    zero=output["receptor_predictions"].sum()*0.0
    listmle=zero
    soft_topk=zero
    if float(config["listmle_weight"])>0:
        listmle=top_weighted_listmle_loss(output,batch,softmin_tau=float(config["softmin_tau"]),score_temperature=float(config["score_temperature"]),top_strength=float(config["top_strength"]),top_center=float(config["top_center"]),top_scale=float(config["top_scale"]))
    if float(config["soft_topk_weight"])>0:
        soft_topk=soft_topk_recall_loss(output,batch,softmin_tau=float(config["softmin_tau"]),score_temperature=float(config["score_temperature"]),rank_temperature=float(config["rank_temperature"]),top_k=int(config["top_k"]),positive_percentile=float(config["positive_percentile"]),false_positive_weight=float(config["false_positive_weight"]),occupancy_weight=float(config["occupancy_weight"]))
    total=float(config["listmle_weight"])*listmle+float(config["soft_topk_weight"])*soft_topk
    return total,{"listmle":listmle,"soft_topk":soft_topk,"weighted_listwise_total":total}
