#!/usr/bin/env python
#
# dials.integrate.py
#
#  Copyright (C) 2013 Diamond Light Source
#
#  Author: James Parkhurst
#
#  This code is distributed under the BSD license, a copy of which is
#  included in the root directory of this package.

from __future__ import division
# DIALS_ENABLE_COMMAND_LINE_COMPLETION

help_message = '''

This program is used to integrate the reflections on the diffraction images. It
is called with an experiment list outputted from dials.index or dials.refine and
a corresponding set of strong spots from which a profile model is calculated.
The program will output a set of integrated reflections and an experiment list
with additional profile model data. The data can be reintegrated using the same
profile model by inputting this integrated_experiments.json file back into
dials.integate.

Examples::

  dials.integrate experiments.json indexed.pickle

  dials.integrate experiments.json indexed.pickle output.reflections=integrated.pickle

  dials.integrate experiments.json indexed.pickle profile.fitting=False

  dials.integrate experiments.json indexed.pickle background.algorithm=glm

'''

# Create the phil scope
from libtbx.phil import parse
phil_scope = parse(
'''

  output {
    experiments = 'integrated_experiments.json'
      .type = str
      .help = "The experiments output filename"

    reflections = 'integrated.pickle'
      .type = str
      .help = "The integrated output filename"

    phil = 'dials.integrate.phil'
      .type = str
      .help = "The output phil file"

    log = 'dials.integrate.log'
      .type = str
      .help = "The log filename"

    debug_log = 'dials.integrate.debug.log'
      .type = str
      .help = "The debug log filename"

    report = None
      .type = str
      .help = "The integration report filename (*.xml or *.json)"

    include_bad_reference = False
      .type = bool
      .help = "Include bad reference data including unindexed spots,"
              "and reflections whose predictions are messed up in the"
              "reflection table output. Reflections will have the"
              "'bad_reference' flag set."
  }

  scan_range = None
    .type = ints(size=2)
    .help = "Explicitly specify the images to be processed. Only applicable"
            "when experiment list contains a single imageset."
    .multiple = True

  sampling
    .expert_level = 1
  {

    reflections_per_degree = 50
      .help = "The number of predicted reflections per degree of the sweep "
              "to integrate."
      .type = float(value_min=0.)

    minimum_sample_size = 1000
      .help = "cutoff that determines whether subsetting of the input "
              "prediction list is done"
      .type = int

    maximum_sample_size = None
      .help = "The maximum number of predictions to integrate."
              "Overrides reflections_per_degree if that produces a"
              "larger sample size."
      .type = int(value_min=1)

    integrate_all_reflections = True
      .help = "Override reflections_per_degree and integrate all predicted"
              "reflections."
      .type = bool

  }

  verbosity = 1
    .type = int(value_min=0)
    .help = "The verbosity level"

  include scope dials.algorithms.integration.integrator.phil_scope
  include scope dials.algorithms.profile_model.factory.phil_scope
  include scope dials.algorithms.spot_prediction.reflection_predictor.phil_scope

''', process_includes=True)


class Script(object):
  ''' The integration program. '''

  def __init__(self):
    '''Initialise the script.'''
    from dials.util.options import OptionParser
    import libtbx.load_env

    # The script usage
    usage  = "usage: %s [options] experiment.json" % libtbx.env.dispatcher_name

    # Create the parser
    self.parser = OptionParser(
      usage=usage,
      phil=phil_scope,
      epilog=help_message,
      read_experiments=True,
      read_reflections=True)

  def run(self):
    ''' Perform the integration. '''
    from dials.util.command_line import heading
    from dials.util.options import flatten_reflections, flatten_experiments
    from dials.util import log
    from logging import info, debug
    from time import time
    from libtbx.utils import Sorry

    # Check the number of arguments is correct
    start_time = time()

    # Parse the command line
    params, options = self.parser.parse_args(show_diff_phil=False)
    reference = flatten_reflections(params.input.reflections)
    experiments = flatten_experiments(params.input.experiments)
    if len(reference) == 0 and len(experiments) == 0:
      self.parser.print_help()
      return
    if len(reference) == 0:
      reference = None
    elif len(reference) != 1:
      raise Sorry('more than 1 reflection file was given')
    else:
      reference = reference[0]
    if len(experiments) == 0:
      raise Sorry('no experiment list was specified')

    # Save phil parameters
    if params.output.phil is not None:
      with open(params.output.phil, "w") as outfile:
        outfile.write(self.parser.diff_phil.as_str())

    # Configure logging
    log.config(
      params.verbosity,
      info=params.output.log,
      debug=params.output.debug_log)

    from dials.util.version import dials_version
    info(dials_version())

    # Log the diff phil
    diff_phil = self.parser.diff_phil.as_str()
    if diff_phil is not '':
      info('The following parameters have been modified:\n')
      info(diff_phil)

    # Print if we're using a mask
    for i, exp in enumerate(experiments):
      mask = exp.imageset.external_lookup.mask
      if mask.filename is not None:
        info('Using external mask: %s' % mask.filename)
        info(' Mask has %d pixels masked' % mask.data.count(False))

    # Print the experimental models
    for i, exp in enumerate(experiments):
      debug("Models for experiment %d" % i)
      debug("")
      debug(str(exp.beam))
      debug(str(exp.detector))
      if exp.goniometer:
        debug(str(exp.goniometer))
      if exp.scan:
        debug(str(exp.scan))
      debug(str(exp.crystal))

    info("=" * 80)
    info("")
    info(heading("Initialising"))
    info("")

    # Load the data
    reference, rubbish = self.process_reference(reference)
    info("")

    # Initialise the integrator
    from dials.algorithms.profile_model.factory import ProfileModelFactory
    from dials.algorithms.integration.integrator import IntegratorFactory
    from dials.array_family import flex

    # Modify experiment list if scan range is set.
    experiments, reference = self.split_for_scan_range(
      experiments,
      reference,
      params.scan_range)

    # Predict the reflections
    info("")
    info("=" * 80)
    info("")
    info(heading("Predicting reflections"))
    info("")
    predicted = flex.reflection_table.from_predictions_multi(
      experiments,
      dmin=params.prediction.d_min,
      dmax=params.prediction.d_max,
      margin=params.prediction.margin,
      force_static=params.prediction.force_static)

    # Match reference with predicted
    if reference:
      matched, reference, unmatched = predicted.match_with_reference(reference)
      assert(len(matched) == len(predicted))
      assert(matched.count(True) <= len(reference))
      if matched.count(True) == 0:
        raise Sorry('''
          Invalid input for reference reflections.
          Zero reference spots were matched to predictions
        ''')
      elif len(unmatched) != 0:
        info('')
        info('*' * 80)
        info('Warning: %d reference spots were not matched to predictions' % (
          len(unmatched)))
        info('*' * 80)
        info('')
      rubbish.extend(unmatched)

    # Select a random sample of the predicted reflections
    if not params.sampling.integrate_all_reflections:
      predicted = self.sample_predictions(experiments, predicted, params)

    # Compute the profile model
    if reference is not None:
      experiments = ProfileModelFactory.create(params, experiments, reference)
      del reference

    # Compute the bounding box
    predicted.compute_bbox(experiments)

    # Create the integrator
    info("")
    integrator = IntegratorFactory.create(params, experiments, predicted)

    # Integrate the reflections
    reflections = integrator.integrate()

    # Append rubbish data onto the end
    if rubbish is not None and params.output.include_bad_reference:
      mask = flex.bool(len(rubbish), True)
      rubbish.unset_flags(mask, rubbish.flags.integrated_sum)
      rubbish.unset_flags(mask, rubbish.flags.integrated_prf)
      rubbish.set_flags(mask, rubbish.flags.bad_reference)
      reflections.extend(rubbish)

    # Save the reflections
    self.save_reflections(reflections, params.output.reflections)
    self.save_experiments(experiments, params.output.experiments)

    # Write a report if requested
    if params.output.report is not None:
      integrator.report().as_file(params.output.report)

    # Print the total time taken
    info("\nTotal time taken: %f" % (time() - start_time))

  def process_reference(self, reference):
    ''' Load the reference spots. '''
    from dials.array_family import flex
    from logging import info
    from time import time
    from libtbx.utils import Sorry
    if reference is None:
      return None, None
    st = time()
    assert("miller_index" in reference)
    assert("id" in reference)
    info('Processing reference reflections')
    info(' read %d strong spots' % len(reference))
    mask = reference.get_flags(reference.flags.indexed)
    rubbish = reference.select(mask == False)
    if mask.count(False) > 0:
      reference.del_selected(mask == False)
      info(' removing %d unindexed reflections' %  mask.count(False))
    if len(reference) == 0:
      raise Sorry('''
        Invalid input for reference reflections.
        Expected > %d indexed spots, got %d
      ''' % (0, len(reference)))
    mask = reference['miller_index'] == (0, 0, 0)
    if mask.count(True) > 0:
      rubbish.extend(reference.select(mask))
      reference.del_selected(mask)
      info(' removing %d reflections with hkl (0,0,0)' %  mask.count(True))
    mask = reference['id'] < 0
    if mask.count(True) > 0:
      raise Sorry('''
        Invalid input for reference reflections.
        %d reference spots have an invalid experiment id
      ''' % mask.count(True))
    info(' using %d indexed reflections' % len(reference))
    info(' found %d junk reflections' % len(rubbish))
    info(' time taken: %g' % (time() - st))
    return reference, rubbish

  def save_reflections(self, reflections, filename):
    ''' Save the reflections to file. '''
    from logging import info
    from time import time
    st = time()
    info('Saving %d reflections to %s' % (len(reflections), filename))
    reflections.as_pickle(filename)
    info(' time taken: %g' % (time() - st))

  def save_experiments(self, experiments, filename):
    ''' Save the profile model parameters. '''
    from logging import info
    from time import time
    from dxtbx.model.experiment.experiment_list import ExperimentListDumper
    st = time()
    info('Saving the experiments to %s' % filename)
    dump = ExperimentListDumper(experiments)
    with open(filename, "w") as outfile:
      outfile.write(dump.as_json())
    info(' time taken: %g' % (time() - st))

  def sample_predictions(self, experiments, predicted, params):
    ''' Select a random sample of the predicted reflections to integrate. '''
    from dials.array_family import flex
    nref_per_degree = params.sampling.reflections_per_degree
    min_sample_size = params.sampling.minimum_sample_size
    max_sample_size = params.sampling.maximum_sample_size

    # this code is very similar to David's code in algorithms/refinement/reflection_manager.py!

    # constants
    from math import pi
    RAD2DEG = 180. / pi
    DEG2RAD = pi / 180.

    working_isel = flex.size_t()
    for iexp, exp in enumerate(experiments):

      sel = predicted['id'] == iexp
      isel = sel.iselection()
      #refs = self._reflections.select(sel)
      nrefs = sample_size = len(isel)

      # set sample size according to nref_per_degree (per experiment)
      if exp.scan and nref_per_degree:
        sweep_range_rad = exp.scan.get_oscillation_range(deg=False)
        width = abs(sweep_range_rad[1] -
                    sweep_range_rad[0]) * RAD2DEG
        sample_size = int(nref_per_degree * width)
      else: sweep_range_rad = None

      # adjust sample size if below the chosen limit
      sample_size = max(sample_size, min_sample_size)

      # set maximum sample size if requested
      if max_sample_size:
        sample_size = min(sample_size, max_sample_size)

      # determine subset and collect indices
      if sample_size < nrefs:
        isel = isel.select(flex.random_selection(nrefs, sample_size))
      working_isel.extend(isel)

    # create subset
    return predicted.select(working_isel)

  def split_for_scan_range(self, experiments, reference, scan_range):
    ''' Update experiments when scan range is set. '''
    from dxtbx.model.experiment.experiment_list import ExperimentList
    from dxtbx.model.experiment.experiment_list import Experiment
    from logging import info
    from dials.array_family import flex

    # Only do anything is the scan range is set
    if scan_range is not None and len(scan_range) > 0:


      # Ensure that all experiments have the same imageset and scan
      iset = [e.imageset for e in experiments]
      scan = [e.scan for e in experiments]
      assert(all(x == iset[0] for x in iset))
      assert(all(x == scan[0] for x in scan))

      # Get the imageset and scan
      iset = experiments[0].imageset
      scan = experiments[0].scan

      # Get the array range
      if scan is not None:
        frame10, frame11 = scan.get_array_range()
        assert(scan.get_num_images() == len(iset))
      else:
        frame10, frame11 = (0, len(iset))

      # Create the new lists
      new_experiments = ExperimentList()
      new_reference_all = reference.split_by_experiment_id()
      new_reference = flex.reflection_table()
      for i in range(len(new_reference_all) - len(experiments)):
        new_reference_all.append(flex.reflection_table())
      assert(len(new_reference_all) == len(experiments))

      # Loop through all the scan ranges and create a new experiment list with
      # the requested scan ranges.
      for frame00, frame01 in scan_range:
        assert(frame01 >  frame00)
        assert(frame00 >= frame10)
        assert(frame01 <= frame11)
        index0 = frame00 - frame10
        index1 = index0 + (frame01 - frame00)
        assert(index0 < index1)
        assert(index0 >= 0)
        assert(index1 <= len(iset))
        new_iset = iset[index0:index1]
        if scan is None:
          new_scan = None
        else:
          new_scan = scan[index0:index1]
        for i, e1 in enumerate(experiments):
          e2 = Experiment()
          e2.beam = e1.beam
          e2.detector = e1.detector
          e2.goniometer = e1.goniometer
          e2.crystal = e1.crystal
          e2.imageset = new_iset
          e2.scan = new_scan
          new_reference_all[i]['id'] = flex.int(
            len(new_reference_all[i]), len(new_experiments))
          new_reference.extend(new_reference_all[i])
          new_experiments.append(e2)
      experiments = new_experiments
      reference = new_reference

      # Print some information
      info('Modified experiment list to integrate over requested scan range')
      for frame00, frame01 in scan_range:
        info(' scan_range = %d -> %d' % (frame00, frame01))
      info('')

    # Return the experiments
    return experiments, reference

if __name__ == '__main__':
  from dials.util import halraiser
  try:
    script = Script()
    script.run()
  except Exception as e:
    halraiser(e)
