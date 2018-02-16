#!/bin/bash
cd ${database}

## install relevant packages
sudo apt-get install sqlite

# fetch UniProt taxon codes
wget http://www.uniprot.org/docs/speclist

dbname=$1

### if no set db name env variable, INTERACTIVE prompt asks for database name and password
while [ -z $dbname ] ; do
  read -p 'Set PostgreSQL database name: ' dbname ; echo ''
done

## create database and load database schema
sqlite3 $dbname < $dbscripts/pantagruel_sqlitedb_initiate.sql

## populate database
# use tail to truncate the header
tail -n +2 ${allcomplete}_metadata_curated.tab > genome_assemblies.tab
cut -f1,3,4,5,6 ${allcomplete}_allreplicons_info.tab | tail -n +2 > genome_replicons.tab
cut -f1,2,3,4,5,6,8 ${allcomplete}_allproteins_info.tab | tail -n +2 > genome_coding_sequences.tab
cut -f2,3 $protali/full_families_info-noORFans.tab > genome_gene_families.tab
cut -f1,7 ${allcomplete}_allproteins_info.tab | tail -n +2 | grep -vP "^\t" | sort -u > genome_protein_products.tab 

# populate database
python $dbscripts/pantagruel_sqlitedb_populate.py $dbname