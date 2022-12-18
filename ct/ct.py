import pathlib
import pydicom
import numpy as np
import glob
from tqdm.autonotebook import tqdm as notebook_tqdm
from scipy.ndimage import zoom

# filename = 'ct_no_tumor_phantom_raw/001/1-001-0%s.img' % f'{i:03}'
# filename = script_dir / Path('../train_dcm') / Path(volname) /
#  Path(edition) / Path('%s.dcm' % f'{i:03}')
here = pathlib.Path(__file__).parent.parent.resolve()


class ctset():
    def __init__(self, name: str, type):
        self.name = name
        self.sheets = len(glob.glob(str(here / "data" / f"{self.name}"
                                        / "ct" / "*.dcm")))
        self.raw_data = np.empty(self.sheets, dtype=object)
        self.img = np.empty(self.sheets, dtype=object)
        for i in notebook_tqdm(range(0, self.sheets)):
            self.raw_data[i] = self.load(i)
        self.raw_data = sorted(self.raw_data,
                               key=lambda x: x.ImagePositionPatient[2])

        if type == "uint8":
            for i in range(0, self.sheets):
                self.img[i] = 255 - self.raw_data[i].pixel_array.astype('uint8')

        if type == "float32":
            for i in range(0, self.sheets):
                self.img[i] = self.raw_data[i].pixel_array.astype('float32')
                self.img[i] /= 4095.
                self.img[i] *= 255.
                self.img[i] = self.img[i].astype('uint8')

    def load(self, num: int):
        file = here / "data" / f"{self.name}" / "ct" / f"{num:04d}.dcm"
        # self.raw_data[num] = pydicom.dcmread(file)
        return pydicom.dcmread(file)
        # self.img[num] = self.raw_data[num].pixel_array.astype('uint8')
        # self.img[num] = 255 - self.img[num]

    def get(self, num: int):
        return self.img[num]

    def get_volume(self, zm=1, pad=0):
        ds = self.raw_data[0]

        # get spacing
        delX, delY = ds.PixelSpacing
        delX, delY = float(delX), float(delY)
        Zs = []
        for idx in range(0, len(self.raw_data)):
            Zs.append(self.raw_data[idx].ImagePositionPatient[2])

        Zs = np.unique(Zs)
        delZ = Zs[0]

        delZs = Zs
        delZs = np.diff(delZs)
        delZ = delZs[0]

        # define output shape
        nx, ny = ds.pixel_array.shape
        nz = len(Zs) + 2 * pad
        volume = np.zeros((nx, nz, ny))

        # create volume
        for idx in range(0, pad):
            volume[:, idx, :] = self.img[10]

        c = 0
        last_z = self.raw_data[0].ImagePositionPatient[2]
        volume[:, c, :] = self.img[0]

        for idx in range(0, len(self.raw_data)):
            if last_z != self.raw_data[idx].ImagePositionPatient[2]:
                c += 1
                volume[:, c + pad, :] = self.img[idx]
                last_z = self.raw_data[idx].ImagePositionPatient[2]

        for idx in range(len(Zs) + pad, len(Zs) + 2 * pad):
            volume[:, idx, :] = self.img[len(self.img) - 20]

        spacing = [delX / zm, delZ / zm, delY / zm]

        volume = zoom(volume, (zm, zm, zm), order=0, mode='nearest')
        return volume, spacing
