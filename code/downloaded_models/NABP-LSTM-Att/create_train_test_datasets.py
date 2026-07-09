import pickle
from sklearn.model_selection import train_test_split
import random
from random import sample
random.seed(123)

with open('data/asPICKLE/clusters.pickle', 'rb') as binary_reader:
    clusters = pickle.load(binary_reader)

with open('data/asPICKLE/intra_group_binding.pickle', 'rb') as binary_reader:
    intra_group_binding = pickle.load(binary_reader)

with open('data/asPICKLE/inter_group_binding.pickle', 'rb') as binary_reader:
    inter_group_binding = pickle.load(binary_reader)

train_pos = []
test_pos = []
for cluster in clusters:
    train, test = train_test_split(
        cluster, test_size=0.2, random_state=123)  # 80% train , 20% test
    train_pos.append(train)
    test_pos.append(test)

train, test = train_test_split(
    intra_group_binding, test_size=0.2, random_state=123)  # 80% train , 20% test
train_pos.append(train)
test_pos.append(test)

total_pos = 0
for cls in clusters:
    total_pos = total_pos + len(cls)

total_pos = total_pos + len(intra_group_binding)

total_train_pos = 0
for T_P in train_pos:
    total_train_pos = total_train_pos + len(T_P)

total_test_pos = 0
for T_P in test_pos:
    total_test_pos = total_test_pos + len(T_P)

t_train_pos = total_pos * 0.8
t_test_pos = total_pos * 0.2

neg_data = []
for _ in range(total_pos):
    item = sample(inter_group_binding, 1)[0]
    item_ = (item[0], item[1], item[2], item[3], item[4], item[5], 0)
    neg_data.append(item_)

train_data_pos = []
test_data_pos = []
for l in train_pos:
    for item in l:
        item_ = (item[0], item[1], item[2], item[3], item[4], item[5], 1)
        train_data_pos.append(item_)

for l in test_pos:
    for item in l:
        item_ = (item[0], item[1], item[2], item[3], item[4], item[5], 1)
        test_data_pos.append(item_)

train_data_neg, test_data_neg = train_test_split(
    neg_data, test_size=0.2, random_state=123)  # 80% train , 20% test

train_data_pos, val_data_pos = train_test_split(
    train_data_pos, test_size=0.05, random_state=123)  # 95% train , 5% validation

train_data_neg, val_data_neg = train_test_split(
    train_data_neg, test_size=0.05, random_state=123)  # 95% train , 5% validation

with open('data/asPICKLE/train_data_pos.pickle', 'wb') as binary_writer:
    pickle.dump(train_data_pos, binary_writer)
with open('data/asPICKLE/val_data_pos.pickle', 'wb') as binary_writer:
    pickle.dump(val_data_pos, binary_writer)
with open('data/asPICKLE/test_data_pos.pickle', 'wb') as binary_writer:
    pickle.dump(test_data_pos, binary_writer)

with open('data/asPICKLE/train_data_neg.pickle', 'wb') as binary_writer:
    pickle.dump(train_data_neg, binary_writer)
with open('data/asPICKLE/val_data_neg.pickle', 'wb') as binary_writer:
    pickle.dump(val_data_neg, binary_writer)
with open('data/asPICKLE/test_data_neg.pickle', 'wb') as binary_writer:
    pickle.dump(test_data_neg, binary_writer)

print('size of pos data is ', total_pos)
print('size of train pos data is ', str(len(train_data_pos)))
print('size of val pos data is ', str(len(val_data_pos)))
print('size of test pos data is ', str(len(test_data_pos)))

print('size of neg data is ', str(len(neg_data)))
print('size of train neg data is ', str(len(train_data_neg)))
print('size of val neg data is ', str(len(val_data_neg)))
print('size of test neg data is ', str(len(test_data_neg)))


# combine the positive and negative samples and shuffle them  for each dataset (train, val, test)
train_data_all = []
val_data_all = []
test_data_all = []

for item in train_data_pos:
    train_data_all.append(item)
for item in train_data_neg:
    train_data_all.append(item)
random.shuffle(train_data_all)

for item in val_data_pos:
    val_data_all.append(item)
for item in val_data_neg:
    val_data_all.append(item)
random.shuffle(val_data_all)

for item in test_data_pos:
    test_data_all.append(item)
for item in test_data_neg:
    test_data_all.append(item)
random.shuffle(test_data_all)

with open('data/asPICKLE/train_data_all.pickle', 'wb') as binary_writer:
    pickle.dump(train_data_all, binary_writer)
with open('data/asPICKLE/val_data_all.pickle', 'wb') as binary_writer:
    pickle.dump(val_data_all, binary_writer)
with open('data/asPICKLE/test_data_all.pickle', 'wb') as binary_writer:
    pickle.dump(test_data_all, binary_writer)

print('size of train data is ', str(len(train_data_all)))
print('size of val data is ', str(len(val_data_all)))
print('size of test data is ', str(len(test_data_all)))

# separate the CDRs with it's number
train_CDR_antigen = []
val_CDR_antigen = []
test_CDR_antigen = []

for item in train_data_all:
    CDR_1 = (item[0], item[1], item[2], item[5], item[6], 1)
    CDR_2 = (item[0], item[1], item[3], item[5], item[6], 2)
    CDR_3 = (item[0], item[1], item[4], item[5], item[6], 3)
    train_CDR_antigen.append(CDR_1)
    train_CDR_antigen.append(CDR_2)
    train_CDR_antigen.append(CDR_3)
random.shuffle(train_CDR_antigen)

for item in val_data_all:
    CDR_1 = (item[0], item[1], item[2], item[5], item[6], 1)
    CDR_2 = (item[0], item[1], item[3], item[5], item[6], 2)
    CDR_3 = (item[0], item[1], item[4], item[5], item[6], 3)
    val_CDR_antigen.append(CDR_1)
    val_CDR_antigen.append(CDR_2)
    val_CDR_antigen.append(CDR_3)
random.shuffle(val_CDR_antigen)

for item in test_data_all:
    CDR_1 = (item[0], item[1], item[2], item[5], item[6], 1)
    CDR_2 = (item[0], item[1], item[3], item[5], item[6], 2)
    CDR_3 = (item[0], item[1], item[4], item[5], item[6], 3)
    test_CDR_antigen.append(CDR_1)
    test_CDR_antigen.append(CDR_2)
    test_CDR_antigen.append(CDR_3)
random.shuffle(test_CDR_antigen)

with open('data/asPICKLE/train_CDR_antigen.pickle', 'wb') as binary_writer:
    pickle.dump(train_CDR_antigen, binary_writer)
with open('data/asPICKLE/val_CDR_antigen.pickle', 'wb') as binary_writer:
    pickle.dump(val_CDR_antigen, binary_writer)
with open('data/asPICKLE/test_CDR_antigen.pickle', 'wb') as binary_writer:
    pickle.dump(test_CDR_antigen, binary_writer)

print('size of train_CDR_antigen data is ', str(len(train_CDR_antigen)))
print('size of val_CDR_antigen data is ', str(len(val_CDR_antigen)))
print('size of test_CDR_antigen data is ', str(len(test_CDR_antigen)))

print('done')
