import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
import argparse
import logging
# from torch.utils.tensorboard import SummaryWriter
import random
import os
from torch.nn import functional as F
import torch.distributed as dist
import warnings
warnings.filterwarnings("ignore")
from models.NanoBind_site import NanoBind_site
from utils.dataloader import infaData_Sabdab
from utils.evaluate import evaluate_site


'''
1.NanoBind_site
CUDA_VISIBLE_DEVICES=0 python train_site.py --Model 0 --finetune 1 --ESM2  esm2_t6_8M_UR50D &

'''

def get_args():
    parser = argparse.ArgumentParser(description='Train the model',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  

    parser.add_argument('--Model', dest='Model', type=int, default=0,
                        help='Model',metavar='E')
    
    parser.add_argument('--finetune', dest='finetune', type=int, default=1,
                        help='finetune',metavar='E')
    
    parser.add_argument('--local_rank', default=-1, type=int,
                    help='node rank for distributed training')
    
    parser.add_argument('--pretrained', dest='pretrained', type=str, default=None,
                        help='pretrained',metavar='E')
    
    parser.add_argument('--ESM2', dest='ESM2', type=str, default=None,
                        help='pretrained',metavar='E')
    
    return parser.parse_args()



def train(model, device, train_loader, optimizer, epoch, Model_type):
    '''
    training function at each epoch
    '''
    # print('Training on {} samples...'.format(len(train_loader.dataset)))
    logging.info('Training on {} samples...'.format(len(train_loader.dataset)))
    model.train()
    train_loss = 0

    for batch_idx, data in enumerate(train_loader):
        # Get input
        seqs_nanobody = data[0]
        seqs_antigen = data[1]
        BSite_antigen = data[3]
        # Calculate output
        optimizer.zero_grad()
        BSite_output = model(seqs_nanobody,seqs_antigen,device)
        
        # Calculate loss
        BSite_antigen = BSite_antigen.to(device)
        loss = F.binary_cross_entropy(BSite_output.flatten(), BSite_antigen[:,:BSite_output.shape[1]].float().flatten())

        train_loss = train_loss + loss.item()

        # Optimize the model
        loss.backward()
        optimizer.step()

        if batch_idx % LOG_INTERVAL == 0:
            logging.info('Train epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(epoch,
                                                                            batch_idx * BATCH_SIZE,
                                                                            len(train_loader.dataset),
                                                                            100. * batch_idx / len(train_loader),
                                                                            loss.item()))
    train_loss = train_loss / len(train_loader)
    return train_loss


def predicting(model, device, loader, Model_type):
    model.eval()
    total_BSite2 = list()
    total_labels = list()

    logging.info('Make prediction for {} samples...'.format(len(loader.dataset)))
    with torch.no_grad():
        # for data in tqdm(loader):
        for data in loader:

            seqs_nanobody = data[0]
            seqs_antigen = data[1]
            BSite_antigen = data[3]
            # Calculate output
            BSite_output = model(seqs_nanobody,seqs_antigen,device).cpu().numpy().tolist()
            
            for n in range(len(seqs_antigen)):
                len_seq = len(seqs_antigen[n])

                if len_seq > len(BSite_output[n]):
                    len_seq = len(BSite_output[n])

                total_BSite2.append(BSite_output[n][:len_seq])
                total_labels.append(BSite_antigen[n][:len_seq])

    return total_labels,total_BSite2
  

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
    BATCH_SIZE = 8
    LR = 0.00005
    LOG_INTERVAL = 20000
    NUM_EPOCHS = 200

    # Get argument parse
    args = get_args()
    model_name = 'NanoBind_site'

    # Set log
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Output name
    add_name = '({})_SabdabData_finetune{}_TF{}'.format(args.ESM2,args.finetune,(args.pretrained is not None)+0)

    logfile = './output/log/log_' + model_name + add_name + '.txt'
    fh = logging.FileHandler(logfile,mode='a')
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    formatter = logging.Formatter("%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s")
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)


    # Step 1:Prepare dataloader
    trainDataset = infaData_Sabdab(pair_path='./data/Sabdab/NAI_train_pos.csv')
    valDataset = infaData_Sabdab(pair_path='./data/Sabdab/NAI_val_pos.csv')
    
    from utils.dataloader import collate_fn_infaData
    train_loader = DataLoader(trainDataset, batch_size=BATCH_SIZE, shuffle=True,pin_memory=True,collate_fn=collate_fn_infaData)
    val_loader = DataLoader(valDataset, batch_size=BATCH_SIZE, shuffle=False,collate_fn=collate_fn_infaData)
    
    #Step 2: Set  model
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # device = torch.device("cpu")

    if args.Model == 0:
        # model = NanoBind_site(finetune=args.finetune).to(device)
        if args.ESM2 == 'esm2_t6_8M_UR50D':
            model = NanoBind_site(pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320, finetune=args.finetune).to(device)
        # model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[args.local_rank])

    # Load pretrained models
    if args.pretrained is not None:
        model_dir = './output/checkpoint/' 
        model_path = model_dir + args.pretrained
        weights = torch.load(model_path,map_location=torch.device('cpu')) # map_location=torch.device('cpu')

        model.load_state_dict(weights)

    #Step 3: Train the model
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)


    logging.info(f'''Starting training:
    Model_name:      {model_name}
    Epochs:          {NUM_EPOCHS}
    Batch size:      {BATCH_SIZE}
    Learning rate:   {LR}
    Training size:   {len(trainDataset)}
    Validating size: {len(valDataset)}
    Finetune:        {args.finetune}
    Device:          {device.type}
    ''')
    
    best_F1 = -1
    best_epoch = 0
    model_file_name =  './output/checkpoint/' + model_name + add_name

    for epoch in range(NUM_EPOCHS):
        # Train
        train_loss = train(model, device, train_loader, optimizer, epoch, args.Model)
        
        # val
        g,p = predicting(model, device, val_loader, args.Model)

        accuracy,precision,recall,F1_score,AUROC,AUPRC,mcc = evaluate_site(g,p)
        print(f"Epoch {epoch}: Train Loss = {train_loss:.4f}, "
          f"Acc= {accuracy:.4f}, Recall = {recall:.4f}, Pre= {precision:.4f}, "
          f"F1= {F1_score:.4f},AUROC={AUROC:.4f},AUPRC={AUPRC:.4f},mcc={mcc:.4f}")
        logging.info("Epoch {}: accuracy={:.4f},precision={:.4f},recall={:.4f},F1_score={:.4f},AUROC={:.4f},AUPRC={:.4f}".format(
            epoch,accuracy,precision,recall,F1_score,AUROC,AUPRC))

        threshold_range = np.arange(0, 1.1, 0.1)

        best_f1 = 0
        best_threshold = 0

        for threshold in threshold_range:
            accuracy,precision,recall,f1_score,AUROC,AUPRC,mcc = evaluate_site(g,p, thresh=threshold)    
            if f1_score > best_f1:
                best_f1 = f1_score
                best_threshold = threshold
        a, pe, re, f1, rc, pr ,mc= evaluate_site(g,p, thresh=best_threshold)
        print(f"Best Threshold: {best_threshold:.2f}, Best_F1: {best_f1:.4f},accuracy={a:.4f},precision={pe:.4f},recall={re:.4f},AUROC={rc:.4f},AUPRC={pr:.4f},mcc={mc:.4f},f1={f1:.4f}")

        if best_F1<f1:
            best_F1 = f1
            best_epoch = epoch
            # Save model
            torch.save(model.state_dict(), model_file_name +'_good.model')
        logging.info("Best epoch {} for ensemble with F1 = {:.4f}".format(best_epoch,best_F1))
        print("Best epoch {} ,best_F1 = {:.4f}".format(best_epoch,best_F1))


        