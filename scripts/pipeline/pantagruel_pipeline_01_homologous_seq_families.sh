#!/bin/bash

#########################################################
## PANTAGRUEL:                                         ##
##             a pipeline for                          ##
##             phylogenetic reconciliation             ##
##             of a bacterial pangenome                ##
#########################################################

# Copyright: Florent Lassalle (f.lassalle@imperial.ac.uk), 30 July 2018

if [ -z "$1" ] ; then echo "missing mandatory parameter: pantagruel config file" ; echo "Usage: $0 ptg_env_file" ; exit 1 ; fi
envsourcescript="$1"
source ${envsourcescript}

checkptgversion
checkfoldersafe ${seqdb}

#############################
## 01. Homologous Sequence db
#############################

## extract all the protein sequences into single proteome fasta files

rm -f ${allfaarad}*
for ass in `ls ${assemblies}` ; do
 faa=$(ls ${assemblies}/${ass}/* | grep "protein.faa")
 zcat ${faa} >> ${allfaarad}.faa && echo $faa >> ${allfaarad}_list
done
promptdate "-- $(wc -l ${allfaarad}_list | cut -d' ' -f1) proteomes in dataset"
promptdate "-- $(grep -c '>' ${allfaarad}.faa) proteins in dataset"

# dereplicate proteins in db based on their identifier
python2.7 ${ptgscripts}/dereplicate_fasta.py ${allfaarad}.faa ${allfaarad}.nrprotids.faa
promptdate "-- $(grep -c '>' ${allfaarad}.nrprotids.faa) non-redundant protein ids in dataset"

mmseqslogs=${ptglogs}/mmseqs && mkdir -p ${mmseqslogs}/
## clustering of identical protein sequences
# notably those from the custom assemblies to those from the public database (and those redudant between RefSeq and Genbank sets)
# run mmseqs clusthash with 100% seq id threshold
# used MMseqs2 Version: 6306925fa9ae6198116c26e605277132deff70d0
echo "${datepad}-- Perform first protein clustering step (100% prot identity clustering with clusthash algorithm)"
mmlog0=${mmseqslogs}/mmseqs-0-identicalprot-clusthash.log
mmseqs createdb ${allfaarad}.nrprotids.faa ${allfaarad}.mmseqsdb &> ${mmlog0}
mmseqs clusthash --min-seq-id 1.0 ${allfaarad}.mmseqsdb ${allfaarad}.clusthashdb_minseqid100 &>> ${mmlog0}
mmseqs clust ${allfaarad}.mmseqsdb ${allfaarad}.clusthashdb_minseqid100 ${allfaarad}.clusthashdb_minseqid100_clust &>> ${mmlog0}
mmsummary0=$(tail -n 4 ${mmlog0} | head -n 3)
mmseqs createseqfiledb ${allfaarad}.mmseqsdb ${allfaarad}.clusthashdb_minseqid100_clust ${allfaarad}.clusthashdb_minseqid100_clusters &>> ${mmlog0}
checkexec "First protein clustering step failed; please inestigate error reports in '${mmlog0}'" "${datepad}-- First protein clustering step complete: ${mmsummary0}"

# get table of redundant protein names
python2.7 ${ptgscripts}/split_mmseqs_clustdb_fasta.py ${allfaarad}.clusthashdb_minseqid100_clusters "NRPROT" ${allfaarad}.clusthashdb_minseqid100_families 6 0 0
grep -v NRPROT000000 ${allfaarad}.clusthashdb_minseqid100_families.tab > ${allfaarad}.identicals.tab
python2.7 ${ptgscripts}/genefam_table_as_list.py ${allfaarad}.identicals.tab ${allfaarad}.identicals.list 0
python2.7 ${ptgscripts}/remove_identical_seqs.py ${allfaarad}.nrprotids.faa ${allfaarad}.identicals.list ${allfaarad}.nr.faa

## collect data from assemblies, including matching of (nr) protein to CDS sequence ids
python2.7 ${ptgscripts}/allgenome_gff2db.py --assemb_list ${genomeinfo}/assemblies_list --dirout ${genomeinfo}/assembly_info \
 --ncbi_taxonomy ${ncbitax} --identical_prots ${allfaarad}.identicals.list

## check consistency of non-redundant protein sets
mkdir -p $ptgtmp
protidfield=$(head -n 1 ${genomeinfo}/assembly_info/allproteins_info.tab |  tr '\t' '\n' | grep -n 'nr_protein_id' | cut -d':' -f1)
if [ -z $protidfield ] ; then 
 protidfield=$(head -n 1 ${genomeinfo}/assembly_info/allproteins_info.tab |  tr '\t' '\n' | grep -n 'protein_id' | cut -d':' -f1)
fi
cut -f $protidfield ${genomeinfo}/assembly_info/allproteins_info.tab | grep -v "^$\|protein_id" | sort -u > ${genomeinfo}/assembly_info/allproteins_in_gff
grep '>' ${allfaarad}.nr.faa | cut -d' ' -f1 | cut -d'>' -f2 | sort -u > ${allfaarad}.nr_protlist
# compare original dataset of nr protein (as described in the input GFF files) to the aligned nr proteome
diff ${genomeinfo}/assembly_info/allproteins_in_gff ${allfaarad}.nr_protlist > $ptgtmp/diff_prot_info_fasta
if [ -s $ptgtmp/diff_prot_info_fasta ] ; then 
  >&2 promptdate
  >&2 echo "ERROR: inconsistent propagation of the protein dataset:"
  >&2 echo "present in aligned fasta proteome / absent in info table generated from input GFF:"
  >&2 grep '>' $ptgtmp/diff_prot_info_fasta | cut -d' ' -f2
  >&2 echo "present in info table generated from input GFF / absent in aligned fasta proteome:"
  >&2 grep '<' $ptgtmp/diff_prot_info_fasta | cut -d' ' -f2
  exit 1
fi

## clustering of proteome db with  MMSeqs2 
# (https://github.com/soedinglab/MMseqs2,  Steinegger M and Soeding J. Sensitive protein sequence searching for the analysis of massive data sets. bioRxiv, doi: 10.1101/079681 (2016))
# compute the memory use of MMSeq2: M = (7 × N × L + 8 × a^k) bytes, N the number of sequences, L their average size, a the size of the alphabet
## clustering of nr proteome 
# run mmseqs cluster with default parameters
# used MMseqs2 Version: e5d64b2701789e7eef8fcec0812ccb910c8dfef3
# compute the memory use of MMSeq2: M = (7 × N × L + 8 × a^k) bytes, N the number of sequences, L their average size, a the size of the alphabet
# create MMseqs2 db
mmlog1=${mmseqslogs}/mmseqs-1-cluster.log
mmseqstmp=${ptgtmp}/mmseqs && rm -rf ${mmseqstmp} && mkdir -p ${mmseqstmp}
mmseqs createdb ${allfaarad}.nr.faa ${allfaarad}.nr.mmseqsdb &> ${mmlog1}
# perform clustering
mkdir -p ${families}
echo "${datepad}-- Perform second protein clustering step (to find homologs with cluster algorithm)"
mmseqsclout=${families}/$(basename ${allfaarad}.nr).mmseqs_clusterdb_default
# perform similarity search and clustering ; uses all CPU cores by default
mmseqs cluster ${allfaarad}.nr.mmseqsdb $mmseqsclout $mmseqstmp &>> ${mmlog1}
mmsummary=$(tail -n 4 ${mmlog1} | head -n 3)
# generate indexed fasta file listing all protein families
mmseqs createseqfiledb ${allfaarad}.nr.mmseqsdb $mmseqsclout ${mmseqsclout}_clusters &>> ${mmlog1}
checkexec "Second protein clustering step failed; please inestigate error reports in '${mmlog1}'" "${datepad}-- Second protein clustering step complete: ${mmsummary1}"
# generate separate fasta files with family identifiers distinc from representative sequence name
python2.7 ${ptgscripts}/split_mmseqs_clustdb_fasta.py ${mmseqsclout}_clusters "${famprefix}P" ${mmseqsclout}_clusters_fasta 6 1 0
checkexec "Fialed to split mmseqs cluster '${mmseqsclout}_clusters'" "${datepad}-- Successfully split mmseqs cluster '${mmseqsclout}_clusters'"
promptdate "-- $(wc -l ${mmseqsclout}_clusters_fasta.tab | cut -d' ' -f1) non-redundant proteins"
promptdate "-- classified into $(ls ${mmseqsclout}_clusters_fasta/ | wc -l) clusters"
echo "${datepad}-- including artificial cluster ${famprefix}P000000 gathering $(grep -c '>' ${mmseqsclout}_clusters_fasta/${famprefix}P000000.fasta) ORFan nr proteins"
echo "${datepad}-- (NB: some are not true ORFans as can be be present as identical sequences in several genomes)"

rm -rf ${mmseqstmp}