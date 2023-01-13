import pathlib
import cupy as cp
# from cupy import resize
import numpy as np
import pickle
import cv2
import math
# from cupyx.scipy.ndimage import resize
from skopt import gp_minimize
from perlin_noise import PerlinNoise
import hashlib
# from tqdm import tqdm
from tqdm.notebook import tqdm
import matplotlib.pyplot as plt

import fbp.tompy as fbp
from ct import ct
from drr import drr

research = pathlib.Path(__file__).resolve().parent.parent
datadir = research / pathlib.Path("data")
graphdir = research / pathlib.Path("graphs")


class patient():
    def __init__(self, name, num_views=450):
        self.name = name
        self.num_views = num_views
        self.m = -1000
        self.b = -1000
        self.resize_factor = 1

        if (datadir / name / "ct.pickle").exists():
            with open(datadir / name / "ct.pickle", 'rb') as handle:
                self.ct = pickle.load(handle)
        else:
            self.generate_ct()

        if (datadir / name / "drr.pickle").exists():
            with open(datadir / name / "drr.pickle", 'rb') as handle:
                self.drr = pickle.load(handle)
        else:
            self.generate_drr()

        if (datadir / name / "posdrr.pickle").exists():
            with open(datadir / name / "posdrr.pickle", 'rb') as handle:
                self.posdrr = pickle.load(handle)
        else:
            self.generate_posdrr()

        if (datadir / name / "fbp.pickle").exists():
            with open(datadir / name / "fbp.pickle", 'rb') as handle:
                self.fbp = pickle.load(handle)
        else:
            self.generate_fbp()

        if (datadir / name / "posfbp.pickle").exists():
            with open(datadir / name / "posfbp.pickle", 'rb') as handle:
                self.posfbp = pickle.load(handle)
        else:
            self.generate_posfbp()

        if (datadir / name / "resize.pickle").exists():
            with open(datadir / name / "resize.pickle", 'rb') as handle:
                self.resize_factor = pickle.load(handle)
        else:
            self.calculate_resize()

    # generators ----------
    def generate_ct(self):
        # print("Creating new CTset")
        self.ct = ct.ctset(name=self.name, type="float32")
        with open(datadir / self.name / "ct.pickle", 'wb') as handle:
            pickle.dump(self.ct, handle, protocol=pickle.HIGHEST_PROTOCOL)
        self.generate_drr()

    def generate_drr(
        self,
        cont=True
    ):
        # print("Creating new DRRset")
        self.drr = drr.drrset(ctset=self.ct, num_views=self.num_views)
        with open(datadir / self.name / "drr.pickle", 'wb') as handle:
            pickle.dump(self.drr, handle, protocol=pickle.HIGHEST_PROTOCOL)
        if cont:
            self.generate_posdrr()

    def generate_posdrr(
        self,
        zm=0.5,
        delx=6e-3,
        cropstartx=75,
        cropstarty=120,
        cropheight=350,
        cropwidth=350,
        cont=True
    ):
        self.posdrr = drr.drrset(ctset=self.ct, num_views=self.num_views,
                                 cropstartx=cropstartx, cropstarty=cropstarty,
                                 cropheight=cropheight, cropwidth=cropwidth,
                                 delx=delx, zm=zm, adjust=False)
        with open(datadir / self.name / "posdrr.pickle", 'wb') as handle:
            pickle.dump(self.posdrr, handle, protocol=pickle.HIGHEST_PROTOCOL)
        if cont:
            self.generate_fbp()

    def generate_fbp(self, load_all=True, cont=True):
        self.fbp = fbp.fbpset(
            self.drr,
            height=500,
            angle=75,
            rotate=191,
            load_all=load_all
        )
        with open(datadir / self.name / "fbp.pickle", 'wb') as handle:
            pickle.dump(self.fbp, handle, protocol=pickle.HIGHEST_PROTOCOL)
        if cont:
            self.generate_posfbp()

    def generate_posfbp(self, load_all=True, cont=True):
        self.posfbp = fbp.fbpset(
            self.posdrr,
            height=500,
            angle=75,
            rotate=191,
            load_all=load_all
        )
        with open(datadir / self.name / "posfbp.pickle", 'wb') as handle:
            pickle.dump(self.posfbp, handle, protocol=pickle.HIGHEST_PROTOCOL)
        if cont:
            self.calculate_resize()

    def calculate_resize(self, base=150, plot=True):
        # print("Calculating resize factor")

        def loss(x):
            return self.get_equiv(base, resize_factor=x[0])[1]

        n_calls = 50
        self.result = gp_minimize(
            loss,
            [(0.5, 2.0)],
            n_calls=n_calls,
            callback=[self.tqdm_skopt(total=n_calls,
                      desc="Resize", leave=False)]
        )
        self.resize_factor = self.result.x[0]
        with open(datadir / self.name / "resize.pickle", 'wb') as handle:
            pickle.dump(self.resize_factor, handle,
                        protocol=pickle.HIGHEST_PROTOCOL)
        if plot:
            plt.cla()
            plt.scatter(self.result.x_iters,
                        self.result.func_vals, s=1.0)
            plt.title("Resize factor")
            plt.xlabel("resize_factor")
            plt.ylabel("Average pixel value difference")
            plt.savefig(graphdir / f"{self.name}_resize.png")

    # helpers --------

    def get_equiv(self, num, resize_factor=0, plot=False):
        if resize_factor == 0:
            resize_factor = self.resize_factor
        ttl = cp.sum(cp.full(cp.shape(self.ct.img[0]), 255))
        history = []
        min_sum = 53106966000
        min_sum_idx = 0
        for idx in range(len(self.fbp.x.img[0])):
            now = cp.sum(cp.absolute(self.ct.img[num] -
                         self.hist_match(self.get_resized_fbp(int(idx),
                                         pos=True,
                                         resize_factor=resize_factor),
                         self.ct.img[num]))) / ttl
            history.append(float(now))
            if min_sum > now:
                min_sum = float(now)
                min_sum_idx = idx
        # print(min_sum_idx, min_sum, resize_factor)
        # print(min_sum / cp.sum(cp.full(cp.shape(self.ct.img[0]), 255)))
        if plot:
            plt.style.use('dark_background')
            plt.figure(figsize=(6, 4), dpi=360)
            plt.title("Position")
            plt.xlabel("FBP Position")
            plt.ylabel("Average pixel value difference")
            plt.plot(history)
        return (min_sum_idx, min_sum)

    def get_equiv_fbp(self, num):
        img = self.get_resized_fbp(self.get_equiv(num)[0], noise=True)
        # return self.hist_match(img, self.ct.img[num])
        return img

    def get_resized_fbp(self, num, pos=False, noise=False, resize_factor=0):
        if resize_factor == 0:
            resize_factor = self.resize_factor
        if pos:
            img = self.posfbp.get(num)
        else:
            img = self.fbp.get(num)

        # add noise
        if noise:
            s = f"{self.name}_{num}"
            seed = int(hashlib.sha1(s.encode("utf-8")).hexdigest(), 16)

            smallnoise = self.getnoise(10, 0.1, height=512, seed=seed)
            midnoise = self.getnoise(6, 0.125, height=512, seed=seed * 2)
            bignoise = self.getnoise(2, 0.15, height=512, seed=seed * 3)
            img *= smallnoise * midnoise * bignoise

        # rescale
        scaled = int(cp.shape(img)[0] * resize_factor)
        img = cp.array(cv2.resize(cp.asnumpy(img), (scaled, scaled)))
        out = cp.shape(self.ct.img[0])[0]
        new_img = cp.zeros(cp.shape(self.ct.img[0]))

        if out > scaled:
            start = int((out - scaled) / 2)
            new_img[start:start + scaled, start:start + scaled] = img
        else:
            start = int((scaled - out) / 2)
            # print(start, out)
            new_img = img[start:start + out, start:start + out]
        new_img = new_img.astype('int16')
        return new_img

    # utils ---------

    class tqdm_skopt(object):
        def __init__(self, **kwargs):
            self._bar = tqdm(**kwargs)

        def __call__(self, res):
            self._bar.update()

    def hist_match(self, source, template):
        """
        Adjust the pixel values of a grayscale image such that its histogram
        matches that of a target image
        https://stackoverflow.com/questions/32655686/histogram-matching-of-two-images-in-python-2-x

        Arguments:
        -----------
            source: cp.ndarray
                Image to transform; the histogram is computed over the
                flattened array
            template: cp.ndarray
                Template image; can have different dimensions to source
        Returns:
        -----------
            matched: cp.ndarray
                The transformed output image
        """

        oldshape = source.shape
        source = source.ravel()
        template = template.ravel()

        # get the set of unique pixel values and their corresponding
        # indices and counts
        s_values, bin_idx, s_counts = cp.unique(source, return_inverse=True,
                                                return_counts=True)
        t_values, t_counts = cp.unique(template, return_counts=True)

        # take the cumsum of the counts and normalize by the number of
        # pixels to get the empirical cumulative distribution functions
        # for the source and template images (maps pixel value --> quantile)
        s_quantiles = cp.cumsum(s_counts).astype(cp.float64)
        s_quantiles /= s_quantiles[-1]
        t_quantiles = cp.cumsum(t_counts).astype(cp.float64)
        t_quantiles /= t_quantiles[-1]

        # interpolate linearly to find the pixel values in the template image
        # that correspond most closely to the quantiles in the source image
        interp_t_values = cp.interp(s_quantiles, t_quantiles, t_values)

        return interp_t_values[bin_idx].reshape(oldshape)

    def circ(self, r, height, width):
        f = cp.full((height, width), 1)
        i = r
        hh, hw = (height / 2, width / 2)
        for x in range(0, height):
            for y in range(0, width):
                dist = math.sqrt((x - hh) * (x - hh) + (y - hw) * (y - hw))
                if dist > i:
                    f[x][y] = 0
        return f

    def getnoise(self, octaves, intensity, height=500, seed=1):
        noise = PerlinNoise(octaves=octaves, seed=seed)
        xpix, ypix = height, height
        pic = ([[noise([i/xpix, j/ypix]) for j in range(xpix)]
               for i in range(ypix)])

        pic = np.stack(pic)
        pic = cp.array(pic)
        pic /= cp.max(pic)
        pic *= self.circ(150, height, height)
        pic *= intensity
        pic += 1

        for x in range(0, len(pic)):
            for y in range(0, len(pic[x])):
                pass

        return cp.array(pic)
