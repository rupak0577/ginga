import numpy as np

from astropy.stats import sigma_clip, biweight_location


def calc_stat(data, sigma=1.8, niter=10, algorithm='mean'):
    """Calculate statistics for given data.
    Parameters
    ----------
    data : ndarray
        Data to be calculated from.
    sigma : float
        Sigma for sigma clipping.
    niter : int
        Number of iterations for sigma clipping.
    algorithm : {'mean', 'median', 'mode', 'stddev'}
        Algorithm for statistics calculation.
    Returns
    -------
    val : float
        Statistics value.
    Raises
    ------
    ValueError
        Invalid algorithm.
    """
    arr = np.ravel(data)

    if len(arr) < 1:
        return 0.0

    # NOTE: Now requires Astropy 1.1 or later, so this check is not needed.
    #from astropy import version as astropy_version
    #if ((astropy_version.major==1 and astropy_version.minor==0) or
    #        (astropy_version.major < 1)):
    #    arr_masked = sigma_clip(arr, sig=sigma, iters=niter)
    #else:
    #    arr_masked = sigma_clip(arr, sigma=sigma, iters=niter)
    arr_masked = sigma_clip(arr, sigma=sigma, iters=niter)

    arr = arr_masked.data[~arr_masked.mask]

    if len(arr) < 1:
        return 0.0

    if algorithm == 'mean':
        val = arr.mean()
    elif algorithm == 'median':
        val = np.median(arr)
    elif algorithm == 'mode':
        val = biweight_location(arr)
    elif algorithm == 'stddev':
        val = arr.std()

    return val
