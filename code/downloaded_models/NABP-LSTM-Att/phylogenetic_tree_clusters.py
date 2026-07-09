import pickle

with open('data/asPICKLE/data_filter_nano_identiy98.pickle', 'rb') as binary_reader:
    data_filter_nano_identiy98 = pickle.load(binary_reader)

# store data_filter_nano_identiy98 as dic
data = dict()
for item in data_filter_nano_identiy98:
    data[item[0]] = item

phylogenetic_tree_clusters_file_path = 'data/clusters.csv'


cluster = []
clusters = []
counter = 0
with open(phylogenetic_tree_clusters_file_path, 'r') as file:
    lines = file.readlines()
    for line in lines:
        line = line.strip()
        complexes = line.split(',')
        for com in complexes:
            if len(com)>0 and (not com.isnumeric()):
                item = data[com.strip()]
                cluster.append((item[0], item[2], item[8], item[9], item[10], item[17]))

        cls = cluster.copy()
        clusters.append(cls)
        cluster.clear()

total_count = 0
for cls in clusters:
    total_count = total_count + len(cls)

print('total_count is', total_count)

with open('data/asPICKLE/clusters.pickle', 'wb') as binary_writer:
    pickle.dump(clusters, binary_writer)

print('done')
