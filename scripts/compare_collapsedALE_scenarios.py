#!/usr/bin/python

import os, sys, glob, getopt
import multiprocessing as mp
import cPickle as pickle
import shelve
import itertools
import gc
import numpy as np
from ptg_utils import *
import re

## Parameters
replacementcladepat = re.compile('^.+_(.+_RC-clade[0-9]+)$')

# block reconstruction
gapsize = 2
gefagr = ['cds_code','replaced_cds_code','gene_family_id']

# stat summary param
threshMinEventFreq = 10
PWMstats = [ \
'PWMatchesSummedJointFreq', \
'PWMatchesSummedMeanFreq', \
'PWMatchesUniqueCount', \
'PWMatchesUniqueCountMinEvFq', \
'PWMatchesTreeExtent', \
'PWMatchesTreeExtentMinEvFq', \
]

## Functions

def matchEventInLineages(dfamevents, genei, fami, genej, famj, noSameFam=True, blocks={}, dspe2pop={}, drefspeeventId2Tups={}, eventtypes='T', excludeNodeLabels=[], **kw):
	"""Generator function yielding matched homologous events from different reconciled scenarios. Proceeds by dissecting gene tree tip-to-root lineages.
	
	It typically involes comparing scenarios from different gene families (enforced if noSameFam=True), 
	but could aslo in theory be ued to compare scenarios from the same gene family, 
	under different reconciliation inference settings (e.g. different DTL rates, 
	or different reference tree collapsing). 
	
	These families can have different reference species tree, or more specifically, 
	different collapsed version of the same full reference species tree.
	
	This function takes a input a dict-of-dict-of dict object 'dfamevents', containing the 
	lists all the sampled event lineages, sorted by families and genes: 
	dfamevents[fami][genei] should thus return a dict of the following form: 
	{(X, [don, ]rec, ):freq, ...}, 
	where keys are tuples of DTL event types ('X' in {D,T,L,S}) and addresses, defined as 'rec' and optionally 'don' 
	(for horizontal transfers), the labels in species tree of node where the event occurred,
	OR, if drefspeeventId2Tups is provided:
	{i:freq, ...}
	where i is the species tree event unique reference id,
	and values are 'freq' the event frequency within the sample of N reconciled gene trees.
	
	!!! Because closely related genes share lineage history that are duplicated in this representation,
	!!! this is a highly redundant representation and thus quite heavy format.
	
	This function is a generator and thus yields matched event tuples 
	
	If 'dspe2pop' is provided, alias addresses in the compared refence species tree will be generated,
	so that events involving strains/lineage from within a population (in a species tree where it is not collapsed) 
	and those involving the collapsed population can be recognised as homologous.
	
	However, it is though safer to not try and match events occurring below the population ancestor nodes,
	because of the low reolution of the population subtree making inferences to be incertain, 
	and to a lesser extant to match events occurring below the population ancestor nodes, 
	due to the possibly poor quality of the heuristic used to tag populations on collapsed gene tree clades.
	
	Such events of uncertain qulity can be excluded from the comparison using 'excludeNodeLabels' argument.
	"""
	def eventLocSpeOrPop(evtup, dspe2pop):
		return [evtup[:1]+tuple(y) for y in itertools.product(*[list(set([ x, dspe2pop.get(x, x) ])) for x in evtup[1:]])]
	
	if noSameFam and fami==famj:
		# stop immediately
		return
	
	devi = dfamevents[fami][genei] #; print devi
	devj = dfamevents[famj][genej] #; print devj
	verbose = kw.get('verbose')
	evtupis = kw.get('events', devi.keys())
	for evtupi in evtupis:
		# one event tuple per sampled recongiled gene tree, representing the gene lineage (= tip-to-root node path in gene tree)
		if verbose : print 'evtupi:', evtupi
		# every event in genei lineage should be matching at most once in genej lineage
		matched = False
		if drefspeeventId2Tups.get(evtupi, evtupi)[0] not in eventtypes: continue
		if dspe2pop: akaevtupis = eventLocSpeOrPop(evtupi, dspe2pop)
		else: akaevtupis = (evtupi,)
		if verbose : print 'akaevtupis:', akaevtupis 
		for evtupj in devj:
			if verbose:  print 'evtupj:', evtupj 
			if matched: break # the for evtupj loop
			# mapping of aliases: species to collapsed population
			if dspe2pop: akaevtupjs = eventLocSpeOrPop(evtupj, dspe2pop)
			else: akaevtupjs = (evtupj,)
			if verbose:  print 'akaevtupjs:', akaevtupjs 
			for akaevtupi in akaevtupis:
				# one event lineage tuple per sampled recongiled gene tree
				if akaevtupi in akaevtupjs:
					if verbose : print 'nosino'
					if not (genej in blocks.get(evtupi, [])):
						# avoid yielding the event match again if was previously spotted in a gene block
						if verbose : print 'rhhhoooooo', [evtupi, devi[evtupi], devj[evtupj]]
						yield [evtupi, devi[evtupi], devj[evtupj]]
					matched = True
					# only one alias should be matched (as with alias vs. alias matching, it can give up to 2^len(evloc) matches)
					break # the for akaevtupi loop

def searchPWMatches(dfamevents, genefams, nfpicklePWMatches=None, dspe2pop={}, drefspeeventId2Tups={}, eventtypes='T'):
	PWMatches = {}
	for i in range(len(genefams)-1):
		genri, fami = genefams[i]
		#~ print genri, fami
		for j in range(i+1, len(genefams)):
			genej, genrj, famj = [genefams[j][f] for f in gefagr]
			#~ print genrj, famj
			for matchedT, fi, fj in matchEventInLineages(dfamevents, genri, fami, genrj, famj, dspe2pop=dspe2pop, drefspeeventId2Tups=drefspeeventId2Tups, eventtypes=eventtypes):
				PWMatches.setdefault((genri, genrj), []).append((matchedT, fi, fj)) 
	if nfpicklePWMatches:
		with open(nfpicklePWMatches, 'wb') as fpicklePWMatches:
			 pickle.dump(PWMatches, fpicklePWMatches, protocol=2)
		print "saved 'PWMatches' to file '%s'"%nfpicklePWMatches
	return PWMatches

def reconstructBlocks(dfamevents, genefams, nfoutblocks=None, nfpicklePWMatches=None, dspe2pop={}, gapsize=-1):
	"""finds blocks of consecutive genes that share homologous events"""
	if nfoutblocks:
		foutblocks = open(nfoutblocks, 'w')
		foutblocks.write('\t'.join(['event', 'don', 'rec', 'len.block', 'sum.freq', 'min.freq', 'max.freq', 'mean.freq', 'median.freq', 'genes', 'eventFreqs'])+'\n' )
	dblockTs = {}
	dblockTsReplGenes = {}
	dblockTfreqs = {}
	PWMatches = {}
	for i in range(len(genefams)-1):
		j = i+1
		genei, genri, fami = [genefams[i][f] for f in gefagr]
		genej, genrj, famj = [genefams[j][f] for f in gefagr]
		#print "%s: %s (%s) <-> %s: %s (%s)"%(fami, genei, genri, famj, genej, genrj)
		for matchedT, fi, fj in matchEventInLineages(dfamevents, genri, fami, genrj, famj, dspe2pop=dspe2pop, blocks=dblockTsReplGenes):
			#print matchedT, 
			dblockTs.setdefault(matchedT, [genei]).append(genej)
			dblockTsReplGenes.setdefault(matchedT, [genri]).append(genrj)
			dblockTfreqs.setdefault(matchedT, [fi]).append(fj)
			#PWMatches.setdefault((genei, genej), []).append((matchedT, fi, fj)) 
			print genei, genej, matchedT, fi, fj
			# try to extend transfer block
			k = j+1
			moreTs = True
			genel = genej ; fl = fj
			if gapsize>=0: curgap = gapsize
			else: curgap = 1
			while (k<len(genefams) and (moreTs or curgap>0)):
				genek, genrk, famk = [genefams[k][f] for f in gefagr]
				moreTs = [Tff for Tff in matchEventInLineages(dfamevents, genri, fami, genrk, famk, dspe2pop=dspe2pop, blocks=dblockTsReplGenes, events=[matchedT])]
				if moreTs:
					curgap = gapsize
					fk = moreTs[0][2]
					#print genek,
					dblockTs[matchedT].append(genek)
					dblockTsReplGenes[matchedT].append(genrk)
					dblockTfreqs[matchedT].append(fk)
					#PWMatches.setdefault((genel, genek), []).append((matchedT, fl, fk)) 
					print ' '*k, genel, genek, matchedT, fl, fk
					genel = genek ; fl = fk
				else:
					if gapsize>=0: curgap -= 1
				k += 1
			else:
				print ''
				if gapsize>=0:
					# remove occurrence of theat transfer pattern for further independent creation of another block
					blockTgenes = dblockTs.pop(matchedT)
					blockTgenesR = dblockTsReplGenes.pop(matchedT)
					blockTfreqs = dblockTfreqs.pop(matchedT)
				else:
					# gap of infinite size ; just test co-transfer linkage without considering gene neighborhood
					blockTgenes = dblockTs[matchedT]
					blockTgenesR = dblockTsReplGenes[matchedT]
					blockTfreqs = dblockTfreqs[matchedT]
				for x, gx in enumerate(blockTgenes):
					for y, gy in enumerate(blockTgenes):
						if x==y: continue
						PWMatches.setdefault((gx, gy), []).append((matchedT, blockTfreqs[x], blockTfreqs[y])) 
				
				if nfoutblocks:
					foutblocks.write('\t'.join(list(matchedT) \
					+ [str(fun(blockTfreqs)) for fun in (len, sum, min, max, mean, median)] \
					+ [' '.join(blockTgenes), ' '.join([str(f) for f in blockTfreqs])])+'\n' )

	if nfoutblocks: foutblocks.close()
	if nfpicklePWMatches:
		with open(nfpicklePWMatches, 'wb') as fpicklePWMatches:
			 pickle.dump(PWMatches, fpicklePWMatches, protocol=2)
		print "saved 'PWMatches' to file '%s'"%nfpicklePWMatches
	return PWMatches				

#~ def treeExtantEventSet(levents, refspetree, fun=max):
	#~ """measure dispersion of a set of events on the species tree
	
	#~ by default return maximum distance, can be average (fun=mean), minimum (fun=min)...
	#~ """
	#~ ldist = []
	#~ if len(levents) <=1: return maxdist
	#~ # from the set of all (recipient) locations, compute the maximum distance on the species tree
	#~ # ... should do that on the consensus gene tree... if one could map each sampled reconciled gene tree to the consensus!!!
	#~ # on levents a list of tuples such as:  ([don, ] rec)
	#~ allTreeLocs = list(set(reduce(lambda x,y: x[-1:]+y[-1:], levents)))
	#~ for loci in allTreeLocs:
		#~ ni = refspetree[loci]
		#~ for locj in allTreeLocs:
			#~ if loci!=locj:
				#~ nj = refspetree[locj]
				#~ d = ni.distance(nj)
				#~ ldist.append(d)
	#~ if fun is max: ldist.append(0)
	#~ return fun(ldist)

def PWMatchesUniqueCount(levff, **kw):
	return len(levff)

def PWMatchesSummedMeanFreq(levff, **kw):
	#~ return float(sum(reduce(lambda x,y: x[1:]+y[1:], levff, (0,))))/2
	return sum(float(fi+fj)/2 for ev,fi,fj in levff)
	
#~ def PWMatchesTreeExtent(pwmatches, refspetree, **kw):
	#~ treeExtantEventSet(pwmatches, refspetree)

def PWMatchesSummedJointFreq(levff, **kw):
	return float(sum(fi*fj for ev,fi,fj in levff))

def matchStats(PWMmats, genepairi, levff, reportStats=['PWMatchesSummedJointFreq'], threshMinEventFreq=[]): #, refspetree=None
	lminflevff = []
	for t in threshMinEventFreq:
		lminflevff.append( [evff for evff in levff if (evff[1]>=t and evff[2]>=t)] )
	for pwstat in PWMstats:
		if pwstat in reportStats:
			pwstatfun = pwstat.rsplit('MinEvFq', 1)[0]
			#~ PWMmats.setdefault(pwstat, {})[genepairi] = eval(pwstat)(levff=levff, pwmatches=pwm, refspetree=refspetree)
			PWMmats.setdefault(pwstat, {})[genepairi] = eval(pwstat)(levff)
			for t, minflevff in zip(threshMinEventFreq, lminflevff):
				PWMmats.setdefault(pwstat+'_MinEventFreq_%f'%float(t), {})[genepairi] = eval(pwstat)(minflevff)

def match_events(dfamevents, recordEvTypes, drefspeeventId2Tups, genefamlist=None, writeOutDirRad=None):
	"""from dictionary of reported events, by family and gene lineage, return matrix of pairwise gene event profile similarity"""
	lfams = dfamevents.keys()
	if genefamlist:
		genefams = [(genefam.get('replaced_cds_code', genefam['cds_code']), genefam['gene_family_id']) for genefam in genefamlist if (genefam['gene_family_id'] in lfams)]
	else:
		genefams = []
		for fam in lfams:
			genefams += [(cdscode, fam) for cdscode in dfamevents[fam]]
	
	if writeOutDirRad:
		nfpicklePWMatches = writeOutRad+'.PWgeneEventMatches.%s.pickle'%recordEvTypes
		nfoutblocks =  writeOutRad+'.matchedEventGeneBlocks.%s.tab'%recordEvTypes
		
	else:
		nfpicklePWMatches = nfoutblocks = None

	if os.access(nfpicklePWMatches, os.F_OK):
		with open(nfpicklePWMatches, 'rb') as fpicklePWMatches:
			PWMatches = pickle.load(fpicklePWMatches)
		print "loaded 'PWMatches' from file '%s'"%nfpicklePWMatches
	else:
		PWMatches = searchPWMatches(dfamevents, genefams, nfpicklePWMatches, dspe2pop=dspe2pop, drefspeeventId2Tups=drefspeeventId2Tups, eventtypes=recordEvTypes)
	# summarize
	genelist = [genefam['cds_code'] for genefam in genefams]

	PWMmats = {PWMstat:np.zeros((len(genelist), len(genelist)), dtype=float) for PWMstat in PWMstats}
	for genepair, levff in PWMatches.iteritems():
		genepairi = tuple(genelist.index(geni) for geni in genepair)
		matchStats(PWMmats, genepairi, levff)
	
	if writeOutDirRad:
		# write output
		for PWMstat, PWMmat in PWMmats.iteritems():
			nfmat = nfgenefamlist.rsplit('.', 1)[0]+'.%s.%s.csv'%(PWMstat, recordEvTypes)
			with open(nfmat, 'w') as fmat:
				nfmat = writeOutRad+'.%s.%s.csv'%(PWMstat, recordEvTypes)
				#~ PWMmat.tofile(fmat, sep=',')
				for i, gene in enumerate(genelist):
					fmat.write(','.join([gene]+[str(x) for x in PWMmat[i,]])+'\n')
				print "wrote %s output into file '%s'"%(PWMstat, nfmat)
	return (PWMstat, PWMmat)

def connectpostgresdb(dbname, **kw):
	psycopg2 = __import__('psycopg2')
	return psycopg2.connect(dbname=dbname, **kw)

def connectsqlitedb(dbname):
	sqlite3 = __import__('sqlite3')
	return sqlite3.connect(dbname)

def get_dbconnection(dbname, dbengine, **kw):
	if (dbengine.lower() in ['postgres', 'postgresql', 'psql', 'pg']):
		dbcon = connectpostgresdb(dbname, **kw)
		dbtype = 'postgres'
		valtoken='%s'
		dbcur = dbcon.cursor()
		dbcur.execute("set search_path = genome, phylogeny;")
	elif (dbengine.lower() in ['sqlite', 'sqlite3']):
		dbcon = connectsqlitedb(dbname)
		dbcur = dbcon.cursor()
		dbtype = 'sqlite'
		valtoken='?'
	else:
		raise ValueError,  "wrong DB type provided: '%s'; select one of dbengine={'postgres[ql]'|'sqlite[3]'}"%dbengine
	return (dbcon, dbcur, dbtype, valtoken)

def mulBoundInt2Float(a, b, scale, maxval=1.0):
	f1 = min(float(a)/scale, maxval)
	f2 = min(float(b)/scale, maxval)
	return f1*f2

def _select_lineage_event_clause_factory(rlocdsidcol, evtypes, valtoken):
	if rlocdsidcol=='replacement_label_or_cds_code': rlocdsIJ = ""
	else: rlocdsIJ = "INNER JOIN replacement_label_or_cds_code2gene_families USING (replacement_label_or_cds_code)"
	if evtypes:
		evtyperestrictIJ = "INNER JOIN species_tree_events USING (event_id)"
		evtyperestrictWC = "AND event_type IN %s"%repr(tuple(e for e in evtypes))
	else:
		evtyperestrictWC = evtyperestrict = ""
	return (rlocdsIJ, evtyperestrictIJ, evtyperestrictWC)

def _select_lineage_by_event_query_factory(rlocdsidcol, evtypes, valtoken, addselcols=(), distinct=False, operator'=', addWhereClause=''):
	rlocdsIJ, evtyperestrictIJ, evtyperestrictWC = _select_lineage_event_clause_factory(rlocdsidcol, evtypes, valtoken)
	tqfields = (('DISTINCT' if distinct else ''), repr((rlocdsidcol,)+tuple(addselcols)).strip('()'), rlocdsIJ, evtyperestrictIJ, operator, valtoken, evtyperestrictWC, addWhereClause)
	preq = "SELECT %s %s FROM gene_lineage_events %s %s WHERE event_id%s%s %s %s ;"
	return preq

def _select_event_by_lineage_query_factory(rlocdsidcol, evtypes, valtoken, addselcols=('freq',), distinct=False, operator'=', addWhereClause=''):
	rlocdsIJ, evtyperestrictIJ, evtyperestrictWC = _select_lineage_event_clause_factory(rlocdsidcol, evtypes, valtoken)
	tqfields = (('DISTINCT' if distinct else ''), repr(('event_id',)+tuple(addselcols)).strip('()'), rlocdsIJ, evtyperestrictIJ, rlocdsidcol, operator, valtoken, evtyperestrictWC, addWhereClause)
	preq = "SELECT %s %s FROM gene_lineage_events %s %s WHERE %s=%s %s %s ;"%tqfields
	return preq

def _query_events_by_lineage(gene, preq, dbcur):
	dbcur.execute(preq, (gene,)) 
	return sorted(dbcur.fetchall(), key=lambda x: x[0])

def _query_matching_lineage_event_profiles(args, returDict=True, use_gene_labels=False, timing=False, arraysize=10000, verbose=False):
	
	if timing: time = __import__('time')
	lineage_id, dbname, dbengine, nsample, evtypes, mineventfreq, reportJFtrhesh = args
	dbcon, dbcul, dbtype, valtoken = get_dbconnection(dbname, dbengine)
	if use_gene_labels: rlocdsidcol = 'replacement_label_or_cds_code'
	elif dbtype=='postgres': rlocdsidcol = 'rlocds_id'
	else: rlocdsidcol = 'oid'
	if returDict: genepaircummulfreq = {}
	else: genepaircummulfreq = []
	if mineventfreq: mineventfreqWC = " AND freq >= %d"%int(mineventfreq) else ''
	# first get the vector of (event_id, freq) tuples in lineage
	preq_evbyli = _select_event_by_lineage_query_factory(rlocdsidcol, evtypes, valtoken, addWhereClause=mineventfreqWC)
	if verbose: print preq_libyevin%lineage_id
	lineage_eventfreqs = _query_events_by_lineage(lineage_id, preq_evbyli, dbcur)
	dlineage_eventfreqs = dict(lineage_eventfreqs)
	lineage_events = tuple(ef[0] for ef in lineage_eventfreqs)
	
	# then build a list of gene lineages to compare, based on common occurence of at least N event (here only 1 common event required)
	# and the id of compared lineage to be > reference lineage, to avoid duplicate comparisons
	lineageorderWC=" AND %s > %s"%(locdsidcol, str(lineage_id))
	preq_libyev = _select_lineage_by_event_query_factory(rlocdsidcol, evtypes, valtoken, operator=' IN ', addWhereClause=mineventfreqWC+lineageorderWC)
	preq_libyevin = preq_libyev.replace(valtoken, repr(lineage_events)))
	if verbose: print preq_libyevin
	dbcul.execute(preq_libyevin) 
	matchgenes = dbcul.fetchall()
	
	lmatches = []
	for match_lineage_id in match_lineages:
		jointfreq = 0.0
		mg_lineage_eventfreqs = _query_events_by_lineage(match_lineage_id, preq_evbyli, dbcur)
		for eid, f in mg_lineage_eventfreqs:
			f0 = dlineage_eventfreqs.get(eid)
			if f0: jointfreq += mulBoundInt2Float(f0, f, nsample, maxval=1.0)
		if jointfreq >= reportJFtrhesh:
			lmatches.append( (lineage_id, match_lineage_id), jointfreq )
	
	dbcon.close()
	if verbose: print lmatches
	return lmatches

def dbquery_matching_lineage_event_profiles(dbname, nsample=1.0, evtypes=None, genefamlist=None, \
                            nbthreads=1, dbengine='postgres', use_gene_labels=False, \
                            matchesOutDirRad=None, nfpickleMatchesOut=None, returnList=False, **kw):
	
	timing = kw.get('timing')
	if timing: time = __import__('time')							
	dbcon, dbcur, dbtype, valtoken = get_dbconnection(dbname, dbengine, **kw)
	nsamplesq = nsample*nsample
	if use_gene_labels: rlocdsidcol = 'replacement_label_or_cds_code'
	elif dbtype=='postgres': rlocdsidcol = 'rlocds_id'
	else: rlocdsidcol = 'oid'
	if not (matchesOutDirRad or nfpickleMatchesOut or returnList):
		raise ValueError, "must specify at least one output option among: 'matchesOutDirRad', 'nfpickleMatchesOut', 'returnList'"	
	if matchesOutDirRad:
		fout = open(os.path.join(matchesOutDirRad, 'matching_events.tab'), 'w')
	
	if genefamlist:
		# create real table so can be seen by other processes
		ingenefams = [genefam.get('replaced_cds_code', genefam['cds_code']) for genefam in genefamlist]
		dbcur.execute("create table ingenefams (replacement_label_or_cds_code VARCHAR(60), gene_family_id VARCHAR(20));" )
		dbcur.executemany("insert into ingenefams values (%s), VARCHAR(20);"%valtoken, ingenefams)
		dbcon.commit()
		# query modifiers
		generestrict = "inner join ingenefams using (replacement_label_or_cds_code) "
	else:
		generestrict = ""
	
	# get set of gene lineages
	#~ dbcur.execute("select distinct %s from gene_lineage_events %s %s;"%(rlocdsidcol, generestrict, evtyperestrict))
	dbcur.execute("select distinct %s from replacement_label_or_cds_code2gene_families %s %s;"%(rlocdsidcol, generestrict, evtyperestrict))
	llineageids = dbcur.fetchall()
			
	if (nfpickleMatchesOut or returnList): lmatches = []
	if nbthreads==1:
		for lineageid in llineageids:
			lm = _query_matching_lineage_event_profiles((lineageid, evtypes, ))
			if (nfpickleMatchesOut or returnList): lmatches += lm
	else:
		pool = mp.Pool(processes=nbthreads)
		iterargs = ((lineageid, evtypes, ) for ineageid in llineageids)
		iterlm = pool.imap_unordered(_query_matching_lineages_by_events, iterargs, chunksize=100)
		# an iterator is returned by imap_unordered(); one needs to actually iterate over it to have the pool of parrallel workers to compute
		for lm in iterlm:
			if (nfpickleMatchesOut or returnList): lmatches += lm
			if matchesOutDirRad:
				for genepair, cummulfreq in lm:
						fout.write('%s\t%f\n'%('\t'.join(genepair), cummulfreq))
		
		
	if nfpickleMatchesOut:
		with open(nfpickleMatchesOut, 'wb') as fpickleOut:
			pickle.dump(lmatches, fpickleOut, protocol=pickle.HIGHEST_PROTOCOL)
			# can be a more efficient option for disk space than a simple table,
			# but the required writing time and the accumulated memory space might make it redibitory
		print "saved 'lmatches' to file '%s'"%nfpickleMatchesOut
			
	if matchesOutDirRad:
		fout.close()
	
def _query_matching_lineages_by_event(args, returDict=True, use_gene_labels=False, serverside=[], timing=False, arraysize=10000):
	"""function handling one event_id query, designed for use in parallel
	
	fetching all gene lineages where the event 'event_id' occurred 
	and computing the joint frequency of this event for all pairs of gene lineages.
	
	takes an ordered tuple of arguments:
	evtid (int), dbname (str), dbengine ({'postgres'|'sqlite'}), 
	nsamplesq (int, size of sample from which freq of observations was derived), 
	evtypes ({'D'|'T'|'S'|'L'}).
	"""
	# test with evtid=1795683
	# genefams of size 8,647
	# at most (but probably close to) 8647*(8647-1)/2 = 37,380,981 gene lineage comparisons (actually ???)
	# when storing (gene1, gene2):jfreq with full gene tree labels and float freq, it uses ~12Gb mem
	# when storing (gene1, gene2):jfreq with int id of gene tree labels and float freq, it uses ~5Gb mem
	
	if timing: time = __import__('time')
	evtid, dbname, dbengine, nsample, evtypes = args
	dbcon, dbcul, dbtype, valtoken = get_dbconnection(dbname, dbengine)
	if use_gene_labels: rlocdsidcol = 'replacement_label_or_cds_code'
	elif dbtype=='postgres': rlocdsidcol = 'rlocds_id'
	else: rlocdsidcol = 'oid'
	# allow big fetch operations
	dbcul.arraysize = arraysize
	if returDict: genepaircummulfreq = {}
	else: genepaircummulfreq = []
	
	if 'combinations' in serverside:
		# get all the genes which event lineage features this event
		if timing: t0 = time.time()
		dbcul.execute("""create temp table genefams as select rlcc2gf.%s as gene, gene_family_id as fam, freq 
						   from (select %s, replacement_label_or_cds_code, freq from gene_lineage_events where event_id=%s ) s1
						   inner join replacement_label_or_cds_code2gene_families as rlcc2gf using (replacement_label_or_cds_code) ;
					  """%(rlocdsidcol, rlocdsidcol, valtoken), (evtid,))

		if timing: t1 = time.time() ; print t1 - t0
		# takes 1s
		if 'math' in serverside:
			dbcul.execute("""SELECT genefams1.gene, genefams2.gene, (LEAST(genefams1.freq, %s) * LEAST(genefams2.freq, %s) / %s )::real
							  FROM genefams as genefams1, genefams AS genefams2
							 WHERE genefams1.fam != genefams2.fam AND genefams1.gene > genefams2.gene;"""%(valtoken,valtoken,valtoken), (nsample, nsample, nsample*nsample,))
			matchgenes = dbcul.fetchmany()
			while matchgenes:
				for gene1, gene2, jfreq  in matchgenes:
					if returDict: genepaircummulfreq[(gene1, gene2)] = jfreq
					else: genepaircummulfreq.append(((gene1, gene2), jfreq))
				matchgenes = dbcul.fetchmany()
			if timing: t2 = time.time() ; print '+', t2 - t1
			# test takes ~ 18min
		else:
			dbcul.execute("""select genefams1.gene, genefams2.gene, genefams1.freq, genefams2.freq 
							  from genefams as genefams1, genefams as genefams2
							 where genefams1.fam != genefams2.fam and genefams1.gene > genefams2.gene;""")
			matchgenes = dbcul.fetchmany()
			while matchgenes:
				for gene1, gene2, freq1, freq2  in matchgenes:
					jfreq = mulBoundInt2Float(freq1, freq2, nsample, maxval=1.0)
					if returDict: genepaircummulfreq[(gene1, gene2)] jfreq
					else: genepaircummulfreq.append(((gene1, gene2), jfreq))
				matchgenes = dbcul.fetchmany()
			if timing: t2 = time.time() ; print '+', t2 - t1
			# test takes ~ 18min
			
	else:
		if timing: t0 = time.time()
		dbcul.execute("""select %s, gene_family_id, freq 
						   from gene_lineage_events
						   inner join replacement_label_or_cds_code2gene_families using (replacement_label_or_cds_code)
						 where event_id=%s ;
					  """%(rlocdsidcol, valtoken), (evtid,)) 
		matchgenes = dbcul.fetchall()
		if timing: t1 = time.time() ; print t1 - t0
		# takes 0.25s
		for genetup1, genetup2 in itertools.combinations(matchgenes, 2):
			gene1, fam1, freq1 = genetup1
			gene2, fam2, freq2 = genetup2
			if fam1!=fam2: # filter genes from same families
				jfreq = mulBoundInt2Float(freq1, freq2, nsample, maxval=1.0)
				if returDict: genepaircummulfreq[(gene1, gene2)] jfreq   # (gene1, gene2) can only be seen once so no need to do d.setdefault((g1,g2), 0) then add value
				else: genepaircummulfreq.append(((gene1, gene2), jfreq))
		if timing: t2 = time.time() ; print t2 - t1
		# compared to server-side computation of combinations, less rows to fetch speeds up the process
		# test takes ~ 9min with tuples of full gene tree label as keys (store in dict)
		# test takes ~ 8min with tuples of int id of gene tree label as keys (store in dict)
		# test takes < 52min when storing tuples in a list rather than dict
	dbcon.close()
	return genepaircummulfreq

def stripstr(obj, stripchar='()'):
	return str(obj).strip(stripchar).replace(', ', ',')

## functions similar to dict.update() but performing cumulative sum of values rather than update
def cumSumDictNumVal(ld, dcumsum, funOnKey=None):
	"""merge dict objects by summing their numerical values; 
	
	input: a list of dict, a [persistent] dict of initial values; output: dict of summed values.
	if funOnKey is specified, the input value will be stored under funOnKey(key); 
	this can be 'hash' or 'repr' or 'str', to enforce the integer or string formatting of the key (necessary for shelve persistant dict).
	"""
	for d in ld:
		for key in d:
			if funOnKey: k = funOnKey(key)
			else: k = key
			preval = dcumsum.setdefault(k, 0.0)
			dcumsum[k] = preval + d[key]

def cumSumSeqNumVal(llt, dcumsum, funOnKey=None):
	"""merge dict objects by summing their numerical values; 
	
	input: a list of list of (key, val) tuples, a [persistent] dict of initial values; output: dict of summed values.
	if a callable is specified via funOnKey, the input value will be stored under funOnKey(key); 
	this can be 'hash' or 'repr' or 'str', to enforce the integer or string formatting of the key (necessary for shelve persistant dict).
	"""
	for lt in llt:
		for key, val in lt:
			if funOnKey: k = funOnKey(key)
			else: k = key
			preval = dcumsum.setdefault(k, 0.0)
			dcumsum[k] = preval + val

def dbquery_matching_lineages_by_event(dbname, nsample=1.0, evtypes=None, genefamlist=None, \
                            nbthreads=1, dbengine='postgres', \
                            matchesOutDirRad=None, nfpickleMatchesOut=None, nfshelveMatchesOut=None, **kw):
	"""look for common events between genes, and retrieve their joint probability of occurence (produce of their observation frequencies)
	
	to explore the entire set of lineage-to-lineage comparisons, of event sets, 
	iterate over all events, getting the set of all gene lineages featuring that event
	and retrieveing allpair combinations and joint probabilities.
	
	This function relies on sub-function calls handling one event each, usually in parallel;
	The maps of (gene pairs)->(joint event prob) generated for each events are then summed over all events,
	to return a map of all (gene pairs)->(frequency of joint occurence in scenarios).
	
	Turns out to be a very heavy approach, du to lots of intermediate results that need to be saved.
	In the end, the number of gene lineage pairs explored is redibitory, not all can be saved:
	Some pairs->freq items which joint freq score falls under a threshold must be discarded 
	(but a account of the distribution of scores can be kept, by counting of how many pairs 
	achieved a score falling in a finite number of bins); this however warants that the score 
	of each gene pair is evaluated at once... not inmany times, like in this function.
	"""
	
	timing = kw.get('timing')
	if timing: time = __import__('time')							
	dbcon, dbcur, dbtype, valtoken = get_dbconnection(dbname, dbengine, **kw)
	nsamplesq = nsample*nsample
	
	if evtypes: evtyperestrict = "inner join species_tree_events using (event_id) where event_type in %s"%repr(tuple(e for e in evtypes))
	else: evtyperestrict = ""
	
	if genefamlist:
		# create real table so can be seen by other processes
		ingenefams = [genefam.get('replaced_cds_code', genefam['cds_code']) for genefam in genefamlist]
		dbcur.execute("create table ingenefams (replacement_label_or_cds_code VARCHAR(60), gene_family_id VARCHAR(20));" )
		dbcur.executemany("insert into ingenefams values (%s), VARCHAR(20);"%valtoken, ingenefams)
		dbcon.commit()
		# query modifiers
		generestrict = "inner join ingenefams using (replacement_label_or_cds_code) "
	else:
		generestrict = ""
	
	# get set of events
	dbcur.execute("select distinct event_id from gene_lineage_events %s %s;"%(generestrict, evtyperestrict))
	ltevtids = dbcur.fetchall()
	
	if nfshelveMatchesOut:
		print "will gradually store event tuples in persistent dictionary (shelve) file: '%s'"%nfshelveMatchesOut
		dgenepaircummulfreq = shelve.open(nfshelveMatchesOut, protocol=2, writeback=True)
		funk = stripstr
	else:
		dgenepaircummulfreq = {}
		funk = None
		
	if nbthreads==1:
		for tevtid in ltevtids:
			dgpcf = _query_matching_lineages_by_event((tevtid[0], dbname, dbengine, nsamplesq, evtypes), returnDict=True)
			cumSumDictNumVal([dgpcf], dgenepaircummulfreq, funOnKey=funk)
	else:
		pool = mp.Pool(processes=nbthreads)
		iterargs = ((tevtid[0], dbname, dbengine, nsamplesq, evtypes) for tevtid in ltevtids)
		iterdgpcf = pool.imap_unordered(_query_matching_lineages_by_events, iterargs, chunksize=100)
		# an iterator is returned by imap_unordered(); one needs to actually iterate over it to have the pool of parrallel workers to compute
		if timing: t2 = time.time()
		for dgpcf in iterdgpcf:
			#~ cumSumSeqNumVal([dgpcf], dgenepaircummulfreq, funOnKey=funk)
			cumSumDictNumVal([dgpcf], dgenepaircummulfreq, funOnKey=funk)
			if timing: t3 = time.time() ; print '+', t3 - t2 ; t2 = t3
			# test take 2min when updating simple dict with list of tuples
			# test take ~2.6h when updating shelve persistant dict with list of tuples
			# storage in simple dict should be prefered as takes much less time to store with int tuple keys
			# vs. str representation for shelve dict (also ultimately takes more space)
			# and less time is spent pickling the dict (only writing once per key at the end = big one)
			# vs. syncing the shelve many times on the same keys during the run
			# only BIG issue is the concurent memory use maintaning a dict with up to 1e6 ^2 = 1e12 entries,
			# that would be expected to use 100 TB mem...
			# storing the data as plain text for 1e12 entries would take ~ 20TB disk space
			# possible but silly...
			# must discard pairs which score falls under a threshold (but keep count of pairs that achived a score, by bins of scores)
			# this warants evaluation of gene pairs at once... not this function.
			
			if nfshelveMatchesOut:
				dgenepaircummulfreq.sync()
				if timing: t4 = time.time() ; print '+', t4 - t3 ; t2 = t4
	
	if matchesOutDirRad: 
		nfout = os.path.join(matchesOutDirRad, 'matching_events.tab')
		with open(nfout, 'w') as fout:
			for genepair, cummulfreq in dgenepaircummulfreq.iteritems():
				fout.write('%s\t%f\n'%('\t'.join(genepair), cummulfreq))
	
	if nfshelveMatchesOut:
		dgenepaircummulfreq.close()
	else:
		if nfpickleMatchesOut:
			with open(nfpickleMatchesOut, 'wb') as fpickleOut:
				pickle.dump(dgenepaircummulfreq, fpickleOut, protocol=pickle.HIGHEST_PROTOCOL)
				# takes ~ 50min to save a dict that stores 80M entries ; cannot decently be used for every round.
			print "saved 'dgenepaircummulfreq' to file '%s'"%nfpickleMatchesOut
	
	
	if genefamlist:
		dbcur.execute("drop table ingenefams;")
		dbcon.commit()
	dbcon.close()	
	return dgenepaircummulfreq

def usage():
	s = "Usage: [HELP MESSAGE INCOMPLETE]\N"
	s += "python %s [OPTIONS] runmode\n"%sys.argv[0]
	s += "Facultative options:"
	s += "\t\t--rec_sample_list path to list of reconciliation file paths\n"
	s += "\t\t--dir_replaced\tfolder containing files listing replaced leaf labels (e.g. wen collapsing gene tree clades)\n"
	s += "\t\t--genefams\ttabulated file with header containing at least those two fields: 'cds_code', 'gene_family_id'\n"
	s += "\t\t\t\trows indicated the genes to be treated in the search, and to which gene family they belong (and hence in which reconciliation file to find them)\n"
	return s

################## Main execution

if __name__=='__main__':

	opts, args = getopt.getopt(sys.argv[1:], 'hv', ['ALE_algo=', 'evtype=', 'minfreq=', 'method=', 'nrec_per_sample=', \
	                                                'events_from_pickle=', 'events_from_shelve=', 'events_from_postgresql_db=', 'events_from_sqlite_db=', \
	                                                'matches_to_shelve=', 'dir_table_out=', \
	                                                'threads=', 'help', 'verbose']) #, 'reuse=', 'max.recursion.limit=', 'logfile='
	dopt = dict(opts)
	
	if ('-h' in dopt) or ('--help' in dopt):
		print usage()
		sys.exit(0)
	
	matchMethod = dopt.get('--method', 'matching_lineage_event_profiles')
	goodmethods = ['matching_lineages_by_event', 'matching_lineage_event_profiles', 'deprecated']
	if matchMethod not in goodmethods:
		raise ValueError, "valid values for --method argument are: %s"%repr(goodmethods).strip('[]')
	
	# reconciliation collection / parsed events input options
	nfpickleEventsIn = dopt.get('--events_from_pickle')
	nfshelveEventsIn = dopt.get('--events_from_shelve')
	dbname   = dopt.get('--events_from_postgresql_db', dopt.get('--events_from_sqlite_db'))
	if nfshelveEventsIn:
		loaddfamevents = 'shelve'
	elif nfpickleEventsIn:
		loaddfamevents = 'pickle'
	elif dbname and ('--events_from_postgresql_db' in dopt):
		loaddfamevents = 'postgres'
	elif dbname and ('--events_from_sqlite_db' in dopt):
		loaddfamevents = 'sqlite'
	else:
		raise ValueError, "must provide input file through either '--events_from_pickle', '--events_from_shelve', '--events_from_sqlite_db' or '--events_from_postgresql_db' options"
	
	# parsed events / matched events output options
	dirTableOut = dopt.get('--dir_table_out')
	nfpickleMatchesOut = dopt.get('--matches_to_pickle')
	nfshelveMatchesOut = dopt.get('--matches_to_shelve')
	
	# other params
	
	# normalization factor (and max per lineage) of observed event frequencies
	nrecsample = dopt.get('--nrec_per_sample', 1000.0)
	# facultative input files
	nfgenefamlist = dopt.get('--genefams')
	
	# event filters
	recordEvTypes = dopt.get('--evtype', 'DTS')
	minFreqReport = float(dopt.get('--minfreq', 0))
	
	# runtime params
	nbthreads = int(dopt.get('--threads', 1))
	verbose = ('-v' in dopt) or ('--verbose' in dopt)
	
	if dirTableOut:
		ltd = ['gene_event_matches']
		for td in ltd:
			ptd = os.path.join(dirTableOut, td)
			if not os.path.isdir(ptd):
				os.mkdir(ptd)
	
	if dirTableOut:
		matchesOutRad = os.path.basename(nfgenefamlist).rsplit('.', 1)[0] if nfgenefamlist else ''
		matchesOutDirRad = os.path.join(dirTableOut, 'gene_event_matches', matchesOutRad)
	else:
		matchesOutDirRad = None
	if matchingMethod=='deparecated'
		if loaddfamevents not in ['shelve', 'pickle']:
			raise ValueError, "deprecated matching engine; only works with pre-computed python objects loaded from pickle or shelve persistent storage, not from DB queries"
		print "deprecated matching engine; should prefer database query-based matching of lineage event profiles"
		# rely on loaded or just-computed python objects containing parsed events
			match_events(dfamevents, recordEvTypes, genefamlist, drefspeeventId2Tups, writeOutDirRad)
	else:
		# rely on database records of parsed events
		if loaddfamevents not in ['postgres', 'sqlite']: raise ValueError, "deprecated matching engine; only works with pre-computed python objects, not DB queries"
		if matchMethod=='matching_lineages_by_event':
			dbquery_matching_lineages_by_event(dbname, dbengine=loaddfamevents, genefamlist=genefamlist, \
										nsample=nrecsample, evtypes=recordEvTypes, \
										nfpickleMatchesOut=nfpickleMatchesOut, nfshelveMatchesOut=nfshelveMatchesOut, matchesOutDirRad=matchesOutDirRad, \
										nbthreads=nbthreads)
		elif matchMethod=='matching_lineage_event_profiles':
			dbquery_matching_lineage_event_profiles(dbname, dbengine=dbengine, genefamlist=genefamlist, \
			                            nsample=nrecsample, evtypes=recordEvTypes, \
                                        nfpickleMatchesOut=nfpickleMatchesOut, matchesOutDirRad=matchesOutDirRad, \
                                        nbthreads=nbthreads)
