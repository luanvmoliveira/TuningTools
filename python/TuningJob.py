__all__ = ['TunedDiscrArchieve', 'TunedDiscrArchieveCol', 'ReferenceBenchmark', 
           'ReferenceBenchmarkCollection', 'TuningJob', 'fixPPCol', 
           'fixLoopingBoundsCol', 'ChooseOPMethod', 'getEfficiencyKeyAndLabel']
import numpy as np

from RingerCore                   import ( Logger, LoggerStreamable, LoggingLevel
                                         , RawDictCnv, LoggerRawDictStreamer, LoggerLimitedTypeListRDS, RawDictStreamer
                                         , save, load, EnumStringification
                                         , checkForUnusedVars, NotSet, csvStr2List, retrieve_kw
                                         , traverse, LimitedTypeList, RawDictStreamable
                                         , LimitedTypeStreamableList, masterLevel
                                         , ProjectGit )
from RingerCore.LoopingBounds     import *

from TuningTools.PreProc          import *
from TuningTools.SubsetGenerator  import *
from TuningTools.dataframe.EnumCollection import Dataset
from TuningTools.coreDef          import npCurrent



class TunedDiscrArchieveRDS( LoggerRawDictStreamer ):
  """
  The TunedDiscrArchieve RawDict Streamer
  """
  def __init__(self, **kw):
    LoggerRawDictStreamer.__init__( self, 
        transientAttrs = {'_readVersion',} | kw.pop('transientAttrs', set()),
        toPublicAttrs = {'_neuronBounds','_sortBounds','_initBounds',
                         '_etaBin', '_etBin', 
                         '_etaBinIdx', '_etBinIdx', 
                         '_tuningInfo', '_tunedDiscr', '_tunedPP'} | kw.pop('toPublicAttrs', set()),
        **kw )

  def treatDict(self, obj, raw):
    """
    Method dedicated to modifications on raw dictionary
    """
    if not obj.neuronBounds or \
       not obj.sortBounds   or \
       not obj.initBounds   or \
       not obj.tunedDiscr   or \
       not obj.tuningInfo   or \
       not obj.tunedPP:
      self._fatal("Attempted to retrieve empty data from TunedDiscrArchieve.")
    # Treat looping bounds:
    raw['neuronBounds'] = transformToMatlabBounds( raw['neuronBounds'] ).getOriginalVec()
    raw['sortBounds']   = transformToPythonBounds( raw['sortBounds'] ).getOriginalVec()
    raw['initBounds']   = transformToPythonBounds( raw['initBounds'] ).getOriginalVec()
    # Treat raw discriminator:
    def transformToRawDiscr(tunedDiscr):
      for obj in traverse( tunedDiscr, simple_ret = True ):
        obj['benchmark'] = obj['benchmark'].toRawObj()
        #obj['summaryInfo']['roc_operation'] = obj['summaryInfo']['roc_operation'].toRawObj()
        #obj['summaryInfo']['roc_test'] = obj['summaryInfo']['roc_test'].toRawObj()
      return tunedDiscr
    self.deepCopyKey(raw, 'tunedDiscr')
    raw['tunedDiscr']   = transformToRawDiscr( raw['tunedDiscr'] )
    #raw['__version'] = obj._version
    import TuningTools, RingerCore
    raw['RingerCore__version__'], raw['TuningTools__version__'] = RingerCore.__version__, TuningTools.__version__
    parent__version__ = ProjectGit.tag
    raw['Project__version__'] = parent__version__
    return LoggerRawDictStreamer.treatDict(self, obj, raw)


class TunedDiscrArchieveRDC( RawDictCnv ):
  """
  The TunedDiscrArchieve RawDict Converter
  """
  def __init__(self, **kw):
    RawDictCnv.__init__( self, 
                         ignoreAttrs = {'type','version',
                                        # We add old version parameters here:
                                        'tuningInformation', 'trainEvolution', 'tunedDiscriminators',
                                        'tunedPPCollection'} | kw.pop('ignoreAttrs', set()), 
                         toProtectedAttrs = {'_neuronBounds','_sortBounds','_initBounds',
                                             '_etaBin', '_etBin', 
                                             '_etaBinIdx', '_etBinIdx',
                                             '_tuningInfo','_tunedDiscr', '_tunedPP'} | kw.pop('toProtectedAttrs', set()), 
                         ignoreRawChildren = kw.pop('ignoreRawChildren', True),
                         **kw )
    self.skipBenchmark = False
    #self._skipROC = None

  def treatObj( self, obj, d ):

    # Treat looping bounds:
    obj._neuronBounds = MatlabLoopingBounds( d['neuronBounds'] )
    obj._sortBounds   = PythonLoopingBounds( d['sortBounds']   )
    obj._initBounds   = PythonLoopingBounds( d['initBounds']   )
    # end of local function retrieveRawDiscr
    #if obj._readVersion >= 8:
    #  def retrieveRawDiscr(tunedDiscr, skipBenchmark, skipROC):
    #    if not skipBenchmark or not skipROC:
    #      for obj in traverse( tunedDiscr, simple_ret = True ):
    #        if type(obj['benchmark']) is dict and not skipBenchmark:
    #          obj['benchmark'] = ReferenceBenchmark.fromRawObj( obj['benchmark'] )
    #        if type(obj['summaryInfo']['roc_test']) is dict and not skipROC:
    #          obj['summaryInfo']['roc_operation'] = Roc.fromRawObj( obj['summaryInfo']['roc_operation'] )
    #          obj['summaryInfo']['roc_test'] = Roc.fromRawObj( obj['summaryInfo']['roc_test'] )
    #    return tunedDiscr
    #  obj._tunedDiscr   = retrieveRawDiscr( d['tunedDiscr'], self.skipBenchmark, self._skipROC )

    if obj._readVersion >= 7:
      def retrieveRawDiscr(tunedDiscr):
        for obj in traverse( tunedDiscr, simple_ret = True ):
          if type(obj['benchmark']) is dict:
            obj['benchmark'] = ReferenceBenchmark.fromRawObj( obj['benchmark'] )
        return tunedDiscr
      obj._tunedDiscr   = retrieveRawDiscr( d['tunedDiscr'] )
      obj._tunedPP      = PreProcCollection.fromRawObj( d['tunedPP'] )
    else:
      # Read tuning information
      if obj._readVersion in (5,6,):
        obj._tuningInfo = d['tuningInformation']
      elif obj._readVersion >= 1:
        obj._tuningInfo = [tData[0]['trainEvolution'] for tData in d['tunedDiscriminators']]
      else:
        obj._logger.warning(("This TunedDiscrArchieve version still needs to have "
                             "implemented the access to the the tuning information."))
        obj._tuningInfo = None
      obj._tunedDiscr   = d['tunedDiscriminators']
      if obj._readVersion <= 4:
        # Before version 4 we didn't save the benchmarks:
        def ffilt(tData): 
          for idx, discr in enumerate(tData):
            if idx == 0:
              discr['benchmark'] = ReferenceBenchmark( 'Tuning_EFCalo_SP', 'SP' )
            elif idx == 1:
              discr['benchmark'] = ReferenceBenchmark( 'Tuning_EFCalo_SP_Pd', 'SP' )
            elif idx == 2:
              discr['benchmark'] = ReferenceBenchmark( 'Tuning_EFCalo_SP_Pf', 'SP' )
        for tData in obj._tunedDiscr:
          ffilt(tData)
      if obj._readVersion == 3:
        # On version 3 we saved only the binning index:
        obj._etaBinIdx    = d['etaBin']
        obj._etBinIdx     = d['etBin']
        obj._etaBin       = npCurrent.array([0.,0.8,1.37,1.54,2.5])
        obj._etaBin       = obj._etaBin[obj._etaBinIdx:obj._etaBinIdx+2]
        obj._etBin        = npCurrent.array([0,30.,40.,50.,20000.])*1e3
        obj._etBin        = obj._etBin[obj._etBinIdx:obj._etBinIdx+2]
      if obj._readVersion <= 1:
        # On first version we didn't save the pre-processing, but we used only Norm1:
        obj._tunedPP      = PreProcCollection( [ PreProcChain( Norm1() ) for i in range(len(obj._sortBounds)) ] )
      elif obj._readVersion < 6:
        # From version 2 to 5 we used non-raw PreProcCollection with key "tunedPPCollection"
        obj._tunedPP      = PreProcCollection( d['tunedPPCollection'] )
      elif obj._readVersion < 7:
        # On version 6 we used raw PreProcCollection with key "tunedPPCollection"
        obj._tunedPP      = PreProcCollection.fromRawObj( d['tunedPPCollection'] )
    return obj


class TunedDiscrArchieve( LoggerStreamable ):
  """
  Manager for Tuned Discriminators archives

  Version 7: - Changes dict attribute names and saves ReferenceBenchmark as dict. 
               Makes profit of RDS and RDC functionality.
  Version 6: - Saves raw object from PreProcCollection
               Saves raw reference object
  Version 5: - added tuning benchmarks. 
             - separated tuning information from the tuned discriminators
               (tunedDiscr) variable.
  Version 4: - added eta/et bin limits
  Version 3: - added eta/et bin compatibility (only indexes)
  Version 2: - added pre-processing collection
  Version 1: - started using MatlabLoopingBounds and PythonLoopingBounds to save 
               the objects.
  Version 0: - save pickle file with a list containing the neuron/sort/init
               bounds in the same object
  """

  _streamerObj  = TunedDiscrArchieveRDS( transientAttrs = {'_tarMember', '_filePath'} )
  _cnvObj       = TunedDiscrArchieveRDC( ignoreRawChildren = True )
  _version      = 7

  def __init__(self, **kw):
    Logger.__init__(self, kw)
    self._neuronBounds = kw.pop('neuronBounds', None                )
    self._sortBounds   = kw.pop('sortBounds',   None                )
    self._initBounds   = kw.pop('initBounds',   None                )
    self._tunedDiscr   = kw.pop('tunedDiscr',   None                )
    self._tuningInfo   = kw.pop('tuningInfo',   None                )
    self._tunedPP      = kw.pop('tunedPP',      None                )
    self._etaBinIdx    = kw.pop('etaBinIdx',    -1                  )
    self._etBinIdx     = kw.pop('etBinIdx',     -1                  )
    self._etaBin       = kw.pop('etaBin',       npCurrent.array([]) )
    self._etBin        = kw.pop('etBin',        npCurrent.array([]) )
    self._tarMember    = kw.pop('tarMember',    None                )
    self._filePath     = kw.pop('filePath',     None                )
    checkForUnusedVars( kw, self._warning )

  @property
  def filePath( self ):
    return self._filePath

  @property
  def tarMember( self ):
    return self._tarMember

  @property
  def neuronBounds( self ):
    return self._neuronBounds

  @property
  def sortBounds( self ):
    return self._sortBounds

  @property
  def initBounds( self ):
    return self._initBounds

  @property
  def tunedDiscr( self ):
    return self._tunedDiscr

  @property
  def tunedPP( self ):
    return self._tunedPP

  @property
  def tuningInfo( self ):
    return self._tuningInfo

  @property
  def etaBinIdx( self ):
    return self._etaBinIdx

  @property
  def etBinIdx( self ):
    return self._etBinIdx

  @property
  def etaBin( self ):
    return self._etaBin

  @property
  def etBin( self ):
    return self._etBin

  def save(self, filePath, compress = True):
    """
    Save the TunedDiscrArchieve object to disk.
    """
    return save( self.toRawObj(), filePath, compress = compress )

  @classmethod
  def load(cls, filePath, useGenerator = False, extractAll = False, 
           eraseTmpTarMembers = True, tarMember = None, ignore_zeros = True,
           skipBenchmark = True):
    """
    Load a TunedDiscrArchieve object from disk and return it.
    """
    lLogger = Logger.getModuleLogger( cls.__name__ )
    # Open file:
    from cPickle import PickleError
    try:
      import sys, inspect
      kwArgs = {'useHighLevelObj' : False, 
                'useGenerator' : useGenerator,
                'tarMember' : tarMember,
                'ignore_zeros' : ignore_zeros, 'extractAll' : extractAll,
                'eraseTmpTarMembers' : eraseTmpTarMembers, 'logger' : lLogger, 
                'returnFileName' : True, 'returnFileMember' : True}
      rawObjCol = load( filePath,  **kwArgs )
    except (PickleError, TypeError, ImportError) as e: # TypeError due to add object inheritance on Logger
      # It failed without renaming the module, retry renaming old module
      # structure to new one.
      lLogger = Logger.getModuleLogger(cls.__name__)
      import traceback
      lLogger.warning("Couldn't load file due to:\n %s.\n Attempting to read on legacy mode...", traceback.format_exc())
      import TuningTools.Neural
      cNeural = TuningTools.Neural.Neural
      cLayer = TuningTools.Neural.Layer
      TuningTools.Neural.Layer = TuningTools.Neural.OldLayer
      TuningTools.Neural.Neural = TuningTools.Neural.OldNeural
      import sys
      import RingerCore.util
      sys.modules['FastNetTool.util'] = RingerCore.util
      sys.modules['FastNetTool.Neural'] = TuningTools.Neural
      rawObjCol = load( filePath, **kwArgs )
      TuningTools.Neural.Layer = cLayer
      TuningTools.Neural.Neural = cNeural
    if not useGenerator and type( rawObjCol ) is tuple:
      rawObjCol = [ rawObjCol ]
    def __objRead(rawObjCol):
      for rawObj, lFilePath, lTarMember in rawObjCol:
        if type(rawObj) is list: # zero version file (without versioning 
          # control):
          # Old version was saved as follows:
          #objSave = [neuron, sort, initBounds, train]
          tunedList = rawObj; rawObj = dict()
          rawObj['__version']    = 0
          rawObj['neuronBounds'] = MatlabLoopingBounds( [tunedList[0], tunedList[0]] )
          rawObj['sortBounds']   = MatlabLoopingBounds( [tunedList[1], tunedList[1]] )
          rawObj['initBounds']   = MatlabLoopingBounds( tunedList[2] )
          rawObj['tunedDiscr']   = tunedList[3]
        # Finally, create instance from raw object
        obj = cls.fromRawObj( rawObj, skipBenchmark = skipBenchmark )
        obj._filePath = lFilePath
        obj._tarMember = lTarMember
        yield obj
      # end of (for rawObj)
    # end of (__objRead)
    o = __objRead(rawObjCol)
    if not useGenerator:
      o = list(o)
      for obj in o: obj._filePath = filePath
      if len(o) == 1: o = o[0]
    return o
  # end of (load)

  def __str__(self):
    """
    Return string representation of object
    """
    ppStr = 'pp-' + self.tunedPP[0].shortName()[:12] # Truncate on 12th char
    neuronStr = self.neuronBounds.formattedString('hn')
    sortStr = self.sortBounds.formattedString('s')
    initStr = self.initBounds.formattedString('i')
    return 'TunedDiscrArchieve<%s.%s.%s.%s>' % (ppStr, neuronStr, sortStr, initStr)

  def getTunedInfo( self, neuron, sort, init ):
    """
    Retrieve tuned information within this archieve using neuron/sort/init indexes.
    """
    nList = self._neuronBounds.list(); nListLen = len( nList )
    sList = self._sortBounds.list();   sListLen = len( sList )
    iList = self._initBounds.list();   iListLen = len( iList )
    try:
      if self._readVersion >= 0:
        # For now, we first loop on sort list, then on neuron bound, to
        # finally loop over the initializations:
        idx = sList.index( sort ) * ( nListLen * iListLen ) + \
              nList.index( neuron ) * ( iListLen ) + \
              iList.index( init )
        sortIdx = sList.index( sort )
      return { 'tunedDiscr' : self._tunedDiscr[ idx ], \
               'tunedPP' : self._tunedPP[ sortIdx ], \
               'tuningInfo' : self._tuningInfo[ idx ] }
    except ValueError, e:
      self._fatal(("Couldn't find one the required indexes on the job bounds. "
          "The retrieved error was: %s") % e, ValueError)
  # getTunedInfo

class ReferenceBenchmarkRDS( LoggerRawDictStreamer ):
  """
   The ReferenceBenchmark RawDict streamer
  """

  def __init__(self, **kw):
    LoggerRawDictStreamer.__init__( self, 
        #transientAttrs = {'_readVersion',} | kw.pop('transientAttrs', set()),
        #transientAttrs = set() | kw.pop('transientAttrs', set()),
        transientAttrs = {'_readVersion',} | kw.pop('transientAttrs', set()),
        toPublicAttrs = { 
                          '_signalEfficiency', 
                          '_backgroundEfficiency',
                          '_signalCrossEfficiency', 
                          '_backgroundCrossEfficiency',
                          '_name', 
                          '_reference',
                        } | kw.pop('toPublicAttrs', set()),
        **kw )

  # TODO: Is this need?
  #def preCall( self, obj ):
  #  """
  #  Treat obj before calling RawDict tranformation
  #  """
  #  try:
  #    self._prevSgnNoChildren = obj._signalCrossEfficiency._streamerObj.noChildren
  #    obj._signalCrossEfficiency._streamerObj.noChildren = True
  #  except AttributeError:
  #    pass
  #  try:
  #    self._prevBkgNoChildren = obj._backgroundCrossEfficiency._streamerObj.noChildren
  #    obj._backgroundCrossEfficiency._streamerObj.noChildren = True
  #  except AttributeError:
  #    pass

  def treatDict( self, obj, d ):
    """
    Post RawDict transformation treatments.
    """
    from TuningTools import  BranchEffCollector, BranchCrossEffCollector
    d['reference'] = ReferenceBenchmark.tostring( d['reference'] )
    d['refVal']    = obj.refVal if not obj.refVal is None else -999
    d['signalEfficiency'] = obj._signalEfficiency.toRawObj() if obj._signalEfficiency is not None \
        else BranchEffCollector( etBin=obj.etBinIdx, etaBin=obj.etaBinIdx ).toRawObj()
    d['backgroundEfficiency'] = obj._backgroundEfficiency.toRawObj() if obj._backgroundEfficiency is not None \
        else BranchEffCollector( etBin=obj.etBinIdx, etaBin=obj.etaBinIdx ).toRawObj()
    d['signalCrossEfficiency'] = obj._signalCrossEfficiency.toRawObj() \
                                       if obj._signalCrossEfficiency is not None else \
                                       BranchCrossEffCollector(etBin=obj.etBinIdx, etaBin=obj.etaBinIdx).toRawObj()
    d['backgroundCrossEfficiency'] = obj._backgroundCrossEfficiency.toRawObj() \
                                       if obj._backgroundCrossEfficiency is not None else \
                                       BranchCrossEffCollector(etBin=obj.etBinIdx, etaBin=obj.etaBinIdx).toRawObj()
    d['_etBinIdx'] = '' if obj.etBinIdx is None else obj.etBinIdx
    d['_etaBinIdx'] = '' if obj.etaBinIdx is None else obj.etaBinIdx
    
    return d

class ReferenceBenchmarkRDC( RawDictCnv ):
  """
  Reference benchmark RawDict converter
  """

  def __init__(self, **kw):
    RawDictCnv.__init__( self, 
                         ignoreAttrs = {'_removeOLs'} | kw.pop('ignoreAttrs', set()), 
                         toProtectedAttrs = { 
                                              '_signalEfficiency', 
                                              '_backgroundEfficiency',
                                              '_signalCrossEfficiency', 
                                              '_backgroundCrossEfficiency',
                                              '_name', 
                                              '_reference',
                                 } | kw.pop('toProtectedAttrs', set()),
                         **kw )

  def treatObj( self, obj, d ):
    """
    Treat object after transforming it to python object
    """
    #self._readVersion = d['__version']
    obj._reference = ReferenceBenchmark.retrieve(d['reference'])
    from TuningTools import BranchEffCollector, BranchCrossEffCollector
    obj._signalEfficiency          = BranchEffCollector.fromRawObj( d['signalEfficiency'] )
    obj._backgroundEfficiency      = BranchEffCollector.fromRawObj( d['backgroundEfficiency'] )
    obj._etBinIdx = None if d['_etBinIdx'] is '' else d['_etBinIdx']
    obj._etaBinIdx = None if d['_etaBinIdx'] is '' else d['_etaBinIdx']
    return obj

class ChooseOPMethod( EnumStringification ):
  """
  Method to choose the operation point
  """
  _ignoreCase = True
  ClosestPointToReference = 0
  BestBenchWithinBound = 1
  MaxSPWithinBound = 2
  AUC = 3
  InBoundAUC = 4
  MSE = 5

class ReferenceBenchmark(EnumStringification, LoggerStreamable):
  """
  Reference benchmark to set discriminator operation point.
    - SP: Use the SUM-PRODUCT coeficient as an optimization target. 
    - Pd: Aims at operating with signal detection probability as close as
      possible from reference value meanwhile minimazing the false
      alarm probability.
    - Pf: Aims at operating with false alarm probability as close as
      possible from reference value meanwhile maximazing the detection
      probability.
    - MSE: Aims at reducing as much as possible the mean-squared error.
      If MSE is used to retrieve the outermost performance, it will return
      the outermost SP-index.
    Version Control:
    - version  1: Changed snake case to cammel case and make use of RawDictStreamable capabilities.
                  Retrieve only the useful information from the Collectors.
    - version  0: Used BranchEffCollector and BranchCrossEffCollector
  """

  _streamerObj = ReferenceBenchmarkRDS()
  _cnvObj      = ReferenceBenchmarkRDC()
  _version     = 2

  SP = 0
  Pd = 1
  Pf = 2
  MSE = 3

  _def_eps = .002
  _def_auc_eps = _def_eps
  _def_model_choose_method = ChooseOPMethod.BestBenchWithinBound

  def __init__(self, name = '', reference = SP, 
               signalEfficiency = None, backgroundEfficiency = None,
               signalCrossEfficiency = None, backgroundCrossEfficiency = None, 
               **kw):
    """
    ref = ReferenceBenchmark(name, reference, signalEfficiency, backgroundEfficiency, 
                                   signalCrossEfficiency = None, backgroundCrossEfficiency = None,
                                   allowLargeDeltas = True])
      * name: The name for this reference benchmark;
      * reference: The reference benchmark type. It must one of ReferenceBenchmark enumerations.
      * signalEfficiency: The signal efficiency for the ReferenceBenchmark retrieve information from.
      * backgroundEfficiency: The background efficiency for the ReferenceBenchmark retrieve information from.
      * signalCrossEfficiency: The signal efficiency measured with the Cross-Validation sets for the ReferenceBenchmark retrieve information from.
      * backgroundCrossEfficiency: The background efficiency with the Cross-Validation sets for the ReferenceBenchmark retrieve information from.
      * allowLargeDeltas [True]: When set to true and no value is within the operation bounds,
       then it will use operation closer to the reference.
    """
    from RingerCore import calcSP
    LoggerStreamable.__init__(self, kw)
    self._allowLargeDeltas = kw.pop('allowLargeDeltas', True  )
    self._etBinIdx  = retrieve_kw( kw, 'etBinIdx', None )
    self._etaBinIdx = retrieve_kw( kw, 'etaBinIdx', None )
    checkForUnusedVars( kw, self._warning )
    self._name      = name
    if not (type(self.name) is str):
      self._fatal("Name must be a string.")
    self._reference = ReferenceBenchmark.retrieve(reference)
    # Fill attributes with standard values
    self._totalSignalCount = 0
    self._totalBackgroundCount = 0
    self._pd = 0.
    self._pf = 0.
    self._sp = 0.
    self.refVal = None
    self._crossPdList = {}
    self._crossPfList = {}

    # Hold all eff branches
    self._signalEfficiency          = signalEfficiency
    self._signalCrossEfficiency     = signalCrossEfficiency
    self._backgroundEfficiency      = backgroundEfficiency
    self._backgroundCrossEfficiency = backgroundCrossEfficiency


    # If non-empty class, add all information:
    if self._name:
      # Check if everything is ok
      if signalEfficiency is None or backgroundEfficiency is None:
        if self._reference != ReferenceBenchmark.SP:
          self._fatal("Cannot specify non-empty ReferenceBenchmark without signalEfficiency and backgroundEfficiency arguments.")
        else:
          return
      # Total counts:
      self._totalSignalCount = signalEfficiency.count
      self._totalBackgroundCount = backgroundEfficiency.count
      # Retrieve efficiency values
      self._pd        = signalEfficiency.efficiency/100.
      self._pf        = backgroundEfficiency.efficiency/100.
      self._sp        = calcSP(self._pd, 1.-self._pf)
      # Retrieve binning indexes
      self._etBinIdx  = signalEfficiency.etBin
      self._etaBinIdx = signalEfficiency.etaBin
      from TuningTools import BranchCrossEffCollector
      if type(signalCrossEfficiency) == type(backgroundCrossEfficiency) == BranchCrossEffCollector:
        self._crossPdList = signalCrossEfficiency.allDSEfficiencyList
        self._crossPfList = signalCrossEfficiency.allDSEfficiencyList
      else:
        self._debug("ReferenceBenchmark build with no cross-validation object")

      self.refVal = self.__refVal()
  # __init__

  @property
  def allowLargeDeltas( self ):
    return self._allowLargeDeltas

  @property
  def name( self ):
    return self._name

  @name.setter
  def name( self, val ):
    self._name = val

  @property
  def reference( self ):
    return self._reference

  @property
  def etaBinIdx(self):
    return self._etaBinIdx

  @property
  def etBinIdx(self):
    return self._etBinIdx

  @property
  def totalSignalCount(self):
    return self._totalSignalCount

  @property
  def totalBackgroundCount(self):
    return self._totalBackgroundCount

  @property
  def signalEfficiency(self):
    return self._signalEfficiency if hasattr(self,'_signalEfficiency') else None

  @property
  def backgroundEfficiency(self):
    return self._backgroundEfficiency if hasattr(self,'_backgroundEfficiency') else None

  @property
  def signalCrossEfficiency(self):
    return self._signalCrossEfficiency if hasattr(self,'_signalCrossEfficiency') else None

  @property
  def backgroundEfficiency(self):
    return self._backgroundCrossEfficiency if hasattr(self,'_backgroundCrossEfficiency') else None

  @property
  def pd(self):
    """
    Returns reference probability of detection
    """
    return self._pd

  @property
  def pf(self):
    """
    Returns reference false alarm/fake rate/false positive probability
    """
    return self._pf

  @property
  def sp(self):
    """
    Returns reference sum-product index
    """
    return self._sp

  @property
  def crossPd(self):
    if type(self._signalCrossEfficiency) == BranchCrossEffCollector:
      return self._signalCrossEfficiency.efficiency
    else:
      return None

  @property
  def crossPf(self):
    if type(self._backgroundCrossEfficiency) == BranchCrossEffCollector:
      return self._backgroundCrossEfficiency.efficiency
    else:
      return None

  @property
  def crossSP(self):
    return self._crossSP

  @property
  def crossPdList(self):
    return self._crossPdList

  @property
  def crossPfList(self):
    return self._crossPdList

  @property
  def crossSPList(self):
    return self._crossSPList

  def __refVal(self):
    # The reference
    if self.reference is ReferenceBenchmark.Pd: 
      return self._pd
    elif self.reference is ReferenceBenchmark.Pf: 
      return self._pf
    elif self.reference is ReferenceBenchmark.SP: 
      return self._sp
    else: 
      return -999

  @property
  def tuningDict(self, ):
    return { 
             'name' : self.name,
             'reference' : self.reference,
             'refVal' : self.refVal 
           }

  def checkEtaBinIdx(self, val):
    return self.etaBinIdx == val

  def checkEtBinIdx(self, val):
    return self.etBinIdx == val

  def getReference(self, ds = Dataset.Unspecified, sort = None):
    """
    Get reference value. If sort is not specified, return the operation value.
    Otherwise, return the efficiency value over the test (or validation if test
    if not available).
    """
    if sort is None: #and ds in (Dataset.Test, Dataset.Validation, Dataset.Operation):
      return self.refVal
    if not self.crossPd:
      self._fatal("Attempted to retrieve Cross-Validation information which is not available.")
    if ds is not Dataset.Unspecified and sort is None:
      if self.reference is ReferenceBenchmark.Pd:
        return self.crossPd[ds]
      elif self.reference is ReferenceBenchmark.Pf:
        return self.crossPf[ds]
      elif self.reference is ReferenceBenchmark.SP:
        return self.crossSP[ds]
      else:
        return -999
    if ds is Dataset.Unspecified:
      ds = Dataset.Test
    # Sort is not None!
    if self.reference is ReferenceBenchmark.Pd:
      return self.crossPdList[ds][sort]
    elif self.reference is ReferenceBenchmark.Pf:
      return self.crossPfList[ds][sort]
    elif self.reference is ReferenceBenchmark.SP:
      return self.crossSPList[ds][sort]
    else:
      return -999

  def getOutermostPerf(self, data, **kw):
    """
    Get outermost performance for the tuned discriminator performances on data. 
    idx = refBMark.getOutermostPerf( data [, eps = .002 ][, cmpType = 1])
     * data: A list with following struction:
        data[0] : SP
        data[1] : Pd
        data[2] : Pf
     * eps [.005] is used for softening. The larger it is, more candidates will
      be possible to be considered, but farther the returned operation may be from
      the reference. The default is _def_eps deviation from the reference value.
     * cmpType [+1.] is used to change the comparison type. Use +1 for best
      performance, and -1 for worst performance.
     * method [BestBenchWithinBound]: method to retrieve outermost performance
     * calcAUCMethod: when specified, then return the AUC using this method for
       the given index
    """
    # Retrieve optional arguments
    eps              = retrieve_kw( kw, 'eps',              self._def_eps                 )
    cmpType          = retrieve_kw( kw, 'cmpType',          1.                            )
    sortIdx          = retrieve_kw( kw, 'sortIdx',          None                          )
    ds               = retrieve_kw( kw, 'ds',               Dataset.Test                  )
    method           = retrieve_kw( kw, 'method',           self._def_model_choose_method )
    calcAUCMethod    = retrieve_kw( kw, 'calcAUCMethod',    None                          )
    aucEps  = retrieve_kw( kw, 'aucEps',  self._def_auc_eps             )
    # We will transform data into np array, as it will be easier to work with
    npData = []
    for aData, label in zip(data, ['SP', 'Pd', 'Pf', 'AUC', 'MSE']):
      npArray = np.array(aData, dtype='float_')
      npData.append( npArray )
      #self._verbose('%s performances are:\n%r', label, npArray)
    calcAUC = False
    # Retrieve reference and benchmark arrays
    if self.reference is ReferenceBenchmark.Pf:
      refVec = npData[2]
      if method is ChooseOPMethod.MaxSPWithinBound:
        benchmark = cmpType * npData[0]
      elif method in (ChooseOPMethod.InBoundAUC, ChooseOPMethod.AUC):
        try:
          benchmark = cmpType * npData[3]
        except IndexError:
          self._fatal("AUC is not available.")
      elif method is ChooseOPMethod.MSE:
          benchmark = (-1. * cmpType) * npData[4]
      else:
        benchmark = (cmpType) * npData[1]
    elif self.reference is ReferenceBenchmark.Pd:
      refVec = npData[1] 
      if method is ChooseOPMethod.MaxSPWithinBound:
        benchmark = cmpType * npData[0]
      elif method in (ChooseOPMethod.InBoundAUC, ChooseOPMethod.AUC):
        try:
          benchmark = cmpType * npData[3]
        except IndexError:
          self._fatal("AUC is not available.")
      elif method is ChooseOPMethod.MSE:
          benchmark = (-1. * cmpType) * npData[4]
      else:
        benchmark = (-1. * cmpType) * npData[2]
    elif self.reference in (ReferenceBenchmark.SP, ReferenceBenchmark.MSE):
      if method in (ChooseOPMethod.InBoundAUC, ChooseOPMethod.AUC):
        try:
          benchmark = cmpType * npData[3]
          refVec = npData[3]
        except IndexError:
          self._fatal("AUC is not available.")
      elif method is ChooseOPMethod.MSE:
          benchmark = (-1. * cmpType) * npData[4]
      else:
        benchmark = (cmpType) * npData[0]
    else:
      self._fatal("Unknown reference %d" , self.reference)
    if method is ChooseOPMethod.MSE:
      return np.argmax( benchmark )
    lRefVal = self.getReference( ds = ds, sort = sortIdx )
    # Finally, return the index:
    if self.reference in (ReferenceBenchmark.SP, ReferenceBenchmark.MSE): 
      idx = np.argmax( cmpType * benchmark )
    else:
      refAllowedIdxs = ( np.abs( refVec - lRefVal) < eps ).nonzero()[0]
      if not refAllowedIdxs.size:
        if not self.allowLargeDeltas:
          # We don't have any candidate, raise:
          self._fatal("eps is too low, no indexes passed constraint! Reference is %r | RefVec is: \n%r" %
              (lRefVal, refVec))
        else:
          if method is not ChooseOPMethod.ClosestPointToReference:
            # FIXME We need to protect it from choosing 0% and 100% references.
            distances = np.abs( refVec - lRefVal )
            minDistanceIdx = np.argmin( distances )
            # We can search for the closest candidate available:
            self._warning("No indexes passed eps constraint (%r%%) for reference value (%s:%r) where refVec is: \n%r",
                                 eps*100., ReferenceBenchmark.tostring(self.reference), lRefVal, refVec)
            # This is the new minimal distance:
            lRefVal = refVec[minDistanceIdx]
            # and the other indexes which correspond to this value
            refAllowedIdxs = ( np.abs(refVec - lRefVal) == 0. ).nonzero()[0]
            self._verbose("Found %d points with minimum available distance of %r%% to original. They are: %r", 
                         len(refAllowedIdxs), distances[minDistanceIdx]*100., refAllowedIdxs )
          else:
            refAllowedIdxs = np.arange( len( refVec ) )
      else:
        if method is not ChooseOPMethod.ClosestPointToReference:
          if len(refAllowedIdxs) != len(refVec):
            self._info("Found %d points within %r%% distance from benchmark.", 
                              len(refAllowedIdxs), eps*100. )
      # Otherwise we return best benchmark for the allowed indexes:
      if method is ChooseOPMethod.ClosestPointToReference:
        idx = refAllowedIdxs[ np.argmin( np.abs(refVec[refAllowedIdxs] - lRefVal ) ) ]
      else:
        idx = refAllowedIdxs[ np.argmax( benchmark[ refAllowedIdxs ] ) ]
    if calcAUCMethod:
      if calcAUCMethod is ChooseOPMethod.InBoundAUC:
        lRefVal = self.getReference( ds = ds, sort = sortIdx )
        if self.reference in (ReferenceBenchmark.SP, ReferenceBenchmark.MSE):
          refVec = npData[0]
          lRefVal = refVec[idx]
          refAllowedIdxs = ( np.abs( refVec - lRefVal) < aucEps ).nonzero()[0]
        #else:
        #  # TODO Improve this calculation by extrapolating the value to the
        #  # bound: ( a = (y1 - y2) / ( x1 - x2 ); b = y1 - a x1, x3 = refVal + (or -) eps y3 = a.x3 + b;
        #  # auc = .5 * (y3 + y1 ) * x3 - x1
        #  try:
        #    auc =  ( npData[2][refAllowedIdxs[-1]] )  * ( aucEps - npData[1][refAllowedIdxs[-1]] + lRefVal )
        #    auc += ( npData[2][refAllowedIdxs[1]]  ) *  ( aucEps + npData[1][refAllowedIdxs[1]] - lRefVal )
        #  except IndexError:
        #    auc = 0
        try:
          auc = -.5 * np.sum( np.diff( npData[2][refAllowedIdxs] ) * ( npData[1][refAllowedIdxs[:-1]] + npData[1][refAllowedIdxs[1:]] ) )
        except IndexError:
          # Not enought points for calculating auc, assume that performance is constant within AUC:
          auc = 0.
      elif calcAUCMethod is ChooseOPMethod.AUC:
        auc = -.5 * np.sum( np.diff( npData[2] ) * ( npData[1][:-1] + npData[1][1:] ) )
      return idx, auc
    else:
      return idx
  # end of getOutermostPerf

  def getEps(self, eps = NotSet ):
    """
      Retrieve eps value replacing it to a custom value if input parameter is
      not NotSet
    """
    return self._def_eps if eps is NotSet else eps

  def __str__(self):
    str_ =  self.name + '(' + ReferenceBenchmark.tostring(self.reference) 
    if self.refVal is not None: str_ += ':' + str(self.refVal)
    str_ += ')'
    return str_


ReferenceBenchmarkCollection = LimitedTypeList('ReferenceBenchmarkCollection',(),
                                               {'_acceptedTypes':(ReferenceBenchmark,type(None),)})
ReferenceBenchmarkCollection._acceptedTypes = ReferenceBenchmarkCollection._acceptedTypes + (ReferenceBenchmarkCollection,)

def fixLoopingBoundsCol( var, 
    wantedType = LoopingBounds,
    wantedCollection = LoopingBoundsCollection ):
  """
    Helper method to correct variable to be a looping bound collection
    correctly represented by a LoopingBoundsCollection instance.
  """
  if not isinstance( var, wantedCollection ):
    if not isinstance( var, wantedType ):
      var = wantedType( var )
    var = wantedCollection( var )
  return var

def fixPPCol( var, nSorts = 1, nEta = 1, nEt = 1, level = None ):
  """
    Helper method to correct variable to be a looping bound collection
    correctly represented by a LoopingBoundsCollection instance.
  """
  tree_types = (PreProcCollection, PreProcChain, list, tuple )
  try: 
    # Retrieve collection maximum depth
    _, _, _, _, depth = traverse(var, tree_types = tree_types).next()
  except GeneratorExit:
    depth = 0
  if depth < 5:
    if depth == 0:
      var = [[[[var]]]]
    elif depth == 1:
      var = [[[var]]]
    elif depth == 2:
      var = [[var]]
    elif depth == 3:
      var = [var]
    # We also want to be sure that they are in correct type and correct size:
    from RingerCore import inspect_list_attrs
    var = inspect_list_attrs(var, 3, PreProcChain,      tree_types = tree_types,                                level = level   )
    var = inspect_list_attrs(var, 2, PreProcCollection, tree_types = tree_types, dim = nSorts, name = "nSorts",                 )
    var = inspect_list_attrs(var, 1, PreProcCollection, tree_types = tree_types, dim = nEta,   name = "nEta",                   )
    var = inspect_list_attrs(var, 0, PreProcCollection, tree_types = tree_types, dim = nEt,    name = "nEt",    deepcopy = True )
  else:
    raise ValueError("Pre-processing dimensions size is larger than 5.")

  return var

class BatchSizeMethod( EnumStringification ):
  _ignoreCase = True
  Manual = 0
  MinClassSize = 1
  OneSample = 2
  HalfSizeSignalClass = 3

class TuningJob(Logger):
  """
    This class is used to create and tune a classifier through the call method.
  """

  def __init__(self, logger = None ):
    """
      Initialize the TuningJob using a log level.
    """
    Logger.__init__( self, logger = logger )
    self.compress = False

  def __call__(self, dataLocation, **kw ):
    """
      Run discriminatior tuning for input data created with CreateData.py
      Arguments:
        - dataLocation: A string containing a path to the data file written
          by CreateData.py
      Mutually exclusive optional arguments: Either choose the cross (x) or
        circle (o) of the following block options.
       -------
        x crossValid [CrossValid( nSorts=50, nBoxes=10, nTrain=6, nValid=4, 
                                  seed=crossValidSeed, method=crossValidMethod )]:
          The cross-validation sorts object. The files can be generated using a
          CreateConfFiles instance which can be accessed via command line using
          the createTuningJobFiles.py script.
        x crossValidSeed [None]: Only used when not specifying the crossValid option.
          The seed is used by the cross validation random sort generator and
          when not specified or specified as None, time is used as seed.
        x crossValidMethod [None]: Use the specified CrossValid method.
        o crossValidFile: The cross-validation file path, pointing to a file
          created with the create tuning job files
       -------
        x confFileList [None]: A python list or a comma separated list of the
          root files containing the configuration to run the jobs. The files can
          be generated using a CreateConfFiles instance which can be accessed via
          command line using the createTuningJobFiles.py script.
        o neuronBoundsCol [MatlabLoopingBounds(5,5)]: A LoopingBoundsCollection
          range where the the neural network should loop upon.
        o sortBoundsCol [PythonLoopingBounds(50)]: A LoopingBoundsCollection
          range for the sorts to use from the crossValid object.
        o initBoundsCol [PythonLoopingBounds(100)]: A LoopingBoundsCollection
          range for the initialization numbers to be ran on this tuning job.
          The neuronBoundsCol, sortBoundsCol, initBoundsCol will be synchronously
          looped upon, that is, all the first collection information upon those 
          variables will be used to feed the first job configuration, all of 
          those second collection information will be used to feed the second job 
          configuration, and so on...
          In the case you have only one job configuration, it can be input as
          a single LoopingBounds instance, or values that feed the LoopingBounds
          initialization. In the last case, the neuronBoundsCol will be used
          to feed a MatlabLoopingBounds, and the sortBoundsCol together with
          initBoundsCol will be used to feed a PythonLoopingBounds.
          For instance, if you use neuronBoundsCol set to [5,2,11], it will 
          loop upon the list [5,7,9,11], while if this was set to sortBoundsCol,
          it would generate [5,7,9].
       -------
        x ppFile [None]: The file containing the pre-processing collection to apply into 
          input space and obtain the pattern space. The files can be generated
          using a CreateConfFiles instance which is accessed via command
          line using the createTuningJobFiles.py script.
        o ppCol PreProcCollection( [ PreProcCollection( [ PreProcCollection( [ PreProcChain( Norm1() ) ] ) ] ) ] ): 
          A PreProcCollection with the PreProcChain instances to be applied to
          each sort and eta/et bin.
        o clusterFile [None]: The file containing the cluster collection to apply into the crossvalid method.
        o cluster [None]: The collection object with type SubsetGeneratorPatternsCollection( 
                          [SubsetGeneratorPatterns(..., PreProcChain(Norm1(), Projection()))])
       -------
      Optional arguments:
        - operation [NotSet]: The discriminator operation level(s). When
            NotSet, the operation level will be retrieved from the tuning data
            file. This is important only when using the MultiStop criterea,
            where all operation points will be optimized together using the
            signal and background efficiency from the operation.
        - etBins [None]: The et bins to use within this job. 
            When not specified, all bins available on the file will be tuned
            separately.
            If specified as a integer or float, it is assumed that the user
            wants to run the job only for the specified bin index.
            In case a list is specified, it is transformed into a
            MatlabLoopingBounds, read its documentation on:
              http://nbviewer.jupyter.org/github/wsfreund/RingerCore/blob/master/readme.ipynb#LoopingBounds
            for more details.
        - etaBins [None]: The eta bins to use within this job. Check etBins
          help for more information.
        - compress [True]: Whether to compress file or not.
        - level [loggingLevel.INFO]: The logging output level.
        - outputFileBase ['nn.tuned']: The tuning outputFile starting string.
            It will also contain a custom string representing the configuration
            used to tune the discriminator.
        - showEvo (TuningWrapper prop) [50]: The number of iterations wher
            performance is shown (used as a boolean on ExMachina).
        - maxFail (TuningWrapper prop) [50]: Maximum number of failures
            tolerated failing to improve performance over validation dataset.
        - epochs (TuningWrapper prop) [10000]: Number of iterations where
            the tuning algorithm can run the optimization.
        - doPerf (TuningWrapper prop) [True]: Whether we should run performance
            testing under convergence conditions, using test/validation dataset
            and also estimate operation condition.
        - maxFail (TuningWrapper prop) [50]: Number of epochs which failed to improve
            validation efficiency. When reached, the tuning process is stopped.
        - batchSize (TuningWrapper prop) [number of observations of the class
            with the less observations]: Set the batch size used during tuning.
        - algorithmName (TuningWrapper prop) [resilient back-propgation]: The
            tuning method to use.
        - batchMethod (TuningWrapper prop) [MinClassSize]: The method to choose 
            the batching size. Use one of those decribed by BatchSizeMethod
            EnumStringification.
       -------
      ExMachina props
        - networkArch (ExMachina prop) ['feedforward']: the neural network
            architeture to use.
        - costFunction (ExMachina prop) ['sp']: the cost function used by ExMachina
        - shuffle (ExMachina prop) [True]: Whether to shuffle datasets while
          training.
       -------
      FastNet props
        - seed (FastNet prop) [None]: The seed to be used by the tuning
            algorithm.
        - doMultiStop (FastNet prop) [True]: Tune classifier using P_D, P_F and
          SP when set to True. Uses only SP when set to False.
    """
    from TuningTools import TuningToolsGit
    from RingerCore import RingerCoreGit 
    TuningToolsGit.ensure_clean() 
    RingerCoreGit.ensure_clean()
    from RingerCore import OMP_NUM_THREADS
    self._info( 'OMP_NUM_THREADS is set to: %d', OMP_NUM_THREADS )
    import gc, os.path
    from copy import deepcopy
    ### Retrieve configuration from input values:
    ## We start with basic information:
    self.level     = retrieve_kw(kw, 'level',           masterLevel()     )
    compress       = retrieve_kw(kw, 'compress',        True              )
    operationPoint = retrieve_kw(kw, 'operationPoint',  None              )
    outputFileBase = retrieve_kw(kw, 'outputFileBase',  'nn.tuned'        )
    outputDir      = retrieve_kw(kw, 'outputDirectory', ''                )
    merged         = retrieve_kw(kw, 'merged',          False             )
    outputDir      = os.path.abspath( outputDir )
    ## Now we go to parameters which need higher treating level, starting with
    ## the CrossValid object:
    # Make sure that the user didn't try to use both options:
    if 'crossValid' in kw and 'crossValidFile' in kw:
      self._fatal("crossValid is mutually exclusive with crossValidFile, \
          either use or another terminology to specify CrossValid object.", ValueError)
    crossValidFile      = retrieve_kw( kw, 'crossValidFile', None )
    from TuningTools.CrossValid import CrossValid, CrossValidArchieve
    if not crossValidFile:
      # Cross valid was not specified, read it from crossValid:
      crossValid                 = kw.pop('crossValid',
          CrossValid( level   = self.level
                    , seed    = retrieve_kw(kw, 'crossValidSeed' )
                    , method  = retrieve_kw(kw, 'crossValidMethod' )
                    , shuffle = retrieve_kw(kw, 'crossValidShuffle' ) ) )
    else:
      with CrossValidArchieve( crossValidFile ) as CVArchieve:
        crossValid = CVArchieve
      del CVArchieve


    ## Read configuration for job parameters:
    # Check if there is no conflict on job parameters:
    if 'confFileList' in kw and ( 'neuronBoundsCol' in kw or \
                                  'sortBoundsCol'   in kw or \
                                  'initBoundsCol'   in kw ):
      self._fatal(("confFileList is mutually exclusive with [neuronBounds, " \
          "sortBounds and initBounds], either use one or another " \
          "terminology to specify the job configuration."), ValueError)
    confFileList    = kw.pop('confFileList', None )
    # Retrieve configuration looping parameters
    if not confFileList:
      self._debug("Retrieving looping configuration from passed arguments")
      # There is no configuration file, read information from kw:
      neuronBoundsCol   = retrieve_kw( kw, 'neuronBoundsCol', MatlabLoopingBounds(5, 5                 ) )
      sortBoundsCol     = retrieve_kw( kw, 'sortBoundsCol',   PythonLoopingBounds(crossValid.nSorts( ) ) )
      initBoundsCol     = retrieve_kw( kw, 'initBoundsCol',   PythonLoopingBounds(100                  ) )
    else:
      self._debug("Retrieving looping configuration from file.")
      # Make sure confFileList is in the correct format
      confFileList = csvStr2List( confFileList )
      # Now loop over confFiles and add to our configuration list:
      neuronBoundsCol = LoopingBoundsCollection()
      sortBoundsCol   = LoopingBoundsCollection()
      initBoundsCol   = LoopingBoundsCollection()
      from TuningTools.CreateTuningJobFiles import TuningJobConfigArchieve
      for confFile in confFileList:
        with TuningJobConfigArchieve( confFile ) as (neuronBounds, 
                                                     sortBounds,
                                                     initBounds):
          neuronBoundsCol += neuronBounds
          sortBoundsCol   += sortBounds
          initBoundsCol   += initBounds
    # Now we make sure that bounds variables are LoopingBounds objects:
    neuronBoundsCol = fixLoopingBoundsCol( neuronBoundsCol,
                                           MatlabLoopingBounds )
    sortBoundsCol   = fixLoopingBoundsCol( sortBoundsCol,
                                           PythonLoopingBounds )
    initBoundsCol   = fixLoopingBoundsCol( initBoundsCol,
                                           PythonLoopingBounds )
    # Check if looping bounds are ok:
    for neuronBounds in neuronBoundsCol():
      if neuronBounds.lowerBound() < 1:
        self._fatal("Neuron lower bound is not allowed, it must be at least 1.", ValueError)
    for sortBounds in sortBoundsCol():
      if sortBounds.lowerBound() < 0:
        self._fatal("Sort lower bound is not allowed, it must be at least 0.", ValueError)
      if sortBounds.upperBound() >= crossValid.nSorts():
        self._fatal(("Sort upper bound (%d) is not allowed, it is higher or equal then the number "
            "of sorts used (%d).") % (sortBounds.upperBound(), crossValid.nSorts(),), ValueError )
    for initBounds in initBoundsCol():
      if initBounds.lowerBound() < 0:
        self._fatal("Attempted to create an initialization index lower than 0.", ValueError)
    nSortsVal = crossValid.nSorts()
    ## Retrieve binning information: 
    etBins  = retrieve_kw(kw, 'etBins',  None )
    etaBins = retrieve_kw(kw, 'etaBins', None )
    # Check binning information
    if type(etBins) in (int,float):
      etBins = [etBins, etBins]
    if type(etaBins) in (int,float):
      etaBins = [etaBins, etaBins]
    if etBins is not None:
      etBins = MatlabLoopingBounds(etBins)
    if etaBins is not None:
      etaBins = MatlabLoopingBounds(etaBins)
    ## Retrieve the Tuning Data Archieve and check for compatible reference information
    from TuningTools.CreateData import TuningDataArchieve, BenchmarkEfficiencyArchieve
    # We assume that the number of bins are equal for all files
    if not isinstance(dataLocation, (list,tuple)):
      dataLocation = [dataLocation]
    isEtDependent, isEtaDependent, nEtBins, nEtaBins, tdVersion = TuningDataArchieve.load(dataLocation[0], retrieveBinsInfo=True, retrieveVersion=True)

    # Read the cluster configuration
    if 'cluster' in kw and 'clusterFile' in kw:
      self._fatal("cluster is mutually exclusive with clusterFile, \
          either use or another terminology to specify SubsetGenaratorCollection object.", ValueError)
    
    clusterFile      = retrieve_kw( kw, 'clusterFile', None )
    if clusterFile is None:
      clusterCol = kw.pop('cluster', None)
      if clusterCol and (type(clusterCol) is not SubsetGeneratorCollection):
        self._fatal('cluster must be a SubsetGeneratorCollection type.', ValueError)
      if tdVersion < 6 and clusterCol is not None:
        self._warning("Cluster collection will be ignored as file version is lower than 6.")
        clusterCol = None
    else:
      with SubsetGeneratorArchieve(clusterFile) as SGArchieve:
        clusterCol = SGArchieve
      if tdVersion < 6 and clusterCol is not None:
        self._warning("Cluster collection will be ignored as file version is lower than 6.")
        clusterCol = None

    self._debug("Total number of et bins: %d" , nEtBins)
    self._debug("Total number of eta bins: %d" , nEtaBins)
    # Check if use requested bins are ok:
    if etBins is not None:
      if not isEtDependent:
        self._fatal("Requested to run for specific et bins, but no et bins are available.", ValueError)
      if etBins.lowerBound() < 0 or etBins.upperBound() >= nEtBins:
        self._fatal("etBins (%r) bins out-of-range. Total number of et bins: %d" % (etBins.list(), nEtBins), ValueError)
      if not isEtaDependent:
        self._fatal("Requested to run for specific eta bins, but no eta bins are available.", ValueError)
      if etaBins.lowerBound() < 0 or etaBins.upperBound() >= nEtaBins:
        self._fatal("etaBins (%r) bins out-of-range. Total number of eta bins: %d" % (etaBins.list(), nEtaBins) , ValueError)

     ## Check ppCol or ppFile
    if 'ppFile' in kw and 'ppCol' in kw:
      self._fatal(("ppFile is mutually exclusive with ppCol, "
          "either use one or another terminology to specify the job "
          "configuration."), ValueError)
    ppFile    = retrieve_kw(kw, 'ppFile', None )
    if not ppFile:
      ppCol = kw.pop( 'ppCol', PreProcChain( Norm1(level = self.level) ) )
    else:
      # Now loop over ppFile and add it to our pp list:
      with PreProcArchieve(ppFile) as ppCol: pass
    # Make sure that our pre-processings are PreProcCollection instances and matches
    # the number of sorts, eta and et bins.
    ppCol = fixPPCol( ppCol,
                      nSortsVal,
                      nEtaBins,
                      nEtBins,
                      level = self.level )
    # Retrieve some useful information and keep it on memory
    nConfigs = len( neuronBoundsCol )
    ## Now create the tuning wrapper:
    from TuningTools.TuningWrapper import TuningWrapper
                                   # Wrapper confs:
    tuningWrapper = TuningWrapper( level                 = self.level
                                 , doPerf                = retrieve_kw( kw, 'doPerf',                NotSet)
                                   # Expert Neural Networks confs:
                                 , merged                = merged
                                 , networks              = retrieve_kw( kw, 'networks',              NotSet)
                                   # All core confs:
                                 , maxFail               = retrieve_kw( kw, 'maxFail',               NotSet)
                                 , algorithmName         = retrieve_kw( kw, 'algorithmName',         NotSet)
                                 , epochs                = retrieve_kw( kw, 'epochs',                NotSet)
                                 , batchSize             = retrieve_kw( kw, 'batchSize',             NotSet)
                                 , batchMethod           = retrieve_kw( kw, 'batchMethod',           NotSet)
                                 , showEvo               = retrieve_kw( kw, 'showEvo',               NotSet)
                                 , useTstEfficiencyAsRef = retrieve_kw( kw, 'useTstEfficiencyAsRef', NotSet)
                                   # ExMachina confs:
                                 , networkArch           = retrieve_kw( kw, 'networkArch',           NotSet)
                                 , costFunction          = retrieve_kw( kw, 'costFunction',          NotSet)
                                 , shuffle               = retrieve_kw( kw, 'shuffle',               NotSet)
                                   # FastNet confs:
                                 , seed                  = retrieve_kw( kw, 'seed',                  NotSet)
                                 , doMultiStop           = retrieve_kw( kw, 'doMultiStop',           NotSet)
                                 )
   


    # Check whether it is need to retrieve efficiencies from another reference file:
    refFile = None
    refFilePath = retrieve_kw( kw, 'refFile', NotSet)
    if not (refFilePath in (None, NotSet)):
      self._info("Reading reference file...")
      refFile = BenchmarkEfficiencyArchieve.load( refFilePath, 
                                                  loadCrossEfficiencies = True )
      if not refFile.checkForCompatibleBinningFile( dataLocation[0] ):
        self._logger.error("Reference file binning information is not compatible with data file. Ignoring reference file!")
        refFile = None

    ## Finished retrieving information from kw:
    checkForUnusedVars( kw, self._warning )
    del kw

    from itertools import product
    for etBinIdx, etaBinIdx in product( range( nEtBins if nEtBins is not None else 1 ) if etBins is None \
                                   else etBins(), 
                                  range( nEtaBins if nEtaBins is not None else 1 ) if etaBins is None \
                                   else etaBins() ):
      binStr = '' 
      saveBinStr = 'no-bin'
      if nEtBins is not None or nEtaBins is not None:
        binStr = ' (etBinIdx=%d,etaBinIdx=%d)' % (etBinIdx, etaBinIdx)
        saveBinStr = 'et%04d.eta%04d' % (etBinIdx, etaBinIdx)
      self._info('Opening data%s...', binStr)


      # Load data bin
      tdArchieve = []
      patterns = []
      if not isinstance(dataLocation, (tuple,list)): dataLocation = [dataLocation]
      for i in range(len(dataLocation)):
        tdArchieve += [ TuningDataArchieve.load(dataLocation[i], etBinIdx = etBinIdx if isEtDependent else None,
                                           etaBinIdx = etaBinIdx if isEtaDependent else None,
                                           loadEfficiencies = True if refFile is None else False,
                                           loadCrossEfficiencies = True if refFile is None else False
                                           ) ]
        patterns += [ [tdArchieve[i].signalPatterns, tdArchieve[i].backgroundPatterns] ]
      
      #FIXME: Only this version is supported
      if tdVersion >= 6:
        baseInfo = (tdArchieve[0].signalBaseInfo, tdArchieve[0].backgroundBaseInfo)
      else:
        baseInfo = (None, None)

      if operationPoint is None:
        operationPoint = refFile.operation if refFile is not None else tdArchieve[0].operation

      if tuningWrapper.doMultiStop:
        try:
          from TuningTools.dataframe.EnumCollection import RingerOperation
          #NOTE: We assume that every data has the same version
          efficiencyKey,refLabel = getEfficiencyKeyAndLabel( dataLocation[0], operationPoint )
          ##FIXME: There are some confusion here, this must be review by @wsfreund.
          #efficiencyKey = RingerOperation.tostring( efficiencyKey )
          try:
            benchmarks = (refFile.signalEfficiencies[efficiencyKey],
                          refFile.backgroundEfficiencies[efficiencyKey])
          except (AttributeError, KeyError):
            if refFile is not None:
              self._logger.error("Couldn't retrieve efficiencies from reference file. Attempting to use tuning data references instead...")
            benchmarks = (tdArchieve[0].signalEfficiencies[efficiencyKey], 
                          tdArchieve[0].backgroundEfficiencies[efficiencyKey])
        except KeyError, e:
          self._fatal("Couldn't retrieve benchmark efficiencies! Reason:\n%s", e)
        crossBenchmarks = None
        try:
          #if tuningWrapper.useTstEfficiencyAsRef:
          try:
            crossBenchmarks = (refFile.signalCrossEfficiencies[efficiencyKey], 
                               refFile.backgroundCrossEfficiencies[efficiencyKey])
          except (AttributeError, KeyError):
            crossBenchmarks = (tdArchieve[0].signalCrossEfficiencies[efficiencyKey], 
                               tdArchieve[0].backgroundCrossEfficiencies[efficiencyKey])
        except (AttributeError, KeyError, TypeError):
          self._info("Cross-validation benchmark efficiencies is not available.")
          crossBenchmarks = None
          tuningWrapper.useTstEfficiencyAsRef = False
      else:
        benchmarks = None
        crossBenchmarks = None

      if isEtDependent:
        etBins = tdArchieve[0].etBins
        self._info('Tuning Et bin: %r', etBins)
      if isEtaDependent:
        etaBins = tdArchieve[0].etaBins
        self._info('Tuning eta bin: %r', etaBins)
      # Add the signal efficiency and background efficiency as goals to the
      # tuning wrapper:
      references = ReferenceBenchmarkCollection([])
      if tuningWrapper.doMultiStop:
        opRefs = [ReferenceBenchmark.SP, ReferenceBenchmark.Pd, ReferenceBenchmark.Pf]
        if benchmarks is None:
          self._fatal("Couldn't access the benchmarks on efficiency file and MultiStop was requested.", RuntimeError)
        for ref in opRefs: 
          if type(benchmarks[0]) is list:
            if crossBenchmarks is not None and (crossBenchmarks[0][etBinIdx]) and crossBenchmarks[1][etBinIdx]:
              references.append( ReferenceBenchmark( "Tuning_" + refLabel.replace('Accept','') + "_" 
                                                   + ReferenceBenchmark.tostring( ref ), 
                                                     ref, benchmarks[0][etBinIdx][etaBinIdx], benchmarks[1][etBinIdx][etaBinIdx],
                                                     crossBenchmarks[0][etBinIdx][etaBinIdx], crossBenchmarks[1][etBinIdx][etaBinIdx]
                                                    , etBinIdx=etBinIdx, etaBinIdx=etaBinIdx ) )
            else:
              references.append( ReferenceBenchmark( "Tuning_" + refLabel.replace('Accept','') + "_" 
                                                   + ReferenceBenchmark.tostring( ref ), 
                                                     ref, benchmarks[0][etBinIdx][etaBinIdx], benchmarks[1][etBinIdx][etaBinIdx]
                                                    , etBinIdx=etBinIdx, etaBinIdx=etaBinIdx))
          else:
            if crossBenchmarks is not None and crossBenchmarks[0].etaBin != -1:
              references.append( ReferenceBenchmark( "Tuning_" + refLabel.replace('Accept','') + "_" 
                                                   + ReferenceBenchmark.tostring( ref ), 
                                                     ref, benchmarks[0], benchmarks[1]
                                                   , crossBenchmarks[0], crossBenchmarks[1], etBinIdx=etBinIdx, etaBinIdx=etaBinIdx) )
            else:
              references.append( ReferenceBenchmark( "Tuning_" + refLabel.replace('Accept','') + "_" 
                                                   + ReferenceBenchmark.tostring( ref ), 
                                                     ref, benchmarks[0], benchmarks[1]
                                                   , etBinIdx=etBinIdx, etaBinIdx=etaBinIdx ) )
      else:
        from TuningTools.dataframe.EnumCollection import RingerOperation
        references.append( ReferenceBenchmark( "Tuning_%s_%s" % ( RingerOperation.tostring(operationPoint)
                                                                , ReferenceBenchmark.tostring( ReferenceBenchmark.SP ) )
                                             , ReferenceBenchmark.SP, etBinIdx=etBinIdx, etaBinIdx=etaBinIdx ) )

      tuningWrapper.setReferences( references )
      del tdArchieve
      # For the bounded variables, we loop them together for the collection:
      for confNum, neuronBounds, sortBounds, initBounds in \
          zip(range(nConfigs), neuronBoundsCol, sortBoundsCol, initBoundsCol ):
        self._info('Running configuration file number %d%s', confNum, binStr)
        tunedDiscr = []
        tuningInfo = []
        nSorts = len(sortBounds)
        # Finally loop within the configuration bounds
        for sort in sortBounds():
          ppChain = ppCol[etBinIdx][etaBinIdx][sort]
          #FIXME: Only this version is supported
          if tdVersion >= 6:
            for i in range(len(patterns)):
              patterns[i] = ppChain.concatenate(patterns[i], baseInfo)

          self._info('Extracting cross validation sort %d%s.', sort, binStr)
          if clusterCol:
            cluster = clusterCol[etBinIdx][etaBinIdx][sort]
            # Setting extra information if needed.
            if cluster.isDependent():
              self._info("Setting dependent patterns into the subset configuration...")
              cluster.setDependentPatterns( baseInfo )
            # Cluster is a LimitedList of clusters [cl_pattern1, cl_pattern2, ...]
            # TODO
            if len(patterns) == 1:
              trnData, valData, tstData = crossValid( patterns[0], sort, cluster )
            else:
              trnData, valData, tstData = [None]*len(patterns), [None]*len(patterns), [None]*len(patterns)
              for i in range(len(patterns)):
                trnData[i], valData[i], tstData[i] = crossValid( patterns[i], sort, cluster )
          else:
            # Here, not apply subset generator
            if len(patterns) == 1:
              trnData, valData, tstData = crossValid( patterns[0], sort  )
            else:
              trnData, valData, tstData = [None]*len(patterns), [None]*len(patterns), [None]*len(patterns)
              for i in range(len(patterns)):
                trnData[i], valData[i], tstData[i] = crossValid( patterns[i], sort  )
          del patterns # Keep only one data representation

          # Take ppChain parameters on training data:
          self._info('Tuning pre-processing chain (%s)...', ppChain)
          self._debug('Retrieving parameters and applying pp chain to train dataset...')
          trnData = ppChain.takeParams( trnData )
          self._debug('Done tuning pre-processing chain!')
          self._info('Applying pre-processing chain to remaining sets...')
          # Apply ppChain:
          self._debug('Applying pp chain to validation dataset...')
          valData = ppChain( valData ) 
          self._debug('Applying pp chain to test dataset...')
          tstData = ppChain( tstData )
          self._debug('Done applying the pre-processing chain to all sets!')

          # Retrieve resulting data shape
          if merged:
            nInputs = [trnData[0][0].shape[npCurrent.pdim], trnData[1][0].shape[npCurrent.pdim]]
          else:
            nInputs = trnData[0].shape[npCurrent.pdim]
          # Update tuningtool working data information:
          tuningWrapper.setTrainData( trnData ); del trnData
          tuningWrapper.setValData  ( valData ); del valData
          if len(tstData) > 0:
            if merged:
              if len(tstData[0]) > 0:
                tuningWrapper.setTestData( tstData ); del tstData
            else:
              tuningWrapper.setTestData( tstData ); del tstData
          else:
            self._debug('Using validation dataset as test dataset.')
          tuningWrapper.setSortIdx(sort)
          # Garbage collect now, before entering training stage:
          gc.collect()
          # And loop over neuron configurations and initializations:
          for neuron in neuronBounds():
            for init in initBounds():
              self._info('Training <Neuron = %d, sort = %d, init = %d>%s...', \
                  neuron, sort, init, binStr)
              if merged:
                self._info( 'Discriminator Configuration: input = %d, hidden layer = %d, output = %d',\
                            (nInputs[0]+nInputs[1]), neuron, 1)
                tuningWrapper.newExpff( [nInputs, neuron, 1], etBinIdx, etaBinIdx, sort )
                cTunedDiscr, cTuningInfo = tuningWrapper.trainC_Exp()
              else:
                self._info( 'Discriminator Configuration: input = %d, hidden layer = %d, output = %d',\
                            nInputs, neuron, 1)
                tuningWrapper.newff([nInputs, neuron, 1])
                cTunedDiscr, cTuningInfo = tuningWrapper.train_c()
              self._debug('Finished C++ tuning, appending tuned discriminators to tuning record...')
              # Append retrieved tuned discriminators and its tuning information
              tunedDiscr.append( cTunedDiscr )
              tuningInfo.append( cTuningInfo )
            self._debug('Finished all initializations for neuron %d...', neuron)
          self._debug('Finished all neurons for sort %d...', sort)
          # Finished all inits for this sort, we need to undo the crossValid if
          # we are going to do a new sort, otherwise we continue
          if not ( (confNum+1) == nConfigs and sort == sortBounds.endBound()):
            if False: # crossValid.isRevertible() and ppChain.isRevertible() and clusterCol is None:
              trnData = tuningWrapper.trnData(release = True)
              valData = tuningWrapper.valData(release = True)
              tstData = tuningWrapper.testData(release = True)
              if merged:
                patterns = [None, None]
                for i in range(2):
                  patterns[i] = crossValid.revert( trnData[i], valData[i], tstData[i], sort = sort )
              else:
                patterns = crossValid.revert( trnData, valData, tstData, sort = sort )
              del trnData, valData, tstData
              patterns = ppChain( patterns , revert = True )
            else:
              # We cannot revert ppChain, reload data:
              self._info('Re-opening raw data...')
              tdArchieve = []
              patterns = [] 
              for i in range(len(dataLocation)):
                tdArchieve += [ TuningDataArchieve.load(dataLocation[i],
                                                    etBinIdx = etBinIdx if isEtDependent else None,
                                                    etaBinIdx = etaBinIdx if isEtaDependent else None) ]
                patterns += [ (tdArchieve[i].signalPatterns, tdArchieve[i].backgroundPatterns) ] 


              del tdArchieve
          self._debug('Finished all hidden layer neurons for sort %d...', sort)
        self._debug('Finished all sorts for configuration %d in collection...', confNum)
        ## Finished retrieving all tuned discriminators for this config file for
        ## this pre-processing. Now we head to save what we've done so far:
        # This pre-processing was tuned during this tuning configuration:
        tunedPP = PreProcCollection( [ ppCol[etBinIdx][etaBinIdx][sort] for sort in sortBounds() ] )
        
        # Define output file name:
        fulloutput = os.path.join(
            outputDir
            ,'{outputFileBase}.{ppStr}.{neuronStr}.{sortStr}.{initStr}.{saveBinStr}.pic'.format( 
                      outputFileBase = outputFileBase, 
                      ppStr = 'pp-' + ppChain.shortName()[:12], # Truncate on 12th char
                      neuronStr = neuronBounds.formattedString('hn'), 
                      sortStr = sortBounds.formattedString('s'),
                      initStr = initBounds.formattedString('i'),
                      saveBinStr = saveBinStr )
            )
        self._info('Saving file named %s...', fulloutput)

        extraKw = {}
        if nEtBins is not None:
          extraKw['etBinIdx'] = etBinIdx
          #extraKw['etBin'] = etBins[etBinIdx]
          extraKw['etBin'] = etBins
        if nEtaBins is not None:
          extraKw['etaBinIdx'] = etaBinIdx
          #extraKw['etaBin'] = etaBins[etaBinIdx]
          extraKw['etaBin'] = etaBins

        savedFile = TunedDiscrArchieve( neuronBounds = neuronBounds, 
                                        sortBounds = sortBounds, 
                                        initBounds = initBounds,
                                        tunedDiscr = tunedDiscr,
                                        tuningInfo = tuningInfo,
                                        tunedPP = tunedPP,
                                        **extraKw
                                      ).save( fulloutput, compress )
        self._info('File "%s" saved!', savedFile)

      # Finished all configurations we had to do
      self._info('Finished tuning job!')

  # end of __call__ member fcn

class TunedDiscrArchieveCol( Logger ):
  """
    The TunedDiscrArchieveCol holds a collection of TunedDiscrArchieve. It is
    used by the file merger method to merge the TunedDiscrArchieve files into a
    unique file.

    Deprecated: Decided not to work with this solution, as this would be
    extremely slow. However code is kept for future reference.
  """

  # Use class factory
  __metaclass__ = LimitedTypeStreamableList
  _streamerObj  = LoggerLimitedTypeListRDS
  #_cnvObj       = LimitedTypeListRDC( level = LoggingLevel.VERBOSE )

  # These are the list (LimitedTypeList) accepted objects:
  _acceptedTypes = (TunedDiscrArchieve, str)

  def __init__( self, *args, **kw ):
    Logger.__init__(self, kw)
    from RingerCore.LimitedTypeList import _LimitedTypeList____init__
    _LimitedTypeList____init__(self, *args)

  def toRawObj(self):
    from RingerCore.RawDictStreamable import _RawDictStreamable__toRawObj
    rawDict = _RawDictStreamable__toRawObj(self)
    # Expand items to be files:
    for idx, item in enumerate(rawDict['items']):
      # FIXME If item is a string, expand it to have the correct format
      rawDict['file_' + str(idx)] = item
    rawDict.pop('items')
    return rawDict

  def save(self, filePath):
    """
    Save the TunedDiscrArchieveCol object to disk.
    """
    return save( self.toRawObj(), filePath, protocol = 'savez_compressed' )

  @classmethod
  def load( cls, filePath ):
    """
    Load a TunedDiscrArchieveCol object from disk and return it.
    """
    rawObj = load( filePath, useHighLevelObj = False )
    # TODO Work with the numpy file
    #return cls.fromRawObj( rawObj )
    return rawObj

def getEfficiencyKeyAndLabel( filePath, operationPoint ):
  from TuningTools.CreateData import TuningDataArchieve, BenchmarkEfficiencyArchieve
  # Retrieve file version:
  effVersion = None
  try:
    tdVersion = TuningDataArchieve.load( filePath, retrieveVersion=True)
  except:
    effVersion = BenchmarkEfficiencyArchieve.load( filePath, retrieveVersion=True)
  from TuningTools.dataframe.EnumCollection import RingerOperation
  efficiencyKey = RingerOperation.retrieve(operationPoint)
  if tdVersion >= 7 or effVersion>1:
    refLabel = RingerOperation.tostring( efficiencyKey )
  else:
    # Retrieve efficiency
    refFile = BenchmarkEfficiencyArchieve.load( filePath, loadCrossEfficiencies=False)
    from TuningTools.coreDef import dataframeConf
    dataframeConf.auto_retrieve_testing_sample( refFile.signalEfficiencies )
    wrapper = _compatibility_version6_dicts()
    refLabel = wrapper[efficiencyKey]
    efficiencyKey = wrapper[efficiencyKey]
  return efficiencyKey, refLabel

def _compatibility_version6_dicts():
  from TuningTools.coreDef import dataframeConf
  from TuningTools import Dataframe, RingerOperation
  if dataframeConf() is Dataframe.PhysVal:
    return { RingerOperation.L2Calo                      : 'L2CaloAccept'
           , RingerOperation.L2                          : 'L2ElAccept'
           , RingerOperation.EFCalo                      : 'EFCaloAccept'
           , RingerOperation.HLT                         : 'HLTAccept'
           , RingerOperation.Offline_LH_VeryLoose        : None
           , RingerOperation.Offline_LH_Loose            : 'LHLoose'
           , RingerOperation.Offline_LH_Medium           : 'LHMedium'
           , RingerOperation.Offline_LH_Tight            : 'LHTight'
           , RingerOperation.Offline_LH                  : ['LHLoose','LHMedium','LHTight']
           , RingerOperation.Offline_CutBased_Loose      : 'CutBasedLoose'
           , RingerOperation.Offline_CutBased_Medium     : 'CutBasedMedium'
           , RingerOperation.Offline_CutBased_Tight      : 'CutBasedTight'
           , RingerOperation.Offline_CutBased            : ['CutBasedLoose','CutBasedMedium','CutBasedTight']
           }
  elif dataframeConf() is Dataframe.PhysVal_v2:
    return { RingerOperation.Trigger                     : 'Efficiency'}

  elif dataframeConf() is Dataframe.SkimmedNtuple:
    return { RingerOperation.L2Calo                  : None
           , RingerOperation.L2                      : None
           , RingerOperation.EFCalo                  : None
           , RingerOperation.HLT                     : None
           , RingerOperation.Offline_LH_VeryLoose    : 'elCand2_isVeryLooseLLH_Smooth_v11' # isVeryLooseLL2016_v11
           , RingerOperation.Offline_LH_Loose        : 'elCand2_isLooseLLH_Smooth_v11'
           , RingerOperation.Offline_LH_Medium       : 'elCand2_isMediumLLH_Smooth_v11'
           , RingerOperation.Offline_LH_Tight        : 'elCand2_isTightLLH_Smooth_v11'
           , RingerOperation.Offline_LH              : ['elCand2_isVeryLooseLLH_Smooth_v11'
                                                       ,'elCand2_isLooseLLH_Smooth_v11'
                                                       ,'elCand2_isMediumLLH_Smooth_v11'
                                                       ,'elCand2_isTightLLH_Smooth_v11']
           , RingerOperation.Offline_CutBased_Loose  : 'elCand2_isEMLoose2015'
           , RingerOperation.Offline_CutBased_Medium : 'elCand2_isEMMedium2015'
           , RingerOperation.Offline_CutBased_Tight  : 'elCand2_isEMTight2015'
           , RingerOperation.Offline_CutBased        : ['elCand2_isEMLoose2015'
                                                       ,'elCand2_isEMMedium2015'
                                                       ,'elCand2_isEMTight2015']
           }
