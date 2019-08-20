#!/usr/bin/python
import tree2
import re

eventypes = 'DTSL'
outtaxlab = 'OUTGROUP'
deadlabnum = '-1'

realscinumpat = re.compile('[1-9]\.[0-9]{1,5}e-[0-9]{2}|0\.[0-9]{1,9}|0')

def cmpSegIds(x, y):
	"""cmp function for strings where abcABC is smaller than 123"""
	xnum = x[0].isdigit()
	ynum = y[0].isdigit()
	if xnum:
		# x = 123
		if ynum:
			# y = 123
			if x < y: return -1
			elif x == y: return 0
			elif x > y: return 1
		else:
			# y = abcABC
			return 1
	else:
		# x = abcABC
		if not ynum:
			# y = abcABC
			if x < y: return -1
			elif x == y: return 0
			elif x > y: return 1
		else:
			# y = 123
			# abcABC smaller than 123
			return -1
			
	
def _parseTERARecEvent(event, dnodefreq, dlevt, deadlab='-1'):
	"""utility fonction toparse just one event string and store it in the dictionaries provided in input $2 and $3"""
	print event
	evori, evtype, evdest1, evdest2, freq = event
	if evtype=='S':
		dlevt['S'].append((evori, freq))
		dnodefreq[evdest1] = dnodefreq.setdefault(evdest1, 0.0) + 1.0
		dnodefreq[evdest2] = dnodefreq.setdefault(evdest2, 0.0) + 1.0
	elif evtype=='SL':
		dlevt['S'].append((evori, freq))
		dlevt['L'].append((evdest1, freq))
		dnodefreq[evdest2] = dnodefreq.setdefault(evdest1, 0.0) + 1.0
	if evtype=='D':
		dlevt['D'].append((evori, freq))
		dnodefreq[evdest1] = dnodefreq.setdefault(evdest1, 0.0) + 1.0
	elif evtype=='DD':	
		pass
	elif evtype.startswith('T'):
		if evdest1==evori: evdon, evrec = (evdest1, evdest2)
		elif evdest2==evori: evdon, evrec = (evdest2, evdest1)
		if evtype.endswith('TD'):
			evrec = deadlab
		elif evtype.endswith('FD'):
			evdon = deadlab
		# register event(s)
		if evtype.startswith('TL'):
			if evdon != deadlab:
				# loss event in the donor species; ignore in the dead/outgroup
				dlevt['L'].append((evdon, freq))
		elif evtype=='TLTD':
			dlevt['L'].append((evdon, freq))
		# transfer event
		dlevt['T'].append((evdon, evrec, freq))
		# register gene occurence
		if evrec != deadlab:
			# gain in the recipient species; ignore in the dead/outgroup
			dnodefreq[evrec] = dnodefreq.setdefault(evrec, 0.0) + 1.0
		if evdon != deadlab:
			# 'gain' in the donor species = maintenance of the lineage; ignore in the dead/outgroup
			dnodefreq[evdon] = dnodefreq.setdefault(evdon, 0.0) + 1.0
	
def _parseTERARecLine(recline, sgsep='_'):
	segid, seventschsegids = recline.strip('\n').split(':', 1)
	if (sgsep in segid):
		# gene tree branch is a leaf: no children
		sevents = seventschsegids
		chsegids = []
	else:
		sevents, schsegids = seventschsegids.split(':')
		chsegids = schsegids.split(',')
	return (segid, chsegids, sevents)
	
class TERARecSegment(object):
	"""store the string of reconciliation events carried by a reconciled gene tree branch, as modelled in TERA output file format"""	
	def __init__(self, recline=None, sgsep='_', segid=None, forcefreq=None, **kw):
		self.segid = None
		self.chsegids = []
		self.sevents = ''
		if recline:
			parsedrecline = _parseTERARecLine(recline, sgsep='_')
			self.segid = parsedrecline[0]
			self.chsegids = parsedrecline[1]
			self.sevents = parsedrecline[2]
		elif segid:
			self.segid = segid
		else:
			raise ValueError, "missing arguments: 'recline' ($1 postional arg) or 'segid' (**kw arg)"
		self.levents = []
		self.children = [] # links to child branches
		#~ self.dlevt = {et:[] for et in eventypes}
		#~ self.dnodefreq = {}
		self.deadlab = kw.get('deadlab', '-1')
		if self.sevents:
			self._parseSegmentString(forcefreq=forcefreq)
	
	def __repr__(self):
		return "<TERARecSegment '%s': \"%s\">"%(self.segid, self.sevents)
	
#	def __repr__(self):
#		return "<%s: %s>"%(str(self).strip('<>'), self.sevents)
	
	def set_child_segments(self, children):
		for c in children:
			if not (c is None):
				assert c.segid in self.chsegids
				self.children.append(c)
		
	def _parseSegmentString(self, forcefreq=None):
		lsevents = self.sevents.split(';')
		for evtsup in lsevents:
			evt, sup = evtsup.split('@')
			freq = float(sup) if (not forcefreq) else float(forcefreq)
			evori, evtype, evdest1, evdest2 = (s.strip("'") for s in evt.split(','))
			self.levents.append((evori, evtype, evdest1, evdest2, freq))

class TERAReconciliation(object):
	"""store the whole reconciliation of a gene tree, extracted from a TERA output file"""
		
	def __init__(self, recfile, **kw):
		self.dsegments = {}
		self.devents = {}
		self.dlevt = {et:[] for et in eventypes}
		self.dnodefreq = {}
		self.sgsep = kw.get('sgsep', '_')
		self.deadlab = kw.get('deadlab', '-1')
		# parse the file, line per pile (each line a reconciliation segment corresponding to a reconciled gene tree branch)
		for line in recfile:
			rs = TERARecSegment(line, **kw)
			self.dsegments[rs.segid] = rs
		self.lsegids = self.dsegments.keys()
		# order segments following their numbering in input file, which should be ordered in a root-to-tip pre-order traversal
		self.lsegids.sort(reverse=True, cmp=lambda x,y: cmpSegIds(x, y)) # older segments have smaller ids, so reverse id order to get parent-to-child order 
		
		# build the tree of segments = the reconciled gene tree
		for segid, segment in self.dsegments.items():
			segment.set_child_segments([self.dsegments.get(cid, TERARecSegment(segid=cid)) for cid in segment.chsegids])
		
		# assemble event set from segments
		if kw.get('noDeadStories'):
			self.shuntEventsToFromDead(**kw)
		else:
			for segid in self.lsegids:
				segment = self.dsegments[segid] # segments should be in a root-to-tip pre-order traversal
				for event in segment.levents:
					_parseTERARecEvent(event, self.dnodefreq, self.dlevt)
	
	def __getitem__(self, segid):
		"""get and [] methods return reconciliation segment with given segment id"""
		return self.dsegments[segid]
	
	def shuntEventsToFromDead(self, verbose=False, **kw):
		"""assemble event set from segments but ommit the string of events that come and go from/to the Dead/Outgroup branch (e.g. for clearer representation purposes)
		
		reset the event disctionary for the reconciliation before proceeeding.
		Will simplify the scenario by shunting the transfer events to/from the dead when the return from the dead follows closely the depart into the dead.
		'exploredepth sets the depth of children segments that will be explored for a return from the dead event (*)
		"""
		self.devents = {}
		self.dlevt = {et:[] for et in eventypes}
		self.dnodefreq = {}
		damongdead = {}
		for segid in self.lsegids:
			print segid
			segment = self.dsegments[segid]
			for n, event in enumerate(segment.levents):
				# include the first event (excluded from final record)
				# as it may provide context for the following events of this segment
				# i.e. the 1st event may be 'to the dead' and the following be the return 'from the dead'
				evori, evtype, evdest1, evdest2, freq = event
				if evtype.endswith('TD'):
					evoritd, evtypetd, evdest1td, evdest2td, freqtd = event
					# event goes 'among the Dead' / to the species tree Outgroup branch
					# store the origin of the lineage among the dead
					# record the event type without the loss (L) or from/to the Dead (TD/FD) qualifiers (irrelevant to the simplified scenario)
					damongdead[segid] = (evori, evtype[0])
				elif n > 0:
					if evtype.endswith('FD'):
						# 'endpoint' of the journey among the dead for this lineage
						# recover origins of the event before it went among the Dead
						evoritd, evtypetd = damongdead[segid]
						if evdest1==self.deadlab:
							# first 'recipient' is the dead; the the second is the 'live' recipient
							evdest1fd = evoritd
							evdest2fd = evdest2
						else:
							# second 'recipient' is the dead; the the first is the 'live' recipient
							evdest2fd = evoritd
							evdest1fd = evdest1
						# creat a new synthetic event that connects origin and endpoint among the living
						# make it the type of the original event
						eventfd = evoritd, evtypetd, evdest1fd, evdest2fd, freq
						_parseTERARecEvent(eventfd, self.dnodefreq, self.dlevt, deadlab=self.deadlab)
					elif evtype=='DD':
						# duplication among the Dead
						# not interested in recording (representing graphically) that
						pass
					else:
						# bona fide event, register it 
						# always skip the first event as a repeat from the last event of branch/segment above
						_parseTERARecEvent(event, self.dnodefreq, self.dlevt, deadlab=self.deadlab)
			else:
				if (not self.sgsep in segment.segid):
					# end of the segment and not a leaf: split event
					for c, evdest in enumerate((evdest1, evdest2)):
						# check species identity of children lineages
						if evdest==self.deadlab:
							# a new lineage emerges among the Dead
							# will try and link following events where the lineage will return into the Live branches
							if verbose: print evdest, c, segment, segment.children
							csid = segment.children[c].segid
							# store the origin of the lineage before it went among the Dead
							try:
								damongdead[csid] = damongdead[segid] 
							except KeyError, e:
								raise KeyError, "no record of origin for segment %s; the origin of this lineage among the Dead should already be known for this segment from a prior event in the same segment or from a parent segment"%(str(e))

def parseTERARec(frec, forcefreq=None, deadlab=outtaxlab, sgsep='_', noDeadStories=True, **kw):
	"""generator function that only parses the information related to the species tree
	
	NB: does not account for the change  of state (number of gene copies) over a species tree branch.
	For simplicity of representation, events are considered to happen at the begin (epper end) of the species tree branch.
	There is no implicit propagation of the gene copy number down the species tree; instead events of Speciations (S), 
	duplications (D) and incoming transfers (T) lead to an increment of the copy number in the recipient species,
	while losses (L) do not lead to decrement the count of gene copies (just no increment).
	"""
	dl = deadlabnum if noDeadStories else outtaxlab
	rec = TERAReconciliation(frec, sgsep=sgsep, forcefreq=forcefreq, noDeadStories=noDeadStories, deadlab=dl, **kw)
	# only support single-reconciliation input files at the moment,
	# but return a sequence for consistency with analog functions
	return [(rec.dnodefreq, rec.dlevt)]	

def parseMowgliRec(frec):
	'''generator function that only parses the information related to the species tree
	
	take as input files containing (possibly single or multiple) recombinations, 
	separated by a line of dashes '--------' (8 or more of the character '-')
	'''
	def parseMowgliRecStreelines(frec):
		'''actual parser'''
		lsegments = []
		for line in frec:
			if line.startswith('--------') and lsegments:
			# delineate reconciliations by their '----' start line
				yield lsegments
				lsegments = []
			 
			if line.startswith('\t'):
				donrec, dates = line.strip('\t\n').split(' ')
				rec, don = donrec.strip('()').split(',')
				begend = [float(d) for d in reascinumpat.findall(dates)]
				beg = begend[0]
				end = begend[1] # ignore the possible 3rd member, always trailing after a colon and a repetion of the 1st and 2nd (when a duplication even?)
				if beg == end:
					# ignore this case as not sure what this [x,x:x] notation is about
					continue
				lsegments.append((rec, don, beg, end))
		else:
			yield lsegments
	
	# interpret the information in terms of events
	for lsegments in parseMowgliRecStreelines(nfrec):
		dnodefreq = {}
		dlevt = {et:[] for et in eventypes}
		for seg in lsegments:
			rec, don, beg, end = seg
			# annotate gene occurence/frequency
			dnodefreq[rec] = dnodefreq.setdefault(rec, 0.0) + 1.0
			# determine the qgenerating event
			if not reftree[rec].is_child(reftree[don]):
				# transfer event
				dlevt['T'].append((don, rec, 1.0))
		yield (dnodefreq, dlevt)

def parseTERARecFile(nfrec, recformat='mowgli', **kw):
	'''wrapper to parse reconciliations from ecceTERA, either in 'mowgli' (.mr) or 'tera' (.txt) format'''
	with open(nfrec, 'r') as frec:
		if recformat=='mowgli':
			return parseMowgliRec(frec, **kw)
		elif recformat=='tera':
			return parseTERARec(frec, **kw)
		else:
			raise ValueError, "wrong reconciliation format specification"
