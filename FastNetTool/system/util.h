

#ifndef FASTNETTOOL_UTIL_H
#define FASTNETTOOL_UTIL_H

#include <ctime>
#include <cstdlib>
#include <iostream>
#include <vector>
#include <map>
#include "math.h"

//Define system variables
#include "FastNetTool/system/defines.h"

namespace util{

  ///Return a float random number between min and max value
  ///This function will be used to generate the weight random numbers
  float rand_float_range(float min = -1.0, float max = 1.0);
  ///Return the norm of the weight
  REAL get_norm_of_weight( REAL *weight , size_t size);

}

#endif
