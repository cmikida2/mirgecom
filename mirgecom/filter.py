__copyright__ = """
Copyright (C) 2020 University of Illinois Board of Trustees
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import math
import numpy as np
import loopy as lp
#from pytools import memoize_method
from pytools.obj_array import make_obj_array


def get_spectral_filter(dim, order, cutoff, filter_order):
    r"""
    Exponential spectral filter from JSH/TW Nodal DG Methods, pp. 130, 186
    """
    npol = 1
    for d in range(1, dim+1):
        npol *= (order + d)
    npol /= math.factorial(int(dim))
    npol = int(npol)
    filter = np.identity(npol)
    alpha = -1.0*np.log(np.finfo(float).eps)
    nfilt = npol - cutoff
    if nfilt <= 0:
        return filter
    nstart = cutoff - 1
    for m in range(nstart, npol):
        filter[m, m] = np.exp(-1.0 * alpha
                              * ((m - nstart) / nfilt) ** filter_order)
    return filter


class SpectralFilter:
    r"""
    Encapsulates the simulation-static filter operators and
    provides the methods to apply filtering to input fields.
    """
    def __init__(self, discr, filter_mat):
        self._filter_operators = {}
        from modepy import vandermonde
        for group in discr.groups:
            vander = vandermonde(group.basis(), group.unit_nodes)
            vanderm1 = np.linalg.inv(vander)
            filter_operator = np.matmul(vander, np.matmul(filter_mat, vanderm1))
            self._filter_operators[group] = filter_operator
        self._knl = lp.make_kernel(
            """{[k,i,j]:
            0<=k<nelements and
            0<=i<ndiscr_nodes_out and
            0<=j<ndiscr_nodes_in}""",
            "result[k,i] = sum(j, mat[i, j] * vec[k, j])",
            default_offset=lp.auto, name="diff")
        self._knl = lp.split_iname(self._knl, "i", 16, inner_tag="l.0")
        self._knl = lp.tag_array_axes(self._knl, "mat", "stride:auto,stride:auto")
        self._knl = lp.tag_inames(self._knl, dict(k="g.0"))

    def __call__(self, discr, fields):
        numfields = len(fields)
        if numfields <= 0:
            return fields
        queue = fields[0].queue
        dtype = fields[0].dtype

        result = make_obj_array([discr.empty(queue=queue, dtype=dtype)
                                 for i in range(numfields)])

        for group in discr.groups:
            filter_operator = self._filter_operators[group]
            for i, field in enumerate(fields):
                self._knl(queue, mat=filter_operator,
                          result=group.view(result[i]),
                          vec=group.view(field))

        return result