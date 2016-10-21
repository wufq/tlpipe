"""Re-order data to have longitude from 0 to 2pi."""

import numpy as np
import tod_task
from tlpipe.core import constants as const
from caput import mpiarray


class ReOrder(tod_task.IterTimestream):
    """Re-order data to have longitude from 0 to 2pi."""

    params_init = {
                    'discard_less': 0.2, # discard if data less than this sidereal day
                  }

    prefix = 'ro_'

    def process(self, ts):

        discard_less = self.params['discard_less']
        nt = ts.vis.shape[0]
        int_time = ts.attrs['inttime']
        if nt * int_time < discard_less * const.sday:
            return None

        ts.redistribute('baseline')

        # re-order data to have longitude from 0 to 2pi
        num_int = np.int(np.ceil(1.0 * const.sday / ts.attrs['inttime']))
        extra_inttime = ts.vis.attrs['extra_inttime']
        if nt > num_int + 2*extra_inttime:
            raise RuntimeError('Now can only process data less than one sidereal day')
        if nt <= 2*extra_inttime:
            raise RuntimeError('Too short data to proceed: %d <= %d' % (nt, 2*extra_inttime))
        # try to complete data if it is short than a sidereal day
        if nt <= num_int + 2*extra_inttime:
            # first complete main data vis
            vis = np.zeros((num_int,)+ts['vis'].local_shape[1:], dtype=ts['vis'].dtype)
            nt1 = nt - 2*extra_inttime
            vis[:nt1] = ts.local_vis[extra_inttime:-extra_inttime]
            # vis[nt1:] = complex(np.nan, np.nan) # mask the completed data
            vis = mpiarray.MPIArray.wrap(vis, axis=ts['vis'].distributed_axis)
            ts.create_main_data(vis, recreate=True, copy_attrs=True)

            # complete vis_mask
            vis_mask = np.ones((num_int,)+ts['vis_mask'].local_shape[1:], dtype=ts['vis_mask'].dtype) # initialize as masked
            vis_mask[:nt1] = ts.local_vis_mask[extra_inttime:-extra_inttime]
            # vis_mask[nt1:] = True # mask the completed data
            vis_mask = mpiarray.MPIArray.wrap(vis_mask, axis=ts['vis'].distributed_axis)
            axis_order = ts.main_axes_ordered_datasets[ts.main_data_name]
            ts.create_main_axis_ordered_dataset(axis_order, 'vis_mask', vis_mask, axis_order, recreate=True, copy_attrs=True)

            # complete ra_dec
            ra_dec = np.zeros((num_int, 2), dtype=ts['ra_dec'].dtype)
            ra_dec[:nt1] = ts['ra_dec'][extra_inttime:-extra_inttime]
            dphi = 2 * np.pi * ts.attrs['inttime'] / const.sday
            ra_dec[nt1:, 0] = np.array([ ts['ra_dec'][-1, 0] + dphi*i for i in range(num_int-nt1) ]) # for ra
            ra_dec[:, 0] = np.where(ra_dec[:, 0]>2*np.pi, ra_dec[:, 0]-2*np.pi, ra_dec[:, 0])
            ra_dec[nt1:, 1] = np.mean(ts['ra_dec'][:, 1]) # for dec
            ts.create_main_axis_ordered_dataset('time', 'ra_dec', ra_dec, (0,), recreate=True, copy_attrs=True)

            # complete other main_time_ordered_datasets with zeros
            for name in ts.main_time_ordered_datasets.keys():
                if name in ts.iterkeys() and not name in ('vis', 'vis_mask', 'ra_dec'):
                    dset = ts[name]
                    axis_order = ts.main_axes_ordered_datasets[name]
                    axis = tuple([ ts.main_data_axes[ax] for ax in axis_order if ax is not None ])
                    # create a new array to hold data for a sidereal day
                    shp = list(dset.local_data.shape)
                    time_axis = ts.main_axes_ordered_datasets[name].index(0)
                    shp[time_axis] = num_int
                    data  = np.zeros(tuple(shp), dtype=dset.dtype)
                    sel1 = [ slice(0, None) ] * len(shp)
                    sel1[time_axis] = slice(0, nt1)
                    sel2 = [ slice(0, None) ] * len(shp)
                    sel2[time_axis] = slice(extra_inttime, -extra_inttime)
                    data[sel1] = dset.local_data[sel2]
                    if dset.distributed:
                        data = mpiarray.MPIArray.wrap(data, axis=time_axis)
                    ts.create_main_axis_ordered_dataset(axis, name, data, axis_order, recreate=True, copy_attrs=True)

        # the new phi
        phi = ts['ra_dec'][:, 0]
        # find phi = 0 ind
        ind0 = np.where(np.diff([phi[-1]] + phi.tolist()) < -1.9 * np.pi)[0][0]

        # re-order all main_time_ordered_datasets
        for name in ts.main_time_ordered_datasets.keys():
            if name in ts.iterkeys():
                dset = ts[name]
                time_axis = ts.main_time_ordered_datasets[name].index(0)
                sel1 = [slice(0, None)] * (time_axis + 1)
                sel2 = sel1[:]
                sel1[time_axis] = slice(ind0, None)
                sel2[time_axis] = slice(0, ind0)
                dset.local_data[:] = np.concatenate([ dset.local_data[sel1], dset.local_data[sel2] ], axis=time_axis)

        ts.add_history(self.history)

        # ts.info()

        return ts
