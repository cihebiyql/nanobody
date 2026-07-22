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
import warnings
warnings.filterwarnings("ignore")
from models.NanoBind_seq import NanoBind_seq
from models.NanoBind_pro import NanoBind_pro
from utils.dataloader import seqData_Sabdab,seqData_NBAT_Test
from utils.evaluate import evaluate

'''
1. NanoBind_seq
CUDA_VISIBLE_DEVICES=0 python train_nai.py --Model 0 --finetune 1 --ESM2  esm2_t6_8M_UR50D &

2. NanoBind_pro
CUDA_VISIBLE_DEVICES=0 python train_nai.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D &

'''


def get_args():
    parser = argparse.ArgumentParser(description='Train the model',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)


    parser.add_argument('--Model', dest='Model', type=int, default=0,
                        help='Model',metavar='E')
    
    parser.add_argument('--finetune', dest='finetune', type=int, default=1,
                        help='finetune',metavar='E')
    
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
        
        # Calculate output
        optimizer.zero_grad()
        
        p= model(seqs_nanobody,seqs_antigen,device)
        
        # Calculate loss
        gt = data[2].float().to(device)
        loss = F.binary_cross_entropy(p.squeeze(),gt)
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
    total_preds_ave = torch.Tensor()
    total_labels = torch.Tensor()

    logging.info('Make prediction for {} samples...'.format(len(loader.dataset)))
    with torch.no_grad():
        # for data in tqdm(loader):
        for data in loader:
            # Get input
            seqs_nanobody = data[0]
            seqs_antigen = data[1]

            # Calculate output
            p = model(seqs_nanobody,seqs_antigen,device)
            
            total_preds_ave = torch.cat((total_preds_ave, p.cpu()), 0)
            
            g = data[2]
            total_labels = torch.cat((total_labels, g), 0)

    return total_labels.numpy().flatten(),total_preds_ave.numpy().flatten()

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
          
    # Get argument parse
    args = get_args()

    if args.Model == 0:
        model_name = 'NanoBind_seq'
    elif args.Model == 1:
        model_name = 'NanoBind_pro'

    # Set log
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Output name
    add_name = '({})_SabdabData_finetune{}_TF{}'.format(args.ESM2,args.finetune,(args.pretrained is not None)+0)
    
    
    logfile = './output/log/log_' + model_name + add_name + '.txt'
    import os
    log_dir = os.path.dirname(logfile)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
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
    trainDataset = seqData_Sabdab('./data/Sabdab/NAI_train.csv')
    valDataset   = seqData_Sabdab('./data/Sabdab/NAI_val.csv')
    testDataset  = seqData_NBAT_Test(seq_path='./data/sdab/NAI_test_seq.fasta',
                                pair_path = './data/sdab/NAI_test.tsv')
    train_loader = DataLoader(trainDataset, batch_size=BATCH_SIZE, shuffle=True,pin_memory=True,drop_last=True)
    val_loader = DataLoader(valDataset, batch_size=BATCH_SIZE, shuffle=False,drop_last=True)
    test_loader = DataLoader(testDataset, batch_size=BATCH_SIZE, shuffle=False,drop_last=False)

    # Step 2: Set  model
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    # device = torch.device("cpu")

    if args.Model == 0:
        if args.ESM2 == 'esm2_t6_8M_UR50D':
            model = NanoBind_seq(pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320, finetune=args.finetune).to(device)
    elif args.Model == 1:
        if args.ESM2 == 'esm2_t6_8M_UR50D':
            model = NanoBind_pro(pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320, finetune=args.finetune,
                             Model_BSite_path='./output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model').to(device)

    # Load pretrained models
    if args.pretrained is not None:
        model_dir = './output/checkpoint/' 
        model_path = model_dir + args.pretrained
        weights = torch.load(model_path,map_location=torch.device('cpu')) # map_location=torch.device('cpu')

        model.load_state_dict(weights)

    # Step 3: Train the model
    # optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01) #0.001
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=LR, weight_decay=0.0001)

                                                    
    logging.info(f'''Starting training:
    Model_name:      {model_name}
    Epochs:          {NUM_EPOCHS}
    Batch size:      {BATCH_SIZE}
    Learning rate:   {LR}
    Training size:   {len(trainDataset)}
    Validating size: {len(valDataset)}
    Testing size:    {len(testDataset)}
    Finetune:        {args.finetune}
    Pretrained:      {args.pretrained}
    Device:          {device.type}
    ''')
    

    best_AUC_PR = -1
    best_epoch = 0
    model_file_name =  './output/checkpoint/' + model_name + add_name

    for epoch in range(NUM_EPOCHS):
        # Train
        train_loss = train(model, device, train_loader, optimizer, epoch, args.Model)

        # Val
        g,p = predicting(model, device, val_loader, args.Model)

        precision,recall,accuracy,F1_score,Top10,Top20,Top50,AUC_ROC,AUC_PR ,mcc= evaluate(g,p) #thres=0.5
        print(f"Epoch {epoch}: Train Loss = {train_loss:.4f}, "
          f"Accuracy={accuracy:.4f}, Recall={recall:.4f}, Precision={precision:.4f}, "
          f"F1 Score = {F1_score:.4f}, AUC_ROC = {AUC_ROC:.4f}, AUC_PR = {AUC_PR:.4f},MCC={mcc:.4f}")
        logging.info("Val: epoch {}: Top10 = {:.4f},Top20 = {:.4f},Top50 = {:.4f},accuracy={:.4f},Recall = {:.4f},Precision={:.4f},F1 score={:.4f},AUC_ROC={:.4f},AUC_PR={:.4f}".format(
            epoch,Top10,Top20,Top50,accuracy,recall,precision,F1_score,AUC_ROC,AUC_PR))

        # Save model
        if best_AUC_PR<AUC_PR:
            best_AUC_PR = AUC_PR
            best_epoch = epoch
            # Save model
            torch.save(model.state_dict(), model_file_name +'_good.model')
            print(f"best_model:{best_epoch},best_aupr:{best_AUC_PR:.4f}")
            
            # Test
            g,p = predicting(model, device, test_loader, args.Model)
            precision_test,recall_test,accuracy_test,F1_score_test,Top10_test,Top20_test,Top50_test,AUC_ROC_test,AUC_PR_test ,mcc= evaluate(g,p)
            
        logging.info("Best val epoch {} for ensemble with AUC_PR = {:.4f}".format(best_epoch,best_AUC_PR))
        logging.info("Test: Top10 = {:.4f},Top20 = {:.4f},Top50 = {:.4f},accuracy={:.4f},Recall = {:.4f},Precision={:.4f},F1 score={:.4f},AUC_ROC={:.4f},AUC_PR={:.4f}".format(
                Top10_test,Top20_test,Top50_test,accuracy_test,recall_test,precision_test,F1_score_test,AUC_ROC_test,AUC_PR_test))





            


            

        
