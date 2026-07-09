import pickle

with open('data/asPICKLE/data_filter.pickle', 'rb') as binary_reader:
    data_filter = pickle.load(binary_reader)

# extract the complexes with antibody identity 98% from data_filter
# 1. read the nanobody_seqs_98.fasta to get the PDB id of the complexes
fasta_file_path = 'data/asFASTA/nanobody_seqs_98.fasta'
PDB = ''
PDBs = []

with open(fasta_file_path, 'r') as file:
    lines = file.readlines()
    for line in lines:
        if line[0] == '>':
            PDB = line[1:]
            PDB = PDB.strip()
            PDBs.append(PDB)
file.close()

data_filter_nano_identiy98 = []
for item in data_filter:
    if item[0] in PDBs:
        data_filter_nano_identiy98.append(item)

# Save data_filter_nano_identiy98 as pickle file
with open('data/asPICKLE/data_filter_nano_identiy98.pickle', 'wb') as binary_writer:
    pickle.dump(data_filter_nano_identiy98, binary_writer)

# write the antigen sequences as FASTA file
antigen_seqs_fasta = open("data/asFASTA/antigen_seqs_after_nanobody_identiy98.fasta", "w")

for item in data_filter_nano_identiy98:
    antigen_seqs_fasta.write(">" + item[0] + " \n")
    antigen_seqs_fasta.write(item[17] + " \n")


