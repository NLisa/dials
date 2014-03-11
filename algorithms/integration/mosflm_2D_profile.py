from __future__ import division
from dials.model.data import Reflection, ReflectionList
from dials.algorithms.integration import add_2d, subtrac_bkg_2d, \
              fitting_2d_partials, fitting_2d_multile_var_build_mat, sigma_2d

from dials.array_family import flex

def make_2d_profile(reflection_pointers, ref_table_in):

  col_intensity = ref_table_in['intensity.raw.value']
  max_i_01 = 0.0
  for t_row in reflection_pointers:
    #if ref.is_valid():
      if col_intensity[t_row] > max_i_01:
        max_i_01 = col_intensity[t_row]

  max_i = 0.0
  for t_row in reflection_pointers:
    #if ref.is_valid():
      if col_intensity[t_row] > max_i and col_intensity[t_row] < max_i_01 * 0.95:
        max_i = col_intensity[t_row]
  thold = 0.5 * max_i

  select_pointers = []
  for t_row in reflection_pointers:
    #if ref.is_valid():
      if col_intensity[t_row] > thold and col_intensity[t_row] < max_i:
        select_pointers.append(t_row)
  counter = 0

  big_nrow = 0
  big_ncol = 0
  col_shoebox = ref_table_in['shoebox']
  for t_row in select_pointers:
    local_nrow = col_shoebox[t_row].data.all()[1]
    local_ncol = col_shoebox[t_row].data.all()[2]
    if local_nrow > big_nrow:
      big_nrow = local_nrow
    if local_ncol > big_ncol:
      big_ncol = local_ncol
    counter += 1

  big_nrow = big_nrow * 2 + 1
  big_ncol = big_ncol * 2 + 1

  col_xyzobs = ref_table_in['xyzobs.px.value']
  col_bbox = ref_table_in['bbox']

  sumation = flex.double(flex.grid(big_nrow, big_ncol), 0)
  descr = flex.double(flex.grid(1, 3), 0)
  for t_row in select_pointers:

    shoebox = col_shoebox[t_row].data
    background = col_shoebox[t_row].background

    data2d = shoebox[0:1, :, :]
    background2d = background[0:1, :, :]

    data2d.reshape(flex.grid(shoebox.all()[1:]))
    background2d.reshape(flex.grid(background.all()[1:]))

    #mask =col_shoebox[t_row].mask                  # may be needed soon
    #mask2d = mask[0:1, :, :]                       # may be needed soon
    #mask2d.reshape(flex.grid(mask.all()[1:]))      # may be needed soon

    cntr_pos = col_xyzobs[t_row]
    bnd_box = col_bbox[t_row]

    descr[0, 0] = cntr_pos[0] - bnd_box[0]
    descr[0, 1] = cntr_pos[1] - bnd_box[2]
    descr[0, 2] = 1.0 / (col_intensity[t_row] * counter)
    peak2d = subtrac_bkg_2d(data2d, background2d)
    sumation = add_2d(descr, peak2d, sumation)

  #if_you_want_to_see_how_the_profiles_look = '''
  from matplotlib import pyplot as plt
  data2d_np = sumation.as_numpy_array()
  plt.imshow(data2d_np, interpolation = "nearest", cmap = plt.gray())
  plt.show()
  #'''

  return sumation, thold

def fit_profile_2d(reflection_pointers, ref_table
                   , arr_proff, row, col, xmax, ymax):

  import math
  local_average = arr_proff[row][col][0]
  thold = arr_proff[row][col][1]

  len_tabl = len(arr_proff)
  descr = flex.double(flex.grid(1, 3))
  x_cuad_size = float(xmax) / len_tabl
  x_half_cuad_size = (x_cuad_size) / 2.0
  y_cuad_size = float(ymax) / len_tabl
  y_half_cuad_size = (y_cuad_size) / 2.0

  col_xyzcal = ref_table['xyzcal.px']
  col_intensity = ref_table['intensity.raw.value']
  col_variance = ref_table['intensity.raw.variance']
  col_shoebox = ref_table['shoebox']
  col_xyzobs = ref_table['xyzobs.px.value']
  col_bbox = ref_table['bbox']
  #for ref in reflections:
  for t_row in range(len(ref_table)):

    #in the future consider searcing for is_valid logical
    #if r.is_valid():
    if col_intensity[t_row] < thold:

      #x, y = ref.image_coord_px       # consider replasing with centroid pos
      x, y = col_xyzcal[t_row][0:2]    # r.image_coord_px

      if (x > x_half_cuad_size        and y > y_half_cuad_size and
          x < xmax - x_half_cuad_size and y < ymax - y_half_cuad_size):

        x_centr_of_cuad = col * x_cuad_size + x_half_cuad_size
        y_centr_of_cuad = row * y_cuad_size + y_half_cuad_size

        if x < x_centr_of_cuad and y < y_centr_of_cuad:
          tp_lf_pos = row - 1, col - 1
          tp_rg_pos =row - 1, col
          bt_lf_pos = row, col - 1
          bt_rg_pos = row, col
        elif x > x_centr_of_cuad and y < y_centr_of_cuad:
          tp_lf_pos = row - 1, col
          tp_rg_pos = row - 1, col + 1
          bt_lf_pos = row, col
          bt_rg_pos = row, col + 1
        elif x < x_centr_of_cuad and y > y_centr_of_cuad:
          tp_lf_pos = row, col - 1
          tp_rg_pos = row, col
          bt_lf_pos = row + 1, col - 1
          bt_rg_pos = row + 1, col
        else:
          tp_lf_pos = row, col
          tp_rg_pos = row, col + 1
          bt_lf_pos = row + 1, col
          bt_rg_pos = row + 1, col + 1

        tp_lf_average = arr_proff[tp_lf_pos[0]][tp_lf_pos[1]][0]
        tp_rg_average = arr_proff[tp_rg_pos[0]][tp_rg_pos[1]][0]
        bt_lf_average = arr_proff[bt_lf_pos[0]][bt_lf_pos[1]][0]
        bt_rg_average = arr_proff[bt_rg_pos[0]][bt_rg_pos[1]][0]

        tp_lf_x = tp_lf_pos[1] * x_cuad_size + x_half_cuad_size
        tp_lf_y = tp_lf_pos[0] * y_cuad_size + y_half_cuad_size
        dx = abs(tp_lf_x - x)
        dy = abs(tp_lf_y - y)
        tp_lf_dist = math.sqrt(dx * dx + dy * dy)

        tp_rg_x = tp_rg_pos[1] * x_cuad_size + x_half_cuad_size
        tp_rg_y = tp_rg_pos[0] * y_cuad_size + y_half_cuad_size
        dx = abs(tp_rg_x - x)
        dy = abs(tp_rg_y - y)
        tp_rg_dist = math.sqrt(dx * dx + dy * dy)

        bt_lf_x = bt_lf_pos[1] * x_cuad_size + x_half_cuad_size
        bt_lf_y = bt_lf_pos[0] * y_cuad_size + y_half_cuad_size
        dx = abs(bt_lf_x - x)
        dy = abs(bt_lf_y - y)
        bt_lf_dist = math.sqrt(dx * dx + dy * dy)

        bt_rg_x = bt_rg_pos[1] * x_cuad_size + x_half_cuad_size
        bt_rg_y = bt_rg_pos[0] * y_cuad_size + y_half_cuad_size
        dx = abs(bt_rg_x - x)
        dy = abs(bt_rg_y - y)
        bt_rg_dist = math.sqrt(dx * dx + dy * dy)

        max_dist = math.sqrt(
        (x_cuad_size * x_cuad_size) + (y_cuad_size * y_cuad_size)
        )
        tp_lf_contr = (max_dist - tp_lf_dist) / max_dist
        tp_rg_contr = (max_dist - tp_rg_dist) / max_dist
        bt_lf_contr = (max_dist - bt_lf_dist) / max_dist
        bt_rg_contr = (max_dist - bt_rg_dist) / max_dist

        total_contr = tp_lf_contr + tp_rg_contr + bt_lf_contr + bt_rg_contr

        re_scale = 1.0 / total_contr
        tp_lf_contr = tp_lf_contr * re_scale
        tp_rg_contr = tp_rg_contr * re_scale
        bt_lf_contr = bt_lf_contr * re_scale
        bt_rg_contr = bt_rg_contr * re_scale

        big_nrow = tp_lf_average.all()[0]
        if tp_rg_average.all()[0] > big_nrow:
          big_nrow = tp_rg_average.all()[0]
        if bt_lf_average.all()[0] > big_nrow:
          big_nrow = bt_lf_average.all()[0]
        if bt_rg_average.all()[0] > big_nrow:
          big_nrow = bt_rg_average.all()[0]

        big_ncol = tp_lf_average.all()[1]
        if tp_rg_average.all()[1] > big_ncol:
          big_ncol = tp_rg_average.all()[1]
        if bt_lf_average.all()[1] > big_ncol:
          big_ncol = bt_lf_average.all()[1]
        if bt_rg_average.all()[1] > big_ncol:
          big_ncol = bt_rg_average.all()[1]

        average = flex.double(flex.grid(big_nrow, big_ncol), 0)

        descr[0, 0] = float(tp_lf_average.all()[1])/2.0
        descr[0, 1] = float(tp_lf_average.all()[0])/2.0
        descr[0, 2] = float(tp_lf_contr)
        average = add_2d(descr, tp_lf_average, average)
        descr[0, 0] = float(tp_rg_average.all()[1])/2.0
        descr[0, 1] = float(tp_rg_average.all()[0])/2.0
        descr[0, 2] = float(tp_rg_contr)
        average = add_2d(descr, tp_rg_average, average)
        descr[0, 0] = float(bt_lf_average.all()[1])/2.0
        descr[0, 1] = float(bt_lf_average.all()[0])/2.0
        descr[0, 2] = float(bt_lf_contr)
        average = add_2d(descr, bt_lf_average, average)
        descr[0, 0] = float(bt_rg_average.all()[1])/2.0
        descr[0, 1] = float(bt_rg_average.all()[0])/2.0
        descr[0, 2] = float(bt_rg_contr)
        average = add_2d(descr, bt_rg_average, average)

        if_you_want_to_see_how_the_profiles_look = '''
        from matplotlib import pyplot as plt
        data2d = average.as_numpy_array()
        plt.imshow(data2d, interpolation = "nearest", cmap = plt.gray())
        plt.show()
        #'''
      else:
        #print "in else"
        average = local_average

      shoebox = col_shoebox[t_row].data
      #shoebox = ref.shoebox

      background = col_shoebox[t_row].background
      #background = ref.shoebox_background

      mask = col_shoebox[t_row].mask
      #mask = ref.shoebox_mask

      tmp_i = col_intensity[t_row]
      #tmp_i = ref.intensity

      col_intensity[t_row] = 0.0
      #ref.intensity = 0.0

      col_variance[t_row] = 0.0
      #ref.intensity_variance = 0.0

      for i in range(shoebox.all()[0]):
        data2d = shoebox[i:i + 1, :, :]
        mask2d = mask[i:i + 1, :, :]
        background2d = background[i:i + 1, :, :]
        try:
          data2d.reshape(flex.grid(shoebox.all()[1:]))
          mask2d.reshape(flex.grid(shoebox.all()[1:]))
          background2d.reshape(flex.grid(shoebox.all()[1:]))

        except:
          print "error reshaping flex-array"
          #print "ref.bounding_box", ref.bounding_box
          break

        cntr_pos = col_xyzobs[t_row]
        bnd_box = col_bbox[t_row]

        descr[0, 0] = cntr_pos[0] - bnd_box[0]
        #descr[0, 0] = ref.centroid_position[0] - ref.bounding_box[0]

        descr[0, 1] = cntr_pos[1] - bnd_box[2]
        #descr[0, 1] = ref.centroid_position[1] - ref.bounding_box[2]

        descr[0, 2] = 1.0 #/ (ref.intensity * counter)
        #fully_record = 'yes'
        tmp_comment = '''
        if(ref.status == 0):
        #if(fully_record == 'yes'):
          tmp_scale = tmp_i
          a_mat_flx = flex.double(flex.grid(4, 4))
          b_vec_flx = flex.double(flex.grid(4, 1))
          ok_lg = fitting_2d_multile_var_build_mat(descr, data2d, background2d, \
                                        average, tmp_scale, a_mat_flx, b_vec_flx)

          #if ok_lg == 0:
          a_mat = a_mat_flx.as_scitbx_matrix()
          b_mat = b_vec_flx.as_scitbx_matrix()
          try:
            x_mat = a_mat.inverse() * b_mat
            k_abc_vec = x_mat.as_flex_double_matrix()
          except:
            print "fail to do profile fitting  <<<<<<<<"
            k_abc_vec=(0,0,0,0)
          #else:
          #  print "ok_lg != 0"
          #  k_abc_vec=(0,0,0,0)

          ref.intensity += k_abc_vec[0]
          ref.intensity_variance += k_abc_vec[1]
        else:
        #'''

        I_R = fitting_2d_partials(descr, data2d, background2d, average, tmp_i)
        col_intensity[t_row] += I_R[0]
        #ref.intensity += I_R[0]
        col_variance[t_row] += I_R[1]
        #ref.intensity_variance += I_R[1]

        var = sigma_2d(col_intensity[t_row], mask2d, background2d)
        col_variance[t_row] += var
        #ref.intensity_variance += var

  ref_table['intensity.raw.value'] = col_intensity
  ref_table['intensity.raw.variance'] = col_variance

  return ref_table
