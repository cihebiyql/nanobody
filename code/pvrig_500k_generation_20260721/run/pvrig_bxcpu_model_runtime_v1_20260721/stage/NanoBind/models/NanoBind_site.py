import math
import torch
from torch import nn
import numpy as np
from transformers import AutoTokenizer, AutoModel
from torch.nn import functional as F

def sinusoidal_position_embedding(batch_size,  max_len, output_dim, device):
    
    position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(-1)
    ids = torch.arange(0, output_dim // 2, dtype=torch.float) 
    theta = torch.pow(10000, -2 * ids / output_dim)
    
    embeddings = position * theta 
    embeddings = torch.stack([torch.sin(embeddings), torch.cos(embeddings)], dim=-1)
    embeddings = embeddings.repeat((batch_size,  *([1] * len(embeddings.shape))))
    embeddings = torch.reshape(embeddings, (batch_size, max_len, output_dim))
    embeddings = embeddings.to(device)
    
    return embeddings
 
def RoPE(q, k):

    batch_size = q.shape[0]
    max_len = q.shape[1]
    output_dim = q.shape[-1]

    pos_emb = sinusoidal_position_embedding(batch_size, max_len, output_dim, q.device)
    cos_pos = pos_emb[...,  1::2].repeat_interleave(2, dim=-1)
    sin_pos = pos_emb[..., ::2].repeat_interleave(2, dim=-1)

    q2 = torch.stack([-q[..., 1::2], q[..., ::2]], dim=-1)
    q2 = q2.reshape(q.shape)
    q = q * cos_pos + q2 * sin_pos
 
    k2 = torch.stack([-k[..., 1::2], k[..., ::2]], dim=-1)
    k2 = k2.reshape(k.shape)
    k = k * cos_pos + k2 * sin_pos
 
    return q, k
 
def attention(q, k, v, mask=None, dropout=None, use_RoPE=True):
 
    if use_RoPE:
        q, k = RoPE(q, k) 
    d_k = k.size()[-1]
 
    att_logits = torch.matmul(q, k.transpose(-2, -1))  # (bs, head, seq_len, seq_len)
    att_logits /= math.sqrt(d_k)
 
    if mask is not None:
        att_logits = att_logits.masked_fill(mask == 0, -1e9) 
    att_scores = F.softmax(att_logits, dim=-1)  # (bs,seq_len, seq_len)
 
    if dropout is not None:
        att_scores = dropout(att_scores)

    return torch.matmul(att_scores, v)

from typing import Tuple
 
class CrossAttention(nn.Module):
    def __init__(self, dim, num_heads=8, max_seq_len=800):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.alpha = nn.Parameter(torch.tensor(0.5))

        self.max_seq_len = max_seq_len
        self.pe = self._init_positional_encoding()
        self.register_buffer('positional_encoding', self.pe)

        self.q_proj = nn.Linear(dim, dim)
        self.kv_proj = nn.Linear(dim, 2*dim)
        self.ln = nn.LayerNorm(dim)
        
    def _init_positional_encoding(self):

        pe = torch.zeros(self.max_seq_len, self.head_dim * self.num_heads)
        position = torch.arange(0, self.max_seq_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, self.head_dim * self.num_heads, 2).float() * (-math.log(10000.0) / self.head_dim * self.num_heads))
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        return pe
    
    def forward(self, nb_features, ag_features):
        b, l1, f = nb_features.shape
        _, l2, _ = ag_features.shape

        nb_pos_enc = self.positional_encoding[:, :l1, :]
        nb_features = nb_features + nb_pos_enc.to(nb_features.device)

        ag_pos_enc = self.positional_encoding[:, :l2, :]
        ag_features = ag_features + ag_pos_enc.to(ag_features.device)

        q = self.q_proj(ag_features)  # (b, l2, dim)
        k, v = torch.chunk(self.kv_proj(nb_features), 2, dim=-1)  # Key/Value (b, l1, dim)

        q = q.view(b, l2, self.num_heads, self.head_dim).transpose(1, 2)  # (b, h, l2, d)
        k = k.view(b, l1, self.num_heads, self.head_dim).transpose(1, 2)    # (b, h, l1, d)
        v = v.view(b, l1, self.num_heads, self.head_dim).transpose(1, 2)    # (b, h, l1, d)

        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)  # (b, h, l2, l1)
        attn_weights = torch.softmax(scores, dim=-1)  # (b, h, l2, l1)

        weighted_features = torch.matmul(attn_weights, v)  # (b, h, l2, d)
        weighted_features = weighted_features.transpose(1, 2).contiguous().view(b, l2, self.num_heads * self.head_dim)  # (b, l2, f)

        combined_features = self.alpha * weighted_features + (1 - self.alpha) * ag_features
        combined_features = self.ln(combined_features+ag_features)
        
        return combined_features

class Residual_Units(nn.Module):
    def __init__(self, dim_input, dim_hidden):
        super(Residual_Units, self).__init__()
        self.layer1 = nn.Linear(dim_input, dim_hidden)
        self.layer2 = nn.Linear(dim_hidden, dim_input)
        self.relu = nn.ReLU()

    def forward(self, inputs):
        x = inputs
        x = self.relu(self.layer1(x))
        x = self.layer2(x)
        outputs = self.relu(x + inputs)
        return outputs

        
class NanoBind_site(nn.Module):
    def __init__(self,pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320,finetune=1):
        super(NanoBind_site, self).__init__()

        self.tokenizer = AutoTokenizer.from_pretrained(pretrained_model)
        self.pretrained_model  = AutoModel.from_pretrained(pretrained_model)

        if finetune == 0:
            for param in self.pretrained_model.parameters():
                param.requires_grad = False
        elif finetune == 1:
            for name,param in self.pretrained_model.named_parameters():
                if 'esm2_t6_8M_UR50D' in pretrained_model and 'encoder.layer.5.' not in name:
                    param.requires_grad = False
                if 'esm2_t12_35M_UR50D' in pretrained_model and 'encoder.layer.11.' not in name:
                    param.requires_grad = False
                if 'esm2_t30_150M_UR50D' in pretrained_model and 'encoder.layer.29.' not in name:
                    param.requires_grad = False
                if 'esm2_t33_650M_UR50D' in pretrained_model and 'encoder.layer.32.' not in name:
                    param.requires_grad = False
                if 'esm2_t36_3B_UR50D' in pretrained_model and 'encoder.layer.35.' not in name:
                    param.requires_grad = False
                if 'esm2_t48_15B_UR50D' in pretrained_model and 'encoder.layer.47.' not in name:
                    param.requires_grad = False
        elif finetune == 2:
            for param in self.pretrained_model.parameters():
                param.requires_grad = True

        self.predict_module = nn.Sequential(
                                            Residual_Units(hidden_size*8,1024),
                                            Residual_Units(hidden_size*8,1024),
                                            Residual_Units(hidden_size*8,1024),
                                            nn.Linear(hidden_size*8,1),nn.Dropout(p=0.4),nn.Sigmoid())
        self.cnn = nn.Sequential(nn.Conv1d(hidden_size, hidden_size, 5,padding=2),nn.BatchNorm1d(hidden_size),nn.ReLU())
        self.att = CrossAttention(hidden_size*2)

    def forward(self,seq1,seq2,device):
        
        # Nanobody
        tokenizer1 = self.tokenizer(seq1,
                                    return_tensors="pt", 
                                    truncation=True,
                                    padding=True,
                                    max_length=800,
                                    add_special_tokens=False)
        input1_ids = torch.tensor(tokenizer1['input_ids']).to(device)
        attention_mask1 = torch.tensor(tokenizer1['attention_mask']).to(device)
        temp_output1 = self.pretrained_model(input_ids=input1_ids,attention_mask=attention_mask1)
        feature_seq1 = temp_output1.last_hidden_state
        feature_seq11 = attention(feature_seq1,feature_seq1,feature_seq1)
        feature_seq12 = feature_seq1.permute(0,2,1)
        feature_seq12 = self.cnn(feature_seq12)
        feature_seq12 = feature_seq12.permute(0,2,1)
        feature_seq1 = torch.cat((feature_seq11,feature_seq12),dim=2)
        feature_seq1_avg = torch.mean(feature_seq1,dim=1)
                                     
        # Antigen
        tokenizer2 = self.tokenizer(seq2,
                                    return_tensors="pt", 
                                    truncation=True,
                                    padding=True,
                                    max_length=800,
                                    add_special_tokens=False)
        input_ids2 = torch.tensor(tokenizer2['input_ids']).to(device)
        attention_mask2 = torch.tensor(tokenizer2['attention_mask']).to(device)
        temp_output2 = self.pretrained_model(input_ids=input_ids2,attention_mask=attention_mask2)
        feature_seq2 = temp_output2.last_hidden_state
        feature_seq21 = attention(feature_seq2,feature_seq2,feature_seq2)
        feature_seq22 = feature_seq2.permute(0,2,1)
        feature_seq22 = self.cnn(feature_seq22)
        feature_seq22 = feature_seq22.permute(0,2,1)
        feature_seq2 = torch.cat((feature_seq21,feature_seq22),dim=2)
        feature_seq2_avg = torch.mean(feature_seq2,dim=1)
                
        feature_seq1_all = feature_seq1_avg.unsqueeze(1).repeat(1, feature_seq2.shape[1], 1)    
        feature_seq2_all = feature_seq2_avg.unsqueeze(1).repeat(1, feature_seq2.shape[1], 1) 
       
        feature_all = torch.cat((feature_seq1_all,feature_seq2_all),dim=2)
        feature_att = self.att(feature_seq1,feature_seq2)
        feature_seq = torch.cat((feature_seq2,feature_att),dim=2)
        feature_seq = torch.cat((feature_seq,feature_all),dim=2)
        
        pre = self.predict_module(feature_seq)
        return pre