#
# finder.py
#
#  Copyright (C) 2013 Diamond Light Source
#
#  Author: James Parkhurst
#
#  This code is distributed under the BSD license, a copy of which is
#  included in the root directory of this package.

from __future__ import division


class Result(object):
  '''
  A class to hold the result from spot finding on an image.

  When doing multi processing, we can process the result of
  each thread as it comes in instead of waiting for all results.
  The purpose of this class is to allow us to set the pixel list
  to None after each image to lower memory usage.

  '''

  def __init__(self, pixel_list):
    '''
    Set the pixel list

    '''
    self.pixel_list = pixel_list


class ExtractPixelsFromImage(object):
  '''
  A class to extract pixels from a single image

  '''

  def __init__(self,
               imageset,
               threshold_function,
               mask,
               region_of_interest,
               max_strong_pixel_fraction):
    '''
    Initialise the class

    :param imageset: The imageset to extract from
    :param threshold_function: The function to threshold with
    :param mask: The image mask
    :param region_of_interest: A region of interest to process
    :param max_strong_pixel_fraction: The maximum fraction of pixels allowed

    '''
    self.threshold_function = threshold_function
    self.imageset = imageset
    self.mask = mask
    self.region_of_interest = region_of_interest
    self.max_strong_pixel_fraction = max_strong_pixel_fraction
    if self.mask is not None:
      detector = self.imageset.get_detector()
      assert(len(self.mask) == len(detector))
    self.first = True

  def __call__(self, index):
    '''
    Extract strong pixels from an image

    :param index: The index of the image

    '''
    from dials.model.data import PixelList
    from dxtbx.imageset import ImageSweep
    from dials.array_family import flex
    from math import ceil
    from logging import info

    # Parallel reading of HDF5 from the same handle is not allowed. Python
    # multiprocessing is a bit messed up and used fork on linux so need to
    # close and reopen file.
    if self.first:
      from dxtbx.imageset import SingleFileReader
      if isinstance(self.imageset.reader(), SingleFileReader):
        self.imageset.reader().nullify_format_instance()
      self.first = False

    # Get the frame number
    if isinstance(self.imageset, ImageSweep):
      frame = self.imageset.get_array_range()[0] + index
    else:
      ind = self.imageset.indices()
      if len(ind) > 1:
        assert(all(i1+1 == i2 for i1, i2 in zip(ind[0:-1], ind[1:-1])))
      frame = ind[index]

    # Create the list of pixel lists
    pixel_list = []

    # Get the image and mask
    image = self.imageset.get_corrected_data(index)
    mask = self.imageset.get_mask(index)

    # Set the mask
    if self.mask is not None:
      assert(len(self.mask) == len(mask))
      mask = tuple(m1 & m2 for m1, m2 in zip(mask, self.mask))

    # Add the images to the pixel lists
    num_strong = 0
    for im, mk in zip(image, mask):
      if self.region_of_interest is not None:
        x0, x1, y0, y1 = self.region_of_interest
        height, width = im.all()
        assert x0 < x1, "x0 < x1"
        assert y0 < y1, "y0 < y1"
        assert x0 >= 0, "x0 >= 0"
        assert y0 >= 0, "y0 >= 0"
        assert x1 <= width, "x1 <= width"
        assert y1 <= height, "y1 <= height"
        im_roi = im[y0:y1,x0:x1]
        mk_roi = mk[y0:y1,x0:x1]
        tm_roi = self.threshold_function.compute_threshold(im_roi, mk_roi)
        threshold_mask = flex.bool(im.accessor(),False)
        threshold_mask[y0:y1,x0:x1] = tm_roi
      else:
        threshold_mask = self.threshold_function.compute_threshold(im, mk)

      # Add the pixel list
      plist = PixelList(frame, im, threshold_mask)
      pixel_list.append(plist)

      # Add to the spot count
      num_strong += len(plist)

    # Check total number of strong pixels
    if self.max_strong_pixel_fraction < 1:
      num_image = 0
      for im in image:
        num_image += len(im)
      max_strong = int(ceil(self.max_strong_pixel_fraction * num_image))
      if num_strong > max_strong:
        raise RuntimeError(
          '''
          The number of strong pixels found (%d) is greater than the
          maximum allowed (%d). Try changing spot finding parameters
        ''' % (num_strong, max_strong))

    # Print some info
    info("Found %d strong pixels on image %d" % (num_strong, index + 1))

    # Return the result
    return Result(pixel_list)


class ExtractSpotsParallelTask(object):
  '''
  Execute the spot finder task in parallel

  We need this external class so that we can pickle it for cluster jobs

  '''
  def __init__(self, function):
    '''
    Initialise with the function to call

    '''
    self.function = function

  def __call__(self, task):
    '''
    Call the function with th task and save the IO

    '''
    from cStringIO import StringIO
    from dials.util import log
    import logging
    log.config_simple_cached()
    result = self.function(task)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1, "Invalid number of logging handlers"
    return result, handlers[0].messages()


class ExtractSpots(object):
  '''
  Class to find spots in an image and extract them into shoeboxes.

  '''

  def __init__(self,
               threshold_function=None,
               mask=None,
               region_of_interest=None,
               max_strong_pixel_fraction=0.1,
               mp_method=None,
               mp_nproc=1,
               mp_njobs=1,
               mp_chunksize=1,
               min_spot_size=1,
               max_spot_size=20):
    '''
    Initialise the class with the strategy

    :param threshold_function: The image thresholding strategy
    :param mask: The mask to use
    :param mp_method: The multi processing method
    :param nproc: The number of processors
    :param max_strong_pixel_fraction: The maximum number of strong pixels

    '''
    # Set the required strategies
    self.threshold_function = threshold_function
    self.mask = mask
    self.mp_method = mp_method
    self.mp_chunksize = mp_chunksize
    self.mp_nproc = mp_nproc
    self.mp_njobs = mp_njobs
    self.max_strong_pixel_fraction = max_strong_pixel_fraction
    self.region_of_interest = region_of_interest
    self.min_spot_size = min_spot_size
    self.max_spot_size = max_spot_size

  def __call__(self, imageset):
    '''
    Find the spots in the imageset

    :param imageset: The imageset to process
    :return: The list of spot shoeboxes

    '''
    from dials.util.command_line import Command
    from dials.array_family import flex
    from dxtbx.imageset import ImageSweep
    from dials.model.data import PixelListLabeller
    from dials.util.mp import batch_multi_node_parallel_map
    from logging import info, warn
    from math import floor, ceil
    import platform
    from logging import warn

    # Change the number of processors if necessary
    mp_nproc = self.mp_nproc
    mp_njobs = self.mp_njobs
    if platform.system() == "Windows" and (mp_nproc > 1 or mp_njobs > 1):
      warn("")
      warn("*" * 80)
      warn("Multiprocessing is not available on windows. Setting nproc = 1, njobs = 1")
      warn("*" * 80)
      warn("")
      mp_nproc = 1
      mp_njobs = 1
    if mp_nproc * mp_njobs > len(imageset):
      mp_nproc = min(mp_nproc, len(imageset))
      mp_njobs = int(ceil(len(imageset) / mp_nproc))

    mp_method = self.mp_method
    mp_chunksize = self.mp_chunksize

    import libtbx
    if mp_chunksize == libtbx.Auto:
      import math
      mp_chunksize = int(math.ceil(len(imageset) / (mp_njobs * mp_nproc)))
      info("Setting chunksize=%i" %mp_chunksize)

    len_by_nproc = int(floor(len(imageset) / (mp_njobs * mp_nproc)))
    if mp_chunksize > len_by_nproc:
      mp_chunksize = len_by_nproc
    assert mp_nproc > 0, "Invalid number of processors"
    assert mp_njobs > 0, "Invalid number of jobs"
    assert mp_njobs == 1 or mp_method is not None, "Invalid cluster method"
    assert mp_chunksize > 0, "Invalid chunk size"

    # The extract pixels function
    function = ExtractPixelsFromImage(
        imageset                  = imageset,
        threshold_function        = self.threshold_function,
        mask                      = self.mask,
        max_strong_pixel_fraction = self.max_strong_pixel_fraction,
        region_of_interest        = self.region_of_interest)

    # The indices to iterate over
    indices = list(range(len(imageset)))

    # Initialise the pixel labeller
    num_panels = len(imageset.get_detector())
    pixel_labeller = [PixelListLabeller() for p in range(num_panels)]

    # Do the processing
    info('Extracting strong pixels from images')
    if mp_njobs > 1:
      info(' Using %s with %d parallel job(s) and %d processes per node\n' % (mp_method, mp_njobs, mp_nproc))
    else:
      info(' Using multiprocessing with %d parallel job(s)\n' % (mp_nproc))
    if mp_nproc > 1 or mp_njobs > 1:
      def process_output(result):
        import logging
        for message in result[1]:
          logging.log(message.levelno, message.msg)
        assert len(pixel_labeller) == len(result[0].pixel_list), "Inconsistent size"
        for plabeller, plist in zip(pixel_labeller, result[0].pixel_list):
          plabeller.add(plist)
        result[0].pixel_list = None
      batch_multi_node_parallel_map(
        func           = ExtractSpotsParallelTask(function),
        iterable       = indices,
        nproc          = mp_nproc,
        njobs          = mp_njobs,
        cluster_method = mp_method,
        chunksize      = mp_chunksize,
        callback       = process_output)
    else:
      for task in indices:
        result = function(task)
        assert len(pixel_labeller) == len(result.pixel_list), "Inconsistent size"
        for plabeller, plist in zip(pixel_labeller, result.pixel_list):
          plabeller.add(plist)
          result.pixel_list = None

    # Extract the pixel lists into a list of reflections
    shoeboxes = flex.shoebox()
    spotsizes = flex.size_t()
    if isinstance(imageset, ImageSweep):
      twod = False
    else:
      twod = True
    for i, p in enumerate(pixel_labeller):
      if p.num_pixels() > 0:
        creator = flex.PixelListShoeboxCreator(
            p,
            i,                   # panel
            0,                   # zrange
            twod,                # twod
            self.min_spot_size,  # min_pixels
            self.max_spot_size)  # max_pixels
        shoeboxes.extend(creator.result())
        spotsizes.extend(creator.spot_size())
    info('')
    info('Extracted {0} spots'.format(len(shoeboxes)))

    # Get the unallocated spots and print some info
    selection = shoeboxes.is_allocated()
    shoeboxes = shoeboxes.select(selection)
    ntoosmall = (spotsizes < self.min_spot_size).count(True)
    ntoolarge = (spotsizes > self.max_spot_size).count(True)
    assert ntoosmall + ntoolarge == selection.count(False)
    info('Removed %d spots with size < %d pixels' % (
      ntoosmall,
      self.min_spot_size))
    info('Removed %d spots with size > %d pixels' % (
      ntoolarge,
      self.max_spot_size))

    # Return the shoeboxes
    return shoeboxes


class SpotFinder(object):
  '''
  A class to do spot finding and filtering.

  '''

  def __init__(self,
               threshold_function=None,
               mask=None,
               region_of_interest=None,
               max_strong_pixel_fraction=0.1,
               mp_method=None,
               mp_nproc=1,
               mp_njobs=1,
               mp_chunksize=1,
               mask_generator=None,
               filter_spots=None,
               scan_range=None,
               write_hot_mask=True,
               min_spot_size=1,
               max_spot_size=20):
    '''
    Initialise the class.

    :param find_spots: The spot finding algorithm
    :param filter_spots: The spot filtering algorithm
    :param scan_range: The scan range to find spots over

    '''

    # Set the filter and some other stuff
    self.threshold_function = threshold_function
    self.mask = mask
    self.region_of_interest = region_of_interest
    self.max_strong_pixel_fraction = max_strong_pixel_fraction
    self.mask_generator = mask_generator
    self.filter_spots = filter_spots
    self.scan_range = scan_range
    self.write_hot_mask = write_hot_mask
    self.min_spot_size = min_spot_size
    self.max_spot_size = max_spot_size
    self.mp_method = mp_method
    self.mp_chunksize = mp_chunksize
    self.mp_nproc = mp_nproc
    self.mp_njobs = mp_njobs

  def __call__(self, datablock):
    '''
    Do the spot finding.

    :param datablock: The datablock to process
    :return: The observed spots

    '''
    from dials.array_family import flex
    from logging import info
    import cPickle as pickle

    # Loop through all the imagesets and find the strong spots
    reflections = flex.reflection_table()
    for i, imageset in enumerate(datablock.extract_imagesets()):

      # Find the strong spots in the sweep
      info('-' * 80)
      info('Finding strong spots in imageset %d' % i)
      info('-' * 80)
      info('')
      table, hot_mask = self._find_in_imageset(imageset)
      table['id'] = flex.int(table.nrows(), i)
      reflections.extend(table)

      # Write a hot pixel mask
      if self.write_hot_mask:
        if imageset.external_lookup.mask.data is not None:
          and_mask = []
          for m1, m2 in zip(imageset.external_lookup.mask.data, hot_mask):
            and_mask.append(m1 & m2)
          imageset.external_lookup.mask.data = tuple(and_mask)
        else:
          imageset.external_lookup.mask.data = hot_mask
        imageset.external_lookup.mask.filename = "hot_mask_%d.pickle" % i

        # Write the hot mask
        with open(imageset.external_lookup.mask.filename, "wb") as outfile:
          pickle.dump(hot_mask, outfile, protocol=pickle.HIGHEST_PROTOCOL)

    # Set the strong spot flag
    reflections.set_flags(
      flex.size_t_range(len(reflections)),
      reflections.flags.strong)

    # Check for overloads
    reflections.is_overloaded(datablock)

    # Return the reflections
    return reflections

  def _find_in_imageset(self, imageset):
    '''
    Do the spot finding.

    :param imageset: The imageset to process
    :return: The observed spots

    '''
    from dials.util.masking import MaskGenerator
    from dials.array_family import flex
    from dials.util.command_line import Command
    from dxtbx.imageset import ImageSweep
    from logging import info

    # The input mask
    mask = self.mask_generator.generate(imageset)
    if self.mask is not None:
      mask = tuple(m1 & m2 for m1, m2 in zip(mask, self.mask))

    # FIXME for dials-171 in here extend or adapt to include capability to
    # perform full spot finding process i.e. derive centroids etc. if
    # not isinstance(imageset, ImageSweep) && params.output.shoeboxes is False
    # suggest best way to do that would be to add new method (say)
    # _find_in_imagegrid

    # Set the spot finding algorithm
    extract_spots = ExtractSpots(
      threshold_function        = self.threshold_function,
      mask                      = mask,
      region_of_interest        = self.region_of_interest,
      max_strong_pixel_fraction = self.max_strong_pixel_fraction,
      mp_method                 = self.mp_method,
      mp_nproc                  = self.mp_nproc,
      mp_njobs                  = self.mp_njobs,
      mp_chunksize              = self.mp_chunksize,
      min_spot_size             = self.min_spot_size,
      max_spot_size             = self.max_spot_size)

    # Get the max scan range
    if isinstance(imageset, ImageSweep):
      max_scan_range = imageset.get_array_range()
    else:
      max_scan_range = (0, len(imageset))

    # Get list of scan ranges
    if not self.scan_range or self.scan_range[0] is None:
      scan_range = [(max_scan_range[0]+1, max_scan_range[1])]
    else:
      scan_range = self.scan_range

    # Get spots from bits of scan
    spots_all = []
    for scan in scan_range:
      j0, j1 = scan
      assert(j1 >= j0 and j0 > max_scan_range[0] and j1 <= max_scan_range[1])
      info('\nFinding spots in image {0} to {1}...'.format(j0, j1))
      j0 -= 1
      if isinstance(imageset, ImageSweep):
        j0 -= imageset.get_array_range()[0]
        j1 -= imageset.get_array_range()[0]
      spots_all.extend(extract_spots(imageset[j0:j1]))

    # Get the list of shoeboxes
    shoeboxes = flex.shoebox(spots_all)

    # Calculate the spot centroids
    centroid = shoeboxes.centroid_valid()
    info('Calculated {0} spot centroids'.format(len(shoeboxes)))

    # Calculate the spot intensities
    intensity = shoeboxes.summed_intensity()
    info('Calculated {0} spot intensities'.format(len(shoeboxes)))

    # Create the observations
    observed = flex.observation(shoeboxes.panels(), centroid, intensity)

    # Write the hot mask
    if self.write_hot_mask:
      # Find spots which cover the whole scan range
      bbox = flex.int6([sbox.bbox for sbox in shoeboxes])
      z0, z1 = bbox.parts()[4:6]
      zr = z1 - z0
      assert zr.all_gt(0)
      possible_hot_spots = (zr == len(imageset))
      num_possible_hot_spots = possible_hot_spots.count(True)
      info('Found %d possible hot spots' % num_possible_hot_spots)

      # Create the hot pixel mask
      hot_mask = tuple(flex.bool(flex.grid(p.get_image_size()[::-1]), True)
                       for p in imageset.get_detector())
      if num_possible_hot_spots > 0:
        hot_shoeboxes = shoeboxes.select(possible_hot_spots)
        for sbox in hot_shoeboxes:
          x0, x1, y0, y1 = sbox.bbox[0:4]
          m = sbox.mask
          p = sbox.panel
          for y in range(m.all()[1]):
            for x in range(m.all()[2]):
              if m[:,y:y+1,x:x+1].all_ne(0):
                hot_mask[p][y0+y,x0+x] = False
      info('Found %d possible hot pixel(s)' % hot_mask.count(False))

    else:
      hot_mask = None

    # Filter the reflections and select only the desired spots
    flags = self.filter_spots(None,
        sweep=imageset,
        observations=observed,
        shoeboxes=shoeboxes)
    observed = observed.select(flags)
    shoeboxes = shoeboxes.select(flags)

    # Return as a reflection list
    return flex.reflection_table(observed, shoeboxes), hot_mask
