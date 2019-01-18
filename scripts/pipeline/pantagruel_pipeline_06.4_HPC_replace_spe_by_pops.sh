#!/bin/bash

#########################################################
## PANTAGRUEL:                                         ##
##             a pipeline for                          ##
##             phylogenetic reconciliation             ##
##             of a bacterial pangenome                ##
#########################################################

# Copyright: Florent Lassalle (f.lassalle@imperial.ac.uk), 15 Jan 2019

if [ -z "$2" ] ; then echo "missing mandatory parameters." ; echo "Usage: $0 ptg_db_name ptg_root_folder" ; exit 1 ; fi
export ptgdbname="$1"  # database anme (will notably be the name of the top folder)
export ptgroot="$2"    # source folder where to create the database
export ptgdb=${ptgroot}/${ptgdbname}

envsourcescript=${ptgdb}/environ_pantagruel_${ptgdbname}.sh
source ${envsourcescript}


################################################################################
## 06.4 Convert format of Bayesian gene trees and replace species by populations
################################################################################

if [[ "${chaintype}" == 'fullgenetree' ]] ; then
  #### OPTION A2: 
  export coltreechains=${genetrees}/${chaintype}_tree_chains
  echo "Error: not implemented yet:"
  echo "must generalize the script replace_species_by_pop_in_gene_trees.py so to only convert the format of gene tree chains, not replacing anything in them"
  # PBS-submitted parallel job
  #~ qsub -N replSpePopinGs -l select=1:ncpus=${ncpus}:mem=64gb,walltime=24:00:00 -o $repllogd -j oe -V << EOF
  #~ module load python
  #~ python ${ptgscripts}/replace_species_by_pop_in_gene_trees.py -G ${tasklist} -o ${coltreechains} --threads=${ncpus} --reuse=0 --verbose=0 --logfile=${repllogs}_${replrun}.log &
  #~ EOF
  exit 1
  
  #### end OPTION A2: 
else
  #### OPTION B2: collapsed rake clades in gene trees need to be replaced by mock population leaves
  #### will edit collapsed gene trees to attribute an (ancestral) species identity to the leafs representing collapsed clades = pre-reconciliation of recent gene history
  if [-z ${replacecolid} ] ; then
   replacecolid=1
  fi
  export coltreechains=${genetrees}/${chaintype}_tree_chains
  export colmethod='replaceCCinGasinS-collapsePOPinSnotinG'
  mkdir -p ${coltreechains}/${collapsecond}

  ## edit the gene trees, producing the corresponding (potentially collapsed) species tree based on the 'time'-tree backbone
  mkdir -p ${ptgdb}/logs/replspebypop
  tasklist=${coltreechains}_${collapsecond}_nexus_list
  ls $bayesgenetrees/${collapsecond}/*run1.t > $tasklist
  repllogd=${ptgdb}/logs/replspebypop
  repllogs=$repllogd/replace_species_by_pop_in_gene_trees
  replrun=$(date +'%d%m%Y')

  # PBS-submitted parallel job
  qsub -N replSpePopinGs -l select=1:ncpus=${ncpus}:mem=64gb,walltime=24:00:00 -o $repllogd -j oe -V << EOF
  module load python
  python ${ptgscripts}/replace_species_by_pop_in_gene_trees.py -G ${tasklist} -c ${colalinexuscodedir}/${collapsecond} -S ${speciestree}.lsd.newick -o ${coltreechains}/${collapsecond} \
   --populations=${speciestree%.*}_populations --population_tree=${speciestree%.*}_collapsedPopulations.nwk --population_node_distance=${speciestree%.*}_interNodeDistPopulations \
   --dir_full_gene_trees=${mlgenetrees}/rootedTree --method=${colmethod} --threads=${ncpus} --reuse=0 --max.recursion.limit=12000 --logfile=${repllogs}_${replrun}.log
EOF

  export replacecoldate=$(date +%Y-%m-%d)

  ## load these information into the database
  ${ptgscripts}/pantagruel_sqlitedb_phylogeny_populate_collapsed_clades.sh ${database} ${sqldb} ${colalinexuscodedir} ${coltreechains} ${collapsecond} ${colmethod} ${collapsecriteriondef} ${collapsecolid} ${replacecolid} ${collapsecoldate} ${replacecoldate}

fi
#### end OPTION B2