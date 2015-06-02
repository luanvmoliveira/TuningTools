#!/usr/bin/python

import sys
import os
import pickle
from CrossValid import *
from util       import *

def include(filename):
  if os.path.exists(filename): 
    execfile(filename)

DatasetLocationInput              = '/afs/cern.ch/user/j/jodafons/public/valid_ringer_sample.pic'


print 'openning data and normalize...'
filehandler       = open(DatasetLocationInput, 'r')
objectsFromFile   = pickle.load(filehandler)

#Job option configuration
Data                              = normalizeSumRow( objectsFromFile[0] )
Target                            = objectsFromFile[1]
CrossValidObject                  = objectsFromFile[2]
OutputName                        = 'output.save'
MonitoringLevel                   = 2
NumberOfInitsPerSort              = 1
NumberOfSortsPerConfigurationMin  = 1
NumberOfSortsPerConfigurationMax  = 1
NumberOfNeuronsInHiddenLayerMin   = 2
NumberOfNeuronsInHiddenLayerMax   = 2
DoMultiStops                      = True
ShowEvolution                     = 4

include('../python/jobs/NeuralTrainingLoop_fastnet_topOption.py')


