## Introduction
NanoBind is a unified framework for comprehensive prediction of nanobody-antigen molecular recognition, specifically comprising five sub-models. Among them, NanoBind-seq and NanoBind-pro predict whether binding occurs, NanoBind-site predicts antigen-interface residues, NanoBind-pair predicts the relative affinity strength between two nanobody-antigen complexes, and NanoBind-affi assesses the affinity range of a nanobody-antigen complex.

Now we will detail the specific usage of NanoBind.

## File Preview
Before getting started, please ensure you have all the following files:

1. **`data`**: This folder contains all the datasets used for binding prediction, antigen-interface residue prediction, and affinity assessment, and they have been split into training, validation, and test sets.
2. **`models`**: This folder includes **`NanoBind_seq.py`**, **`NanoBind_site.py`**, **`NanoBind_pro.py`**, **`NanoBind_pair.py`**, and **`NanoBind_affi.py`**, which correspond to the binding prediction model, the interface prediction model, the enhanced binding prediction model, the affinity comparison model, and the affinity range prediction model, respectively. Additionally, it provides the ESM2 encoder (the **`esm2_t6_8M_UR50D`** folder, esm2_t6_8M_UR50D version; users can replace it with other parameter versions as needed).
3. **`output`**: 
4. **`utils`**: This folder contains **`dataloader.py`** for loading data and **`evaluate.py`** for evaluating model prediction results.
5. **'NanoBind_env.yaml'**: It includes the required environment dependencies for running NanoBind.
6. **'predict_seq.py'**: Performing rapid binding prediction using the NanoBind-seq model.
7. **'predict_affi.py'**: Performing rapid binding affinity range prediction using the NanoBind-affi model.
8. **'predict_pair.py'**: Rapid prediction of relative affinity strength using the NanoBind-pair model.
9. **'predict_pro.py'**: Performing rapid binding prediction using the NanoBind-pro model.
10. **'predict_site.py'**: Performing rapid antigen-interface residues prediction using the NanoBind-site model.
11. **'test_seq.py'**: For reproducing the binding prediction results using NanoBind-seq as presented in the NanoBind paper.
12. **'test_site.py'**: For reproducing the antigen-interface residues prediction results using NanoBind-site as presented in the NanoBind paper.
13. **'test_pro.py'**: For reproducing the binding prediction results using NanoBind-pro as presented in the NanoBind paper.
14. **'test_pair'**: For reproducing the relative affinity strength prediction results using NanoBind-pair as presented in the NanoBind paper.
15. **'test_case.py'**: For reproducing the binding affinity range prediction results using NanoBind-affi as presented in the NanoBind paper.
16. **'train_nai.py'**: For training the NanoBind-seq and NanoBind-pro models.
17. **'train_site.py'**: For training the NanoBind-site model.
18. **'train_pair.py'**: For training the NanoBind-pair model.

## Getting Started

This section details the usage and operation of the NanoBind framework.

### Installation

To set up the environment, follow these steps:

1. **Clone the repository**；
   ```bash
   git clone https://github.com/zhaosq17/NanoBind.git
   cd NanoBind
   ```
2. **Install Git LFS and pull large model files** (some model files are stored with Git LFS due to size >100 MB):
   ```bash
   # Install Git LFS if not already installed
   # On Ubuntu: sudo apt install git-lfs
   # On macOS: brew install git-lfs
   # On Windows: download from https://git-lfs.com/
   git lfs install
   git lfs pull
    ```
4. **Create a new virtual environment** (optional but recommended):

   ```bash
   conda env create -f NanoBind_env.yml
   ```
3. **Activate the environment**:

    ```bash
    conda activate NanoBind
    ```
### Reproducing the results from the NanoBind paper

Simple run each line of code below in sequence to obtain the results presented in the paper: binding predictions, antigen-interface residue predictions, relative affinity strength predictions:

```bash
python test_seq.py
python test_site.py
python test_pro.py
python test_pair.py
```

### Using the NanoBind tool for nanoody-antigen molecular recognition prediction

```bash
python predict_seq.py --nb .\data\example\nb1.fasta --ag .\data\example\ag1.fasta
python predict_site.py --nb .\data\example\nb1.fasta --ag .\data\example\ag1.fasta
python predict_pro.py --nb .\data\example\nb1.fasta --ag .\data\example\ag1.fasta
python predict_pair.py --nb1 .\data\example\nb1.fasta --ag1 .\data\example\ag1.fasta --nb2 .\data\example\nb2.fasta --ag2 .\data\example\ag2.fasta
python predict_affi.py --nb .\data\example\nb1.fasta --ag .\data\example\ag1.fasta
```

### Applying the NanoBind framework for custom training

```bash
python train_nai.py --Model 0 --finetune 1 --ESM2  esm2_t6_8M_UR50D
python train_nai.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D
python train_site.py --Model 0 --finetune 1 --ESM2  esm2_t6_8M_UR50D
python train_pair.py
```


