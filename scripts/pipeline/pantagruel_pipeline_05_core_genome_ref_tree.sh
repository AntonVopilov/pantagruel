#!/bin/bash

#########################################################
## PANTAGRUEL:                                         ##
##             a pipeline for                          ##
##             phylogenetic reconciliation             ##
##             of a bacterial pangenome                ##
#########################################################

# Copyright: Florent Lassalle (f.lassalle@imperial.ac.uk), 30 July 2018

if [ -z "$2" ] ; then echo "missing mandatory parameters." ; echo "Usage: $0 ptg_db_name ptg_root_folder" ; exit 1 ; fi
export ptgdbname="$1"  # database anme (will notably be the name of the top folder)
export ptgroot="$2"    # source folder where to create the database
export ptgdb=${ptgroot}/${ptgdbname}
envsourcescript=${ptgdb}/environ_pantagruel_${ptgdbname}.sh
source ${envsourcescript}

export resumetask="$3"

if [ "${resumetask}" == "true" ] ; then
  echo "will try and resume computation where it was last stopped; may skip/resume computing: core genome concatenated alignment, core ML tree search, core tree bootstrapping, core tree rooting with ${rootingmethod}"
fi

# to set misc variables ; not safe though
if [ -e ${ptgtmp}/nondefvardecl.sh ] ; then
  source ${ptgtmp}/nondefvardecl.sh
fi

case "${coreseqtype}" in
  prot)
      alifastacodedir=${protalifastacodedir}
      raxmloptions="-n ${treename} -m PROTCATLGX -j -p 1753 -w ${coretree}"
      if [ "${poplgthresh}" == 'default' ] ; then
        poplgthresh=0.0002
      fi
      if [ "${popbsthresh}" == 'default' ] ; then
        popbsthresh=80
      fi
      popstemconds="[('lg', '>=', ${poplgthresh}), ('bs', '>=', ${popbsthresh})]"
      withinpopconds="[('max', 'lg', '<=', ${poplgthresh}, -1)]"
      ;;
  cds)
      alifastacodedir=${cdsalifastacodedir}
      raxmloptions="-n ${treename} -m GTRCATX -j -p 1753 -w ${coretree}"
      if [ "${poplgthresh}" == 'default' ] ; then
        poplgthresh=0.0005
      fi
      if [ "${popbsthresh}" == 'default' ] ; then
        popbsthresh=80
      fi
      popstemconds="[('lg', '>=', ${poplgthresh}), ('bs', '>=', ${popbsthresh})]"
      withinpopconds="[('max', 'lg', '<=', ${poplgthresh}, -1)]"
      ;;
  *)
      echo "ERROR: incorrect core sequence type was specified: ${coreseqtype} (must be 'prot' or 'cds'); exit now"
      exit 1 ;;
esac

###########################################
## 05. Core Genome Phylogeny (Species tree)
###########################################

## select psedo-core genome marker gene set
export coregenome=${ptgdb}/05.core_genome
mkdir -p ${coregenome}/

if [[ ! -z "${userreftree}" ]] ; then
  # use user-provided tree as reference tree
  if [[ ! -e "${userreftree}" ]] ; then
    echo "Error: cannot open user-provided tree '$userreftree' ; exit now."
    exit 1
  else
    # test if it is a valid Newick tree file
    R --vanilla --slave << EOF
    library('ape')
    nftree = '${userreftree}'
    tree = read.tree(nftree)
    if (is.null(tree)){
      cat(sprintf("cannot read '%s' as a Newick tree file\n", nftree))
      quit(status=3)
    }else{
      goodtipset = TRUE
      # test that tip labels are all correct
      nfgencode = '${database}/genome_codes.tab'
      genome.codes = as.character(read.table(nfgencode, sep='\t', header=F)[,2])
      if (length(genome.codes)!=length(tree[['tip.label']])){
        goodtipset = FALSE
        cat("wrong number of tips compared to genome code set\n")
      }
      extratips = setdiff(tree[['tip.label']], genome.codes)
      missdtips = setdiff(genome.codes, tree[['tip.label']])
      if (length(extratips)>0){
        goodtipset = FALSE
        cat("tips not in genome code set:\n")
        print(extratips, quote=F)
      }
      if (length(missdtips)>0){
        goodtipset = FALSE
        cat("tips missing with respect to genome code set:\n")
        print(missdtips, quote=F)
      }
      if (!goodtipset){
        cat(sprintf("incorrect tree tip set (according to '%s')\n", nfgencode))
        quit(status=3)
      }
      if (!is.null(tree[['node.label']])){
        if (is.rooted(tree)){
          quit(status=6) 
        }else{
          quit(status=5) 
      }}else{
        quit(status=4)
      }
    }
EOF
    treecheck=$?
    # evaluate output from tree check
    case ${treecheck} in
     3)
       echo "ERROR: ${userreftree} is not a valid tree file; exit now" 1>&2
       exit 1 ;;
     4)
       echo "'$userreftree' is a correct tree file but has no branch support"
       echo "will use its topology for reference tree; skip RAxML ML tree computation but will compute rapid bootstraps from (pseudo-)core-genome concatenate alignment"
       echo "emulate resuming RAxML computation pipeline after ML tree search (not that tree will be re-rooted according to set criterion: '$rootingmethod')"
       ln -s ${userreftree} ${nrbesttree}
       resumetask='true' ;;
     5)
       echo "'$userreftree' is a correct tree file, with branch supports but not rooted"
       echo "will use its topology and branch supports for reference tree; skip RAxML ML tree and bootsrap computations but will perform rooting according to set criterion: '$rootingmethod'"
       echo "emulate resuming RAxML computation pipeline after rapid bootstrap tree search"
       ln -s ${userreftree} ${nrbesttree}
       ln -s ${userreftree} ${nrbiparts}
       resumetask='true' ;;
     6)
      echo "'$userreftree' is a correct rooted tree file with branch supports"
      echo "will use it as a reference tree; skip all RAxML computations from (pseudo-)core-genome concatenate alignment" 
      mv ${envsourcescript} ${envsourcescript}0 && \
       sed -e "s#'REPLACEuserreftree'#${userreftree}#" ${envsourcescript}0 > ${envsourcescript} && \
       rm ${envsourcescript}0
      echo "userreftree=${userreftree} is recorded in init file '${envsourcescript}'"
       ln -s ${userreftree} ${speciestree} ;;
     *)
      echo "something went wrong when evaluatiing input tree (tree check output value: ${treecheck}); exit now"
      exit 1 ;;
    esac
  fi
fi

if  [[ ! -s ${speciestree} ]] ; then
  ### compute reference tree from (pseudo-)core genome
  
  ## generate core genome alignment path list
  if [[ "${resumetask}" == "true" && -s ${pseudocorealn} ]] ; then
   echo "skip concatenating core genome alignment"
  else
   rm -f ${coregenome}/pseudo-coregenome_sets/${pseudocore}_${coreseqtype}_aln_list
   for fam in `cat ${coregenome}/pseudo-coregenome_sets/${pseudocore}_families.tab` ; do
    ls ${alifastacodedir}/$fam.codes.aln >> ${coregenome}/pseudo-coregenome_sets/${pseudocore}_${coreseqtype}_aln_list
   done
   # concatenate pseudo-core prot/CDS alignments
   python ${ptgscripts}/concat.py ${coregenome}/pseudo-coregenome_sets/${pseudocore}_${coreseqtype}_aln_list ${pseudocorealn}
   rm ${alifastacodedir}/*_all_sp_new
  fi

  ## compute species tree using RAxML
  mkdir -p ${ptglogs}/raxml ${coretree}/
  # define RAxML binary and options; uses options -T (threads) -j (checkpoints) 
  if [ ! -z $(grep -o avx2 /proc/cpuinfo | head -n 1) ] ; then
    raxmlflav='-AVX2 -U'
  elif [ ! -z $(grep -o avx /proc/cpuinfo | head -n 1) ] ; then
    raxmlflav='-AVX -U'
  elif [ ! -z $(grep -o sse3 /proc/cpuinfo | head -n 1) ] ; then
    raxmlflav='-SSE3 -U'
  else
    raxmlflav=''
  fi
  raxmlbin="raxmlHPC-PTHREADS${raxmlflav} -T $(nproc)"

  # first check the alignment for duplicate sequences and write a reduced alignment with  will be excluded
  if [[ "${resumetask}" == "true" && -e ${pseudocorealn}.identical_sequences ]] ; then
   echo "skip identical sequence removal in core alignment"
  else
   $raxmlbin -s ${pseudocorealn} ${raxmloptions} -f c &> ${ptglogs}/raxml/${treename}.check.
   grep 'exactly identical$' ${coretree}/RAxML_info.${treename} | sed -e 's/IMPORTANT WARNING: Sequences \(.\+\) and \(.\+\) are exactly identical/\1\t\2/g' > ${pseudocorealn}.identical_sequences
   mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_identical_sequences.${treename}
   if [[ ! -z "${userreftree}" ]] ; then 
     # work on the full alignment as the user-provided tree is expected to bear all leaves
     coretreealn=${pseudocorealn}
   else
     coretreealn=${pseudocorealn}.reduced
   fi
  fi

  # compute bestTree (ML tree) on reduced alignment
  if [[ "${resumetask}" == "true" && -s ${nrbesttree} ]] ; then
   # ML tree search already done
   echo "skip ML tree search"
  else
   ckps=($(ls -t ${coretree}/RAxML_checkpoint.${treename}.*))
   if [[ "${resumetask}" == "true" && -z "${ckps}" ]] ; then
    # resume search from checkpoint
    echo "resume from checkpoint ${ckps[0]##*.}"
    mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_bestTree.${treename}.up_to_ckp${ckps[0]##*.}
    mv ${ptglogs}/raxml/${treename}.ML_run.log ${ptglogs}/raxml/${treename}.ML_run.log.up_to_ckp${ckps[0]##*.}
    $raxmlbin -s ${coretreealn} ${raxmloptions} -t ${ckps[0]} &> ${ptglogs}/raxml/${treename}.ML_run.log
   else
    # initial search
    $raxmlbin -s ${coretreealn} ${raxmloptions} &> ${ptglogs}/raxml/${treename}.ML_run.log
   fi
   mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_bestTree.${treename}
   rm -f ${nrbesttree}
   ln -s ${coretree}/RAxML_bestTree.${treename} ${nrbesttree}
  fi

  # compute ${ncorebootstrap} rapid bootstraps (you can set variable by editing ${envsourcescript})
  if [[ "${resumetask}" == "true" && -s ${nrbiparts} ]] ; then
   # tree with branch supports already provided bootstrap tree search already done
   echo "skip bootstraping and mapping to ML tree"
  else
   if [[ "${resumetask}" == "true" && -s ${coretree}/RAxML_bootstrap.${treename} ]] ; then
    nbs=$(wc -l ${coretree}/RAxML_bootstrap.${treename} | cut -d' ' -f1)
    if [ ${nbs} -ge ${ncorebootstrap} ] ; then
     # bootstrap tree search already done
     echo "skip bootstrapping"
    else
     # resume bootstrap tree search from previous run
     export ncorebootstrap=$(( ${ncorebootstrap} - ${nbs} ))
     echo "resume bootstraping after ${nbs} trees (${ncorebootstrap} left to compute)"
     mv ${coretree}/RAxML_bootstrap.${treename} ${coretree}/RAxML_bootstrap.${treename}.firstbs${nbs}
     mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_bootstrap.${treename}.up_to_bs${nbs}
     mv ${ptglogs}/raxml/${treename}_bs.log ${ptglogs}/raxml/${treename}_bs.log.up_to_bs${nbs}
     $raxmlbin -s ${coretreealn} ${raxmloptions} -x 198237 -N ${ncorebootstrap} &> ${ptglogs}/raxml/${treename}_bs.log
    fi
   else
    # bootstrapping tree search from scratch
    $raxmlbin -s ${coretreealn} ${raxmloptions} -x 198237 -N ${ncorebootstrap} &> ${ptglogs}/raxml/${treename}_bs.log
   fi
   # mapping bootstraps to ML tree
   mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_bootstrap.${treename}
   $raxmlbin -s ${coretreealn} ${raxmloptions} -f b -z ${coretree}/RAxML_bootstrap.${treename} -t ${nrbesttree} 
   mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_bipartitions.${treename}
   rm -f ${nrbiparts}
   #~ ln -s ${coretree}/RAxML_bipartitionsBranchLabels.${treename} ${nrbiparts}
   ln -s ${coretree}/RAxML_bipartitions.${treename} ${nrbiparts}
  fi

  # root ML tree
  if [[ "${resumetask}" == "true" && -s ${nrrootedtree} ]] ; then
   echo "skip tree rooting with '${rootingmethod}' method"
  else
   # variables automoatically defined in ${envsourcescript} :
   #~ export nrbesttree=${coretree}/RAxML_bestTree.${treename}
   #~ export nrbiparts=${nrbesttree/bestTree/bipartitions}
   #~ export nrrootedtree=${nrbiparts}.${rootingmethod/:/-}rooted
   if [[ "${rootingmethod}" == 'treebalance' ]] ; then
    # root ML tree with RAxML tree-balance algorithm
    nrbipartbranchlab=$(readlink -f $nrbiparts | sed -e 's/bipartitions/bipartitionsBranchLabels/')
    if [ ! -s ${nrbipartbranchlab} ] ; then
      echo "Error: could not detect tree file with brach support annotated on the branches ; exit now"
      exit 1
    fi
    $raxmlbin -s ${coretreealn} ${raxmloptions} -f I -t ${nrbipartbranchlab}  
    mv ${coretree}/RAxML_info.${treename} ${coretree}/RAxML_info_rootedTree.${treename}
    rm -f ${nrrootedtree}
    ln -s ${coretree}/RAxML_rootedTree.${treename} ${nrrootedtree}
   else
    if [[ "${rootingmethod}" == 'MAD' ]] ; then
     # root tree with MAD (Tria et al. Nat Ecol Evol (2017) Phylogenetic rooting using minimal ancestor deviation. s41559-017-0193 doi:10.1038/s41559-017-0193)
     R BATCH --vanilla --slave << EOF
     source('${ptgscripts}/mad_R/MAD.R')
     mad.rooting = MAD(readLines('${nrbiparts}'), 'full')
     write(mad.rooting[[1]], file='${nrbiparts}.${rootingmethod}rooted')
     save(mad.rooting, file='${nrbiparts}.${rootingmethod}rooting.RData}')
EOF
    rm -f ${nrrootedtree}
    ln -s ${nrbiparts}.${rootingmethod}rooting ${nrrootedtree}
    else
     if [[ "${rootingmethod:0:8}" == 'outgroup' ]] ; then
    # outgroup rooting; assume argument was of the shape 'outgroup:SPECIESCODE'
    # verify the presence of outgroup species in tree
    outgroup=$(echo ${rootingmethod} | cut -d':' -f2)
    if [ -z $(grep ${outgroup} ${nrbesttree}) ] ; then
      echo "Error, outgroup species '$outgroup' is absent from tree '${nrbesttree}'"
      exit 1
    fi
    roottag=${rootingmethod/:/-}rooted
    R --vanilla --slave << EOF
    library('ape')
    tree = read.tree('${nrbiparts}')
    rtree = root(tree, outgroup='${outgroup}', resolve.root=T)
    write.tree(rtree, file='${nrbiparts}.${roottag}')
EOF
    rm -f ${nrrootedtree}
    ln -s ${nrbiparts}.${roottag} ${nrrootedtree}
     fi
    fi
   fi
  fi

  # from here no skipping in resume mode
  if [ "${coretreealn}" == "${pseudocorealn}.reduced" ] ; then
    # reintroduce excluded species name into the tree
    python ${ptgscripts}/putidentseqbackintree.py --input.nr.tree=${nrbiparts} --ref.rooted.nr.tree=${nrrootedtree} \
     --list.identical.seq=${pseudocorealn}.identical_sequences --output.tree=${speciestree}
  else
    # only process tree format 
    python ${ptgscripts}/putidentseqbackintree.py --input.nr.tree=${nrbiparts} --ref.rooted.nr.tree=${nrrootedtree} \
     --output.tree=${speciestree}
  fi
fi

### make version of full reference tree with actual organism names
python ${ptgscripts}/code2orgnames_in_tree.py ${speciestree} $database/organism_codes.tab ${speciestree}.names

### generate ultrametric 'dated' species tree for more meaningfulgptghical representation of reconciliation AND to use the dated (original) version of ALE
## use LSD (v 0.3 beta; To et al. Syst. Biol. 2015) to generate an ultrametric tree from the rooted ML tree (only assumin different, uncorrelated clocks for each branch)
alnlen=$(head -n1 ${pseudocorealn}.reduced | cut -d' ' -f2 )
lsd -i ${speciestree} -c -v 1 -s $alnlen -o ${speciestree}.lsd

### delineate populations of near-identical strains (based on tree with branch lengths in subs/site) and generate the population tree, i.e. the species tree withs population collapsed
python ${ptgscripts}/replace_species_by_pop_in_gene_trees.py -S ${speciestree} --threads=8 \
--pop_stem_conds="${popstemconds}" --within_pop_conds="${withinpopconds}"
nspepop=$(tail -n+3 ${speciestree%.*}_populations | wc -l)
echo "Found $nspepop disctinct populations in the species tree"


### extract sister clade pairs from the reference species tree for later clade-specific gene search
python << EOF
import tree2, sys
sys.setrecursionlimit(20000)
reftree = tree2.Node(file='${speciestree}')
nfout = "${speciestree}_clade_defs"
fout = open(nfout, 'w')
fout.write('\t'.join(['', 'clade', 'sisterclade'])+'\n')
k = 0
for node in reftree:
  if len(node.children) != 2: continue
  for child in node.children:
    if child.nb_leaves() <= 1: continue
    focchildlab = child.label()
    if not focchildlab:
      focchildlab = "clade%d"%k
      k += 1
    focchildleaflabset = ','.join(sorted(child.get_leaf_labels()))
    sischildleaflabset = ','.join(sorted(child.go_brother().get_leaf_labels()))
    fout.write('\t'.join([focchildlab, focchildleaflabset, sischildleaflabset])+'\n')

fout.close()
EOF
