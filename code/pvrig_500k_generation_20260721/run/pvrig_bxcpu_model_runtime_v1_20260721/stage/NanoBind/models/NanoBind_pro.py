import math
import torch
from torch import nn
import numpy as np
from transformers import AutoTokenizer, AutoModel
from torch.nn import functional as F
from models.NanoBind_site import NanoBind_site
    
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


class NanoBind_pro(nn.Module):
    def __init__(self,pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320,d_prompt=8,finetune=1,
                 Model_BSite_path=r'./output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model'):
        super(NanoBind_pro, self).__init__()

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
        self.cnn = nn.Sequential(nn.Conv1d(hidden_size, hidden_size, 5),nn.BatchNorm1d(hidden_size),nn.ReLU())

        # Antigen_BSite_predictor
        self.Antigen_BSite_predictor = NanoBind_site(pretrained_model=pretrained_model,hidden_size=hidden_size,finetune=0)
        weights = torch.load(Model_BSite_path,map_location=torch.device('cpu'))
        self.Antigen_BSite_predictor.load_state_dict(weights) 
        
        for param in self.Antigen_BSite_predictor.parameters():
            param.requires_grad = False
        self.embeddingLayer = nn.Embedding(2, d_prompt)
        self.positionalEncodings = nn.Parameter(torch.rand(4000, d_prompt), requires_grad=True)
        encoder_layers = nn.TransformerEncoderLayer(d_prompt, nhead=8,dim_feedforward=128,dropout=0.4)
        encoder_norm = nn.LayerNorm(d_prompt)
        self.Prompt_encoder = nn.TransformerEncoder(encoder_layers,1,encoder_norm) 
        
        if finetune == 0:
            for param in self.embeddingLayer.parameters():
                param.requires_grad = False
            self.positionalEncodings.requires_grad = False
            for param in self.Prompt_encoder.parameters():
                param.requires_grad = False
                
        self.mlp = nn.Sequential(nn.Linear(hidden_size*2+d_prompt, hidden_size*2),nn.BatchNorm1d(hidden_size*2), nn.ReLU())
        self.predict_module  =  nn.Sequential(
                                    nn.Linear(hidden_size*2, 1024), nn.BatchNorm1d(1024), nn.ReLU(),
                                    nn.Linear(1024, 512), nn.BatchNorm1d(512), nn.ReLU(),
                                    nn.Linear(512, 256), nn.BatchNorm1d(256), nn.ReLU(),
                                    nn.Linear(256, 128), nn.BatchNorm1d(128), nn.ReLU(),
                                    nn.Linear(128, 1),nn.Sigmoid())

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
        temp_output1 = self.pretrained_model(input_ids = input1_ids,attention_mask = attention_mask1) 
        feature_seq1 = temp_output1.last_hidden_state
        feature_seq11 = attention(feature_seq1,feature_seq1,feature_seq1)
        feature_seq11 = torch.mean(feature_seq11,dim=1)
        feature_seq12 = feature_seq1.permute(0,2,1)
        feature_seq12 = self.cnn(feature_seq12)
        feature_seq12 = feature_seq12.permute(0,2,1)
        feature_seq12 = torch.mean(feature_seq12,dim=1)
        feature_seq1 = torch.cat((feature_seq11,feature_seq12),dim=1)
     
        # Antigen
        tokenizer2 = self.tokenizer(seq2,
                                    return_tensors="pt", 
                                    truncation=True,
                                    padding=True,
                                    max_length=800,
                                    add_special_tokens=False)
        input_ids2 = torch.tensor(tokenizer2['input_ids']).to(device)
        attention_mask2 = torch.tensor(tokenizer2['attention_mask']).to(device)
        temp_output2 = self.pretrained_model(input_ids = input_ids2,attention_mask = attention_mask2)
        feature_seq2 = temp_output2.last_hidden_state 
        feature_seq21 = attention(feature_seq2,feature_seq2,feature_seq2)
        feature_seq21 = torch.mean(feature_seq21,dim=1)
        feature_seq22 = feature_seq2.permute(0,2,1)
        feature_seq22 = self.cnn(feature_seq22) 
        feature_seq22 = feature_seq22.permute(0,2,1)
        feature_seq22 = torch.mean(feature_seq22,dim=1)
        feature_seq2 = torch.cat((feature_seq21,feature_seq22),dim=1)
        
        # Prompt
        BSite2 = self.Antigen_BSite_predictor(seq1,seq2,device)
        BSite2 = (BSite2.squeeze()>0.5)+0
        BSite2_embedding = self.embeddingLayer(BSite2)
        BSite2_embedding = BSite2_embedding + self.positionalEncodings[:BSite2_embedding.shape[1],:]
        BSite2_embedding = BSite2_embedding.permute(1,0,2)
        BSite2_embedding = self.Prompt_encoder(BSite2_embedding)
        BSite2_embedding = BSite2_embedding.permute(1,0,2)
        BSite2_embedding_ave = torch.mean(BSite2_embedding,dim = 1)
               
        # MLP
        feature_seq2 = torch.cat((feature_seq2,BSite2_embedding_ave),dim=1)
        feature_seq2 = self.mlp(feature_seq2)

        feature_seq = torch.multiply(feature_seq1,feature_seq2)
        p = self.predict_module(feature_seq)   
        return p
