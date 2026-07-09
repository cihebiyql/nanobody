# NABP-LSTM-Att (Nanobody-Antigen Binding Prediction using bidirectional LSTM and soft attention mechanism)
In vertebrates, antibody-mediated immunity is a vital component of the immune system, and antibodies have become a rapidly expanding class of therapeutic agents. Nanobodies, a distinct type of antibody, have recently emerged as a stable and cost-effective alternative to traditional antibodies. Their small size, high target specificity, notable solubility, and stability make nanobodies promising candidates for developing high-quality drugs. However, the lack of available nanobodies for most antigens remains a key challenge. Advancing the development of nanobodies requires a better understanding of their interactions with antigens to enhance binding affinity and specificity. Experimental methods for identifying these interactions are essential but often costly and time-consuming, posing challenges for developing nanobody therapies. Although several computational approaches have been designed to screen potential nanobodies, their dependency on 3D structures limits their broad application.
This research introduces NABP-LSTM-Att, a deep learning model designed to predict nanobody-antigen binding solely from sequence information. NABP-LSTM-Att leverages bidirectional long short-term memory (biLSTM) to capture both long- and short-term dependencies within nanobody and antigen sequences, combined with a soft attention mechanism to focus on key features. When evaluated on nanobody-antigen sequence pairs from the SAbDab-nano database, NABP-LSTM-Att achieved an AUROC of 0.926 and an AUPR of 0.952. Considering the significance of nanobody-based treatments and their prospective uses in immunotherapy and diagnostics, we believe that the proposed model will serve as an effective tool for predicting nanobody-antigen binding.

# File Description 

- Get and pre-processing the data

    If you prefer not to obtain and preprocess the data from beginning, you may utilize the final pre-processed data (which was utilized for the model's training and testing) from the following link: https://drive.google.com/drive/folders/1P8Ps9gRh_IAuAof-EfYLOeOh4LdsuaVU?usp=sharing/.

   Nevertheless, if you wish to acquire and preprocess the data independently, execute the subsequent source code files in the specified order and follow the instructions below:         

    1) getDataFromSAbDab-nano.py: This file includes the code for retrieving nanobody-antigen pairs from the SAbDab-nano database.
    2) read_CSVs.py: This file contains the code for preprocessing the raw data of SAbDab-nano, which was obtained from the previous code. This code generates a pickle file for the data after applying the rules and a fasta file containing the nanobody sequences, named "nanobody_seqs.fasta".
    3) Install cd-hit as detailed in the guide available at "http://www.bioinformatics.org/cd-hit/cd-hit-user-guide."
    4) Execute the cd-hit command: "cd-hit -i nanobody_seqs.fasta -o nanobody_seqs_98.fasta -c 0.98 -n 5" to eliminate redundancy in nanobody sequences, applying a sequence identity threshold of 0.98. The input file is "nanobody_seqs.fasta," and the output file is "nanobody_seqs_98.fasta."
    5) prepareAntigenSeqs.py: This file contains the code for preparing the antigen sequences following the removal of redundancy in the nanobody sequences. This code generates a FASTA file containing the antigen sequences named "antigen_seqs_after_nanobody_identity98.fasta".
    6) Execute the cd-hit command: "cd-hit -i antigen_seqs_after_nanobody_identiy98.fasta -o antigen_seqs_after_nanobody_identiy98_90.fasta -c 0.90 -n 5" to classify the pre-processed complexes into subgroups based on antigen sequences, applying a sequence identity threshold of 0.90. The input file is "antigen_seqs_after_nanobody_identiy98.fasta," while the output file is "antigen_seqs_after_nanobody_identiy98_90.fasta." Additionally, there is another output file named "antigen_seqs_after_nanobody_identiy98_90.fasta.clstr," which contains the sub-groups of the antigen sequences.
    7) create_intra_inter_group_binding.py: This file contains the code for establishing intra- and inter-group binding data.
    8) Utilize Clustal Omega at "https://www.ebi.ac.uk/jdispatcher/msa/clustalo" to construct the phylogenetic tree of the antigen sequences. Input the file "antigen_seqs_after_nanobody_identiy98.fasta" into the Clustal Omega website. Following the generation of the phylogenetic tree, the complexes are organized into five clusters, which are saved in the "clusters.csv" file.    
    9) phylogenetic_tree_clusters.py: This file includes the code for storing the clusters of the phylogenetic tree in a pickle file.
    10) create_train_test_datasets.py:  This file contains the code for generating the training dataset, which comprises 80% of the data, and the testing dataset, which constitutes 20% of the data, as explained in the paper "data section".
    11) createTSV.py: This script generates TSV files for the CDRs and antigen sequences, requiring specification of the k-mer for their representation.
    12) embedding.py: This script is designed to embed the CDRs and antigen sequences into feature vectors.
            
- model.py

  It contains the implementation of our proposed NABP-LSTM-Att model


- train.py

  Perform model training.

- test.py

  Evaluate the performance of the model.
  
You can find the weights of the models on google Drive: https://drive.google.com/drive/folders/1P8Ps9gRh_IAuAof-EfYLOeOh4LdsuaVU?usp=sharing

