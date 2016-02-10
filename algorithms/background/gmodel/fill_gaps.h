/*
 * fill_gaps.h
 *
 *  Copyright (C) 2013 Diamond Light Source
 *
 *  Author: James Parkhurst
 *
 *  This code is distributed under the BSD license, a copy of which is
 *  included in the root directory of this package.
 */


#ifndef DIALS_ALGORITHMS_BACKGROUND_GMODEL_FILL_GAPS_H
#define DIALS_ALGORITHMS_BACKGROUND_GMODEL_FILL_GAPS_H

#include <vector>
#include <scitbx/vec2.h>
#include <scitbx/vec3.h>
#include <dxtbx/model/beam.h>
#include <dxtbx/model/panel.h>
#include <dials/array_family/scitbx_shared_and_versa.h>
#include <dials/algorithms/polygon/spatial_interpolation.h>
#include <dials/algorithms/image/filter/summed_area.h>
#include <dials/model/data/shoebox.h>
#include <dials/error.h>

namespace dials { namespace algorithms { namespace background {

  using dxtbx::model::Beam;
  using dxtbx::model::Panel;
  using dxtbx::model::angle_safe;
  using scitbx::vec2;
  using scitbx::vec3;
  using scitbx::af::int2;
  using scitbx::af::int6;
  using dials::model::Shoebox;
  using dials::algorithms::polygon::simple_area;
  using dials::algorithms::polygon::clip::vert4;
  using dials::algorithms::polygon::clip::vert8;
  using dials::algorithms::polygon::clip::quad_with_convex_quad;
  using dials::algorithms::polygon::spatial_interpolation::reverse_quad_inplace_if_backward;
  using dials::algorithms::summed_area;

  namespace {

    template <typename T>
    T min4(T a, T b, T c, T d) {
      return std::min(std::min(a,b), std::min(c,d));
    }

    template <typename T>
    T max4(T a, T b, T c, T d) {
      return std::max(std::max(a,b), std::max(c,d));
    }
  }

  inline
  af::shared<double> row_median(
      const af::const_ref< double, af::c_grid<2> > &data,
      const af::const_ref< bool, af::c_grid<2> > &mask) {
    DIALS_ASSERT(data.accessor().all_eq(mask.accessor()));
    af::shared<double> result(data.accessor()[0], 0);
    for (std::size_t j = 0; j < data.accessor()[0]; ++j) {
      std::vector<double> pixels(data.accessor()[1]);
      std::size_t npix = 0;
      for (std::size_t i = 0; i < data.accessor()[1]; ++i) {
        if (mask(j,i)) {
          pixels[npix++] = data(j,i);
        }
      }
      if (npix > 0) {
        std::size_t n = npix / 2;
        std::nth_element(
            pixels.begin(),
            pixels.begin() + n,
            pixels.begin()+npix);
        result[j] = pixels[n];
      } else {
        result[j] = 0;
      }
    }
    return result;
  }

  af::versa< double, af::c_grid<2> > fill_gaps(
      const af::const_ref< double, af::c_grid<2> > &data,
      const af::const_ref< bool, af::c_grid<2> > &mask,
      int2 size,
      std::size_t niter) {
    DIALS_ASSERT(size.all_ge(0));

    int total_size = (2*size[0]+1)*(2*size[1]+1);

    af::versa< int, af::c_grid<2> > int_mask(data.accessor());
    for (std::size_t i = 0; i < int_mask.size(); ++i) {
      int_mask[i] = (int)mask[i];
    }

    af::versa< double, af::c_grid<2> > result(data.accessor());
    std::copy(data.begin(), data.end(), result.begin());
    for (std::size_t iter = 0; iter < niter; ++iter) {
      // Calculate the summed area under the mask
      af::versa< int, af::c_grid<2> > summed_mask = summed_area<int>(int_mask.const_ref(), size);

      // Calculate the summed area under the image
      af::versa< double, af::c_grid<2> > summed_data =
        summed_area<double>(result.const_ref(), size);

      // Calculate the mean filtered image
      for (std::size_t i = 0; i < data.size(); ++i) {
        if (!mask[i]) {
          result[i] = summed_data[i] / (double)total_size;///= (double)summed_mask[i];
        }
      }
    }

    return result;
  }

  class PolarTransformResult {
  public:

    PolarTransformResult(
        af::versa<double, af::c_grid<2> > data,
        af::versa<bool, af::c_grid<2> > mask)
      : data_(data),
        mask_(mask) {
      DIALS_ASSERT(data_.accessor().all_eq(mask_.accessor()));
    }

    /**
     * @return The data array
     */
    af::versa< double, af::c_grid<2> > data() const {
      return data_;
    }

    /**
     * @return The mask array
     */
    af::versa< bool, af::c_grid<2> > mask() const {
      return mask_;
    }

  private:

    af::versa< double, af::c_grid<2> > data_;
    af::versa< bool,   af::c_grid<2> > mask_;
  };

  class PolarTransform {
  public:

    PolarTransform(
        const Beam &beam,
        const Panel &panel)
      : beam_(beam),
        panel_(panel),
        r_(af::c_grid<2>(
              panel_.get_image_size()[1]+1,
              panel_.get_image_size()[0]+1)),
        a_(af::c_grid<2>(
              panel_.get_image_size()[1]+1,
              panel_.get_image_size()[0]+1)) {
      vec3<double> s0 = beam_.get_s0();
      double angle = angle_safe(s0, vec3<double>(0,0,1));
      vec3<double> axis = ((angle == 0)
        ? vec3<double>(0,0,1)
        : s0.cross(vec3<double>(0,0,1))).normalize();
      for (std::size_t j = 0; j < r_.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < r_.accessor()[1]; ++i) {
          vec2<double> px(i,j);
          vec3<double> xyz = panel_.get_pixel_lab_coord(px).normalize();
          xyz = xyz.rotate_around_origin(axis, angle);
          r_(j,i) = std::acos(xyz[2] / 1.0);
          a_(j,i) = std::atan2(xyz[1], xyz[0]);
        }
      }
      min_r_ = af::min(r_.const_ref());
      max_r_ = af::max(r_.const_ref());
      min_a_ = af::min(a_.const_ref());
      max_a_ = af::max(a_.const_ref());
      min_r_step_ = (max_r_ - min_r_);// / af::sum(r_.accessor().const_ref());
      min_a_step_ = (max_a_ - min_a_);// / af::sum(a_.accessor().const_ref());
      //double min_r_step = max_r - min_r;
      //double min_a_step = max_a - min_a;
      for (std::size_t j = 0; j < r_.accessor()[0]-1; ++j) {
        for (std::size_t i = 0; i < r_.accessor()[1]-1; ++i) {
          if (r_(j,i) > 0.01) {
          double r1 = std::abs(r_(j,i) - r_(j+1,i));
          double r2 = std::abs(r_(j,i) - r_(j,i+1));
          double a1 = std::abs(a_(j,i) - a_(j+1,i));
          double a2 = std::abs(a_(j,i) - a_(j,i+1));
          min_r_step_ = std::min(min_r_step_, std::max(r1, r2));
          min_a_step_ = std::min(min_a_step_, std::max(a1, a2));
          }
        }
      }
      min_r_step_ *= 2;
      min_a_step_ *= 2;
      num_r_ = (max_r_ - min_r_) / min_r_step_;
      num_a_ = (max_a_ - min_a_) / min_a_step_;

      angle_ = angle;
      axis_ = axis;

      std::cout << min_r_step_ << ", " << min_a_step_ << std::endl;
      std::cout << min_r_ << ", " << max_r_ << std::endl;
      std::cout << min_a_ << ", " << max_a_ << std::endl;
      std::cout << num_r_ << ", " << num_a_ << std::endl;
    }

    af::versa<double, af::c_grid<2> > r() const {
      return r_;
    }

    af::versa<double, af::c_grid<2> > a() const {
      return a_;
    }

    vec2<double> xy(double j, double i) const {
      double r = min_r_ + j * min_r_step_;
      double a = min_a_ + i * min_a_step_;
      double z = std::cos(r);
      double y = std::sin(r) * std::sin(a);
      double x = std::sin(r) * std::cos(a);
      vec3<double> xyz(x, y, z);
      xyz = xyz.normalize();
      xyz = xyz.rotate_around_origin(axis_, -angle_);
      return panel_.get_ray_intersection_px(xyz);
    }

    vec2<double> xy2(double j, double i) const {
        vec2<double> px(i,j);
        vec3<double> xyz = panel_.get_pixel_lab_coord(px).normalize();
        xyz = xyz.rotate_around_origin(axis_, angle_);
        double r = std::acos(xyz[2] / 1.0);
        double a = std::atan2(xyz[1], xyz[0]);
        vec2<double> xy(
            (a - min_a_) / min_a_step_,
            (r - min_r_) / min_r_step_);
        return xy;
    }

    PolarTransformResult to_polar(
        const af::const_ref< double, af::c_grid<2> > &data,
        const af::const_ref<bool, af::c_grid<2> > &mask) const {
      af::versa< double, af::c_grid<2> > result(af::c_grid<2>(num_r_, num_a_));
      af::versa< bool, af::c_grid<2> > result_mask(af::c_grid<2>(num_r_, num_a_), false);
      for (std::size_t j = 0; j < num_r_; ++j) {
        for (std::size_t i = 0; i < num_a_; ++i) {
          vec2<double> xy0 = xy(j+0.5, i+0.5);
          double x = xy0[0];
          double y = xy0[1];
          if (x >= 0 && y >= 0 && x < data.accessor()[1]-1 && y < data.accessor()[0]-1) {
            int x0 = std::floor(x);
            int x1 = x0 + 1;
            int y0 = std::floor(y);
            int y1 = y0 + 1;
            if (!mask(y0,x0) || !mask(y0,x1) || !mask(y1,x1) || !mask(y1,x1)) {
              continue;
            }
            double px = x - x0;
            double py = y - y0;
            double f00 = data(y0,x0);
            double f01 = data(y0,x1);
            double f10 = data(y1,x0);
            double f11 = data(y1,x1);
            double fxy = f00*(1-px)*(1-py)+f01*px*(1-py)+f10*(1-px)*py+f11*px*py;
            result(j,i) = fxy;
            result_mask(j,i) = mask(y0,x0);
          }
        }
      }
      /* std::size_t ys = data.accessor()[0]; */
      /* std::size_t xs = data.accessor()[1]; */
      /* af::versa< double, af::c_grid<2> > result(af::c_grid<2>(num_r_, num_a_)); */
      /* for (std::size_t j = 0; j < result.accessor()[0]; ++j) { */
      /*   std::cout << j << std::endl; */
      /*   for (std::size_t i = 0; i < result.accessor()[1]; ++i) { */
      /*     std::cout << j << ", " << i << std::endl; */
      /*     vec2<double> xy00 = xy(j,i); */
      /*     vec2<double> xy01 = xy(j,i+1); */
      /*     vec2<double> xy11 = xy(j+1,i+1); */
      /*     vec2<double> xy10 = xy(j+1,i); */
      /*     int x0 = (int)std::floor(min4(xy00[0], xy01[0], xy11[0], xy10[0])); */
      /*     int x1 = (int)std::ceil (max4(xy00[0], xy01[0], xy11[0], xy10[0])); */
      /*     int y0 = (int)std::floor(min4(xy00[1], xy01[1], xy11[1], xy10[1])); */
      /*     int y1 = (int)std::ceil (max4(xy00[1], xy01[1], xy11[1], xy10[1])); */
      /*     DIALS_ASSERT(x0 < x1); */
      /*     DIALS_ASSERT(y0 < y1); */
      /*     if (x0 <  0) x0 = 0; */
      /*     if (y0 <  0) y0 = 0; */
      /*     if (x1 > xs) x1 = xs; */
      /*     if (y1 > ys) y1 = ys; */
      /*     vert4 p1(xy00, xy01, xy11, xy10); */
      /*     reverse_quad_inplace_if_backward(p1); */
      /*     std::cout << y0 << ", " << y1 << ", " << x0 << ", " << x1 << std::endl; */
      /*     for (std::size_t jj = y0; jj < y1; ++jj) { */
      /*       for (std::size_t ii = x0; ii < x1; ++ii) { */
      /*         vec2<double> xy200(ii,jj); */
      /*         vec2<double> xy201(ii,jj+1); */
      /*         vec2<double> xy211(ii+1,jj+1); */
      /*         vec2<double> xy210(ii+1,jj); */
      /*         vert4 p2(xy200, xy201, xy211, xy210); */
      /*         reverse_quad_inplace_if_backward(p2); */
      /*         vert8 p3 = quad_with_convex_quad(p1, p2); */
      /*         double area = simple_area(p3); */
      /*         const double EPS = 1e-7; */
      /*         if (area < 0.0) { */
      /*           DIALS_ASSERT(area > -EPS); */
      /*           area = 0.0; */
      /*         } */
      /*         if (area > 1.0) { */
      /*           DIALS_ASSERT(area <= (1.0 + EPS)); */
      /*           area = 1.0; */
      /*         } */
      /*         DIALS_ASSERT(0.0 <= area && area <= 1.0); */
      /*         result(j,i) += area * data(jj,ii); */
      /*       } */
      /*     } */
      /*   } */
      /* } */
      return PolarTransformResult(result, result_mask);
    }


    af::versa< double, af::c_grid<2> > to_cartesian(
        const af::const_ref< double, af::c_grid<2> > &data) const {
      std::size_t xs = panel_.get_image_size()[0];
      std::size_t ys = panel_.get_image_size()[1];
      af::versa< double, af::c_grid<2> > result(af::c_grid<2>(ys, xs));
      for (std::size_t j = 0; j < ys; ++j) {
        for (std::size_t i = 0; i < xs; ++i) {
          vec2<double> xy0 = xy2(j+0.5, i+0.5);
          double x = xy0[0];
          double y = xy0[1];
//          std::cout << x << ", " << y << std::endl;
          if (x >= 0 && y >= 0 && x < data.accessor()[1]-1 && y < data.accessor()[0]-1) {
            int x0 = std::floor(x);
            int x1 = x0 + 1;
            int y0 = std::floor(y);
            int y1 = y0 + 1;
            double px = x - x0;
            double py = y - y0;
            double f00 = data(y0,x0);
            double f01 = data(y0,x1);
            double f10 = data(y1,x0);
            double f11 = data(y1,x1);
            double fxy = f00*(1-px)*(1-py)+f01*px*(1-py)+f10*(1-px)*py+f11*px*py;
            result(j,i) = fxy;
          }
        }
      }
      return result;
    }

  private:

    Beam beam_;
    Panel panel_;
    af::versa< double, af::c_grid<2> > r_;
    af::versa< double, af::c_grid<2> > a_;
    std::size_t num_r_;
    std::size_t num_a_;
    double min_r_step_;
    double min_a_step_;
    double min_r_;
    double max_r_;
    double min_a_;
    double max_a_;
    double angle_;
    vec3<double> axis_;
  };


  class FillGaps {
  public:

    FillGaps(
        const Beam &beam,
        const Panel &panel)
      : resolution_(
          af::c_grid<2>(
            panel.get_image_size()[1],
            panel.get_image_size()[0])) {
      vec3<double> s0 = beam.get_s0();
      for (std::size_t j = 0; j < resolution_.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < resolution_.accessor()[1]; ++i) {
          vec2<double> px(i+0.5, j+0.5);
          resolution_(j,i) = panel.get_resolution_at_pixel(s0, px);
        }
      }
    }


    void operator()(
        af::ref< double, af::c_grid<2> > data,
        const af::const_ref< bool, af::c_grid<2> > &mask,
        double sigma,
        int kernel_size,
        std::size_t niter,
        bool all) const {

      // Compute an image of sigmas for the gaussian kernel which varies with
      // resolution.
      af::versa< double, af::c_grid<2> > sigma_image(data.accessor());
      for (std::size_t j = 0; j < data.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < data.accessor()[1]; ++i) {
          double d0 = resolution_(j,i);
          double dsum = 0.0;
          double dcnt = 0.0;
          if (j > 0) {
            dsum += std::abs(resolution_(j-1,i) - d0);
            dcnt++;
          }
          if (i > 0) {
            dsum += std::abs(resolution_(j,i-1) - d0);
            dcnt++;
          }
          if (j < data.accessor()[0]-1) {
            dsum += std::abs(resolution_(j+1,i) - d0);
            dcnt++;
          }
          if (i < data.accessor()[1]-1) {
            dsum += std::abs(resolution_(j,i+1) - d0);
            dcnt++;
          }
          sigma_image(j,i) = sigma * dsum / dcnt;
        }
      }

      // Iteratively filter the image
      for (std::size_t iter = 0; iter < niter; ++iter) {
        std::cout << iter << std::endl;
        fill_image(data, mask, sigma_image.const_ref(), kernel_size, all);
      }
    }

  private:

    void fill_image(
        af::ref< double, af::c_grid<2> > data,
        const af::const_ref< bool, af::c_grid<2> > &mask,
        const af::const_ref< double, af::c_grid<2> > &sigma_image,
        int kernel_size,
        bool all) const {
      int height = (int)data.accessor()[0];
      int width = (int)data.accessor()[1];
      for (std::size_t j = 0; j < data.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < data.accessor()[1]; ++i) {
          if (all || mask(j,i) == false) {
            int jc = (int)j;
            int ic = (int)i;
            int j0 = std::max(jc - kernel_size, 0);
            int j1 = std::min(jc + kernel_size, height);
            int i0 = std::max(ic - kernel_size, 0);
            int i1 = std::min(ic + kernel_size, width);
            double d0 = resolution_(j,i);
            double kernel_data = 0.0;
            double kernel_sum = 0.0;
            double sigma = sigma_image(j,i);
            for (int jj = j0; jj < j1; ++jj) {
              for (int ii = i0; ii < i1; ++ii) {
                if (jj != j && ii != i) {
                  double d = resolution_(jj,ii);
                  double kernel_value = std::exp(-(d-d0)*(d-d0)/(2.0*sigma*sigma));
                  kernel_data += data(jj,ii) * kernel_value;
                  kernel_sum += kernel_value;
                }
              }
            }
            DIALS_ASSERT(kernel_sum > 0);
            data(j,i) = kernel_data / kernel_sum;
          }
        }
      }
    }

    af::versa< double, af::c_grid<2> > resolution_;
  };

  class FillGaps2 {
  public:

    FillGaps2(
        const Beam &beam,
        const Panel &panel)
      : resolution_(
          af::c_grid<2>(
            panel.get_image_size()[1],
            panel.get_image_size()[0])) {
      vec3<double> s0 = beam.get_s0();
      for (std::size_t j = 0; j < resolution_.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < resolution_.accessor()[1]; ++i) {
          vec2<double> px(i+0.5, j+0.5);
          resolution_(j,i) = panel.get_resolution_at_pixel(s0, px);
        }
      }
    }


    void operator()(
        af::ref< double, af::c_grid<2> > data,
        const af::const_ref< int, af::c_grid<2> > &mask,
        double sigma,
        int kernel_size,
        std::size_t niter) const {

      // Compute an image of sigmas for the gaussian kernel which varies with
      // resolution.
      af::versa< double, af::c_grid<2> > sigma_image(data.accessor());
      for (std::size_t j = 0; j < data.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < data.accessor()[1]; ++i) {
          double d0 = resolution_(j,i);
          double dsum = 0.0;
          double dcnt = 0.0;
          if (j > 0) {
            dsum += std::abs(resolution_(j-1,i) - d0);
            dcnt++;
          }
          if (i > 0) {
            dsum += std::abs(resolution_(j,i-1) - d0);
            dcnt++;
          }
          if (j < data.accessor()[0]-1) {
            dsum += std::abs(resolution_(j+1,i) - d0);
            dcnt++;
          }
          if (i < data.accessor()[1]-1) {
            dsum += std::abs(resolution_(j,i+1) - d0);
            dcnt++;
          }
          sigma_image(j,i) = sigma * dsum / dcnt;
        }
      }

      // Iteratively filter the image
      for (std::size_t iter = 0; iter < niter; ++iter) {
        std::cout << iter << std::endl;
        fill_image(data, mask, sigma_image.const_ref(), kernel_size);
      }
    }

  private:

    void fill_image(
        af::ref< double, af::c_grid<2> > data,
        const af::const_ref< int, af::c_grid<2> > &mask,
        const af::const_ref< double, af::c_grid<2> > &sigma_image,
        int kernel_size) const {

      int height = (int)data.accessor()[0];
      int width = (int)data.accessor()[1];
      for (std::size_t j = 0; j < data.accessor()[0]; ++j) {
        for (std::size_t i = 0; i < data.accessor()[1]; ++i) {
          if (mask(j,i) == 0) {
            int jc = (int)j;
            int ic = (int)i;
            int j0 = std::max(jc - kernel_size, 0);
            int j1 = std::min(jc + kernel_size, height);
            int i0 = std::max(ic - kernel_size, 0);
            int i1 = std::min(ic + kernel_size, width);
            double d0 = resolution_(j,i);
            double kernel_data = 0.0;
            double kernel_sum = 0.0;
            double sigma = sigma_image(j,i);
            for (int jj = j0; jj < j1; ++jj) {
              for (int ii = i0; ii < i1; ++ii) {
                if (jj != j && ii != i) {
                  if (mask(jj,ii) >= 0) {
                    double d = resolution_(jj,ii);
                    double kernel_value = std::exp(-(d-d0)*(d-d0)/(2.0*sigma*sigma));
                    kernel_data += data(jj,ii) * kernel_value;
                    kernel_sum += kernel_value;
                  }
                }
              }
            }
            DIALS_ASSERT(kernel_sum > 0);
            data(j,i) = kernel_data / kernel_sum;
          }
        }
      }
    }

    af::versa< double, af::c_grid<2> > resolution_;
  };


  /**
   * A class to fit the background model
   */
  class Fitter {
  public:

    /**
     * Initialise the creator
     */
    Fitter(const af::const_ref< double, af::c_grid<2> > background)
      : background_(background.accessor()) {
      std::copy(background.begin(), background.end(), background_.begin());
    }

    /**
     * Compute the background values
     * @param sbox The shoeboxes
     * @returns Success True/False
     */
    af::shared<double> compute_background(af::ref< Shoebox<> > sbox) const {
      af::shared<double> scale(sbox.size(), -1.0);
      for (std::size_t i = 0; i < sbox.size(); ++i) {
        try {
          scale[i] = compute(sbox[i]);
        } catch(scitbx::error) {
          // Do nothing
        } catch(dials::error) {
          // Do nothing
        }
      }
      return scale;
    }

  private:

    /**
     * Compute the background values for a single shoebox
     * @param sbox The shoebox
     */
    double compute(Shoebox<> &sbox) const {
      DIALS_ASSERT(sbox.is_consistent());

      // Get image dimensions
      std::size_t height = background_.accessor()[0];
      std::size_t width = background_.accessor()[1];

      // Get shoebox dimensions
      std::size_t xs = sbox.xsize();
      std::size_t ys = sbox.ysize();
      std::size_t zs = sbox.zsize();
      int6 bbox = sbox.bbox;

      // Get the shoebox model
      af::versa< double, af::c_grid<2> > model(af::c_grid<2>(ys, xs));
      double sum_m = 0.0;
      for (std::size_t j = 0; j < ys; ++j) {
        for (std::size_t i = 0; i < xs; ++i) {
          int jj = bbox[2] + j;
          int ii = bbox[0] + i;
          if (jj >= 0 && ii >= 0 && jj < height && ii < width) {
            model(j,i) = background_(jj,ii);
            sum_m += model(j,i);
          }
        }
      }
      DIALS_ASSERT(sum_m > 0);

      // Compute the background scale
      double sum_b = 0.0;
      for (std::size_t i = 0; i < sbox.data.size(); ++i) {
        if (sbox.mask[i]) {
          sum_b += sbox.data[i];
        }
      }
      double scale = sum_b / (zs*sum_m);

      // Apply the background
      for (std::size_t j = 0; j < ys; ++j) {
        for (std::size_t i = 0; i < xs; ++i) {
          double value = model(j,i) * scale;
          for (std::size_t k = 0; k < zs; ++k) {
            sbox.background(k,j,i) = value;
          }
        }
      }

      // Return the background scale
      return scale;
    }

    af::versa< double, af::c_grid<2> > background_;
  };

}}}

#endif // DIALS_ALGORITHMS_BACKGROUND_GMODEL_FILL_GAPS_H
