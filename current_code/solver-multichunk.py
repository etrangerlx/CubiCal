from msread import *
from time import time


def compute_jhr(obser_arr, model_arr, gains):
    """
    This function computes the (J^H)R term of the GN/LM method for the
    full-polarisation, phase-only case.

    Args:
        obser_arr (np.array): Array containing the observed visibilities.
        model_arr (np.array): Array containing the model visibilities.
        gains (np.array): Array containing the current gain estimates.

    Returns:
        jhr (np.array): Array containing the result of computing (J^H)R.
    """

    spec_eye = np.zeros([2, 4])
    spec_eye[(0, 1), (0, 3)] = 1

    new_shape = list(model_arr.shape)
    new_shape[-3:] = [4, 1]

    rg = np.einsum("gh...ij,gh...jk->gh...ik", obser_arr, gains)

    rgmh = np.einsum("...ij,...kj->...ik", rg, model_arr.conj())

    rgmh = np.sum(rgmh, axis=-3)

    ghi = np.einsum("...ij,...jk->...ik", gains.conj(), spec_eye)

    ghirgmh = np.einsum("...ij,...jk->...ik", ghi, rgmh.reshape(new_shape))

    jhr = -2 * ghirgmh.imag

    return jhr


def compute_jhjinv(model_arr):
    """
    This function computes the ((J^H)J)^-1 term of the GN/LM method for the
    full-polarisation, phase-only case. Note that this depends only on the
    model visibilities.

    Args:
        model_arr (np.array): Array containing the model visibilities.

    Returns:
        jhjinv (np.array): Array containing the result of computing ((J^H)J)^-1.
    """

    new_shape = list(model_arr.shape)
    new_shape[-2:] = [4]

    to_norm = np.array([[2, 0, 0, 0], [1, 0, 0, 1],
                        [1, 0, 0, 1], [0, 0, 0, 2]])

    jhjinv = np.sum(abs(model_arr.reshape(new_shape))**2, axis=-2).dot(to_norm)

    jhjinv[jhjinv != 0] = 1./jhjinv[jhjinv != 0]

    new_shape[-2:] = [2, 2]

    return jhjinv.reshape(new_shape)


def compute_update(model_arr, obser_arr, gains, jhjinv):
    """
    This function computes the update step of the GN/LM method. This is
    equivalent to the complete (((J^H)J)^-1)(J^H)R.

    Args:
        obser_arr (np.array): Array containing the observed visibilities.
        model_arr (np.array): Array containing the model visibilities.
        gains (np.array): Array containing the current gain estimates.
        jhjinv (np.array): Array containing (J^H)J)^-1. (Invariant)

    Returns:
        update (np.array): Array containing the result of computing
            (((J^H)J)^-1)(J^H)R
    """

    jhr = compute_jhr(obser_arr, model_arr, gains)

    update = np.einsum("...ij,...jk->...ik", jhjinv, jhr)

    return update


def compute_residual(obser_arr, model_arr, gains):
    """
    This function computes the residual. This is the difference between the
    observed data, and the model data with the gains applied to it.

    Args:
        obser_arr (np.array): Array containing the observed visibilities.
        model_arr (np.array): Array containing the model visibilities.
        gains (np.array): Array containing the current gain estimates.

    Returns:
        residual (np.array): Array containing the result of computing D-GMG^H.
    """

    gm = np.einsum("...lij,...lmjk->...lmik", gains, model_arr)

    gmgh = np.einsum("...lmij,...mkj->...lmik", gm, gains.conj())

    residual = obser_arr - gmgh

    return residual


def full_pol_phase_only(model_arr, obser_arr, min_delta_g=1e-3, maxiter=30,
                        chi_tol=1e-6, chi_interval=5):
    """
    This function is the main body of the GN/LM method. It handles iterations
    and convergence tests.

    Args:
        obser_arr (np.array): Array containing the observed visibilities.
        model_arr (np.array): Array containing the model visibilities.
        min_delta_g (float): Gain improvement threshold.
        maxiter (int): Maximum number of iterations allowed.
        chi_tol (float): Chi-squared improvement threshold.
        chi_interval (int): Interval at which the chi-squared test is performed.

    Returns:
        gains (np.array): Array containing the final gain estimates.
    """

    phase_shape = list(model_arr.shape)
    phase_shape[-3:] = [2, 1]

    phases = np.zeros(phase_shape)

    gains = np.einsum("...ij,...jk", np.exp(-1j*phases), np.ones([1, 2]))
    gains[..., (0, 1), (1, 0)] = 0

    delta_g = 1
    iters = 0
    chi = np.inf

    jhjinv = compute_jhjinv(model_arr)

    while delta_g > min_delta_g:

        if iters % 2 == 0:
            fact = 0.5
        else:
            fact = 1

        phases += fact*compute_update(model_arr, obser_arr, gains, jhjinv)

        delta_g = gains.copy()

        gains = np.einsum("...ij,...jk", np.exp(-1j*phases), np.ones([1, 2]))
        gains[..., (0, 1), (1, 0)] = 0

        iters += 1

        if iters > maxiter:
            return gains

        if (iters % chi_interval) == 0:
            old_chi = chi
            chi = np.linalg.norm(compute_residual(obser_arr, model_arr, gains))
            if (old_chi - chi) < chi_tol:
                return gains
            if old_chi < chi:
                print "Bad solutions."
                return gains

        delta_g = np.linalg.norm(delta_g - gains)

    return gains


def apply_gains(obser_arr, gains):
    """
    Applies the inverse of the gain estimates to the observed data matrix.

    Args:
        obser_arr (np.array): Array of the observed visibilities.
        gains (np.array): Array of the gain estimates.

    Returns:
        inv_gdgh (np.array): Array containing (G^-1)D(G^-H).
    """

    inv_gains = np.transpose(gains[..., ::-1, ::-1], axes=[0, 1, 2, 4, 3])

    inv_gains = np.array([[1, -1], [-1, 1]]) * inv_gains

    inv_gains *= 1./(gains[..., 0, 0] * gains[..., 1, 1]
                   - gains[..., 0, 1] * gains[..., 1, 0])[..., None, None]

    inv_gd = np.einsum("...lij,...lmjk->...lmik", inv_gains, obser_arr)

    inv_gdgh = np.einsum("...lmij,...mkj->...lmik", inv_gd, inv_gains.conj())

    return inv_gdgh


ms = DataHandler("WESTERBORK_POINT.MS")
ms.fetch_all()
ms.define_chunk(10, 1)

t0 = time()
for b, a in ms:
    gains = full_pol_phase_only(a, b)
    corr_vis = apply_gains(b, gains)
    ms.array_to_vis(corr_vis, ms._first_t, ms._last_t, ms._first_f, ms._last_f)
print time() - t0

ms.save(ms.covis, "CORRECTED_DATA")

