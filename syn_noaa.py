import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
from tensorflow.keras import models
import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)
import xarray as xr
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.colors

def perf_qm(org_stack, syn_stack, qm_stack, qm_type=0, nbins=100):
    map_syn = np.empty((qm_stack.sizes['time'],qm_stack.sizes['lat'],qm_stack.sizes['lon']))
    map_syn[:] = np.nan

    #print(nbins)
    # ----- Get list of percentage for generating quantile -----
    binmid = np.arange(0, 1.+1./nbins, 1./nbins)

    obs = org_stack.water_fraction.values
    syn = syn_stack.water_fraction.values

    qobs = np.nanquantile(obs, binmid, axis=0)
    qsyn = np.nanquantile(syn, binmid, axis=0)

    if qm_type==0:
        # ----- Conventional quantile-to-quantile mapping -----
        # (g = f = 1)
        # -- 1. Finding difference of quantile --
        d_ii = qobs - qsyn
        # -- 2. Get difference of mean --
        d_med = np.nanmean(obs,axis=0) - np.nanmean(syn,axis=0)
        # -- 3. Get difference of 1. - 2. --
        d_ii_med = d_ii - d_med
        # -- 4. Get parameters for 2. and 3. to get the correction value --
        #g = np.mean(syn)/np.mean(syn)
        #f = sci.stats.iqr(syn)/sci.stats.iqr(syn)
        g = 1
        f = 1

    # -- 5. Get the correction value as the linear summation of 2. and 3. --
    bias = g*d_med + f*d_ii_med

    # -- The correction value is based on which quantile bin the data value belongs to. --
    # -- So, to apply the correction value, need to first find out which quantile bin   --
    # -- that the data value corresponds to.                                            --
    # -- Here, it is done by interpolation.
    for ct_r in range(org_stack.sizes['lat']):
        for ct_c in range(org_stack.sizes['lon']):

            if np.isfinite(obs[0,ct_r,ct_c])==True and np.isfinite(syn[0,ct_r,ct_c])==True:
                qm_syn = qm_stack.water_fraction.values[:, ct_r, ct_c]
                # -- Interpolation: (x,y):(data value, quantile) --
                # -- 1. Get which quantile bin the given data value belongs to --
                bin_unc_mdl = np.interp(qm_syn, qsyn[:,ct_r,ct_c], binmid)
                # -- 2. Get the corresponding correction value --
                # -- Empirical quantiles (linear interpolation) --
                crt = np.interp(bin_unc_mdl, binmid, bias[:, ct_r, ct_c])

                temp = qm_syn + crt
                temp[temp>100] = 100
                temp[temp<0] = 0

                map_syn[:,ct_r,ct_c] = temp

    return map_syn

def run_fier(AOI_str, doi):

    # Path to read ncecesary data
    TF_model_path = 'AOI/'+AOI_str+'/TF_model/'
    hist_real_stack_path = 'AOI/'+AOI_str+'/aux_img_stack/hist_real_wf_2020.nc'
    hist_syn_stack_path = 'AOI/'+AOI_str+'/aux_img_stack/hist_syn_stack_2020.nc'
    RSM_path = 'AOI/'+AOI_str+'/RSM/RSM_hydro.nc'
    forecast_q_path = 'AOI/'+AOI_str+'/hydrodata/mid_fct_2019_2021_0024.nc'

    xr_RSM=xr.open_dataset(RSM_path)
    img_stack=xr.open_dataset(hist_real_stack_path)
    syn_wf=xr.open_dataset(hist_syn_stack_path)
    q_out = xr.open_dataarray(forecast_q_path)

    wf_mean = np.nanmean(img_stack.water_fraction.values, axis=0)
    for ct_mode in range(xr_RSM.sizes['mode']):

        mode = xr_RSM.spatial_modes.mode[ct_mode].values

        sm = xr_RSM.spatial_modes.sel(mode=mode)
        site = xr_RSM.hydro_site[ct_mode].values

        hydro_single = q_out[ct_mode]
        good_hydro = hydro_single[hydro_single.time.values==doi]
        #print(good_hydro)
        in_model = models.load_model(TF_model_path+'site-'+str(site)+'_tpc'+str(mode).zfill(2))

        in_good_hydro = good_hydro.values.reshape((len(good_hydro),1))
        tf_good_hydro = tf.data.Dataset.from_tensors(in_good_hydro)
        est_tpc = in_model.predict(tf_good_hydro)

        for ct_t in range(len(est_tpc)):
            syn_wf_temp = sm*est_tpc[ct_t]
            if ct_mode==0:
                syn_wf_fct = syn_wf_temp
            else:
                syn_wf_fct = syn_wf_fct + syn_wf_temp

    syn_wf_fct.values = syn_wf_fct.values + wf_mean
    # -- Remove empty coordicate and rename the data array to avoid confusion --
    syn_wf_fct=syn_wf_fct.assign_coords({'time':doi})
    syn_wf_fct=syn_wf_fct.expand_dims(dim='time',axis=0)
    syn_wf_fct.name = 'water_fraction'

    syn_wf_fct = syn_wf_fct.to_dataset()

    map_syn_fct = perf_qm(img_stack, syn_wf, syn_wf_fct, 0, 100)

    xr_RSM.close()
    img_stack.close()
    syn_wf.close()
    q_out.close()

    # # Create image
    # folder_name = 'Output'
    #
    # fig = plt.figure()
    # plt.imshow(map_syn_fct[0,:,:], cmap='jet', vmin=0, vmax=100,interpolation='none')
    # plt.axis('off')
    # plt.savefig(folder_name +'/water_fraction.png', bbox_inches='tight', dpi=300, pad_inches = 0)
    # plt.close()

    bounds = [[syn_wf_fct.lat.values.min(), syn_wf_fct.lon.values.min()],
    [syn_wf_fct.lat.values.max(), syn_wf_fct.lon.values.max()]]

    return bounds