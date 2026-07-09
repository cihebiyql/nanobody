import pickle
import random
import os
random.seed(123)

CDR_kmer = 3
Ag_kmer = 3

def sequence2tokens(seq, kmer):
    tokens = []
    for i in range(len(seq) - (kmer-1)):
        tokens.append(seq[i:i + kmer])
    return tokens

def CDR_Ag_create_tsv(CDR_Ag_pairs, mode, CDR_kmer, Ag_kmer, CDR_TSV, Ag_TSV):

    f1 = open(CDR_TSV, "w")
    f2 = open(Ag_TSV, "w")

    for pair in CDR_Ag_pairs:
        ID = pair[0]
        CDR_seq = pair[2]
        Ag_seq = pair[3]
        label = pair[4]
        CDR_number = pair[5]

        label_str = str(label)
        CDR_number_str = str(CDR_number)
        CDR = str(CDR_seq).lower()
        CDR_tokens = ""
        tokens = sequence2tokens(CDR, CDR_kmer)
        for token in tokens:
            CDR_tokens = CDR_tokens + token + " "
        res = mode + "\t" + ID + "\t" + label_str + "\t" + CDR_tokens + "\t" + CDR_number_str
        f1.write(res + "\n")

        Ag = str(Ag_seq).lower()
        Ag_tokens = ""
        tokens = sequence2tokens(Ag, Ag_kmer)
        for token in tokens:
            Ag_tokens = Ag_tokens + token + " "
        res = mode + "\t" + ID + "\t" + label_str + "\t" + Ag_tokens + "\t" + CDR_number_str
        f2.write(res + "\n")

def CDR_Ag_createTrainValTestTSV():
    with open('data/asPICKLE/train_CDR_antigen.pickle', 'rb') as binary_reader:
        train_CDR_antigen = pickle.load(binary_reader)

    with open('data/asPICKLE/val_CDR_antigen.pickle', 'rb') as binary_reader:
        val_CDR_antigen = pickle.load(binary_reader)

    with open('data/asPICKLE/test_CDR_antigen.pickle', 'rb') as binary_reader:
        test_CDR_antigen = pickle.load(binary_reader)

    # create tsv files for the train dataset
    CDR_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/CDR_tr.tsv"
    Ag_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/Ag_tr.tsv"
    CDR_Ag_create_tsv(train_CDR_antigen, "train", CDR_kmer, Ag_kmer, CDR_TSV, Ag_TSV)

    # create tsv files for the val dataset
    CDR_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/CDR_val.tsv"
    Ag_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/Ag_val.tsv"
    CDR_Ag_create_tsv(val_CDR_antigen, "val", CDR_kmer, Ag_kmer, CDR_TSV, Ag_TSV)

    # create tsv files for the test dataset
    CDR_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/CDR_te.tsv"
    Ag_TSV = "data/asTSV/cdr_kmer" + str(CDR_kmer) + "_ag_kmer" + str(Ag_kmer) + "/Ag_te.tsv"
    CDR_Ag_create_tsv(test_CDR_antigen, "test", CDR_kmer, Ag_kmer, CDR_TSV, Ag_TSV)

if not os.path.exists('./data/asTSV'):
    os.makedirs('./data/asTSV')

CDR_Ag_createTrainValTestTSV()
print("hello")