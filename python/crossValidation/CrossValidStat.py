__all__ = ['CrossValidStatAnalysis','GridJobFilter','PerfHolder',
           'fixReferenceBenchmarkCollection']

from RingerCore import EnumStringification, get_attributes, checkForUnusedVars, \
    calcSP, save, load, Logger, LoggingLevel, expandFolders, traverse, \
    retrieve_kw, NotSet, csvStr2List, select, progressbar, getFilters, \
    apply_sort, LoggerStreamable, appendToFileName, ensureExtension, \
    measureLoopTime, checkExtension 

from TuningTools.TuningJob import TunedDiscrArchieve, ReferenceBenchmark, ReferenceBenchmarkCollection
from TuningTools import PreProc
from TuningTools.ReadData import Dataset
from pprint import pprint
from cPickle import UnpicklingError
from time import time
import numpy as np
import os
import sys

def percentile( data, score ):
  """
  val = percentile( data, score )
  Retrieve the data percentile at score
  """
  size = len(data)
  if size:
    pos = score*size
    if pos % 10 or pos == size:
      return data[pos]
    else:
      return data[pos] + data[pos+1]
  else: return None

def fixReferenceBenchmarkCollection( refCol, nBins, nTuned, level = None ):
  """
    Make sure that input data is a ReferenceBenchmarkCollection( ReferenceBenchmarkCollection([...]) ) 
    with dimensions [nBins][nTuned] or transform it to that format if it is possible.
  """
  from copy import deepcopy
  tree_types = (ReferenceBenchmarkCollection, list, tuple )
  try: 
    # Retrieve collection maximum depth
    _, _, _, _, depth = traverse(refCol, tree_types = tree_types).next()
  except GeneratorExit:
    depth = 0
  if depth == 0:
    refCol = ReferenceBenchmarkCollection( [deepcopy(refCol) for _ in range(nTuned)] )
    refCol = ReferenceBenchmarkCollection( [deepcopy(refCol) for _ in range(nBins if nBins is not None else 1) ] )
  elif depth == 1:
    lRefCol = len(refCol)
    if lRefCol == 1:
      refCol = ReferenceBenchmarkCollection( [ deepcopy( refCol[0] ) for _ in range(nTuned ) ] )
      refCol = ReferenceBenchmarkCollection( [ deepcopy( refCol    ) for _ in range(nBins if nBins is not None else 1 ) ] )
    elif lRefCol == nTuned:
      refCol = ReferenceBenchmarkCollection( refCol )
      refCol = ReferenceBenchmarkCollection( [ deepcopy( refCol ) for _ in range(nBins if nBins is not None else 1 ) ] )
    elif lRefCol == nBins:
      refColBase = ReferenceBenchmarkCollection( [ deepcopy( ref ) for ref in refCol for _ in range(nTuned) ] )
      refCol = ReferenceBenchmarkCollection([])
      for i in range(nBins): refCol.append( ReferenceBenchmarkCollection( refColBase[i*nTuned:(i+1)*nTuned] ) )
    else:
      self._logger.fatal(("The ReferenceBenchmark collection size does not " \
          "match either the number of tuned operating points or the number of bins."), ValueError)
  elif depth == 2:
    pass
  else:
    self._logger.fatal("Collection dimension is greater than 2!", ValueError)
  from RingerCore import inspect_list_attrs
  refCol = inspect_list_attrs(refCol, 2,                               tree_types = tree_types,                                level = level,    )
  refCol = inspect_list_attrs(refCol, 1, ReferenceBenchmarkCollection, tree_types = tree_types, dim = nTuned, name = "nTuned",                   )
  refCol = inspect_list_attrs(refCol, 0, ReferenceBenchmarkCollection, tree_types = tree_types, dim = nBins,  name = "nBins",  deepcopy = True   )
  return refCol

class JobFilter( object ):
  def __call__(self, paths):
    return []

class GridJobFilter( JobFilter ):
  """
  Filter grid job files returning each unique job id.
  """

  import re
  pat = re.compile(r'.*user.[a-zA-Z0-9]+.(?P<jobID>[0-9]+)\..*$')
  #pat = re.compile(r'user.(?P<user>[A-z0-9]*).(?P<jobID>[0-9]+).*\.tgz')

  def __call__(self, paths):
    """
      Returns the unique jobIDs
    """
    jobIDs = sorted(list(set([self.pat.match(f).group('jobID') for f in paths if self.pat.match(f) is not None])))
    return jobIDs

class CrossValidStatAnalysis( Logger ):

  def __init__(self, paths, **kw):
    """
    Usage: 
    # Create object
    cvStatAna = CrossValidStatAnalysis( 
                                        paths 
                                        [,binFilters=None]
                                        [,logger[,level=INFO]]
                                      )
    # Fill the information and save output file with cross-validation summary
    cvStatAna( refBenchMark, **args...)
    # Call other methods if necessary.
    """
    Logger.__init__(self, kw)    
    self._binFilters            = retrieve_kw(kw, 'binFilters',            None         )
    self._binFilterJobIdxs      = retrieve_kw(kw, 'binFilterIdxs',         None         )
    self._useTstEfficiencyAsRef = retrieve_kw(kw, 'useTstEfficiencyAsRef', False        )
    checkForUnusedVars(kw, self._logger.warning)
    # Check if path is a file with the paths
    self._paths = csvStr2List( paths )
    # Recursively expand all folders in the given paths so that we have all
    # files lists:
    self._paths = expandFolders( self._paths )
    self._nBins = 1
    if self._binFilters:
      self._binFilters = getFilters( self._binFilters, self._paths, 
                                     idxs = self._binFilterJobIdxs, 
                                     printf = self._logger.info )
      if self._binFilters:
        self._paths = select( self._paths, self._binFilters ) 
        self._nBins = len(self._binFilters)
    if self._nBins is 1:
      self._paths = [self._paths]
    #if self._level <= LoggingLevel.VERBOSE:
    #  for binFilt in self._binFilters if self._binFilters is not None else [None]:
    #    self._logger.verbose("The stored files are (binFilter=%s):", binFilt)
    #    for path in self._paths:
    #      self._logger.verbose("%s", path)
    self._nFiles = [len(l) for l in self._paths]
    self._logger.info("A total of %r files were found.", self._nFiles )
    #alloc variables to the TFile and bool flag
    self._sg = None
    self._sgdirs=list()

  def __addPerformance( self, tunedDiscrInfo, path, ref, benchmarkRef,
                              neuron, sort, init, 
                              etBinIdx, etaBinIdx, 
                              tunedDiscr, trainEvolution,
                              tarMember ):
    refName = ref.name
    self._logger.verbose("Adding performance for <ref:%s, config:%r,sort:%s,init:%s>", refName, neuron, sort, init)
    # We need to make sure that the key will be available on the dict if it
    # wasn't yet there
    if not refName in tunedDiscrInfo:
      tunedDiscrInfo[refName] = { 'benchmark' : ref,
                                  'tuningBenchmark' : benchmarkRef }
      #ref.level = self.level
      #tunedDiscr['benchmark'].level = self.level
    if not neuron in tunedDiscrInfo[refName]:
      tunedDiscrInfo[refName][neuron] = dict()
    if not sort in tunedDiscrInfo[refName][neuron]:
      tunedDiscrInfo[refName][neuron][sort] = { 'headerInfo' : [], 
                                                'initPerfTstInfo' : [], 
                                                'initPerfOpInfo' : [] }
    # The performance holder, which also contains the discriminator
    perfHolder = PerfHolder( tunedDiscr, trainEvolution, level = self.level )
    # Retrieve operating points:
    (spTst, detTst, faTst, cutTst, idxTst) = perfHolder.getOperatingBenchmarks(ref)
    (spOp, detOp, faOp, cutOp, idxOp)      = perfHolder.getOperatingBenchmarks(ref, ds = Dataset.Operation)
    headerInfo = { 
                   'discriminator': tunedDiscr['discriminator'],
                   'neuron':        neuron,
                   'sort':          sort,
                   'init':          init,
                   'path':          path,
                   'tarMember':     tarMember
                 }
    # Create performance holders:
    iInfoTst = { 'sp' : spTst, 'det' : detTst, 'fa' : faTst, 'cut' : cutTst, 'idx' : idxTst, }
    iInfoOp  = { 'sp' : spOp,  'det' : detOp,  'fa' : faOp,  'cut' : cutOp,  'idx' : idxOp,  }
    #if self._level <= LoggingLevel.VERBOSE:
    #  self._logger.verbose("Retrieved file '%s' configuration for benchmark '%s' as follows:", 
    #                     os.path.basename(path),
    #                     ref )
    #  pprint({'headerInfo' : headerInfo, 'initPerfTstInfo' : iInfoTst, 'initPerfOpInfo' : iInfoOp })
    # Append information to our dictionary:
    tunedDiscrInfo[refName][neuron][sort]['headerInfo'].append( headerInfo )
    tunedDiscrInfo[refName][neuron][sort]['initPerfTstInfo'].append( iInfoTst )
    tunedDiscrInfo[refName][neuron][sort]['initPerfOpInfo'].append( iInfoOp )

  def __addMonPerformance( self, discr, trainEvolution, refname, neuron, sort, init):
    # Create perf holder
    perfHolder = PerfHolder(discr, trainEvolution, level = self.level)
    # Adding graphs into monitoring file
    dirname = ('%s/config_%s/sort_%s/init_%d') % (refname,str(neuron).zfill(3),str(sort).zfill(3),init)
    if not dirname in self._sgdirs:
      self._sg.mkdir(dirname)
      self._sgdirs.append(dirname)
    self._sg.cd(dirname)

    graphNames = [ 'mse_trn', 'mse_val', 'mse_tst',
         'bestsp_point_sp_val', 'bestsp_point_det_val', 'bestsp_point_fa_val',
         'bestsp_point_sp_tst', 'bestsp_point_det_tst', 'bestsp_point_fa_tst',
         'det_point_sp_val'   , 'det_point_det_val'   , 'det_point_fa_val'   , # det_point_det_val is det_fitted
         'det_point_sp_tst'   , 'det_point_det_tst'   , 'det_point_fa_tst'   , 
         'fa_point_sp_val'    , 'fa_point_det_val'    , 'fa_point_fa_val'    , # fa_point_fa_val is fa_fitted
         'fa_point_sp_tst'    , 'fa_point_det_tst'    , 'fa_point_fa_tst'    ,  
         'roc_tst'            , 'roc_op',]

    # Attach graphs
    for gname in graphNames:
      g = perfHolder.getGraph(gname); g.SetName(gname)
      g.Write()
      #self._sg.attach(g, holdObj = False)
      del g
 
    # Attach stops
    from RingerCore.util import createRootParameter
    createRootParameter("double", "mse_stop", perfHolder.epoch_mse_stop ).Write()
    createRootParameter("double", "sp_stop",  perfHolder.epoch_sp_stop  ).Write()
    createRootParameter("double", "det_stop", perfHolder.epoch_det_stop ).Write()
    createRootParameter("double", "fa_stop",  perfHolder.epoch_fa_stop  ).Write()

  def __call__(self, **kw ):
    """
    Hook for loop method.
    """
    self.loop( **kw )

  def loop(self, **kw ):
    """
    Optional args:
      * refBenchmarkCol: a list of reference benchmark objects which will be used
        as the operation points.
      * toMatlab [True]: also create a matlab file from the obtained tuned discriminators
      * outputName ['crossValStat']: the output file name.
      * test [False]: Run only for a small number of files
      * doMonitoring [True]: Whether to do tuning monitoring file or not.
      * doCompress [True]: Whether to compress output files or not.
    """
    import gc
    refBenchmarkColKW = 'refBenchmarkCol'
    if not 'refBenchmarkCol' in kw and 'refBenchmarkList' in kw:
      refBenchmarkColKW = 'refBenchmarkList'
    refBenchmarkCol = retrieve_kw( kw, refBenchmarkColKW,    None           )
    toMatlab        = retrieve_kw( kw, 'toMatlab',           True           )
    outputName      = retrieve_kw( kw, 'outputName',         'crossValStat' )
    mFName          = retrieve_kw( kw, 'monitoringFileName', None           )
    test            = retrieve_kw( kw, 'test',               False          )
    doMonitoring    = retrieve_kw( kw, 'doMonitoring',       True           )
    compress        = retrieve_kw( kw, 'doCompress',         True           )
    self._eps       = retrieve_kw( kw, 'eps',                NotSet         )
    checkForUnusedVars( kw,            self._logger.warning )
    tuningBenchmarks = ReferenceBenchmarkCollection([])

    if not self._paths:
      self._logger.warning("Attempted to run without any file!")
      return

    pbinIdxList=[]
    isMergedList=[]
    for binIdx, binPath in enumerate(progressbar(self._paths, 
                                                 len(self._paths), 'Retrieving tuned operation points: ', 30, True,
                                                 logger = self._logger)):
      
      
      tdArchieve = TunedDiscrArchieve.load(binPath[0], 
                                           useGenerator = True, 
                                           ignore_zeros = False, 
                                           skipBenchmark = False).next()
      isMerged = False
      if checkExtension( binPath[0], 'tgz|tar.gz'):
        from subprocess import Popen, PIPE
        from RingerCore import is_tool
        tar_cmd = 'gtar' if is_tool('gtar') else 'tar'
        tarlist_ps = Popen((tar_cmd, '-tzif', binPath[0],), 
                           stdout = PIPE, bufsize = 1)
        start = time()
        for idx, line in enumerate( iter(tarlist_ps.stdout.readline, b'') ):
          if idx > 0:
            isMerged = True
            tarlist_ps.kill()
        self._logger.debug("Detecting merged file took %.2fs", time() - start)
      if isMerged:
        self._logger.info("These bin files are merged.")
      else:
        self._logger.info("These bin files are non-merged.")
      isMergedList.append( isMerged )
      tunedArchieveDict = tdArchieve.getTunedInfo( tdArchieve.neuronBounds[0],
                                                   tdArchieve.sortBounds[0],
                                                   tdArchieve.initBounds[0] )
      tunedDiscrList = tunedArchieveDict['tunedDiscr']
      nTuned         = len(refBenchmarkCol[0])
      try:
        if nTuned  - len(tunedDiscrList):
          self._logger.fatal("For now, all bins must have the same number of tuned (%d) benchmarks (%d).",\
              len(tunedDiscrList),nTuned)
      except NameError:
        pass
      nTuned            = len(tunedDiscrList)
      binTuningBench    = ReferenceBenchmarkCollection( 
                             [tunedDiscrDict['benchmark'] for tunedDiscrDict in tunedDiscrList]
                          )

      # Change output level from the tuning benchmarks
      for bench in binTuningBench: bench.level = self.level
      tuningBenchmarks.append( binTuningBench )
      etBinIdx          = tdArchieve.etBinIdx
      etaBinIdx         = tdArchieve.etaBinIdx

      self._logger.debug("Found a total of %d tuned operation points on bin (et:%d,eta:%d). They are: ", 
          nTuned, etBinIdx, etaBinIdx)

      for bench in binTuningBench:
        self._logger.debug("%s", bench)
    # end of (tuning benchmarks retrieval)

    # Make sure everything is ok with the reference benchmark collection (do not check for nBins):
    refBenchmarkCol = fixReferenceBenchmarkCollection(refBenchmarkCol, nBins = None, 
                                                      nTuned = nTuned, level = self.level )

    # FIXME Moved due to crash when loading latter.
    from ROOT import TFile, gROOT, kTRUE
    gROOT.SetBatch(kTRUE)
   
    # Match between benchmarks from pref and files in path
    # FIXME This shouldn't be needed anymore as this is done by code inserted more ahead
    #if len(refBenchmarkCol) != 1 and refBenchmarkCol[0][0] is not None:
    #  tRefBenchmarkList=[]
    #  for etBinIdx, etaBinIdx in pbinIdxList:
    #    for idx, refBenchmark in enumerate(refBenchmarkCol):
    #      if refBenchmark[0].checkEtBinIdx(etBinIdx) and refBenchmark[0].checkEtaBinIdx(etaBinIdx):
    #        self._logger.info('BenchmarkCollection found in perf file with operation on bin (et:%d,eta:%d). They are:', etBinIdx,etaBinIdx)
    #        for cref in refBenchmark:  self._logger.debug('%s',cref)
    #        tRefBenchmarkList.append(refBenchmarkCol.pop(idx))
    #  refBenchmarkCol=tRefBenchmarkList

    self._logger.info("Started analysing cross-validation statistics...")
    self._summaryInfo = [ dict() for i in range(self._nBins) ]
    self._summaryPPInfo = [ dict() for i in range(self._nBins) ]

    # Loop over the files
    from itertools import product
    # FIXME If job fails, it will not erase expanded files at temporary folder
    for binIdx, binPath in enumerate(self._paths):
      if self._binFilters:
        self._logger.info("Running bin filter '%s'...",self._binFilters[binIdx])
      tunedDiscrInfo = dict()
      cSummaryInfo = self._summaryInfo[binIdx]
      cSummaryPPInfo = self._summaryPPInfo[binIdx]

      # Retrieve binning information
      # FIXME: We shouldn't need to read file three times for retrieving basic information...
      tdArchieve = TunedDiscrArchieve.load(binPath[0], 
                                           useGenerator = True, 
                                           ignore_zeros = False).next()
      if tdArchieve.etaBinIdx != -1:
        self._logger.info("File eta bin index (%d) limits are: %r", 
                           tdArchieve.etaBinIdx, 
                           tdArchieve.etaBin, )
      if tdArchieve.etBinIdx != -1:
        self._logger.info("File Et bin index (%d) limits are: %r", 
                           tdArchieve.etBinIdx, 
                           tdArchieve.etBin, )

      self._logger.info("Retrieving summary...")
      # Search for the reference binning information that is the same from the
      # benchmark
      # FIXME: Can I be sure that this will work if user enter None as benchmark?
      rBenchIdx = binIdx
      if tdArchieve.etaBinIdx != -1 and tdArchieve.etaBinIdx != -1:
        for cBenchIdx, rBenchmarkList in enumerate(refBenchmarkCol):
          for rBenchmark in rBenchmarkList:
            if rBenchmark is not None: break
          if rBenchmark is None: break
          if rBenchmark.checkEtaBinIdx(tdArchieve.etaBinIdx) and \
             rBenchmark.checkEtBinIdx(tdArchieve.etBinIdx):
            rBenchIdx = cBenchIdx
        # Retrieved rBenchIdx
      # end of if
      # Retrieve the benchmark list referent to this binning
      cRefBenchmarkList = refBenchmarkCol[rBenchIdx]

      # Find the tuned benchmark that matches with this reference
      tBenchIdx = binIdx
      if tdArchieve.etaBinIdx != -1 and tdArchieve.etBinIdx != -1:
        for cBenchIdx, tBenchmarkList in enumerate(tuningBenchmarks):
          tBenchmark = tBenchmarkList[0]
          if tBenchmark.checkEtaBinIdx(tdArchieve.etaBinIdx) and \
              tBenchmark.checkEtBinIdx(tdArchieve.etBinIdx) :
            tBenchIdx = cBenchIdx
        # Retrieved tBenchIdx
      # end of if
      # Retrieve the tuning benchmark list referent to this binning
      tBenchmarkList = tuningBenchmarks[tBenchIdx]
      isMerged = isMergedList[tBenchIdx]

      # Check if user requested for using the tuning benchmark info by setting
      # any reference value to None
      if None in cRefBenchmarkList:
        # Check if we have only one reference and it is set to None. 
        # In case the user tuned for the SP or MSE, than replace the tuning benchmark to be set 
        # to SP, Pd and Pf
        if len(cRefBenchmarkList) == 1 and  len(tBenchmarkList) == 1 and \
            tBenchmarkList[0].reference in (ReferenceBenchmark.SP, ReferenceBenchmark.MSE):
          self._logger.info("Found a unique tuned MSE or SP reference. Expanding it to SP/Pd/Pf operation points.")
          from copy import deepcopy
          copyRefList = ReferenceBenchmarkCollection( [deepcopy(ref) for ref in cRefBenchmarkList] )
          # Work the benchmarks to be a list with multiple references, using the Pd, Pf and the MaxSP:
          if refBenchmark.signalEfficiency is not None:
            opRefs = [ReferenceBenchmark.SP, ReferenceBenchmark.Pd, ReferenceBenchmark.Pf]
            for ref, copyRef in zip(opRefs, copyRefList):
              copyRef.reference = ref
              if ref is ReferenceBenchmark.SP:
                copyRef.name = copyRef.name.replace("Tuning_", "OperationPoint_") \
                                           .replace("_" + ReferenceBenchmark.tostring(cRefBenchmarkList[0].reference),
                                                    "_" + ReferenceBenchmark.tostring(ref))
          else:
            if copyRefList.reference is ReferenceBenchmark.MSE:
              copyRefList[0].name = "OperationPoint_" + copyRefList[0].split("_")[1] + "_SP"
          # Replace the reference benchmark by the copied list we created:
          cRefBenchmarkList = copyRefList
        # Replace the requested references using the tuning benchmarks:
        for idx, refBenchmark in enumerate(cRefBenchmarkList):
          if refBenchmark is None:
            cRefBenchmarkList[idx] = tBenchmarkList[idx]
            cRefBenchmarkList[idx].name = cRefBenchmarkList[idx].name.replace('Tuning_', 'OperatingPoint_')
      # finished checking

      self._logger.info('Using references: %r.', [(ReferenceBenchmark.tostring(ref.reference),ref.refVal) for ref in cRefBenchmarkList])

      # What is the output name we should give for the written files?
      if self._binFilters:
        cOutputName = appendToFileName( outputName, self._binFilters[binIdx] )
      else:
        cOutputName = outputName
   
      # Finally, we start reading this bin files:
      nBreaks = 0
      cMember = 0
      for cFile, path in progressbar( enumerate(binPath),
                                      self._nFiles[binIdx], 'Reading files: ', 60, 1, True,
                                      logger = self._logger ):
        flagBreak = False
        start = time()
        self._logger.info("Reading file '%s'", path )
        # And open them as Tuned Discriminators:
        try:
          # Try to retrieve as a collection:
          for tdArchieve in measureLoopTime( TunedDiscrArchieve.load(path, useGenerator = True, 
                                                                     extractAll = True if isMerged else False, 
                                                                     eraseTmpTarMembers = False if isMerged else True,
                                                                    ), 
                                             prefix_end = "read all file '%s' members." % path,
                                             prefix = "Reading member",
                                             logger = self._logger ):
            cMember += 1
            if flagBreak: break
            self._logger.info("Retrieving information from %s.", str(tdArchieve))

            # Calculate the size of the list
            barsize = len(tdArchieve.neuronBounds.list()) * len(tdArchieve.sortBounds.list()) * \
                      len(tdArchieve.initBounds.list())

            for neuron, sort, init in progressbar( product( tdArchieve.neuronBounds(), 
                                                            tdArchieve.sortBounds(), 
                                                            tdArchieve.initBounds() ),\
                                                            barsize, 'Reading configurations: ', 60, 1, False,
                                                   logger = self._logger):
              tunedDict      = tdArchieve.getTunedInfo( neuron, sort, init )
              tunedDiscr     = tunedDict['tunedDiscr']
              tunedPPChain   = tunedDict['tunedPP']
              trainEvolution = tunedDict['tuningInfo']
              if not len(tunedDiscr) == nTuned:
                self._logger.fatal("File %s contains different number of tunings in the collection.", ValueError)
              # We loop on each reference benchmark we have.
              from itertools import izip, count
              for idx, refBenchmark, tuningRefBenchmark in izip(count(), cRefBenchmarkList, tBenchmarkList):
                if   neuron == tdArchieve.neuronBounds.lowerBound() and \
                     sort == tdArchieve.sortBounds.lowerBound() and \
                     init == tdArchieve.initBounds.lowerBound() and \
                     idx == 0:
                  # Check if everything is ok in the binning:
                  if not refBenchmark.checkEtaBinIdx(tdArchieve.etaBinIdx):
                    if refBenchmark.etaBinIdx is None:
                      self._logger.warning("TunedDiscrArchieve does not contain eta binning information!")
                    else:
                      self._logger.error("File (%d) eta binning information does not match with benchmark (%r)!", 
                          tdArchieve.etaBinIdx,
                          refBenchmark.etaBinIdx)
                  if not refBenchmark.checkEtBinIdx(tdArchieve.etBinIdx):
                    if refBenchmark.etaBinIdx is None:
                      self._logger.warning("TunedDiscrArchieve does not contain Et binning information!")
                    else:
                      self._logger.error("File (%d) Et binning information does not match with benchmark (%r)!", 
                          tdArchieve.etBinIdx,
                          refBenchmark.etBinIdx)
                # We always use the first tuned discriminator if we have more
                # than one benchmark and only one tuning
                if type(tunedDiscr) in (list, tuple,):
                  # fastnet core version
                  discr = tunedDiscr[refBenchmark.reference]
                else:
                  # exmachina core version
                  discr = tunedDiscr
                # Retrieve the pre-processing information:
                self.__addPPChain( cSummaryPPInfo,
                                   tunedPPChain, 
                                   sort )                    
                # And the tuning information:
                self.__addPerformance( tunedDiscrInfo = tunedDiscrInfo,
                                       path = tdArchieve.filePath, ref = refBenchmark, 
                                       benchmarkRef = tuningRefBenchmark,
                                       neuron = neuron, sort = sort, init = init,
                                       etBinIdx = tdArchieve.etBinIdx, etaBinIdx = tdArchieve.etaBinIdx,
                                       tunedDiscr = discr, trainEvolution = trainEvolution,
                                       tarMember = tdArchieve.tarMember ) 
                # Add bin information to reference benchmark
              # end of references
            # end of configurations
            if test and (cMember - 1) == 3:
              break
          # end of (tdArchieve collection)
        except (UnpicklingError, ValueError, EOFError), e:
          import traceback
          # Couldn't read it as both a common file or a collection:
          self._logger.warning("Ignoring file '%s'. Reason:\n%s", path, traceback.format_exc())
        # end of (try)
        if test and (cMember - 1) == 3:
          break
        # Go! Garbage
        gc.collect()
        elapsed = (time() - start)
        self._logger.debug('Total time is: %.2fs', elapsed)
      # Finished all files in this bin
   
      # Print information retrieved:
      if self._level <= LoggingLevel.VERBOSE:
        for refBenchmark in cRefBenchmarkList:
          refName = refBenchmark.name
          self._logger.verbose("Retrieved %d discriminator configurations for benchmark '%s':", 
              len(tunedDiscrInfo[refName]) - 1, 
              refBenchmark)
          for nKey, nDict in tunedDiscrInfo[refName].iteritems():
            if nKey in ('benchmark', 'tuningBenchmark'): continue
            self._logger.verbose("Retrieved %d sorts for configuration '%r'", len(nDict), nKey)
            for sKey, sDict in nDict.iteritems():
              self._logger.verbose("Retrieved %d inits for sort '%d'", len(sDict['headerInfo']), sKey)
            # got number of inits
          # got number of sorts
        # got number of configurations
      # finished all references

      self._logger.info("Creating summary...")

      # Create summary info object
      iPathHolder = dict()
      extraInfoHolder = dict()
      for refKey, refValue in tunedDiscrInfo.iteritems(): # Loop over operations
        refBenchmark = refValue['benchmark']
        # Create a new dictionary and append bind it to summary info
        refDict = { 'rawBenchmark' : refBenchmark.toRawObj(),
                    'rawTuningBenchmark' : refValue['tuningBenchmark'].toRawObj() }
        refDict['rawBenchmark']['eps'] = refBenchmark.getEps( self._eps )
        cSummaryInfo[refKey] = refDict
        for nKey, nValue in refValue.iteritems(): # Loop over neurons
          if nKey in ('benchmark', 'tuningBenchmark',):
            continue
          nDict = dict()
          refDict['config_' + str(nKey).zfill(3)] = nDict

          for sKey, sValue in nValue.iteritems(): # Loop over sorts
            sDict = dict()
            nDict['sort_' + str(sKey).zfill(3)] = sDict
            self._logger.debug("%s: Retrieving test outermost init performance for keys: config_%s, sort_%s",
                refBenchmark, nKey, sKey )
            # Retrieve information from outermost initializations:
            ( sDict['summaryInfoTst'], \
              sDict['infoTstBest'], sDict['infoTstWorst']) = self.__outermostPerf( 
                                                                                   sValue['headerInfo'],
                                                                                   sValue['initPerfTstInfo'], 
                                                                                   refBenchmark,
                                                                                 )
            self._logger.debug("%s: Retrieving operation outermost init performance for keys: config_%s, sort_%s",
                refBenchmark,  nKey, sKey )
            ( sDict['summaryInfoOp'], \
              sDict['infoOpBest'], sDict['infoOpWorst'])   = self.__outermostPerf( 
                                                                                   sValue['headerInfo'],
                                                                                   sValue['initPerfOpInfo'], 
                                                                                   refBenchmark, 
                                                                                 )
            wantedKeys = ['infoOpBest', 'infoOpWorst', 'infoTstBest', 'infoTstWorst']
            for key in wantedKeys:
              kDict = sDict[key]
              iPathKey = kDict['path']
              value = (kDict['neuron'], kDict['sort'], kDict['init'], refBenchmark.reference, refBenchmark.name,)
              extraValue = kDict['tarMember']
              if iPathKey in iPathHolder:
                if not(value in iPathHolder[iPathKey]):
                  iPathHolder[iPathKey].append( value )
                  extraInfoHolder[iPathKey].append( extraValue )
              else:
                iPathHolder[iPathKey] = [value]
                extraInfoHolder[iPathKey] = [extraValue]
          ## Loop over sorts
          # Retrieve information from outermost sorts:
          keyVec = [ key for key, sDict in nDict.iteritems() ]
          self._logger.verbose("config_%s unsorted order information: %r", nKey, keyVec )
          sortingIdxs = np.argsort( keyVec )
          sortedKeys  = apply_sort( keyVec, sortingIdxs )
          self._logger.debug("config_%s sorted order information: %r", nKey, sortedKeys )
          allBestTstSortInfo   = apply_sort( 
                [ sDict['infoTstBest' ] for key, sDict in nDict.iteritems() ]
              , sortingIdxs )
          allBestOpSortInfo    = apply_sort( 
                [ sDict['infoOpBest'  ] for key, sDict in nDict.iteritems() ]
              , sortingIdxs )
          self._logger.debug("%s: Retrieving test outermost sort performance for keys: config_%s",
              refBenchmark,  nKey )
          ( nDict['summaryInfoTst'], \
            nDict['infoTstBest'], nDict['infoTstWorst']) = self.__outermostPerf( 
                                                                                 allBestTstSortInfo,
                                                                                 allBestTstSortInfo, 
                                                                                 refBenchmark, 
                                                                               )
          self._logger.debug("%s: Retrieving operation outermost sort performance for keys: config_%s",
              refBenchmark,  nKey )
          ( nDict['summaryInfoOp'], \
            nDict['infoOpBest'], nDict['infoOpWorst'])   = self.__outermostPerf( 
                                                                                 allBestOpSortInfo,
                                                                                 allBestOpSortInfo, 
                                                                                 refBenchmark, 
                                                                               )
        ## Loop over configs
        # Retrieve information from outermost discriminator configurations:
        keyVec = [ key for key, nDict in refDict.iteritems() if key not in ('rawBenchmark', 'rawTuningBenchmark',) ]
        self._logger.verbose("Ref %s unsort order information: %r", refKey, keyVec )
        sortingIdxs = np.argsort( keyVec )
        sortedKeys  = apply_sort( keyVec, sortingIdxs )
        self._logger.debug("Ref %s sort order information: %r", refKey, sortedKeys )
        allBestTstConfInfo   = apply_sort(
              [ nDict['infoTstBest' ] for key, nDict in refDict.iteritems() if key not in ('rawBenchmark', 'rawTuningBenchmark',) ]
            , sortingIdxs )
        allBestOpConfInfo    = apply_sort( 
              [ nDict['infoOpBest'  ] for key, nDict in refDict.iteritems() if key not in ('rawBenchmark', 'rawTuningBenchmark',) ]
            , sortingIdxs )
        self._logger.debug("%s: Retrieving test outermost neuron performance", refBenchmark)
        ( refDict['summaryInfoTst'], \
          refDict['infoTstBest'], refDict['infoTstWorst']) = self.__outermostPerf( 
                                                                                   allBestTstConfInfo,
                                                                                   allBestTstConfInfo, 
                                                                                   refBenchmark, 
                                                                                 )
        self._logger.debug("%s: Retrieving operation outermost neuron performance", refBenchmark)
        ( refDict['summaryInfoOp'], \
          refDict['infoOpBest'], refDict['infoOpWorst'])   = self.__outermostPerf( 
                                                                                   allBestOpConfInfo,  
                                                                                   allBestOpConfInfo, 
                                                                                   refBenchmark, 
                                                                                 )
      # Finished summary information
      #if self._level <= LoggingLevel.VERBOSE:
      #  self._logger.verbose("Priting full summary dict:")
      #  pprint(cSummaryInfo)

      # Build monitoring root file
      if doMonitoring:
        self._logger.info("Creating monitoring file...")
        # Fix root file name:
        if mFName is None: mFName = cOutputName
        if mFName == cOutputName: mFName = appendToFileName( mFName, 'monitoring' )
        mFName = ensureExtension( mFName, '.root' )
        self._sg = TFile( mFName ,'recreate')
        # Just to start the loop over neuron and sort
        refPrimaryKey = cSummaryInfo.keys()[0]
        for iPath in progressbar(iPathHolder, len(iPathHolder), 'Reading configs: ', 60, 1, True, logger = self._logger):
          start = time()
          infoList, extraInfoList = iPathHolder[iPath], extraInfoHolder[iPath]
          self._logger.info("Reading file '%s' which has %d configurations.", iPath, len(infoList))
          # FIXME Check if extension is tgz, and if so, merge multiple tarMembers
          tdArchieve = TunedDiscrArchieve.load(iPath)
          for (neuron, sort, init, refEnum, refName,), tarMember in zip(infoList, extraInfoList):
            tunedDict      = tdArchieve.getTunedInfo(neuron,sort,init)
            trainEvolution = tunedDict['tuningInfo']
            tunedDiscr     = tunedDict['tunedDiscr']
            if type(tunedDiscr) in (list, tuple,):
              if len(tunedDiscr) == 1:
                discr = tunedDiscr[0]
              else:
                discr = tunedDiscr[refEnum]
            else:
              # exmachina core version
              discr = tunedDiscr
            self.__addMonPerformance(discr, trainEvolution, refName, neuron, sort, init)
          elapsed = (time() - start)
          self._logger.debug('Total time is: %.2fs', elapsed)
        self._sg.Close()
      # Do monitoring

      if isMerged:
        # Now we proceed and remove all temporary files created if we are
        # dealing with merged files.
        # First, we need to find all unique temporary folders:
        uniqueTmpFolders = np.unique( map( lambda filename: os.path.dirname(filename), iPathHolder) ) 
        for tmpFolder in uniqueTmpFolders:
          from shutil import rmtree
          self._logger.debug("Removing temporary folder: %s", tmpFolder)
          rmtree( tmpFolder )
        # for tmpFolder
      # if isMerged

      #    Don't bother with the following code, just something I was working on in case extractAll is an issue
      #    neuronList, sortList, initList = iPathHolder[iPath]
      #    tarMemberList, refBenchmarkIdxList, refBenchmarkNameList = extraInfoHolder[iPath]
      #    uniqueMemberList, inverseIdxList = np.unique(tarMemberList, return_inverse=True)
      #    # What would happen to tarMember if multiple files are added?
      #    for tdArchieve, cIdx in enumerate( TunedDiscrArchieve.load(iPath, tarMemberList = uniqueMemberList ) ):
      #      repeatIdxList = matlab.find( inverseIdxList == inverseIdxList[cIdx] )
      #      for repeatIdx in repeatIdxList:
      #        neuron, sort, init, refIdx, refName = neuronList[i], sortList[i], initList[i], refBenchmarkIdxList[i], refBenchmarkNameList[i]

      # Strip keys from summary info that are only used for monitoring and
      # shouldn't be at the final file.
      for refKey, refValue in cSummaryInfo.iteritems(): # Loop over operations
        for nKey, nValue in refValue.iteritems():
          if 'config_' in nKey:
            for sKey, sValue in nValue.iteritems():
              if 'sort_' in sKey:
                for key in ['infoOpBest','infoOpWorst','infoTstBest','infoTstWorst']:
                  sValue[key].pop('path',None)
                  sValue[key].pop('tarMember',None)
              else:
                sValue.pop('path',None)
                sValue.pop('tarMember',None)
          elif nKey in ['infoOpBest','infoOpWorst','infoTstBest','infoTstWorst']:
            nValue.pop('path',None)
            nValue.pop('tarMember',None)
      # Remove keys only needed for 
      # FIXME There is probably a "smarter" way to do this
      #holdenParents = []
      #for _, key, parent, _, level in traverse(cSummaryInfo, tree_types = (dict,)):
      #  if key in ('path', 'tarMember') and not(parent in holdenParents):
      #    holdenParents.append(parent)


      if self._level <= LoggingLevel.VERBOSE:
        pprint(cSummaryInfo)
      elif self._level <= LoggingLevel.DEBUG:
        for refKey, refValue in cSummaryInfo.iteritems(): # Loop over operations
          self._logger.debug("This is the summary information for benchmark %s", refKey )
          pprint({key : { innerkey : innerval for innerkey, innerval in val.iteritems() if not(innerkey.startswith('sort_'))} 
                                              for key, val in refValue.iteritems() if type(key) is str} 
                , depth=3
                )

      # Append pp collections
      cSummaryInfo['infoPPChain'] = cSummaryPPInfo

      outputPath = save( cSummaryInfo, cOutputName, compress=compress )
      self._logger.info("Saved file '%s'",outputPath)
      # Save matlab file
      if toMatlab:
        try:
          import scipy.io
          scipy.io.savemat( ensureExtension( cOutputName, '.mat'), cSummaryInfo)
        except ImportError:
          self._logger.warning(("Cannot save matlab file, it seems that scipy is not "
              "available."))
          with open(ensureExtension( cOutputName, '.mat'), 'w') as dummy_mat:
            dummy_mat.write("## This is just a dummy file. ##")
      # Finished bin
    # finished all files
  # end of loop

  #def __retrieveFileInfo(self, tdArchieve, 
  #                             cRefBenchmarkList,
  #                             tunedDiscrInfo,
  #                             cSummaryPPInfo):
  #  """
  #  Retrieve tdArchieve information
  #  """
  # end of __retrieveFileInfo

  def __addPPChain(self, cSummaryPPInfo, tunedPPChain, sort):
    if not( 'sort_' + str(sort).zfill(3) in cSummaryPPInfo ) and tunedPPChain:
      ppData = tunedPPChain.toRawObj()
      cSummaryPPInfo['sort_' + str( sort ).zfill(3) ] = ppData
  # end of __addPPChain

  def __outermostPerf(self, headerInfoList, perfInfoList, refBenchmark):

    summaryDict = {'cut': [], 'sp': [], 'det': [], 'fa': [], 'idx': []}
    # Fetch all information together in the dictionary:
    for key in summaryDict.keys():
      summaryDict[key] = [ perfInfo[key] for perfInfo in perfInfoList ]
      if not key == 'idx':
        summaryDict[key + 'Mean'] = np.mean(summaryDict[key],axis=0)
        summaryDict[key + 'Std' ] = np.std( summaryDict[key],axis=0)

    # Put information together on data:
    benchmarks = [summaryDict['sp'], summaryDict['det'], summaryDict['fa']]

    # The outermost performances:
    refBenchmark.level = self.level # FIXME Something ignores previous level
                                    # changes, but couldn't discover what...
    print refBenchmark
    print benchmarks
    bestIdx  = refBenchmark.getOutermostPerf(benchmarks, eps = self._eps )
    worstIdx = refBenchmark.getOutermostPerf(benchmarks, cmpType = -1., eps = self._eps )
    if self._level <= LoggingLevel.DEBUG:
      self._logger.debug('Retrieved best index as: %d; values: (SP:%f, Pd:%f, Pf:%f)', bestIdx, 
          benchmarks[0][bestIdx],
          benchmarks[1][bestIdx],
          benchmarks[2][bestIdx])
      self._logger.debug('Retrieved worst index as: %d; values: (SP:%f, Pd:%f, Pf:%f)', worstIdx,
          benchmarks[0][worstIdx],
          benchmarks[1][worstIdx],
          benchmarks[2][worstIdx])

    # Retrieve information from outermost performances:
    def __getInfo( headerInfoList, perfInfoList, idx ):
      info = dict()
      wantedKeys = ['discriminator', 'neuron', 'sort', 'init', 'path', 'tarMember']
      headerInfo = headerInfoList[idx]
      for key in wantedKeys:
        info[key] = headerInfo[key]
      wantedKeys = ['cut','sp', 'det', 'fa', 'idx']
      perfInfo = perfInfoList[idx]
      for key in wantedKeys:
        info[key] = perfInfo[key]
      return info

    bestInfoDict  = __getInfo( headerInfoList, perfInfoList, bestIdx )
    worstInfoDict = __getInfo( headerInfoList, perfInfoList, worstIdx )
    if self._level <= LoggingLevel.VERBOSE:
      self._logger.debug("The best configuration retrieved is: <config:%s, sort:%s, init:%s>",
                           bestInfoDict['neuron'], bestInfoDict['sort'], bestInfoDict['init'])
      self._logger.debug("The worst configuration retrieved is: <config:%s, sort:%s, init:%s>",
                           worstInfoDict['neuron'], worstInfoDict['sort'], worstInfoDict['init'])
    return (summaryDict, bestInfoDict, worstInfoDict)
  # end of __outermostPerf

  def exportDiscrFiles(self, ringerOperation, **kw ):
    """
    Export discriminators operating at reference benchmark list to the
    ATLAS environment using this CrossValidStat information.
    """
    if not self._summaryInfo:
      self._logger.fatal("Create the summary information using the loop method.")
    CrossValidStat.exportDiscrFiles( self._summaryInfo, 
                                     ringerOperation, 
                                     level = self._level,
                                     **kw )

  @classmethod
  def exportDiscrFiles(cls, summaryInfoList, ringerOperation, **kw):
    """
    Export discriminators operating at reference benchmark list to the
    ATLAS environment using summaryInfo. 
    
    If benchmark name on the reference list is not available at summaryInfo, an
    KeyError exception will be raised.
    """
    baseName      = kw.pop( 'baseName'      , 'tunedDiscr'      )
    refBenchCol   = kw.pop( 'refBenchCol'   , None              )
    configCol     = kw.pop( 'configCol'     , []                )
    triggerChains = kw.pop( 'triggerChains' , None              )
    etBins        = kw.pop( 'EtBins'        , None              )
    etaBins       = kw.pop( 'EtaBins'       , None              )
    level         = kw.pop( 'level'         , LoggingLevel.INFO )

    # Initialize local logger
    logger      = Logger.getModuleLogger("exportDiscrFiles", logDefaultLevel = level )
    checkForUnusedVars( kw, logger.warning )

    try:
      nEtBins = len(etBins) - 1
    except ValueError:
      nEtBins = 1

    try:
      nEtaBins = len(etaBins) - 1
    except ValueError:
      nEtaBins = 1

    # Treat the summaryInfoList
    if not isinstance( summaryInfoList, (list,tuple)):
      summaryInfoList = [ summaryInfoList ]
    summaryInfoList = list(traverse(summaryInfoList,simple_ret=True))
    nSummaries = len(summaryInfoList)

    if refBenchCol is None:
      refBenchCol = summaryInfoList[0].keys()

    # Treat the reference benchmark list
    if not isinstance( refBenchCol, (list,tuple)):
      refBenchCol = [ refBenchCol ] * nSummaries

    if len(refBenchCol) == 1:
      refBenchCol = refBenchCol * nSummaries

    nRefs = len(list(traverse(refBenchCol,simple_ret=True)))

    # Make sure that the lists are the same size as the reference benchmark:
    nConfigs = len(list(traverse(configCol,simple_ret=True)))
    if nConfigs == 0:
      configCol = [None for i in range(nRefs)]
    elif nConfigs == 1:
      configCol = configCol * nSummaries

    if nConfigs != nRefs:
      self._logger.fatal("Summary size is not equal to the configuration list.", ValueError)
    
    if nRefs == nConfigs == nSummaries:
      # If user input data without using list on the configuration, put it as a list:
      for o, idx, parent, _, _ in traverse(configCol):
        parent[idx] = [o]
      for o, idx, parent, _, _ in traverse(refBenchCol):
        parent[idx] = [o]

    configCol   = list(traverse(configCol,max_depth_dist=1,simple_ret=True))
    refBenchCol = list(traverse(refBenchCol,max_depth_dist=1,simple_ret=True))
    nConfigs = len(configCol)
    nSummary = len(refBenchCol)

    if nRefs != nConfigs != nSummary:
      self._logger.fatal("Number of references, configurations and summaries do not match!", ValueError)

    # Retrieve the operation:
    from TuningTools.ReadData import RingerOperation
    ringerOperation = RingerOperation.retrieve(ringerOperation)
    logger.info(('Exporting discrimination info files for the following '
                'operating point (RingerOperation:%s).'), 
                RingerOperation.tostring(ringerOperation))

    if ringerOperation is RingerOperation.L2:
      if triggerChains is None:
        triggerChains = "custom"
      if type(triggerChains) not in (list,tuple):
        triggerChains = [triggerChains]
      nExports = len(refBenchCol[0])
      if len(triggerChains) == 1 and nExports != 1:
        baseChainName = triggerChains[0]
        triggerChains = ["%s_chain%d" % (baseChainName,i) for i in range(nExports)]
      if nExports != len(triggerChains):
        self._logger.fatal("Number of exporting chains does not match with number of given chain names.", ValueError)

      #output = open('TrigL2CaloRingerConstants.py','w')
      #output.write('def SignaturesMap():\n')
      #output.write('  signatures=dict()\n')
      outputDict = dict()
    elif ringerOperation is RingerOperation.Offline:
      # Import athena cpp information
      try:
        import cppyy
      except ImportError:
        import PyCintex as cppyy
      try:
        cppyy.loadDict('RingerSelectorTools_Reflex')
      except RuntimeError:
        self._logger.fatal("Couldn't load RingerSelectorTools_Reflex dictionary.")
<<<<<<< HEAD
      from copy import deepcopy
=======
>>>>>>> 0e33ec3... add mu dependent configuration into TuningJob
      from ROOT import TFile
      ## Import reflection information
      from ROOT import std # Import C++ STL
      from ROOT.std import vector # Import C++ STL
      # Import Ringer classes:
      from ROOT import Ringer
      from ROOT import MsgStream
      from ROOT import MSG
      from ROOT.Ringer import IOHelperFcns
      from ROOT.Ringer import PreProcessing
      from ROOT.Ringer.PreProcessing      import Norm
      from ROOT.Ringer.PreProcessing.Norm import Norm1VarDep
      from ROOT.Ringer import IPreProcWrapperCollection
      from ROOT.Ringer import Discrimination
      from ROOT.Ringer import IDiscrWrapper
      #from ROOT.Ringer import IDiscrWrapperCollection
>>>>>>> 0e33ec3... add mu dependent configuration into TuningJob
      from ROOT.Ringer.Discrimination import NNFeedForwardVarDep
      from ROOT.Ringer import IThresWrapper
      from ROOT.Ringer.Discrimination import UniqueThresholdVarDep
      # Create the vectors which will hold the procedures
      BaseVec = vector("Ringer::PreProcessing::Norm::Norm1VarDep*")
      #vec = BaseVec( ); vec += [ Norm1VarDep() for _ in range(nEtaBins) ]
      #vecvec = vector( BaseVec )(); vecvec += [deepcopy(vec) for _ in range(nEtBins) ]
      #norm1Vec.push_back(vecvec)
      vec = BaseVec( 1, Norm1VarDep() ); vecvec = vector( BaseVec )( 1, vec )
      norm1Vec = vector( vector( BaseVec ) )() # We are not using longitudinal segmentation
      norm1Vec.push_back(vecvec)
      ## Discriminator matrix to the RingerSelectorTools format:
      BaseVec = vector("Ringer::Discrimination::NNFeedForwardVarDep*")
      vec = BaseVec( ); vec += [ NNFeedForwardVarDep() for _ in range(nEtaBins) ]
      vecvec = vector( BaseVec )(); vecvec += [deepcopy(vec) for _ in range(nEtBins) ]
      ringerNNVec = vector( vector( BaseVec ) )() # We are not using longitudinal segmentation
      ringerNNVec.push_back(vecvec)
      BaseVec = vector("Ringer::Discrimination::UniqueThresholdVarDep*")
      vec = BaseVec(); vec +=  [UniqueThresholdVarDep()  for _ in range(nEtaBins) ]
      thresVec = vector( BaseVec )(); thresVec += [deepcopy(vec) for _ in range(nEtBins) ]
    else:
      logger.fatal( "Chosen operation (%s) is not yet implemented.", RingerOperation.tostring(ringerOperation) )

    import time
    for summaryInfo, refBenchmarkList, configList in \
                        zip(summaryInfoList,
                            refBenchCol,
                            configCol,
                           ):
      if type(summaryInfo) is str:
        logger.info('Loading file "%s"...', summaryInfo)
        summaryInfo = load(summaryInfo)
      elif type(summaryInfo) is dict:
        pass
      else:
        self._logger.fatal("Cross-valid summary info is not string and not a dictionary.", ValueError)
      from itertools import izip, count
      for idx, refBenchmarkName, config in izip(count(), refBenchmarkList, configList):
        refBenchmarkNameToMatch = summaryInfo.keys()
        for ref in  refBenchmarkNameToMatch:
          if refBenchmarkName in ref:
            refBenchmarkName = ref
            break
        # Retrieve raw information:
        info   = summaryInfo[refBenchmarkName]['infoOpBest'] if config is None else \
                 summaryInfo[refBenchmarkName]['config_' + str(config).zfill(3)]['infoOpBest']
        etBin  = summaryInfo[refBenchmarkName]['rawTuningBenchmark']['signal_efficiency']['etBin']
        etaBin = summaryInfo[refBenchmarkName]['rawTuningBenchmark']['signal_efficiency']['etaBin']
        # Check if user specified parameters for exporting discriminator
        # operation information:
        sort = info['sort']
        init = info['init']

        ## Write the discrimination wrapper
        if ringerOperation in (RingerOperation.L2, RingerOperation.L2Calo):
          ## Discriminator configuration
          discrData={}
          discrData['datecode']  = time.strftime("%Y-%m-%d %H:%M")
          discrData['configuration']={}
          discrData['configuration']['benchmarkName'] = refBenchmarkName
          discrData['configuration']['etBin']     = ( etBins[etBin]  , etBins[etBin+1]   )
          discrData['configuration']['etaBin']    = ( etaBins[etaBin], etaBins[etaBin+1] )
          discrData['discriminator'] = info['discriminator']
          discrData['discriminator']['threshold'] = info['cut']
        elif ringerOperation is RingerOperation.Offline:
          logger.debug( 'Exporting information for et/eta bin: %d (%f->%f) / %d (%f->%f)', etBin, etBins[etBin], etBins[etBin+1], 
                                                                                           etaBin, etaBins[etaBin], etaBins[etaBin+1] )
          ## Retrieve the pre-processing chain:
          #norm1VarDep = norm1Vec[0][etBin][etaBin]
          #norm1VarDep.setEtDep( etBins[etBin], etBins[etBin+1] )
          #norm1VarDep.setEtaDep( etaBins[etaBin], etaBins[etaBin+1] )
          ## Retrieve the discriminator collection:
          # Retrieve discriminator
          tunedDiscr = info['discriminator']
          # And get their weights
          nodes = std.vector("unsigned int")(); nodes += tunedDiscr['nodes']
          weights = std.vector("float")(); weights += tunedDiscr['weights']
          bias = vector("float")(); bias += tunedDiscr['bias']
          ringerDiscr = ringerNNVec[0][etBin][etaBin]
          ringerDiscr.changeArchiteture(nodes, weights, bias)
          ringerDiscr.setEtDep( etBins[etBin], etBins[etBin+1] )
          ringerDiscr.setEtaDep( etaBins[etaBin], etaBins[etaBin+1] )
          logger.verbose('Discriminator information: %d/%d (%f->%f) (%f->%f)', etBin, etaBin, ringerDiscr.etMin(), ringerDiscr.etMax(), ringerDiscr.etaMin(), ringerDiscr.etaMax())
          # Print information discriminator information:
          msg = MsgStream('ExportedNeuralNetwork')
          msg.setLevel(LoggingLevel.toC(level))
          ringerDiscr.setMsgStream(msg)
          getattr(ringerDiscr,'print')(MSG.DEBUG)
          ## Add it to Discriminator collection
          ## Add current threshold to wrapper:
          thres = thresVec[etBin][etaBin]
          thres.setThreshold( info['cut'] )
          thres.setEtDep( etBins[etBin], etBins[etBin+1] )
          thres.setEtaDep( etaBins[etaBin], etaBins[etaBin+1] )
          if logger.isEnabledFor( LoggingLevel.DEBUG ):
            thresMsg = MsgStream("ExportedThreshold")
            thresMsg.setLevel(LoggingLevel.toC(level))
            thres.setMsgStream(thresMsg)
            getattr(thres,'print')(MSG.DEBUG)
        elif ringerOperation is RingerOperation.L2:
          triggerChain = triggerChains[idx]
          if not triggerChain in outputDict:
            cDict={}
            outputDict[triggerChain] = cDict
          else:
            cDict = outputDict[triggerChain]
          # to list because the dict stringfication
          discrData['discriminator']['bias']    = discrData['discriminator']['bias'].tolist()
          discrData['discriminator']['weights'] = discrData['discriminator']['weights'].tolist()
          cDict['et%d_eta%d' % (etBin, etaBin) ] = discrData
        logger.info('neuron = %d, sort = %d, init = %d, thr = %f',
                    info['neuron'],
                    info['sort'],
                    info['init'],
                    info['cut'])
      # for benchmark
    # for summay in list

    if ringerOperation in (RingerOperation.L2Calo, RingerOperation.L2):
      #for key, val in outputDict.iteritems():
      #  output.write('  signatures["%s"]=%s\n' % (key, val))
      #output.write('  return signatures\n')
      return outputDict
    elif ringerOperation is RingerOperation.Offline: 
      from ROOT.Ringer import RingerProcedureWrapper
      ## Instantiate the templates:
      RingerNorm1IndepWrapper = RingerProcedureWrapper("Ringer::PreProcessing::Norm::Norm1VarDep",
                                                       "Ringer::EtaIndependent",
                                                       "Ringer::EtIndependent",
                                                       "Ringer::NoSegmentation")
      RingerNNDepWrapper = RingerProcedureWrapper("Ringer::Discrimination::NNFeedForwardVarDep",
                                                  "Ringer::EtaDependent",
                                                  "Ringer::EtDependent",
                                                  "Ringer::NoSegmentation")
      RingerThresWrapper = RingerProcedureWrapper("Ringer::Discrimination::UniqueThresholdVarDep",
                                                  "Ringer::EtaDependent",
                                                  "Ringer::EtDependent",
                                                  "Ringer::NoSegmentation")
      ## Create pre-processing wrapper:
      logger.debug('Initiazing norm1Wrapper...')
      norm1Wrapper = RingerNorm1IndepWrapper(norm1Vec)
      ## Add it to the pre-processing collection chain
      logger.debug('Creating PP-Chain...')
      ringerPPCollection = IPreProcWrapperCollection()
      ringerPPCollection.push_back(norm1Wrapper)
      ## Create the discrimination wrapper:
      logger.debug('Exporting RingerNNDepWrapper...')
      nnWrapper = RingerNNDepWrapper( ringerPPCollection, ringerNNVec )
      # Export the discrimination wrapper to a TFile and save it:
      logger.debug('Creating vector collection...')
      discrCol = vector('Ringer::IDiscrWrapper*')() 
      logger.debug('Pushing back discriminator wrappers...')
      discrCol.push_back(nnWrapper)
      fDiscrName = baseName + '_Discr_' + refBenchmarkName + ".root"
      IDiscrWrapper.writeCol(discrCol, fDiscrName)
      logger.info("Successfully created file %s.", fDiscrName)
      ## Create threshold wrapper:
      logger.debug('Initiazing Threshold Wrapper:')
      thresWrapper = RingerThresWrapper(thresVec)
      fThresName = baseName + '_Thres_' + refBenchmarkName + ".root"
      IThresWrapper.writeWrapper( thresWrapper, fThresName )
      logger.info("Successfully created file %s.", fThresName)
    # which operation to export
  # exportDiscrFiles 




  @classmethod
  def printTables(cls, confBaseNameList,
                       crossValGrid,
                       configMap):
    "Print tables for the cross-validation data."
    # TODO Improve documentation

    # We first loop over the configuration base names:
    for ds in [Dataset.Test, Dataset.Operation]:
      for confIdx, confBaseName in enumerate(confBaseNameList):
        print "{:=^90}".format("  %s ( %s )  " % (confBaseName, Dataset.tostring(ds)) )
        # And then on et/eta bins:
        for crossList in crossValGrid:
          print "{:-^90}".format("  Starting new Et  ")
          for crossFile in crossList:
            # Load file and then search the benchmark references with the configuration name:
            summaryInfo = load(crossFile)
            etIdx = -1
            etaIdx = -1
            for key in summaryInfo.keys():
              try:
                rawBenchmark = summaryInfo[key]['rawBenchmark']
                try:
                  etIdx = rawBenchmark['signalEfficiency']['etBin']
                  etaIdx = rawBenchmark['signalEfficiency']['etaBin']
                except KeyError:
                  etIdx = rawBenchmark['signalEfficiency']['_etBin']
                  etaIdx = rawBenchmark['signalEfficiency']['_etaBin']
                break
              except (KeyError, TypeError) as e:
                pass
            print "{:-^90}".format("  Eta (%d) | Et (%d)  " % (etaIdx, etIdx))
            #from scipy.io import loadmat
            #summaryInfo = loadmat(crossFile)
            confPdKey = confSPKey = confPfKey = None
            for key in summaryInfo.keys():
              if key == 'infoPPChain': continue
              rawBenchmark = summaryInfo[key]['rawBenchmark']
              reference = rawBenchmark['reference']
              # Retrieve the configuration keys:
              if confBaseName in key:
                if reference == 'Pd':
                  confPdKey = key 
                if reference == 'Pf':
                  confPfKey = key 
                if reference == 'SP':
                  confSPKey = key 
            # Loop over each one of the cases and print ringer performance:
            print '{:^13}   {:^13}   {:^13} |   {:^13}   |  {}  '.format("Pd (%)","SP (%)","Pf (%)","cut","(ReferenceBenchmark)")
            print "{:-^90}".format("  Ringer  ")
            for keyIdx, key in enumerate([confPdKey, confSPKey, confPfKey]):
              if not key:
                print '{:-^90}'.format(' Information Unavailable ')
                continue
              if ds is Dataset.Test:
                ringerPerf = summaryInfo[key] \
                                        ['config_' + str(configMap[confIdx][etIdx][etaIdx][keyIdx]).zfill(3)] \
                                        ['summaryInfoTst']
                print '%6.3f+-%5.3f   %6.3f+-%5.3f   %6.3f+-%5.3f |   % 5.3f+-%5.3f   |  (%s) ' % ( 
                    ringerPerf['detMean'] * 100.,   ringerPerf['detStd']  * 100.,
                    ringerPerf['spMean']  * 100.,   ringerPerf['spStd']   * 100.,
                    ringerPerf['faMean']  * 100.,   ringerPerf['faStd']   * 100.,
                    ringerPerf['cutMean']       ,   ringerPerf['cutStd']        ,
                    key)
              else:
                ringerPerf = summaryInfo[key] \
                                        ['config_' + str(configMap[confIdx][etIdx][etaIdx][keyIdx]).zfill(3) ] \
                                        ['infoOpBest']
                print '{:^13.3f}   {:^13.3f}   {:^13.3f} |   {:^ 13.3f}   |  ({}) '.format(
                    ringerPerf['det'] * 100.,
                    ringerPerf['sp']  * 100.,
                    ringerPerf['fa']  * 100.,
                    ringerPerf['cut'],
                    key)

            print "{:-^90}".format("  Baseline  ")
            reference_sp = calcSP(
                                  rawBenchmark['signalEfficiency']['efficiency'] / 100.,
                                  ( 1. - rawBenchmark['backgroundEfficiency']['efficiency'] / 100. )
                                 )
            print '{:^13.3f}   {:^13.3f}   {:^13.3f} |{:@<43}'.format(
                                      rawBenchmark['signalEfficiency']['efficiency']
                                      ,reference_sp * 100.
                                      ,rawBenchmark['backgroundEfficiency']['efficiency']
                                      ,''
                                     )
            if ds is Dataset.Test:
              print "{:.^90}".format("")
              try:
                sgnCrossEff    = rawBenchmark['signalCrossEfficiency']['_branchCollectorsDict'][Dataset.Test]
                bkgCrossEff    = rawBenchmark['backgroundCrossEfficiency']['_branchCollectorsDict'][Dataset.Test]
                sgnRawCrossVal = rawBenchmark['signalCrossEfficiency']['efficiency']['Test']
                bkgRawCrossVal = rawBenchmark['backgroundCrossEfficiency']['efficiency']['Test']
              except KeyError:
                sgnCrossEff = rawBenchmark['signalCrossEfficiency']['_branchCollectorsDict'][Dataset.Validation]
                bkgCrossEff = rawBenchmark['backgroundCrossEfficiency']['_branchCollectorsDict'][Dataset.Validation]
                sgnRawCrossVal = rawBenchmark['signalCrossEfficiency']['efficiency']['Validation']
                bkgRawCrossVal = rawBenchmark['backgroundCrossEfficiency']['efficiency']['Validation']
              try:
                reference_sp = [ calcSP(rawSgn,(100.-rawBkg))
                                  for rawSgn, rawBkg in zip(sgnCrossEff, bkgCrossEff)
                               ]
              except TypeError: # Old format compatibility
                reference_sp = [ calcSP(rawSgn['efficiency'],(100.-rawBkg['efficiency']))
                                  for rawSgn, rawBkg in zip(sgnCrossEff, bkgCrossEff)
                               ]
              print '{:6.3f}+-{:5.3f}   {:6.3f}+-{:5.3f}   {:6.3f}+-{:5.3f} |{:@<43}'.format( 
                  sgnRawCrossVal[0]
                  ,sgnRawCrossVal[1]
                  ,np.mean(reference_sp)
                  ,np.std(reference_sp)
                  ,bkgRawCrossVal[0]
                  ,bkgRawCrossVal[1]
                  ,'')
        print "{:=^90}".format("")


class PerfHolder( LoggerStreamable ):
  """
  Hold the performance values and evolution for a tuned discriminator
  """
  def __init__(self, tunedDiscrData, tunedEvolutionData, **kw ):
    LoggerStreamable.__init__(self, kw )
    self.roc_tst              = tunedDiscrData['summaryInfo']['roc_test']
    self.roc_operation        = tunedDiscrData['summaryInfo']['roc_operation']
    trainEvo                  = tunedEvolutionData
    self.epoch                = np.array( range(len(trainEvo['mse_trn'])),  dtype ='float_')
    self.nEpoch               = len(self.epoch)
    def toNpArray( obj, key, d, dtype, default = []):
      """
      Set self value to a numpy array of the dict value
      """
      if ':' in key:
        key = key.split(':')
        sKey, dKey = key
      else:
        sKey, dKey = key, key
      setattr(obj, sKey, np.array( d.get(dKey, default), dtype = dtype ) )
    # end of toNpArray
    
    try:
      # Current schema from Fastnet core
      keyCollection = ['mse_trn' ,'mse_val' ,'mse_tst'
                      ,'bestsp_point_sp_val' ,'bestsp_point_det_val' ,'bestsp_point_fa_val' ,'bestsp_point_sp_tst' ,'bestsp_point_det_tst' ,'bestsp_point_fa_tst'
                      ,'det_point_sp_val' ,'det_point_det_val' ,'det_point_fa_val' ,'det_point_sp_tst' ,'det_point_det_tst' ,'det_point_fa_tst'
                      ,'fa_point_sp_val' ,'fa_point_det_val' ,'fa_point_fa_val' ,'fa_point_sp_tst' ,'fa_point_det_tst' ,'fa_point_fa_tst'
                      ]
      # Test if file format is the new one:
      if not 'bestsp_point_sp_val' in trainEvo: raise KeyError
      for key in keyCollection:
        toNpArray( self, key, trainEvo, 'float_' )
    except KeyError:
      # Old schemma
      from RingerCore import calcSP
      self.mse_trn                = np.array( trainEvo['mse_trn'],                                     dtype = 'float_' )
      self.mse_val                = np.array( trainEvo['mse_val'],                                     dtype = 'float_' )
      self.mse_tst                = np.array( trainEvo['mse_tst'],                                     dtype = 'float_' )

      self.bestsp_point_sp_val    = np.array( trainEvo['sp_val'],                                      dtype = 'float_' )
      self.bestsp_point_det_val   = np.array( [],                                                      dtype = 'float_' )
      self.bestsp_point_fa_val    = np.array( [],                                                      dtype = 'float_' )
      self.bestsp_point_sp_tst    = np.array( trainEvo['sp_tst'],                                      dtype = 'float_' )
      self.bestsp_point_det_tst   = np.array( trainEvo['det_tst'],                                     dtype = 'float_' )
      self.bestsp_point_fa_tst    = np.array( trainEvo['fa_tst'],                                      dtype = 'float_' )
      self.det_point_det_val      = np.array( trainEvo['det_fitted'],                                  dtype = 'float_' ) \
                                    if 'det_fitted' in trainEvo else np.array([], dtype='float_')
      self.det_point_fa_val       = np.array( trainEvo['fa_val'],                                      dtype = 'float_' )
      self.det_point_sp_val       = np.array( calcSP(self.det_point_det_val, 1-self.det_point_fa_val), dtype = 'float_' ) \
                                    if 'det_fitted' in trainEvo else np.array([], dtype='float_')
      self.det_point_sp_tst       = np.array( [],                                                      dtype = 'float_' )
      self.det_point_det_tst      = np.array( [],                                                      dtype = 'float_' )
      self.det_point_fa_tst       = np.array( [],                                                      dtype = 'float_' )
      self.fa_point_det_val       = np.array( trainEvo['det_val'],                                     dtype = 'float_' )
      self.fa_point_fa_val        = np.array( trainEvo['fa_fitted'],                                   dtype = 'float_' ) \
                                    if 'fa_fitted' in trainEvo else np.array([],  dtype='float_')
      self.fa_point_sp_val        = np.array( calcSP(self.fa_point_det_val, 1.-self.fa_point_fa_val),  dtype = 'float_' ) \
                                    if 'fa_fitted' in trainEvo else np.array([],  dtype='float_')
      self.fa_point_sp_tst        = np.array( [],                                                      dtype = 'float_' )
      self.fa_point_det_tst       = np.array( [],                                                      dtype = 'float_' )
      self.fa_point_fa_tst        = np.array( [],                                                      dtype = 'float_' )

    self.roc_tst_det = np.array( self.roc_tst.detVec,       dtype = 'float_'     )
    self.roc_tst_fa  = np.array( self.roc_tst.faVec,        dtype = 'float_'     )
    self.roc_tst_cut = np.array( self.roc_tst.cutVec,       dtype = 'float_'     )
    self.roc_op_det  = np.array( self.roc_operation.detVec, dtype = 'float_'     )
    self.roc_op_fa   = np.array( self.roc_operation.faVec,  dtype = 'float_'     )
    self.roc_op_cut  = np.array( self.roc_operation.cutVec, dtype = 'float_'     )

    toNpArray( self, 'epoch_mse_stop:epoch_best_mse', trainEvo, 'int_', -1 )
    toNpArray( self, 'epoch_sp_stop:epoch_best_sp',   trainEvo, 'int_', -1 )
    toNpArray( self, 'epoch_det_stop:epoch_best_det', trainEvo, 'int_', -1 )
    toNpArray( self, 'epoch_fa_stop:epoch_best_fa',   trainEvo, 'int_', -1 )


  def getOperatingBenchmarks( self, refBenchmark, idx = None, 
                              ds = Dataset.Test, sortIdx = None, useTstEfficiencyAsRef = False,
                              twoIdxs = False ):
    """
      Returns the operating benchmark values for this tunned discriminator
    """
    if ds is Dataset.Test:
      detVec = self.roc_tst_det
      faVec = self.roc_tst_fa
      cutVec = self.roc_tst_cut
    elif ds is Dataset.Operation:
      detVec = self.roc_op_det
      faVec = self.roc_op_fa
      cutVec = self.roc_op_cut
    else:
      self._logger.fatal("Cannot retrieve maximum ROC SP for dataset '%s'", ds, ValueError)
    spVec = calcSP( detVec, 1 - faVec )
    idx2 = None
    if idx is None:
      if refBenchmark.reference is ReferenceBenchmark.SP:
        idx = np.argmax( spVec )
        if twoIdxs:
          idx2 = np.argmax( spVec[np.arange( spVec ) != idx] )
          if idx2 >= idx: idx2 += 1
      else:
        # Get reference for operation:
        if refBenchmark.reference is ReferenceBenchmark.Pd:
          ref = detVec
        elif refBenchmark.reference is ReferenceBenchmark.Pf:
          ref = faVec
        # We only use reference test or whatever benchmark if it was flagged to
        # be usedd
        if ds is not Dataset.Operation and not useTstEfficiencyAsRef: 
          ds = Dataset.Operation
        delta = ref - refBenchmark.getReference( ds = ds, sort = sortIdx )
        idx   = np.argmin( np.abs( delta ) )
        if twoIdxs:
          idx2 = np.argmin( delta[np.arange( delta ) != idx] )
          if idx2 >= idx: idx2 += 1
    if twoIdxs:
      sp  = (spVec[idx],  spVec[idx2],  )
      det = (detVec[idx], detVec[idx2], )
      fa  = (faVec[idx],  faVec[idx2],  )
      cut = (cutVec[idx], cutVec[idx2], )
    else:
      sp  = spVec[idx]
      det = detVec[idx]
      fa  = faVec[idx]
      cut = cutVec[idx]
    self._logger.verbose('Retrieved following performances: SP:%r| Pd:%r | Pf:%r | cut: %r | idx:%r', 
                         sp, det, fa, cut, (idx if (idx2 is None) else (idx,idx2,) ))
    return (sp, det, fa, cut, idx)

  def getGraph( self, graphType ):
    """
      Retrieve a TGraph from the discriminator tuning information.
      perfHolder.getGraph( option )
      The possible options are:
        * mse_trn
        * mse_val
        * mse_tst
        * (bestsp,det or fa)_point_sp_val
        * (bestsp,det or fa)_point_sp_tst
        * (bestsp,det or fa)_point_det_val
        * (bestsp,det or fa)_point_det_tst
        * (bestsp,det or fa)_point_fa_val
        * (bestsp,det or fa)_point_fa_tst
        * roc_val
        * roc_op
        * roc_val_cut
        * roc_op_cut
    """
    from ROOT import TGraph, gROOT, kTRUE
    gROOT.SetBatch(kTRUE)
    def epoch_graph( benchmark ):
      """
      Helper function to create graphics containing benchmarks evolution thorugh tuning epochs
      """
      return TGraph(self.nEpoch, self.epoch, benchmark) if len( benchmark ) else TGraph()
    if   graphType == 'mse_trn'             : return epoch_graph( self.mse_trn              )
    elif graphType == 'mse_val'             : return epoch_graph( self.mse_val              )
    elif graphType == 'mse_tst'             : return epoch_graph( self.mse_tst              )
    elif graphType == 'bestsp_point_sp_val' : return epoch_graph( self.bestsp_point_sp_val  )
    elif graphType == 'bestsp_point_det_val': return epoch_graph( self.bestsp_point_det_val )
    elif graphType == 'bestsp_point_fa_val' : return epoch_graph( self.bestsp_point_fa_val  )
    elif graphType == 'bestsp_point_sp_tst' : return epoch_graph( self.bestsp_point_sp_tst  )
    elif graphType == 'bestsp_point_det_tst': return epoch_graph( self.bestsp_point_det_tst )
    elif graphType == 'bestsp_point_fa_tst' : return epoch_graph( self.bestsp_point_fa_tst  )
    elif graphType == 'det_point_sp_val'    : return epoch_graph( self.det_point_sp_val     )
    elif graphType == 'det_point_det_val'   : return epoch_graph( self.det_point_det_val    )
    elif graphType == 'det_point_fa_val'    : return epoch_graph( self.det_point_fa_val     )
    elif graphType == 'det_point_sp_tst'    : return epoch_graph( self.det_point_sp_tst     )
    elif graphType == 'det_point_det_tst'   : return epoch_graph( self.det_point_det_tst    )
    elif graphType == 'det_point_fa_tst'    : return epoch_graph( self.det_point_fa_tst     )
    elif graphType == 'fa_point_sp_val'     : return epoch_graph( self.fa_point_sp_val      )
    elif graphType == 'fa_point_det_val'    : return epoch_graph( self.fa_point_det_val     )
    elif graphType == 'fa_point_fa_val'     : return epoch_graph( self.fa_point_fa_val      )
    elif graphType == 'fa_point_sp_tst'     : return epoch_graph( self.fa_point_sp_tst      )
    elif graphType == 'fa_point_det_tst'    : return epoch_graph( self.fa_point_det_tst     )
    elif graphType == 'fa_point_fa_tst'     : return epoch_graph( self.fa_point_fa_tst      )
    elif graphType == 'roc_tst'             : return TGraph(len(self.roc_tst_fa), self.roc_tst_fa, self.roc_tst_det )
    elif graphType == 'roc_op'              : return TGraph(len(self.roc_op_fa),  self.roc_op_fa,  self.roc_op_det  )
    elif graphType == 'roc_tst_cut'         : return TGraph(len(self.roc_tst_cut),
                                                            np.array(range(len(self.roc_tst_cut) ), 'float_'), 
                                                            self.roc_tst_cut )
    elif graphType == 'roc_op_cut'          : return TGraph(len(self.roc_op_cut), 
                                                         np.array(range(len(self.roc_op_cut) ),  'float_'), 
                                                         self.roc_op_cut  )
    else: self._logger.fatal( "Unknown graphType '%s'" % graphType, ValueError )