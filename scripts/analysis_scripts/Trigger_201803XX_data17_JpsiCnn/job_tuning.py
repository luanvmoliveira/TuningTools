#/usr/bin/env python
from timeit import default_timer as timer
from RingerCore.Logger import Logger, LoggingLevel
from TuningTools.TuningJob import TuningJob
from TuningTools.PreProc import *
from TuningTools.TuningJob import fixPPCol
from TuningTools.coreDef      import coreConf, TuningToolCores
from TuningTools.TuningJob    import ReferenceBenchmark,   ReferenceBenchmarkCollection, BatchSizeMethod
from RingerCore.Configure import Development
import logging
import argparse


start = timer()
Development.set( True )
coreConf.set(TuningToolCores.keras)
#coreConf.set(TuningToolCores.FastNet)



mainLogger = Logger.getModuleLogger("job")
parser = argparse.ArgumentParser(description = '', add_help = False)
parser = argparse.ArgumentParser()

parser.add_argument('-d','--data', action='store', 
    dest='data', required = True,
    help = "The input tuning files.")

parser.add_argument('-g','--gpu', action='store', 
    dest='gpu', required = False, default='0',
    help = "The GPU slot number.")


import sys,os
if len(sys.argv)==1:
  parser.print_help()
  sys.exit(1)
args = parser.parse_args()

os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu


from keras.models import Sequential
from keras.layers import Dense, Dropout, Flatten, Conv2D, MaxPooling2D, Activation
model = Sequential()
model.add(Conv2D(8, kernel_size=(2, 2), activation='relu', input_shape=(10,10,1)) ) # 8X8
model.add(Conv2D(16, (2, 2), activation='relu')) # 6X6
model.add(Flatten())
model.add(Dropout(0.25))
model.add(Dense(128, activation='relu'))
model.add(Dense(1))
model.add(Activation('tanh'))


## get et/eta index by hand
d = args.data
d=d.replace('.npz','')
d=d.split('_')
end=len(d)-1
et = int(d[end-1].replace('et',''))
eta = int(d[end].replace('eta',''))

tuningJob = TuningJob()
tuningJob( args.data, 
           epochs = 1000,
           batchSize= 1024*4,
           showEvo = 1,
           level = 9,
           etBins = et,
           etaBins = eta,
           doMultiStop=False,
           reshapeStrategy = RingerReshapeStrategy.AllLayers,
           modelBoundsCol = [model], 
           #neuronBoundsCol = [5, 20], 
           sortBoundsCol = [0, 10],
           initBoundsCol = 10,
           #crossValidFile= 'data_cern/files/crossValid.GRL_v97.pic.gz',
           )
end = timer()

print 'execution time is: ', (end - start)      
