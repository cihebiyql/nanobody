import pickle
from features import CDR_Ag_Processor
import tokenization
from features import convert_examples_to_features
import os
import random

def get_Feature(tsv_file_path, kmer, max_seq_length):
    vocab_file = "vocab/vocab_" + str(kmer) + "kmer.txt"
    processor = CDR_Ag_Processor()
    label_list = processor.get_labels()
    cdr_number_list = ["1", "2", "3"]
    tokenizer = tokenization.FullTokenizer(vocab_file=vocab_file, do_lower_case=True)

    examples = processor.get_examples(tsv_file_path)

    features = convert_examples_to_features(examples, label_list, cdr_number_list, max_seq_length, tokenizer)

    return features


# the max len of the CDRs is 24, so when k = 1 the max tokens is 24
# the max len of the AGs is 2373 , so when k = 3 the max tokens is (2373 - (3-1)) = 2371
cdr_kmer = 3
ag_kmer = 3
if not os.path.exists('./data/features'):
    os.makedirs('./data/features')

tsv_path = "data/asTSV/cdr_kmer" + str(cdr_kmer) + "_ag_kmer" + str(ag_kmer) + "/"
ag_max_seq_length = 2371
cdr_max_seq_length = 24
cdr_tsv_file_name = "CDR_te.tsv"
ag_tsv_file_name = "Ag_te.tsv"
cdr_tsv_file_path = tsv_path + cdr_tsv_file_name
ag_tsv_file_path = tsv_path + ag_tsv_file_name
cdr_features = get_Feature(cdr_tsv_file_path, cdr_kmer, cdr_max_seq_length)
ag_features = get_Feature(ag_tsv_file_path, ag_kmer, ag_max_seq_length)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_te.pickle', 'wb') as binary_writer:
    pickle.dump(cdr_features, binary_writer)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_te.pickle', 'wb') as binary_writer:
    pickle.dump(ag_features, binary_writer)

##################################################

cdr_tsv_file_name = "CDR_tr.tsv"
ag_tsv_file_name = "Ag_tr.tsv"
cdr_tsv_file_path = tsv_path + cdr_tsv_file_name
ag_tsv_file_path = tsv_path + ag_tsv_file_name
cdr_features = get_Feature(cdr_tsv_file_path, cdr_kmer, cdr_max_seq_length)
ag_features = get_Feature(ag_tsv_file_path, ag_kmer, ag_max_seq_length)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_tr.pickle', 'wb') as binary_writer:
    pickle.dump(cdr_features, binary_writer)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_tr.pickle', 'wb') as binary_writer:
    pickle.dump(ag_features, binary_writer)
##################################################

cdr_tsv_file_name = "CDR_val.tsv"
ag_tsv_file_name = "Ag_val.tsv"
cdr_tsv_file_path = tsv_path + cdr_tsv_file_name
ag_tsv_file_path = tsv_path + ag_tsv_file_name
cdr_features = get_Feature(cdr_tsv_file_path, cdr_kmer, cdr_max_seq_length)
ag_features = get_Feature(ag_tsv_file_path, ag_kmer, ag_max_seq_length)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/cdr_features_val.pickle', 'wb') as binary_writer:
    pickle.dump(cdr_features, binary_writer)
with open('data/features/cdr_kmer' + str(cdr_kmer) + '_ag_kmer' + str(ag_kmer) + '/ag_features_val.pickle', 'wb') as binary_writer:
    pickle.dump(ag_features, binary_writer)

print("done")