import pickle

with open('data/asPICKLE/data_filter_nano_identiy98.pickle', 'rb') as binary_reader:
    data_filter_nano_identiy98 = pickle.load(binary_reader)

# store data_filter_nano_identiy98 as dic
data = dict()
for item in data_filter_nano_identiy98:
    data[item[0]] = item

clstr_file_path = 'data/asFASTA/antigen_seqs_after_nanobody_identiy98_90.fasta.clstr'


groups = []
cluster = []
counter = 0
with open(clstr_file_path, 'r') as file:
    lines = file.readlines()
    for line in lines:
        if line[0] == '>':
            if (len(cluster)>0):
                cls = cluster.copy()
                groups.append(cls)
                cluster.clear()
        else:
            temp = line.split('>')
            pdb = temp[1][0:4]
            cluster.append(pdb)

cls = cluster.copy()
groups.append(cls)
cluster.clear()

file.close()

intra_group_binding = []
inter_group_binding = []
# 1 -> id , 2-> VHH seq , 8 -> CDRH1, 9-> CDRH2, 10 -> CDRH3, 17 -> antigen seq
id = 0
for group in groups:
    if len(group) > 1:
        for i in range(0, len(group)-1):
            item_i = data[group[i]]
            for j in range(i+1, len(group)):
                item_j = data[group[j]]
                intra_group_binding.append(('intra_'+str(id), item_i[2], item_i[8], item_i[9], item_i[10], item_j[17]))
                id = id +1
                intra_group_binding.append(('intra_'+str(id), item_j[2], item_j[8], item_j[9], item_j[10], item_i[17]))
                id = id +1

# Save intra_group_binding as pickle file
with open('data/asPICKLE/intra_group_binding.pickle', 'wb') as binary_writer:
    pickle.dump(intra_group_binding, binary_writer)


id = 0
for i in range(0, len(groups)-1):
    group_i = groups[i]
    for j in range(i+1, len(groups)):
        group_j = groups[j]
        for id_i in group_i:
            item_i = data[id_i]
            for id_j in group_j:
                item_j = data[id_j]
                inter_group_binding.append(('inter_'+str(id), item_i[2], item_i[8], item_i[9], item_i[10], item_j[17]))
                id = id +1
                inter_group_binding.append(('inter_'+str(id), item_j[2], item_j[8], item_j[9], item_j[10], item_i[17]))
                id = id +1

# Save inter_group_binding as pickle file
with open('data/asPICKLE/inter_group_binding.pickle', 'wb') as binary_writer:
    pickle.dump(inter_group_binding, binary_writer)

print("size of intra_group_binding is ", len(intra_group_binding))
print("size of inter_group_binding is ", len(inter_group_binding))

print('done')