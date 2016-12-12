/*
 * bias.h
 *
 *  Copyright (C) 2013 Diamond Light Source
 *
 *  Author: James Parkhurst
 *
 *  This code is distributed under the BSD license, a copy of which is
 *  included in the root directory of this package.
 */
#ifndef DIALS_ALGORITHMS_IMAGE_CENTROID_BIAS_H
#define DIALS_ALGORITHMS_IMAGE_CENTROID_BIAS_H

#include <dials/error.h>

namespace dials { namespace algorithms {

  /**
   * A function to compute an estimate of the average centroid bias_sq
   * assuming a gaussian profile for the spot. For large sigma (> 0.5 pixels)
   * this is zero. For zero sigma (i.e. a delta function) this is 1/12.
   * Otherwise, we get the values from a lookup table generated from the
   * dev.dials.generate_bias_lookup_table command
   */
  inline
  double centroid_bias_sq(double variance) {

    DIALS_ASSERT(variance >= 0);

    // A lookup in 0.01 increments of sigma
    double lookup[50] = {
      0.0833333,
      0.0777914,
      0.0724495,
      0.0673076,
      0.0623657,
      0.0576239,
      0.0530820,
      0.0487401,
      0.0445982,
      0.0406563,
      0.0369144,
      0.0333725,
      0.0300306,
      0.0268887,
      0.0239468,
      0.0212048,
      0.0186625,
      0.0163194,
      0.0141742,
      0.0122246,
      0.0104667,
      0.0088951,
      0.0075022,
      0.0062790,
      0.0052146,
      0.0042969,
      0.0035131,
      0.0028497,
      0.0022935,
      0.0018313,
      0.0014508,
      0.0011403,
      0.0008892,
      0.0006879,
      0.0005281,
      0.0004021,
      0.0003038,
      0.0002278,
      0.0001694,
      0.0001250,
      0.0000915,
      0.0000665,
      0.0000479,
      0.0000342,
      0.0000243,
      0.0000171,
      0.0000119,
      0.0000083,
      0.0000057,
      0.0000039,
    };

    // Get the index
    double sigma = std::sqrt(variance);
    std::size_t index = std::floor(sigma / 0.01);
    if (index >= 50) {
      return 0.0;
    }
    return lookup[index];
  }

}}

#endif /* DIALS_ALGORITHMS_IMAGE_CENTROID_BIAS_H */