import numpy as np
import torch 
import random
import os
from torch.nn import functional as F
from models.NanoBind_pair import NanoBind_pair
from utils.dataloader import seq_affinity
from utils.evaluate import evaluate_aff
from torch.utils.data import DataLoader

def train(model, device, train_loader, optimizer, epoch):

    model.train()
    train_loss = 0
    for batch_idx, data in enumerate(train_loader):
        # Get input
        ab1 = data[0]
        ag1 = data[1]
        ab2 = data[2]
        ag2 = data[3]
        g=data[4].float().to(device)        
        # Calculate output
        optimizer.zero_grad()        
        p=model(ab1,ag1,ab2,ag2,device)
        
        # Calculate loss
        loss= F.binary_cross_entropy(p.squeeze(),g)
        train_loss = train_loss + loss.item()

        # Optimize the model
        loss.backward()
        optimizer.step()

    train_loss = train_loss / len(train_loader)
    return train_loss


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


def set_seed(seed = 1998):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministics = True


if __name__ == '__main__':
    
    set_seed()
    # Train setting
    BATCH_SIZE = 32
    LR = 0.00005 
    LOG_INTERVAL = 20000 
    NUM_EPOCHS = 10 
    
    # Step 1:Prepare dataloader
    trainDataset = seq_affinity('./data/affinity/train_100.csv')
    valDataset   = seq_affinity('./data/affinity/val_100.csv')
    # trainDataset = seq_affinity('./data/affinity/train_50.csv')
    # valDataset   = seq_affinity('./data/affinity/val_50.csv')
    # trainDataset = seq_affinity('./data/affinity/train_0.csv')
    # valDataset   = seq_affinity('./data/affinity/val_0.csv')   

    train_loader = DataLoader(trainDataset, batch_size=BATCH_SIZE, shuffle=True,pin_memory=True,drop_last=True)
    val_loader = DataLoader(valDataset, batch_size=BATCH_SIZE, shuffle=False,drop_last=True)

    # Step 2: Set  model
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model=NanoBind_pair()
    model = model.to(device)
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=LR, weight_decay=0.0001)

    best_AUC_PR = -1
    best_epoch = 0
    model_file_name =  './output/checkpoint/' + 'NanoBind_pair'

    for epoch in range(NUM_EPOCHS):
        # Train
        train_loss = train(model, device, train_loader, optimizer, epoch)

        # Val
        g,p = predicting(model, device, val_loader)

        precision,recall,accuracy,F1_score,AUC_ROC,AUC_PR,mcc = evaluate_aff(g,p,thresh=0.5)
        print(f"Epoch {epoch}: Loss={train_loss:.4f}, Accuracy={accuracy:.4f}, Recall={recall:.4f}, Precision={precision:.4f},F1={F1_score:.4f}, AUROC={AUC_ROC:.4f}, AUPRC={AUC_PR:.4f},MCC={mcc:.4f}")

        # Save model
        if best_AUC_PR<AUC_PR:
            best_AUC_PR = AUC_PR
            best_epoch = epoch
            torch.save(model.state_dict(), model_file_name +'_100.model')
        print("Best epoch {} ,best_aupr = {:.4f}".format(best_epoch,best_AUC_PR))
