# *Pantagruel*: a bioinformatic pipeline for the inference of gene evolution scenarios in bacterial pangenomes.

## Aim and description
*Pantagruel* provides an all-in-one software solution to reconstruct the complex evolutionary process of diversification of bacterial genomes.  

From a dataset of bacterial genomes, builds a database that describes the homology structure of all genes in the dataset -- the pangenome. With that, *Pantagruel* will first generate two key outputs:  
- a **reference (species) tree**, depicting the main signal of evolutionary relationships between input *genomes*;  
- **gene trees**, depicting the evolutionary relationships between gene sequences within a family of homologous genes.   

![pipeline1]

A **scenario of gene evolution** is inferred for each gene family in the dataset by reconciling the topology of gene trees with the reference species tree in a probabilistic framework.  

Such scenario describes the likely events of gene **duplication, horizontal transfer and loss** (DTL model) that marked the gene family history. These events are annotated on the branch of the gene tree and the of the reference tree, and make their history consistent.
From these annotations, one can derive the history of gain and loss of this gene over the reference tree of species, and follow the diversification of *gene lineages* within and across *genome lineages*.  

Gene tree/species tree reconciliation methods rely on the best available information to infer such scenarios, as they account for the phylogeny of genes; a probablilistic method is chosen to quantify the statistical support for inferences, in face of the large space of possible scenario and of the uncertainty in the input gene phylogeny.  
While probablilistic reconciliation methods are computationally costly, this pipeline uses innovative phylogenetic apporoaches based on the reduction of gene trees to their informative backbone that allow their use in a resonable time on **datasets of 1,000+ bacterial genome** and covering **multiple species**.

![pipeline2]


These historical data are then gathered in the database, which provides a way to:  
- quantify gene-to-gene association on the basis of their *co-evolution* signal at the gene lineage level;  
- classify genes into *orthologous clusters* based on the gain/loss scenarios, from which one can define *clade-specific gene sets*.  

Two version of the pipeline are distributed:  

- a script version, which source code is adaptable and can be deployed on high-performance computing (HPC) "cluster" Linux systems;  

- (in development) a pre-compiled Docker image that can be deployed on pretty much any platform, including swarms of virtual machines (VMs). The latter version was implemented using Philippe Veber's [Bistro](https://github.com/pveber/bistro) framework.

See below for instruction on software [installation](https://github.com/flass/pantagruel#installing-pantagruel-and-its-dependencies) and [usage](https://github.com/flass/pantagruel#using-pantagruel).

--------------------

## Using Pantagruel

The pipeline can be run using a single interface to deploy the several arms of the pipeline.  
It first requires to initiate the *Pantagruel* database, i.e. giving it a name, creating the base file structure, defining main options.
The generic syntax is as follows:  
```sh
pantagruel -d db_name -r root_dir [options] init [init_file]
```  
the `init_file` can be generated by editing **a copy** of the [template environment script](https://github.com/flass/pantagruel/blob/master/scripts/pipeline/environ_pantagruel_template.sh). Note than it is only safe to edit the top parameters.

Then, the pipeline can be run step-by-step by performing each task in the following list **in order**:
```sh
pantagruel -d db_name -r root_dir [options] TASK
```
with `TASK` to be picked among the following (equivalent digit/number/keywords are separated by a `|`):
```
  0|00|fetch|fetch_data
       fetch public genome data from NCBI sequence databases and annotate private genomes
  1|01|homologous|homologous_seq_families
       classify protein sequences into homologous families
  2|02|align|align_homologous_seq
       align homologous protein sequences and translate alignemnts into coding sequences
  3|03|sqldb|create_sqlite_db
       initiate SQL database and load genomic object relationships
  4|04|functional|functional_annotations
       use InterProScan to functionally annotate proteins in the database, including with Gene Ontology and metabolic pathway terms
  5|05|core|core_genome_ref_tree
       select core-genome markers and compute reference tree
  6|06|genetrees|gene_trees
       compute gene tree
  7|07|reconciliations
       compute species tree/gene tree reconciliations
  8|08|specific|clade_specific_genes
       classify genes into orthologous groups (OGs) and search clade-specific OGs
  9|09|coevolution
       quantify gene co-evolution and build gene association network

```  

Options are detailed here:  
```
    -d|--dbname       database name
    -r|--rootdir      root directory where to create the database; defaults to current folder
    -p|--ptgrepo      location of pantagruel software head folder; defaults to directory where this script is located
    -i|--iam          database creator identity (e-mail address is preferred)
    -f|--famprefix    alphanumerical prefix (no number first) of the names for homologous protein/gene family clusters; defaults to 'PANTAG'
                       the chosen prefix will be appended with a 'P' for protein families and a 'C' for CDS families.
    -T|--taxonomy      path to folder of taxonomy database flat files; defaults to $rootdir/NCBI/Taxonomy
                       if this is not containing the expected file, triggers downloading the daily dump from NCBI Taxonomy at task 00
    -A|--refseq_ass  path to folder of source genome assembly flat files formated like NCBI Assembly RefSeq whole directories;
                       these can be obtained by searching https://www.ncbi.nlm.nih.gov/assembly and downloadingresults with options:
                         Source Database = 'RefSeq' and File type = 'All file types (including assembly-structure directory)'.
                       defaults to $rootdir/NCBI/Assembly
    -a|--custom_ass  path to folder of user-provided genome containing:
                      _mandatory_ 
                       - a 'contigs/' folder where are stored all source genome assembly FASTA files
                           OR
                       - a 'prokka_annotation//' folder where are stored all files resulting from Prokka annotation
                      _optionally_ 
                       - a 'strain_infos.txt' file
                       (unnanotated contig fasta files); defaults to $rootdir/user_genomes
    -s|--pseudocore  integer number, the minimum number of genomes in which a gene family should be present
                       to be included in the pseudo-core genome gene set (otherwise has to be set interactively before running task 'core')
    -h|--help          print this help message and exit.
```  
Here are some examples of using options:  
```sh
pantagruel -d databasename -r /root/folder/for/database -f PANTAGFAM -i f.lassalle@imperial.ac.uk -A /folder/of/public/genome/in/RefSeq/format init

pantagruel -d databasename -r /root/folder/for/database 01
```  

Alternatively, several tasks ca be run at once yb providing a strin of tasks identifiers:  
```sh
pantagruel -d db_name -r root_dir TASK1 TASK2 ...
```
Finally, it is possible to run the whole pipeline at once, simply perform the `all` task:
```sh
pantagruel -d db_name -r root_dir all
```  
Note that in the later two cases, no task-specific options can be specified trough the command line; instead, you should edit the database's environment file (produced during initiation step) that should be located at `${root_dir}/${db_name}/environ_pantagruel_${db_name}.sh`, with `${db_name}` and `${root_dir}` the arguments of `-d` and `-r` options on the `pantagruel init` call.

-------------

## Installing Pantagruel and its dependencies

Under a Debian environment (e.g. Ubuntu), please follow the indications in the [INSTALL](https://github.com/flass/pantagruel/blob/master/INSTALL.md) page.  

Below is a summary of the software on which Pantagruel dependends:

### Required bioinformatic software
- **MMseqs2/Linclust** for homologous sequence clustering  
  (Install from [source code](https://github.com/soedinglab/MMseqs2); last tested version https://github.com/soedinglab/MMseqs2/commit/c92411b91175a2362554849b8889a5770a1ae537)

- **Clustal Omega** for homologous sequence alignment  
  (Install from [source code](http://www.clustal.org/omega/) or *clustalo* debian package; version used and recommended: 1.2.1)  
  - \[ future development: consider using [FAMSA](http://sun.aei.polsl.pl/REFRESH/famsa) \]

- **PAL2NAL** for reverse tanslation of protein sequence alignments into CDS alignments  
  ([Perl source code](http://www.bork.embl.de/pal2nal/))

- **RAxML** for species tree and initial (full) gene tree estimation  
  (Install from [source code](https://github.com/stamatak/standard-RAxML) or *raxml* debian package; version used and recommended: 8.2.9)  
  - \[ future development: consider using RAxML-NG (Install from [source code](https://github.com/amkozlov/raxml-ng)) \]

- **MrBayes** for secondary estimation of (collapsed) gene trees  
  (Install from [source code](http://mrbayes.sourceforge.net/) or *mrbayes* and *mrbayes-mpi* debian packages; version used and recommended: 3.2.6)  
  - \[ future development: consider using [RevBayes](http://revbayes.github.io/) \]

- **MAD** for species tree rooting  
  ([R source code](https://www.mikrobio.uni-kiel.de/de/ag-dagan/ressourcen/mad-r-tar.gz))

- **ALE/xODT** for gene tree / species tree reconciliation  
  (Install from [source code](https://github.com/ssolo/ALE); version used and recommended: 0.4; notably depends on [Bio++ libs](https://github.com/BioPP) (v2.2.0))
  
### Required code libraries
- **R** (version 3, >=3.2.3 recommended) + packages:
  - ape
  - phytools
  - vegan
  - ade4
  - igraph
  - getopt
  - parallel
  - DBI, RSQLite
  - topGO (optional)
  - pvclust (optional)
  
- **Python** (version 2.7, >=2.7.13 recommended) + packages:
  - [sqlite3](https://docs.python.org/2/library/sqlite3.html) (standard package in Python 2.7)
  - [scipy/numpy](https://www.scipy.org/scipylib/download.html)
  - [tree2](https://github.com/flass/tree2)
  - [BioPython](http://biopython.org/wiki/Download)
  - [Cython](https://pypi.org/project/Cython/)
  - [igraph](http://igraph.org/python/) (available as a Debian package)

### Other required software
- [sqlite3](https://www.sqlite.org) (available as a Debian package *sqlite3*)
- [LFTP](https://lftp.yar.ru/get.html) (available as a Debian package *lftp*)
- [(linux)brew](http://linuxbrew.sh/) (available as a Debian package *linuxbrew-wrapper*)
- [docker](https://www.docker.com/) (available as a Debian package *docker.io*)


-------------

![repas]


[repas]: https://github.com/flass/pantagruel/blob/master/pics/Pantagruels_childhood.jpg
[pipeline1]: https://github.com/flass/pantagruel/blob/master/pics/extract_cluster_concat_spetree_MLgenetrees.png
[pipeline2]: https://github.com/flass/pantagruel/blob/master/pics/collapse_samplebackbones_reconcile_compare.png
