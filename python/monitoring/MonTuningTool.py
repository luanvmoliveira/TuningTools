#Author: Joao Victo da Fonseca Pinto
#Analysis framework

__all__ = ['MonTuningTool']

#Import necessary classes
from MonTuningInfo import MonTuningInfo
from TuningStyle import SetTuningStyle
from pprint        import pprint
from RingerCore    import calcSP, save, load, Logger, mkdir_p
import os

#Main class to plot and analyser the crossvalidStat object
#created by CrossValidStat class from tuningTool package
class MonTuningTool( Logger ):
  """
  Main class to plot and analyser the crossvalidStat object
  created by CrossValidStat class from tuningTool package
  """  
  #Hold all information abount the monitoring root file
  _infoObjs = list()
  #Init class
  def __init__(self, crossvalFileName, monFileName, **kw):
    from ROOT import TFile
    #Set all global setting from ROOT style plot!
    SetTuningStyle()
    Logger.__init__(self, kw)

    try:#Protection
      self._logger.info('Reading monRootFile (%s)',monFileName)
      self._rootObj = TFile(monFileName, 'read')
    except RuntimeError:
      raise RuntimeError('Could not open root monitoring file.')
    from RingerCore import load
    try:#Protection
      self._logger.info('Reading crossvalFile (%s)',crossvalFileName)
      crossvalObj = load(crossvalFileName)
    except RuntimeError:
      raise RuntimeError('Could not open pickle summary file.')
    #Loop over benchmarks
    for benchmarkName in crossvalObj.keys():
      #Must skip if ppchain collector
      if benchmarkName == 'infoPPChain':  continue
      #Add summary information into MonTuningInfo helper class
      self._logger.info('Creating MonTuningInfo for %s and the iterator object',benchmarkName)
      self._infoObjs.append( MonTuningInfo(benchmarkName, crossvalObj[benchmarkName] ) ) 
    #Loop over all benchmarks

    #Reading the data rings from path or object
    perfFile = kw.pop('perfFile', None)
    if perfFile:
      if type(perfFile) is str:
        from TuningTools import TuningDataArchieve
        TDArchieve = TuningDataArchieve(perfFile)
        self._logger.info(('Reading perf file with name %s')%(perfFile))
        try:
          with TDArchieve as data:
            #Always be the same bin for all infoObjs  
            etabin = self._infoObjs[0].etabin()
            etbin = self._infoObjs[0].etbin()
            self._data = (data['signal_patterns'][etbin][etabin], data['background_patterns'][etbin][etabin])
        except RuntimeError:
          raise RuntimeError('Could not open the patterns data file.')
      else:
        self._data = None


  #Main method to execute the monitoring 
  def __call__(self, **kw):
    """
      Call the Monitoring tool analysis, the args can be:
        basePath: holt the location where all plots and files will
                  be saved. (defalt is Mon/)
        doBeamer: Start beamer Latex presentation maker (Default is True)
        shortSliedes: Presentation only with tables (Default is False)
    """
    self.loop(**kw)

  #Loop over 
  def loop(self, **kw): 

    basepath    = kw.pop('basePath', 'Mon') 
    tuningReport= kw.pop('tuningReport', 'tuningReport') 
    doBeamer    = kw.pop('doBeamer', True)
    shortSlides = kw.pop('shortSlides', False)

    if shortSlides:
      self._logger.warning('Short slides enabled! Doing only tables...')

    wantedPlotNames = {'allBestTstSorts','allBestOpSorts','allWorstTstSorts', 'allWorstOpSorts',\
                       'allBestTstNeurons','allBestOpNeurons', 'allWorstTstNeurons', 'allWorstOpNeurons'} 

    perfBenchmarks = dict()
    pathBenchmarks = dict()

    from PlotHelper import PlotsHolder, plot_4c
    from MonTuningInfo import MonPerfInfo

    #Loop over benchmarks
    for infoObj in self._infoObjs:
      #Initialize all plos
      plotObjects = dict()
      perfObjects = dict()
      pathObjects = dict()
      #Init PlotsHolder 
      for plotname in wantedPlotNames:  
        if 'Sorts' in plotname:
          plotObjects[plotname] = PlotsHolder(label = 'Sort')
        else:
          plotObjects[plotname] = PlotsHolder(label = 'Neuron')

      #Retrieve benchmark name
      benchmarkName = infoObj.name()
      #Retrieve reference name
      reference = infoObj.reference()
      #summary
      csummary = infoObj.summary()
      #benchmark object
      cbenchmark = infoObj.rawBenchmark()
      #Eta bin
      etabin = infoObj.etabin()
      #Et bin
      etbin = infoObj.etbin()
      basepath+=('_et%d_eta%d')%(etbin,etabin)

      self._logger.info(('Start loop over the benchmark: %s and etaBin = %d etBin = %d')%(benchmarkName,etabin, etbin)  )
      import copy
      #Loop over neuron, sort, inits. Creating plot objects
      for neuron, sort, inits in infoObj.iterator():
       
        sortName = 'sort_'+str(sort)
        #Create path list from initBound list          
        initPaths = [('%s/config_%s/sort_%s/init_%s')%(benchmarkName,\
                                                       neuron,sort,init) for init in inits]
        self._logger.debug('Creating init plots into the path: %s, (neuron_%s,sort_%s)', \
                            benchmarkName, neuron, sort)
        obj = PlotsHolder(label = 'Init')
        try: #Create plots holder class (Helper), store all inits
          obj.retrieve(self._rootObj, initPaths)
        except RuntimeError:
          raise RuntimeError('Can not create plot holder object')
        #Hold all inits from current sort
        obj.setIdxCorrection(inits)

        neuronName = 'config_'+str(neuron);  sortName = 'sort_'+str(sort)
        csummary[neuronName][sortName]['tstPlots'] = copy.copy(obj)
        csummary[neuronName][sortName]['opPlots']  = copy.copy(obj)

        # Hold all init plots objects
        csummary[neuronName][sortName]['tstPlots'].setBestIdx(csummary[neuronName][sortName]['infoTstBest']['init'])
        csummary[neuronName][sortName]['tstPlots'].setWorstIdx(csummary[neuronName][sortName]['infoTstWorst']['init'])
        csummary[neuronName][sortName]['opPlots'].setBestIdx(csummary[neuronName][sortName]['infoOpBest']['init'])
        csummary[neuronName][sortName]['opPlots'].setWorstIdx(csummary[neuronName][sortName]['infoOpWorst']['init'])
      #Loop over neuron, sort


      # Creating plots
      for neuron in infoObj.neuronBounds():

        # Figure path location
        currentPath =  ('%s/figures/%s/%s') % (basepath,benchmarkName,'neuron_'+str(neuron))
        neuronName = 'config_'+str(neuron)
        # Create folder to store all plot objects
        mkdir_p(currentPath)
        #Clear all hold plots stored
        plotObjects['allBestTstSorts'].clear()
        plotObjects['allBestOpSorts'].clear()
        #plotObjects['allWorstTstSorts'].clear()
        #plotObjects['allWorstOpSorts'].clear()

        for sort in infoObj.sortBounds(neuron):
          sortName = 'sort_'+str(sort)
          plotObjects['allBestTstSorts'].append(  copy.copy(csummary[neuronName][sortName]['tstPlots'].getBest() ) )
          plotObjects['allBestOpSorts'].append(   copy.copy(csummary[neuronName][sortName]['opPlots'].getBest()  ) )
          #plotObjects['allWorstTstSorts'].append( csummary[neuronName][sortName]['tstPlots'].getBest() )
          #plotObjects['allWorstOpSorts'].append(  csummary[neuronName][sortName]['opPlots'].getBest()  )
        #Loop over sorts


        
        plotObjects['allBestTstSorts'].setIdxCorrection(  infoObj.sortBounds(neuron) )
        plotObjects['allBestOpSorts'].setIdxCorrection(   infoObj.sortBounds(neuron) )
        #plotObjects['allWorstTstSorts'].setIdxCorrection( infoObj.sortBounds(neuron) )
        #plotObjects['allWorstOpSorts'].setIdxCorrection(  infoObj.sortBounds(neuron) )
        

        # Best and worst sorts for this neuron configuration
        plotObjects['allBestTstSorts'].setBestIdx(  csummary[neuronName]['infoTstBest']['sort']  )
        plotObjects['allBestTstSorts'].setWorstIdx( csummary[neuronName]['infoTstWorst']['sort'] )
        plotObjects['allBestOpSorts'].setBestIdx(   csummary[neuronName]['infoOpBest']['sort']   )
        plotObjects['allBestOpSorts'].setWorstIdx(  csummary[neuronName]['infoOpWorst']['sort']  )
  
        # Best and worst neuron sort for this configuration
        plotObjects['allBestTstNeurons'].append( copy.copy(plotObjects['allBestTstSorts'].getBest()   ))
        plotObjects['allBestOpNeurons'].append(  copy.copy(plotObjects['allBestOpSorts'].getBest()    ))
        plotObjects['allWorstTstNeurons'].append(copy.copy(plotObjects['allBestTstSorts'].getWorst() ))
        plotObjects['allWorstOpNeurons'].append( copy.copy(plotObjects['allBestOpSorts'].getWorst()  ))
        
        # Create perf (tables) Objects for test and operation (Table)
        perfObjects['neuron_'+str(neuron)] =  MonPerfInfo(benchmarkName, reference, 
                                                          csummary[neuronName]['summaryInfoTst'], 
                                                          csummary[neuronName]['infoOpBest'], 
                                                          cbenchmark) 

        # Debug information
        self._logger.info(('Crossval indexs: (bestSort = %d, bestInit = %d) (worstSort = %d, bestInit = %d)')%\
              (plotObjects['allBestTstSorts'].best, plotObjects['allBestTstSorts'].getBest()['bestInit'],
               plotObjects['allBestTstSorts'].worst, plotObjects['allBestTstSorts'].getWorst()['bestInit']))
        self._logger.info(('Operation indexs: (bestSort = %d, bestInit = %d) (worstSort = %d, bestInit = %d)')%\
              (plotObjects['allBestOpSorts'].best, plotObjects['allBestOpSorts'].getBest()['bestInit'],
               plotObjects['allBestOpSorts'].worst, plotObjects['allBestOpSorts'].getWorst()['bestInit']))



        opt = dict()
        opt['reference'] = reference
        svec = infoObj.sortBounds(neuron)
        # Configuration of each sort val plot: (Figure 1)
        opt['label']     = ('#splitline{#splitline{Total sorts: %d}{etaBin: %d, etBin: %d}}'+\
                            '{#splitline{sBestIdx: %d iBestIdx: %d}{sWorstIdx: %d iBestIdx: %d}}') % \
                           (plotObjects['allBestTstSorts'].size(),etabin, etbin, plotObjects['allBestTstSorts'].best, \
                            plotObjects['allBestTstSorts'].getBest()['bestInit'], plotObjects['allBestTstSorts'].worst,\
                            plotObjects['allBestTstSorts'].getWorst()['bestInit'])

        opt['cname']     = ('%s/plot_%s_neuron_%s_sorts_val')%(currentPath,benchmarkName,neuron)
        opt['set']       = 'val'
        opt['operation'] = False
        opt['paintListIdx'] = [plotObjects['allBestTstSorts'].best, plotObjects['allBestTstSorts'].worst]
        pname1 = plot_4c(plotObjects['allBestTstSorts'], opt)

        # Configuration of each sort operation plot: (Figure 2)
        opt['label']     = ('#splitline{#splitline{Total sorts: %d (operation)}{etaBin: %d, etBin: %d}}'+\
                            '{#splitline{sBestIdx: %d iBestIdx: %d}{sWorstIdx: %d iBestIdx: %d}}') % \
                           (plotObjects['allBestOpSorts'].size(),etabin, etbin, plotObjects['allBestOpSorts'].best, \
                            plotObjects['allBestOpSorts'].getBest()['bestInit'], plotObjects['allBestOpSorts'].worst,\
                            plotObjects['allBestOpSorts'].getWorst()['bestInit'])

        opt['cname']     = ('%s/plot_%s_neuron_%s_sorts_op')%(currentPath,benchmarkName,neuron)
        opt['set']       = 'val'
        opt['operation'] = True
        opt['paintListIdx'] = [plotObjects['allBestOpSorts'].best, plotObjects['allBestOpSorts'].worst]
        pname2 = plot_4c(plotObjects['allBestOpSorts'], opt)


        # Configuration of best network plot: (Figure 3)
        opt['label']     = ('#splitline{#splitline{Best network neuron: %d}{etaBin: %d, etBin: %d}}'+\
                            '{#splitline{{sBestIdx: %d iBestIdx: %d}{}}') % \
                           (neuron,etabin, etbin, plotObjects['allBestOpSorts'].best, plotObjects['allBestOpSorts'].getBest()['bestInit'])
        opt['cname']     = ('%s/plot_%s_neuron_%s_best_op')%(currentPath,benchmarkName,neuron)
        opt['set']       = 'val'
        opt['operation'] = True
        splotObject = PlotsHolder()
        # The current neuron will be the last position of the plotObjects
        splotObject.append( plotObjects['allBestOpNeurons'][-1] )
        pname3 = plot_4c(splotObject, opt)
        
        # Best discriminator output (figure 4)
        from PlotHelper import plot_nnoutput
        opt['cname']     = ('%s/plot_%s_neuron_%s_best_op_output')%(currentPath,benchmarkName,neuron)
        opt['nsignal']   = self._data[0].shape[0]
        opt['nbackground'] = self._data[1].shape[0]
        opt['rocname'] = 'roc_op'
        pname4 = plot_nnoutput(splotObject,opt)
    

        # Map names for beamer, if you add a plot, you must add into
        # the path objects holder
        pathObjects['neuron_'+str(neuron)+'_sorts_val']      = pname1 
        pathObjects['neuron_'+str(neuron)+'_sort_op']        = pname2
        pathObjects['neuron_'+str(neuron)+'_best_op']        = pname3
        pathObjects['neuron_'+str(neuron)+'_best_op_output'] = pname4
  
      #Loop over neurons

      #Start individual operation plots
      #plot(plotObjects['neuronTstBest'], opt)

      #External 
      pathBenchmarks[benchmarkName]  = pathObjects
      perfBenchmarks[benchmarkName]  = perfObjects
    #Loop over benchmark


    #Start beamer presentation
    if doBeamer:
      from BeamerMonReport import BeamerMonReport
      from BeamerTemplates import BeamerPerfTables, BeamerFigure, BeamerBlocks
      #Eta bin
      etabin = self._infoObjs[0].etabin()
      #Et bin
      etbin = self._infoObjs[0].etbin()
      #Create the beamer manager
      beamer = BeamerMonReport(basepath+'/'+tuningReport, title = ('Tuning Report (et=%d, eta=%d)')%(etbin,etabin) )
      neuronBounds = self._infoObjs[0].neuronBounds()

      for neuron in neuronBounds:
        #Make the tables for crossvalidation
        ptableCross = BeamerPerfTables(frametitle= ['Neuron '+str(neuron)+': Cross Validation Performance',
                                                    'Neuron '+str(neuron)+": Operation Best Network"],
                                       caption=['Efficiencies from each benchmark.',
                                                'Efficiencies for the best operation network'])

        block = BeamerBlocks('Neuron '+str(neuron)+' Analysis', [('All sorts (validation)','All sorts evolution are ploted, each sort represents the best init;'),
                                                                 ('All sorts (operation)', 'All sorts evolution only for operation set;'),
                                                                 ('Best operation', 'Detailed analysis from the best sort discriminator.'),
                                                                 ('Tables','Cross validation performance')])
        if not shortSlides:  block.tolatex( beamer.file() )

        for info in self._infoObjs:
          #If we produce a short presentation, we do not draw all plots
          if not shortSlides:  
            bname = info.name().replace('OperationPoint_','')
            fig1 = BeamerFigure( pathBenchmarks[info.name()]['neuron_'+str(neuron)+'_sorts_val'].replace(basepath+'/',''), 0.7,
                               frametitle=bname+', Neuron '+str(neuron)+': All sorts (validation)') 
            fig2 = BeamerFigure( pathBenchmarks[info.name()]['neuron_'+str(neuron)+'_sort_op'].replace(basepath+'/',''), 0.7, 
                               frametitle=bname+', Neuron '+str(neuron)+': All sorts (operation)') 
            fig3 = BeamerFigure( pathBenchmarks[info.name()]['neuron_'+str(neuron)+'_best_op'].replace(basepath+'/',''), 0.7,
                               frametitle=bname+', Neuron '+str(neuron)+': Best Network') 
            fig4 = BeamerFigure( pathBenchmarks[info.name()]['neuron_'+str(neuron)+'_best_op_output'].replace(basepath+'/',''), 0.8,
                               frametitle=bname+', Neuron '+str(neuron)+': Best Network output') 
            
          
            #Draw figures into the tex file
            fig1.tolatex( beamer.file() )
            fig2.tolatex( beamer.file() )
            fig3.tolatex( beamer.file() )
            fig4.tolatex( beamer.file() )

          #Concatenate performance table, each line will be a benchmark
          #e.g: det, sp and fa
          ptableCross.add( perfBenchmarks[info.name()]['neuron_'+str(neuron)] ) 

        ptableCross.tolatex( beamer.file() )# internal switch is false to true: test
        ptableCross.tolatex( beamer.file() )# internal swotch is true to false: operation

      beamer.close()

  #End of loop()




