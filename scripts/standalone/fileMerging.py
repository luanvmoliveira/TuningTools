#!/usr/bin/env python

from RingerCore import csvStr2List, str_to_class, NotSet, BooleanStr, WriteMethod, \
                       get_attributes, expandFolders, Logger, getFilters, select, \
                       appendToFileName, ensureExtension, progressbar, LoggingLevel

from TuningTools.parsers import argparse, loggerParser, LoggerNamespace

from TuningTools import GridJobFilter

mainParser = argparse.ArgumentParser(description = 'Merge files into unique file.',
                                     add_help = False)
mainMergeParser = mainParser.add_argument_group( "Required arguments", "")
mainMergeParser.add_argument('-i','--inputFiles', action='store', 
    metavar='InputFiles', required = True, nargs='+',
    help = "The input files that will be used to generate a unique file")
mainMergeParser.add_argument('-o','--outputFile', action='store', 
    metavar='OutputFile', required = True, 
    help = "The output file generated")
mainMergeParser.add_argument('-wm','--writeMethod', action='store', 
    default = "ShUtil",
    help = "The write method to use. Possibles method are: " \
           + str(get_attributes( WriteMethod, onlyVars = True, getProtected = False))
           )
mainMergeParser.add_argument('--allowTmpFiles', action='store', 
    default = "True",
    help = "When reading .pic files, whether the creation of temporary files is enabled." \
           + str(get_attributes( BooleanStr, onlyVars = True, getProtected = False))
           )
optMergeParser = mainParser.add_argument_group( "Optional arguments", "")
optMergeParser.add_argument('--binFilters', action='store', default = NotSet, 
    help = """This option filter the files types from each job. It can be a string
    with the name of a class defined on python/CrossValidStat dedicated to automatically 
    separate the files or a comma separated list of patterns that identify unique group 
    of files for each bin. A python list can also be speficied. 

    E.g.: You can specify 'group001,group002' if you have file001.group001.pic, 
    file002.group001, file001.group002, file002.group002 available and group001 
    specifies one binning limit, and group002 another, both of them with 2 files 
    available in this case.
    When not set, all files are considered to be from the same binning. 
    """)
parser = argparse.ArgumentParser(description = 'Merge files into unique file.',
                                 parents = [mainParser, loggerParser],
                                 conflict_handler = 'resolve')

mainLogger = Logger.getModuleLogger(__name__)

import sys
if len(sys.argv)==1:
  parser.print_help()
  sys.exit(1)

## Retrieve parser args:
args = parser.parse_args( namespace = LoggerNamespace() )
## Treat special arguments
args.inputFiles = expandFolders( args.inputFiles )
if args.binFilters is not NotSet:
  try:
    args.binFilters = str_to_class( "TuningTools.CrossValidStat", args.binFilters )
  except TypeError:
    args.binFilters = csvStr2List( args.binFilters )
  args.binFilters = getFilters( args.binFilters, args.inputFiles, 
                                printf = mainLogger.info )
  args.inputFiles = select( args.inputFiles, args.binFilters ) 
  if len(args.binFilters) is 1:
    args.inputFiles = [args.inputFiles]
else:
  args.inputFiles = [args.inputFiles]

import re
searchFormat = re.compile(r'.*\.(tar.gz|tgz|pic)(\.[0-9]*)?$')

for idx, fileCollection in enumerate(args.inputFiles):
  m = searchFormat.match( fileCollection[0] )
  # Treat output file name:
  try:
    cOutputName = appendToFileName( args.outputFile, args.binFilters[idx] )
  except (IndexError, TypeError,):
    if len(args.inputFiles) > 1:
      cOutputName = appendToFileName( args.outputFile, str(idx) )
    else:
      cOutputName = args.outputFile
  cOutputName = ensureExtension( cOutputName, 'tar.gz|tgz' )
  if m:
    file_format = m.group(1)
    wantedFormat = re.compile(r'.*\.' + file_format + r'(\.[0-9]*)?$')
    isSame = [ bool(wantedFormat.match(filename)) for filename in fileCollection ]
    from RingerCore.util import cat_files_py
    if all(isSame):
      if file_format in ("tgz", "tar.gz"):
        cat_files_py( fileCollection, cOutputName, args.writeMethod, mainLogger )
      elif file_format == "pic":
        if BooleanStr.retrieve(args.allowTmpFiles):
          import tempfile
          tmpFolderPath=tempfile.mkdtemp()
          for inputFile in progressbar(fileCollection, len(fileCollection), prefix="Compressing: ", 
                                       disp = True if mainLogger is not None else False, step = 10,
                                       logger = mainLogger, level = LoggingLevel.INFO ):
            import subprocess
            import os.path
            lFile = os.path.split(inputFile)[-1]
            subprocess.Popen(['tar', '-czf',
                             tmpFolderPath + '/' + ensureExtension( lFile, '.tgz|.tar.gz'), 
                             os.path.relpath(inputFile)])
          cat_files_py( expandFolders( tmpFolderPath ), cOutputName, args.writeMethod, mainLogger )
          import shutil
          shutil.rmtree(tmpFolderPath)
        else:
          import tarfile
          with tarfile.open(cOutputName, "w:gz") as tar:
            for inputFile in progressbar(fileCollection, len(fileCollection), prefix="Merging: ", 
                                         disp = True if mainLogger is not None else False, step = 10,
                                         logger = mainLogger, level = LoggingLevel.INFO ):
              tar.add(inputFile)
        # TODO gzip files
      else:
        raise NotImplementedError("Cannot merge files with format '%s'." % file_format)
    else:
      raise RuntimeError("Not all files format are the same!")
  else:
    raise RuntimeError("Couldn't retrieve file format! Scanned file: '%s'" % fileCollection[0])
# end of (for fileCollection)

