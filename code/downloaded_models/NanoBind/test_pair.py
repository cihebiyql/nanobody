import numpy as np
import torch 
import random
import pandas as pd
from torch.nn import functional as F
from models.NanoBind_pair import NanoBind_pair
from utils.dataloader import seq_affinity
from utils.evaluate import evaluate_aff
from torch.utils.data import DataLoader

def predicting(model, device, loader):
    model.eval()
    total_preds = torch.Tensor()
    total_labels = torch.Tensor()

    with torch.no_grad():
        # for data in tqdm(loader):
        for data in loader:
            # Get input
            ab1 = data[0]
            ag1 = data[1]
            ab2 = data[2]
            ag2 = data[3]

            # Calculate output
            p=model(ab1,ag1,ab2,ag2,device)            
            total_preds = torch.cat((total_preds, p.cpu()), 0)
            
            g = data[4]
            total_labels = torch.cat((total_labels, g), 0)

    return total_labels.numpy().flatten(),total_preds.numpy().flatten()

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
model=NanoBind_pair()
model = model.to(device)
model_path = './output/checkpoint/' + 'NanoBind_pair_100.model'
weights = torch.load(model_path,map_location=torch.device('cpu'))
model.load_state_dict(weights)

testDataset = seq_affinity('./data/affinity/test_100.csv')
test_loader = DataLoader(testDataset, batch_size=32, shuffle=False)

g,p = predicting(model, device, test_loader)
precision,recall,accuracy,F1_score,AUC_ROC,AUC_PR,mcc = evaluate_aff(g,p,thresh=0.4)
# precision,recall,accuracy,F1_score,AUC_ROC,AUC_PR,mcc = evaluate_aff(g,p,thresh=0.4) # 50%
# precision,recall,accuracy,F1_score,AUC_ROC,AUC_PR,mcc = evaluate_aff(g,p,thresh=0.2) # 0%

# save
csv_metrics = pd.DataFrame([{
    'accuracy': f"{accuracy:.4f}",
    'precision': f"{precision:.4f}",
    'recall': f"{recall:.4f}",
    'F1_score': f"{F1_score:.4f}",
    'AUC_ROC': f"{AUC_ROC:.4f}",
    'AUC_PR': f"{AUC_PR:.4f}",
    'MCC': f"{mcc:.4f}",
}])
csv_metrics.to_csv(f'./output/test_results/NanoBind_pair(100%)_results.csv', index=False)
