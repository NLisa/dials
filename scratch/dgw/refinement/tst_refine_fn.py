#!/usr/bin/env cctbx.python

# Copyright (C) (2012) David Waterman, STFC Rutherford Appleton Laboratory, UK.
# This code is developed as part of the DIALS project and is provided for
# testing purposes only

"""
Test refinement of beam, detector and crystal orientation parameters
using generated reflection positions from ideal geometry.

Control of the experimental model and choice of minimiser is done via
PHIL, which means we can do, for example:

cctbx.python tst_orientation_refinement.py \
"random_seed=3; engine=LBFGScurvs"

"""

# Python and cctbx imports
from __future__ import division
import sys
from math import pi
from scitbx import matrix
from libtbx.phil import parse

# Get modules to build models using PHIL
import setup_geometry

# Model parameterisations
from dials.scratch.dgw.refinement.detector_parameters import \
    DetectorParameterisationSinglePanel
from dials.scratch.dgw.refinement.source_parameters import \
    BeamParameterisationOrientation
from dials.scratch.dgw.refinement.crystal_parameters import \
    CrystalOrientationParameterisation, CrystalUnitCellParameterisation

# Symmetry constrained parameterisation for the unit cell
from cctbx.uctbx import unit_cell
from rstbx.symmetry.constraints.parameter_reduction import \
    symmetrize_reduce_enlarge

# Reflection prediction
from dials.algorithms.spot_prediction import IndexGenerator
from dials.scratch.dgw.prediction import ReflectionPredictor
from cctbx.sgtbx import space_group, space_group_symbols

# Parameterisation of the prediction equation
from dials.scratch.dgw.refinement.prediction_parameters import \
    DetectorSpacePredictionParameterisation

# Imports for the target function
from dials.scratch.dgw.refinement.target import \
    LeastSquaresPositionalResidualWithRmsdCutoff, ReflectionManager

# Import helper functions
from dials.scratch.dgw.refinement import print_model_geometry, refine

#############################
# Setup experimental models #
#############################

args = sys.argv[1:]
master_phil = parse("""
    include file geometry.params
    include file minimiser.params
    """, process_includes=True)

models = setup_geometry.Extract(master_phil, cmdline_args = args)

mydetector = models.detector
mygonio = models.goniometer
mycrystal = models.crystal
mybeam = models.beam

###########################
# Parameterise the models #
###########################

det_param = DetectorParameterisationSinglePanel(mydetector)
s0_param = BeamParameterisationOrientation(mybeam)
xlo_param = CrystalOrientationParameterisation(mycrystal)
xluc_param = CrystalUnitCellParameterisation(mycrystal)

# Fix beam to the X-Z plane (imgCIF geometry)
s0_param.set_fixed([True, False])

# Fix crystal parameters
#xluc_param.set_fixed([True, True, True, True, True, True])

########################################################################
# Link model parameterisations together into a parameterisation of the #
# prediction equation                                                  #
########################################################################

pred_param = DetectorSpacePredictionParameterisation(
mydetector, mybeam, mycrystal, mygonio, [det_param], [s0_param],
[xlo_param], [xluc_param])

################################
# Apply known parameter shifts #
################################

# shift detector by 1.0 mm each translation and 2 mrad each rotation
det_p_vals = det_param.get_p()
p_vals = [a + b for a, b in zip(det_p_vals,
                                [1.0, 1.0, 1.0, 2., 2., 2.])]
det_param.set_p(p_vals)

# shift beam by 2 mrad in free axis
s0_p_vals = s0_param.get_p()
p_vals = list(s0_p_vals)

p_vals[0] += 2.
s0_param.set_p(p_vals)

# rotate crystal a bit (=2 mrad each rotation)
xlo_p_vals = xlo_param.get_p()
p_vals = [a + b for a, b in zip(xlo_p_vals, [2., 2., 2.])]
xlo_param.set_p(p_vals)

# change unit cell a bit (=0.1 Angstrom length upsets, 0.1 degree of
# gamma angle)
xluc_p_vals = xluc_param.get_p()
cell_params = mycrystal.get_unit_cell().parameters()
cell_params = [a + b for a, b in zip(cell_params, [0.1, 0.1, 0.1, 0.0,
                                                   0.0, 0.1])]
new_uc = unit_cell(cell_params)
newB = matrix.sqr(new_uc.fractionalization_matrix()).transpose()
S = symmetrize_reduce_enlarge(mycrystal.get_space_group())
S.set_orientation(orientation=newB)
X = S.forward_independent_parameters()
xluc_param.set_p(X)

#############################
# Generate some reflections #
#############################

print "Reflections will be generated with the following geometry:"
print_model_geometry(mybeam, mydetector, mycrystal)
print "Target values of parameters are"
msg = "Parameters: " + "%.5f " * len(pred_param)
print msg % tuple(pred_param.get_p())
print

# All indices in a 2.0 Angstrom sphere
resolution = 2.0
index_generator = IndexGenerator(mycrystal.get_unit_cell(),
                space_group(space_group_symbols(1).hall()).type(), resolution)
indices = index_generator.to_array()

# Select those that are excited in a 180 degree sweep and get angles
UB = mycrystal.get_U() * mycrystal.get_B()
sweep_range = (0., pi)
ref_predictor = ReflectionPredictor(mycrystal, mybeam, mygonio, sweep_range)

obs_refs = ref_predictor.predict(indices)

print "Total number of reflections excited", len(obs_refs)

# Pull out reflection data as lists
temp = [(ref.miller_index, ref.rotation_angle,
         matrix.col(ref.beam_vector)) for ref in obs_refs]
hkls, angles, svecs = zip(*temp)

# Project positions on camera
# currently assume all reflections intersect panel 0
impacts = [mydetector[0].get_ray_intersection(
                        ref.beam_vector) for ref in obs_refs]
d1s, d2s = zip(*impacts)

print "Total number of observations made", len(hkls)

# Invent some uncertainties
im_width = 0.1 * pi / 180.
px_size = mydetector.get_pixel_size()
sigd1s = [px_size[0] / 2.] * len(hkls)
sigd2s = [px_size[1] / 2.] * len(hkls)
sigangles = [im_width / 2.] * len(hkls)

###############################
# Undo known parameter shifts #
###############################

s0_param.set_p(s0_p_vals)
det_param.set_p(det_p_vals)
xlo_param.set_p(xlo_p_vals)
xluc_param.set_p(xluc_p_vals)

print "Initial values of parameters are"
msg = "Parameters: " + "%.5f " * len(pred_param)
print msg % tuple(pred_param.get_p())
print

#####################################
# Select reflections for refinement #
#####################################

refman = ReflectionManager(hkls, svecs,
                        d1s, sigd1s,
                        d2s, sigd2s,
                        angles, sigangles,
                        mybeam, mygonio)

##############################
# Set up the target function #
##############################

# The current 'achieved' criterion compares RMSD against 1/3 the pixel size and
# 1/3 the image width in radians. For the simulated data, these are just made up
mytarget = LeastSquaresPositionalResidualWithRmsdCutoff(
    refman, ref_predictor, mydetector, pred_param, im_width)

###########################
# Use the refine function #
###########################

print "Prior to refinement the experimental model is:"
print_model_geometry(mybeam, mydetector, mycrystal)

refine(mybeam, mygonio, mycrystal, mydetector, im_width, sweep_range,
       hkls, svecs, d1s, sigd1s, d2s, sigd2s, angles, sigangles,
       verbosity = 1)

print
print "Refinement has completed with the following geometry:"
print_model_geometry(mybeam, mydetector, mycrystal)
