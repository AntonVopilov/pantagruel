#!/usr/bin/python

import sys, getopt
import os
import gzip
import re

daliasrepli = {'ANONYMOUS':'chromosome'}

dfoutheaders = { \
'proteins':['protein_id', 'genomic_accession', 'gene_begin', 'gene_end', 'gene_strand', 'gene_product', 'genbank_cds_id'], \
'ribosomes':['rrna_id', 'genomic_accession', 'gene_begin', 'gene_end', 'gene_strand', 'gene_product'], \
'replicons':['assembly_accession', 'assembly_name', 'genomic_accession', 'replicon_name', 'replicon_type', 'size', 'tax_id', 'strain'] \
}

fouttags = ['proteins', 'ribosomes', 'replicons']
annottype2fouttag = {'CDS':'proteins', 'rRNA':'ribosomes', 'tRNA':'ribosomes', 'tmRNA':'ribosomes',}

assembpatgenbank = re.compile('(GC[AF]_[^\._]+\.[0-9])_(.+)')
assembpat = re.compile('(.+?\.[0-9])_(.+)')

def parseCDSFasta(nfcds):
	dgenbankcdsids = {}
	with gzip.open(nfcds, 'rb') as fcds:
		# register unambiguously the exact naming of the CDS sequence in the corresponding extracted CDS sequence file
		for line in fcds:
			if line.startswith('>'):
				genbankcdsid, cdstags = line.strip('>\n').split(' ', 1)
				dcdstags = dict(cdstag.split('=', 1) for cdstag in cdstags.strip('[]').split('] ['))
				dgenbankcdsids[(dcdstags['locus_tag'], dcdstags.get('protein_id', ''))] = genbankcdsid
	return dgenbankcdsids

def parseGFFline(line):
	#~ print line
	lsp = line.rstrip('\n').split('\t')
	seqreg = lsp[0]
	annottype = lsp[2]
	beg = lsp[3]
	end = lsp[4]
	strand = lsp[6]
	desc = dict(d.split('=', 1) for d in lsp[8].split(';'))
	return (seqreg, annottype, beg, end, strand, desc)

def indexRegionsAndGenes(fgff, dfout, assacc, assname, dtaxid2sciname={}, dmergedtaxid={}):
	currseqreg = ''
	#~ dgenedesc = {}
	dgeneloctag = {}
	dgenenchild = {}
	for line in fgff:
		if line.startswith('#'): continue
		elif line.startswith('>'): break
		#~ print line
		seqreg, annottype, beg, end, strand, desc = parseGFFline(line)
		if annottype=='region':
			if seqreg!=currseqreg and beg=='1':
				# new replicon
				currseqreg = seqreg.split('|')[-1]	# to account for Prokka-style annotation that prepends 'gnl|Sequencing_Centre' to the region_id
				dbxref = dict(d.split(':') for d in desc['Dbxref'].split(','))
				taxid = dbxref['taxon']
				strain = desc.get('strain', '')
				repliname = desc.get('Name', '')
				replitype = desc.get('genome', '')
				replineout = [assacc, assname, seqreg, daliasrepli.get(repliname, repliname), replitype, end, taxid, strain]
				tid = int(taxid)
				if dtaxid2sciname: replineout.append(dtaxid2sciname[dmergedtaxid.get(tid, tid)])
				dfout['replicons'].write('\t'.join(replineout)+'\n')
		elif annottype in ['gene', 'pseudogene']:
			#~ dgenedesc[desc['ID']] = desc
			dgeneloctag[desc['ID']] = desc['locus_tag']
		elif annottype in annottype2fouttag:
			parentgene = desc.get('Parent')
			if parentgene:
				dgenenchild[parentgene] = dgenenchild.setdefault(parentgene, 0) + 1
	return (dgeneloctag, dgenenchild)

def compileFeatures(fgff, dfout, dgenbankcdsids, dgeneloctag, dgenenchild, didentseq={}):
	dgenerangeprods = {}
	annottype = None
	lineout = []
	nprintmullicds = 0
	for line in fgff:
		if line.startswith('#'): continue
		elif line.startswith('>'): break
		#~ print line
		seqreg, annottype, beg, end, strand, desc = parseGFFline(line)
		if annottype in annottype2fouttag:
			parentgene = desc['Parent']
			#~ locustag = dgenedesc[parentgene]['locus_tag']
			locustag = dgeneloctag[parentgene]
			# need to buffer extraction of entries as several lines can relate to the same gene in case of CDS/RNA in several segments (due  to introns, framshifts, ...)
			if annottype=="CDS":
				productid = desc.get('protein_id', '').split('|')[-1]	# to account for Prokka-style annotation that prepends 'gnl|Sequencing_Centre' to the protein_id
				genbankcdsid = dgenbankcdsids[(locustag, productid)]	# get unique CDS id
				lineout.append(genbankcdsid)
				if didentseq: lineout.append(didentseq.get(productid, productid))
			else:
				productid = desc.get('ID', '')
			dgenerangeprods.setdefault(parentgene, []).append((beg, end, productid))
			begs, ends, products = zip(*dgenerangeprods[parentgene])
			lineout = [productid, seqreg, locustag, min(begs), max(ends), strand, desc.get('product', '')] + lineout
			
			if len(dgenerangeprods[parentgene]) > 1:
				if nprintmullicds==0: print "multiline feature:",
				print productid,
				nprintmullicds +=1
				if products[0]!=productid: raise IndexError, "multiline feature not pointing at the same product: %s and %s"%(products[0], productid)
			if len(dgenerangeprods[parentgene])==dgenenchild[parentgene]:
				# write out previous CDS/RNA gene info (potential synthesis of several lines)
				dfout[annottype2fouttag.get(annottype, 'misc_features')].write('\t'.join(lineout)+'\n')
				lineout = []
				del dgenenchild[parentgene]
	
	if dgenenchild:
		raise IndexError, "some genes not written:\n%s"%(repr(dgenenchild))
	if lineout:
		raise IndexError, "extra unwritten line:\n%"%lineout
		#~ # write out last CDS info (potential synthesis of  several lines); flush buffer
		#~ dfout[annottype2fouttag[annottype]].write('\t'.join(lineout)+'\n')
	if nprintmullicds>0: print	'\n'


def parseAssemb(dirassemb, dfout, dtaxid2sciname={}, dmergedtaxid={}, didentseq={}):
	# parse CDS fasta file
	dgenbankcdsids = parseCDSFasta("%s/%s_cds_from_genomic.fna.gz"%(dirassemb, os.path.basename(dirassemb)))
	# extract assembly acc and name
	assembsearch = assembpat.search(os.path.basename(dirassemb))
	assacc, assname = assembsearch.groups()
	# parse GFF file
	fgff = gzip.open("%s/%s_genomic.gff.gz"%(dirassemb, os.path.basename(dirassemb)), 'rb')
	# first scans the file for region and (pseudo)gene features
	dgeneloctag, dgenenchild = indexRegionsAndGenes(fgff, dfout, assacc, assname, dtaxid2sciname=dtaxid2sciname, dmergedtaxid=dmergedtaxid)
	# resume reading the file from start
	fgff.seek(0)
	compileFeatures(fgff, dfout, dgenbankcdsids, dgeneloctag, dgenenchild, didentseq=didentseq)
	fgff.close()

def usage():
	s =  'Usage:\n'
	s += 'python all_genome_gff2db.py '
	s += '--assemb_list /path/to/list_of_assembly_folders '
	s += '--dirout /path/to/output_folder '
	s += '[--ncbi_taxonomy /path/to/NCBI_Taxonomy_db_dump_folder] '
	s += '[--identical_seqs /path/to/table_of_identical_proteins]'
	return s

def main():
	opts, args = getopt.getopt(sys.argv[1:], 'hv', ['dirout=', 'assemb_list=', 'ncbi_taxonomy=', 'identical_prots=', 'help'])
	dopt = dict(opts)
	if ('-h' in dopt) or ('--help' in dopt):
		print usage()
		sys.exit(0)

	nfldirassemb = dopt['--assemb_list']
	dirout = dopt['--dirout']
	dirncbitax = dopt.get('--ncbi_taxonomy')
	nfidentseq = dopt.get('--identical_prots')

	if os.path.exists(dirout):
		if os.path.isfile(dirout):
			raise ValueError, "Cannot create folder '%s' as it already exist as a file"%(dirout)
	else:
		os.mkdir(dirout)

	with open(nfldirassemb, 'r') as fldirassemb:
		ldirassemb = [line.rstrip('\n') for line in fldirassemb.readlines()]

	# optional link to NCBI Taxonomy database
	dmergedtaxid = {}
	dtaxid2sciname = {}
	if dirncbitax:
		nftaxmergedump = "%s/merged.dmp"%dirncbitax
		print "parse NCBI Taxonomy merged taxon ids from '%s'"%nftaxmergedump
		with open(nftaxmergedump, 'r') as ftaxmergedump:
			for line in ftaxmergedump:
				lsp = [f.strip('\t') for f in line.rstrip('|\n').split('|')]
				dmergedtaxid[int(lsp[0])] = int(lsp[1])

		nftaxnamesdump = "%s/names.dmp"%dirncbitax
		print "parse NCBI Taxonomy taxon names from '%s'"%nftaxnamesdump
		with open(nftaxnamesdump, 'r') as ftaxnamesdump:
			for line in ftaxnamesdump:
				lsp = [f.strip('\t') for f in line.rstrip('|\n').split('|')]
				if lsp[-1]=='scientific name':
					dtaxid2sciname[int(lsp[0])] = lsp[1]

	# optional parsing of table of identical proteins
	didentseq = {}
	if nfidentseq:
		print "parse redundant protein names from '%s'"%nfidentseq
		curfam = None
		refprot = None
		with open(nfidentseq, 'r') as fidentseq:
			for line in fidentseq:
				fam, prot = line.rstrip('\n').split('\t')
				if fam == curfam:
					didentseq[prot] = refprot
				else:
					curfam = fam
					refprot = prot

	# prepare annoatation db output files
	if dtaxid2sciname: dfoutheaders['replicons'].append('taxon_name')
	if didentseq: dfoutheaders['proteins'].append('nr_protein_id')

	dfout = {}
	for fouttag in fouttags:
		dfout[fouttag] = open(os.path.join(dirout, "all%s_info.tab"%(fouttag) ), 'w')
		dfout[fouttag].write('\t'.join(dfoutheaders[fouttag])+'\n')

	# parse all assemblies
	for dirassemb in ldirassemb:
		print "parse assembly '%s'"%dirassemb
		parseAssemb(dirassemb, dfout, dtaxid2sciname=dtaxid2sciname, dmergedtaxid=dmergedtaxid, didentseq=didentseq)

	for fouttag in fouttags:
		dfout[fouttag].close()

if __name__ == '__main__':
	main()
