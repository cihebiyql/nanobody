import os
os.environ["CUDA_VISIBLE_DEVICES"]="3"
import pickle
from model import get_model
from sklearn.metrics import roc_auc_score,average_precision_score

cdr_kmer = 3
ag_kmer = 1

with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_te.pickle', 'rb') as binary_reader:
    cdr_features_te = pickle.load(binary_reader)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_te.pickle', 'rb') as binary_reader:
    ag_features_te = pickle.load(binary_reader)


# Test data
dtest_cdr_ids = []
dtest_cdr_number_ids = []
dtest_ag_ids = []
dtest_labels = []
dtest_labels_pos = 0
dtest_labels_neg = 0

for feature in cdr_features_te:
    dtest_cdr_ids.append(feature.input_ids)
    dtest_cdr_number_ids.append(feature.cdr_number_ids)
    dtest_labels.append(feature.label_id)
    dtest_labels_pos = dtest_labels_pos + feature.label_id
dtest_labels_neg = len(dtest_labels) - dtest_labels_pos

for feature in ag_features_te:
    dtest_ag_ids.append(feature.input_ids)


model=None
model=get_model()

directory_path = './model/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/'
model.load_weights(directory_path + "Model99.h5")


print("****************Testing the model ****************")

labels_pred = model.predict([dtest_cdr_ids, dtest_cdr_number_ids, dtest_ag_ids])
auc_test = roc_auc_score(dtest_labels, labels_pred)
aupr_test = average_precision_score(dtest_labels, labels_pred)

print("AUC_test : ", auc_test)
print("AUPR_test : ", aupr_test)