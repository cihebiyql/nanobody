import csv
import pickle
import os

if not os.path.exists('./data/asPICKLE'):
    os.makedirs('./data/asPICKLE')

if not os.path.exists('./data/asFASTA'):
    os.makedirs('./data/asFASTA')

data = []
data_filter = []
dir= './data/nano'
files=os.listdir(dir+"/")
steps = []

Hchain_sequence_len = []
CDRH1_len =[]
CDRH2_len =[]
CDRH3_len =[]

Antigen_sequence_1_len =[]

antigen_names = set()
antigen_seqs = set()
nanobody_seqs = set()
for file in files:
    print("file:" + dir + "/" + file + "\n")
    step = int(file.split('.')[0])
    steps.append(step)
    csv_file_path = dir + "/" + file
    counter = -1
    with open(csv_file_path, 'r') as f:
        # Create a CSV reader
        csv_reader = csv.reader(f)
        # Loop over each row in the CSV file
        for row in csv_reader:
            if (counter > -1 and counter % step == 0):
                data.append((row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10],
                             row[11], row[12], row[13], row[14], row[15], row[16], row[17], row[18], row[19], row[20],
                             row[21], row[22], row[23], row[24], row[25], row[26], row[27], row[28]))
                resolution = row[27]
                antigen_type = row[14]

                if (float(resolution) >= 3.0):
                    if (antigen_type == 'protein' or antigen_type == 'peptide'):
                        data_filter.append((row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
                                            row[10], row[11], row[12], row[13], row[14], row[15], row[16], row[17], row[18],
                                            row[19], row[20], row[21], row[22], row[23], row[24], row[25], row[26], row[27],
                                            row[28]))

            counter = counter + 1
    f.close()


# each antibody binds exclusively to a single antigen, with the reverse also being applicable.
data_filter_copy = data_filter.copy()
removed_items = set()
for i in range(0,len(data_filter)-1):
    item1 = data_filter[i]
    for j in range(i+1, len(data_filter)):
        item2 = data_filter[j]
        if (str(item1[2]) == str(item2[2]) or str(item1[17]) == str(item2[17])):
            removed_items.add(item1)
            break
for r_item in removed_items:
    data_filter.remove(r_item)
removed_items.clear()

with open('data/asPICKLE/data_filter.pickle', 'wb') as binary_writer:
    pickle.dump(data_filter, binary_writer)

for row in data_filter:
    Hchain_sequence_len.append(len(row[2]))
    CDRH1_len.append(len(row[8]))
    CDRH2_len.append(len(row[9]))
    CDRH3_len.append(len(row[10]))
    Antigen_sequence_1_len.append(len(row[17]))

    nanobody_seqs.add(row[2])
    antigen_seqs.add(row[17])

print(str(len(data)))
print(str(len(data_filter_copy)))
print(str(len(data_filter)))
print("Hchain_sequence_max_len : ",str(max(Hchain_sequence_len)), '\n')
print("CDRH1_len_max : ",str(max(CDRH1_len)), '\n')
print("CDRH2_len_max : ",str(max(CDRH2_len)), '\n')
print("CDRH3_len_max : ",str(max(CDRH3_len)), '\n')
print("Antigen_sequence_1_max_len : ",str(max(Antigen_sequence_1_len)), '\n')

print("Hchain_sequence_min_len : ",str(min(Hchain_sequence_len)), '\n')
print("CDRH1_len_min : ",str(min(CDRH1_len)), '\n')
print("CDRH2_len_min : ",str(min(CDRH2_len)), '\n')
print("CDRH3_len_min : ",str(min(CDRH3_len)), '\n')
print("Antigen_sequence_1_min_len : ",str(min(Antigen_sequence_1_len)), '\n')


# write the nanobody sequences as a FASTA file:
nanobody_seqs = open("data/asFASTA/nanobody_seqs.fasta", "w")
for item in data_filter:
    nanobody_seqs.write(">" + item[0] + " \n")
    nanobody_seqs.write(item[2] + " \n")

print("done")
