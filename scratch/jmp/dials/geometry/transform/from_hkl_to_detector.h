
#ifndef DIALS_GEOMETRY_TRANSFORM_FROM_HKL_TO_DETECTOR_H
#define DIALS_GEOMETRY_TRANSFORM_FROM_HKL_TO_DETECTOR_H

#include "from_hkl_to_beam_vector.h"
#include "from_beam_vector_to_detector.h"

namespace dials { namespace geometry { namespace transform {

/** A transform from miller indices to detector coordinates */
class FromHklToDetector {

public:

    /** Default constructor */
    FromHklToDetector() {}

    /**
     * Initialise the transform using component transform objects.
     * @param hkl_to_s1 The hkl to beam vector transform
     * @param s1_to_xy The beam vector to detector transform
     */
    FromHklToDetector(FromHklToBeamVector hkl_to_s1,
                      FromBeamVectorToDetector s1_to_xy)
        : hkl_to_s1_(hkl_to_s1),
          s1_to_xy_(s1_to_xy) {}
     
    /**
     * Initialise the transform using component transform objects.
     * @param rlcs The reciprocal lattice coordinate system class
     * @param s0 The incident beam vector
     * @param m2 The rotation axis
     * @param dcs The detector coordinate system
     * @param pixel_size The detector pixel size in mm     
     * @param origin The origin of the detector coordinate system
     * @param distance The distance from the detector to the crystal     
     */        
    FromHklToDetector(scitbx::mat3 <double> ub_matrix,
                      scitbx::vec3 <double> s0,
                      scitbx::vec3 <double> m2,
                      equipment::Detector detector)
        : hkl_to_s1_(ub_matrix, s0, m2),
          s1_to_xy_(detector) {}

public:

    /**
     * Apply the transform to the miller indices and rotation angle.
     * @param hkl The miller indices
     * @param phi The rotation angle
     * @returns The detector coordinates
     */
    scitbx::vec2 <double> apply(scitbx::vec3 <int> hkl, double phi) {
        return s1_to_xy_.apply(hkl_to_s1_.apply(hkl, phi));
    }

private:

    FromHklToBeamVector hkl_to_s1_;
    FromBeamVectorToDetector s1_to_xy_;
};

}}} // namespace = dials::geometry::transform

#endif // DIALS_GEOMETRY_TRANSFORM_FROM_HKL_TO_DETECTOR_H
