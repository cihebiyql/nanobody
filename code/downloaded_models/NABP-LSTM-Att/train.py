import os
os.environ["CUDA_VISIBLE_DEVICES"]="4"
import pickle
from model import get_model
from keras.callbacks import Callback
from datetime import datetime
from sklearn.metrics import roc_auc_score,average_precision_score

cdr_kmer = 3
ag_kmer = 1
epochs=100
batch_size=64
directory_path = './model/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/'


def create_directory_if_not_exists(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"Directory '{directory_path}' created.")
    else:
        print(f"Directory '{directory_path}' already exists.")

class roc_callback(Callback):
    def __init__(self, val_data):
        self.cdr_ids = val_data[0]
        self.cdr_number_ids = val_data[1]
        self.ag_ids = val_data[2]
        self.labels = val_data[3]

    def on_train_begin(self, logs={}):
        return

    def on_train_end(self, logs={}):
        return

    def on_epoch_begin(self, epoch, logs={}):
        return

    def on_epoch_end(self, epoch, logs={}):
        labels_pred = self.model.predict([self.cdr_ids, self.cdr_number_ids, self.ag_ids])
        auc_val = roc_auc_score(self.labels, labels_pred)
        aupr_val = average_precision_score(self.labels, labels_pred)

        create_directory_if_not_exists(directory_path)
        self.model.save_weights(directory_path + "Model%d.h5" % (epoch))

        print('\r auc_val: %s ' %str(round(auc_val, 4)), end=100 * ' ' + '\n')
        print('\r aupr_val: %s ' % str(round(aupr_val, 4)), end=100 * ' ' + '\n')
        return

    def on_batch_begin(self, batch, logs={}):
        return

    def on_batch_end(self, batch, logs={}):
        return

t1 = datetime.now().strftime('%Y-%m-%d-%H:%M:%S')


with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_tr.pickle', 'rb') as binary_reader:
    cdr_features_tr = pickle.load(binary_reader)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_tr.pickle', 'rb') as binary_reader:
    ag_features_tr = pickle.load(binary_reader)

with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_val.pickle', 'rb') as binary_reader:
    cdr_features_val = pickle.load(binary_reader)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_val.pickle', 'rb') as binary_reader:
    ag_features_val = pickle.load(binary_reader)

# Training data
dtrain_cdr_ids = []
dtrain_cdr_number_ids = []
dtrain_ag_ids = []
dtrain_labels = []
dtrain_labels_pos = 0
dtrain_labels_neg = 0

for feature in cdr_features_tr:
    dtrain_cdr_ids.append(feature.input_ids)
    dtrain_cdr_number_ids.append(feature.cdr_number_ids)
    dtrain_labels.append(feature.label_id)
    dtrain_labels_pos = dtrain_labels_pos + feature.label_id
dtrain_labels_neg = len(dtrain_labels) - dtrain_labels_pos

for feature in ag_features_tr:
    dtrain_ag_ids.append(feature.input_ids)

########################################################
# validation data
dval_cdr_ids = []
dval_cdr_number_ids = []
dval_ag_ids = []
dval_labels = []
dval_labels_pos = 0
dval_labels_neg = 0

for feature in cdr_features_val:
    dval_cdr_ids.append(feature.input_ids)
    dval_cdr_number_ids.append(feature.cdr_number_ids)
    dval_labels.append(feature.label_id)
    dval_labels_pos = dval_labels_pos + feature.label_id
dval_labels_neg = len(dval_labels) - dval_labels_pos

for feature in ag_features_val:
    dval_ag_ids.append(feature.input_ids)

#################################
# get the model
model=None
model=get_model()
model.summary()

print ('Training the model')

back = roc_callback(val_data=[dval_cdr_ids, dval_cdr_number_ids, dval_ag_ids, dval_labels])

history=model.fit([dtrain_cdr_ids, dtrain_cdr_number_ids, dtrain_ag_ids], dtrain_labels,
                  validation_data=([dval_cdr_ids, dval_cdr_number_ids, dval_ag_ids], dval_labels),
                  epochs=epochs,
                  batch_size=batch_size,
                  callbacks=[back])

t2 = datetime.now().strftime('%Y-%m-%d-%H:%M:%S')
print("开始时间:"+t1+"结束时间："+t2)
