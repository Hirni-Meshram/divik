from functools import reduce
from multiprocessing import Pool
import os

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClusterMixin, TransformerMixin
import tqdm

import divik.distance as dst
from divik.kmeans._core import normalize_rows
import divik.predefined as predefined
import divik.summary as summary


class DiviK(BaseEstimator, ClusterMixin, TransformerMixin):
    """DiviK clustering

    Parameters
    ----------

    gap_trials: int, optional, default: 10
        The number of random dataset draws to estimate the GAP index for the
        clustering quality assessment.

    distance_percentile: float, optional, default: 99.0
        The percentile of the distance between points and their closest
        centroid. 100.0 would simply select the furthest point from all the
        centroids found already. Lower value provides better robustness against
        outliers. Too low value reduces the capability to detect centroid
        candidates during initialization.

    max_iter: int, optional, default: 100
        Maximum number of iterations of the k-means algorithm for a single run.

    distance: str, optional, default: 'correlation'
        The distance metric between points, centroids and for GAP index
        estimation.

    minimal_size: int, optional, default: None
        The minimum size of the region (the number of observations) to be
        considered for any further divisions. When left None, defaults to
        0.1% of the training dataset size.

    rejection_size: int, optional, default: None
        Size under which split will be rejected - if a cluster appears in the
        split that is below rejection_size, the split is considered improper
        and discarded. This may be useful for some domains (like there is no
        justification for a 3-cells cluster in biological data). By default,
        no segmentation is discarded, as careful post-processing provides the
        same advantage.

    rejection_percentage: float, optional, default: None
        An alternative to ``rejection_size``, with the same behavior, but this
        parameter is related to the training data size percentage. By default,
        no segmentation is discarded.

    minimal_features_percentage: float, optional, default: 0.01
        The minimal percentage of features that must be preserved after
        GMM-based feature selection. By default at least 1% of features is
        preserved in the filtration process.

    fast_kmeans_iters: int, optional, default: 10
        Maximum number of iterations of the k-means algorithm for a single run
        during computation of the GAP index. Decreased with respect to the
        max_iter, as GAP index requires multiple segmentations to be evaluated.

    k_max: int, optional, default: 10
        Maximum number of clusters evaluated during the auto-tuning process.
        From 1 up to k_max clusters are tested per evaluation.

    normalize_rows: bool, optional, default: None
        Whether to normalize each row of the data to the norm of 1. By default,
        it normalizes rows for correlation metric, does no normalization
        otherwise.

    use_logfilters: bool, optional, default: False
        Whether to compute logarithm of feature characteristic instead of the
        characteristic itself. This may improve feature filtering performance,
        depending on the distribution of features, however all the
        characteristics (mean, variance) have to be positive for that -
        filtering will fail otherwise. This is useful for specific cases in
        biology where the distribution of data may actually require this option
        for any efficient filtering.

    n_jobs : int, optional, default: None
        The number of jobs to use for the computation. This works by computing
        each of the GAP index evaluations in parallel.

    verbose : bool, optional, default: False
        Whether to report the progress of the computations.

    Attributes
    ----------

    result_ : divik.types.DivikResult
        Hierarchical structure describing all the consecutive segmentations.

    labels_ :
        Labels of each point

    centroids_ : array, [n_clusters, n_features]
        Coordinates of cluster centers. If the algorithm stops before fully
        converging, these will not be consistent with ``labels_``. Also, the
        distance between points and respective centroids must be captured
        in appropriate features subspace. This is realized by the ``transform``
        method.

    depth_ : int
        The number of hierarchy levels in the segmentation.

    n_clusters_ : int
        The final number of clusters in the segmentation, on the tree leaf
        level.

    paths_ : Dict[int, Tuple[int]]
        Describes how the cluster number corresponds to the path in the tree.
        Element of the tuple indicates the sub-segment number on each tree
        level.

    reverse_paths_ : Dict[Tuple[int], int]
        Describes how the path in the tree corresponds to the cluster number.
        For more details see ``paths_``.

    Examples
    --------

    >>> from divik import DiviK
    >>> from sklearn.datasets import make_blobs
    >>> X, _ = make_blobs(n_samples=200, n_features=100, centers=20,
    ...                   random_state=42)
    >>> divik = DiviK(distance='euclidean').fit(X)
    >>> divik.labels_
    array([1, 1, 1, 0, ..., 0, 0], dtype=int32)
    >>> divik.predict([[0, ..., 0], [12, ..., 3]])
    array([1, 0], dtype=int32)
    >>> divik.cluster_centers_
    array([[10., ...,  2.],
           ...,
           [ 1, ...,  2.]])

    """

    def __init__(self,
                 gap_trials: int = 10,
                 distance_percentile: float = 99.,
                 max_iter: int = 100,
                 distance: str = dst.KnownMetric.correlation.value,
                 minimal_size: int = None,
                 rejection_size: int = None,
                 rejection_percentage: float = None,
                 minimal_features_percentage: float = .01,
                 fast_kmeans_iters: int = 10,
                 k_max: int = 10,
                 normalize_rows: bool = None,
                 use_logfilters: bool = False,
                 n_jobs: int = None,
                 verbose: bool = False):
        if distance not in list(dst.KnownMetric):
            raise ValueError('Unknown distance: %s' % distance)

        self.gap_trials = gap_trials
        self.distance_percentile = distance_percentile
        self.max_iter = max_iter
        self.distance = distance
        self.minimal_size = minimal_size
        self.rejection_size = rejection_size
        self.rejection_percentage = rejection_percentage
        self.minimal_features_percentage = minimal_features_percentage
        self.fast_kmeans_iters = fast_kmeans_iters
        self.k_max = k_max
        self.normalize_rows = normalize_rows
        self.use_logfilters = use_logfilters
        self.n_jobs = n_jobs
        self.verbose = verbose

    def fit(self, X, y=None):
        """Compute DiviK clustering.

        Parameters
        ----------
        X : array-like or sparse matrix, shape=(n_samples, n_features)
            Training instances to cluster. It must be noted that the data
            will be converted to C ordering, which will cause a memory
            copy if the given data is not C-contiguous.
        y : Ignored
            not used, present here for API consistency by convention.
        """
        n_cpu = os.cpu_count()
        n_jobs = 1 if self.n_jobs is None else self.n_jobs
        n_jobs = (n_jobs + n_cpu) % n_cpu or n_cpu

        if self.normalize_rows is None:
            if self.distance == dst.KnownMetric.correlation.value:
                normalize_rows = True
            else:
                normalize_rows = False
        else:
            normalize_rows = self.normalize_rows

        minimal_size = int(X.shape[0] * 0.001) if self.minimal_size is None \
            else self.minimal_size

        with Pool(n_jobs) as pool,\
                tqdm.tqdm(total=X.shape[0], leave=self.verbose) as progress:
            divik = predefined.basic(
                gap_trials=self.gap_trials,
                distance_percentile=self.distance_percentile,
                iters_limit=self.max_iter,
                distance=self.distance,
                minimal_size=minimal_size,
                rejection_size=self.rejection_size,
                rejection_percentage=self.rejection_percentage,
                minimal_features_percentage=self.minimal_features_percentage,
                fast_kmeans_iters=self.fast_kmeans_iters,
                k_max=self.k_max,
                correction_of_gap=True,
                normalize_rows=normalize_rows,
                use_logfilters=self.use_logfilters,
                pool=pool,
                progress_reporter=progress if self.verbose else None
            )
            self.result_ = divik(X)

        self.labels_, self.paths_ = summary.merged_partition(self.result_,
                                                             return_paths=True)
        self.reverse_paths_ = {value: key for key, value in self.paths_.items()}
        self.centroids_ = pd.DataFrame(X).groupby(self.labels_).mean().values
        self.depth_ = summary.depth(self.result_)
        self.n_clusters_ = summary.total_number_of_clusters(self.result_)

        return self

    def fit_predict(self, X, y=None):
        """Compute cluster centers and predict cluster index for each sample.

        Convenience method; equivalent to calling fit(X) followed by
        predict(X).

        Parameters
        ----------

        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            New data to transform.

        y : Ignored
            not used, present here for API consistency by convention.

        Returns
        -------

        labels : array, shape [n_samples,]
            Index of the cluster each sample belongs to.
        """
        return self.fit(X).labels_

    def fit_transform(self, X, y=None, **fit_params):
        """Compute clustering and transform X to cluster-distance space.

        Equivalent to fit(X).transform(X), but more efficiently implemented.

        Parameters
        ----------

        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            New data to transform.

        y : Ignored
            not used, present here for API consistency by convention.

        Returns
        -------

        X_new : array, shape [n_samples,]
            X transformed in the new space.
        """
        # TODO: optimize
        return self.fit(X).transform(X)

    def transform(self, X, with_path: bool = False):
        """Transform X to a cluster-distance space.

        In the new space, each dimension is the distance to the cluster
        centers.  Note that even if X is sparse, the array returned by
        `transform` will typically be dense.

        Parameters
        ----------

        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            New data to transform.

        Returns
        -------

        X_new : array, shape [n_samples,]
            X transformed in the new space.
        """
        if self.normalize_rows is None:
            if self.distance == dst.KnownMetric.correlation.value:
                normalize_rows_ = True
            else:
                normalize_rows_ = False
        else:
            normalize_rows_ = self.normalize_rows

        if normalize_rows_:
            X = normalize_rows(X)

        distance = dst.ScipyDistance(dst.KnownMetric[self.distance])

        # TODO: optimize
        distances, paths = [], []
        for row in X:
            division = self.result_
            path = []
            while division is not None:
                selectors = division.filters
                restricted = reduce(np.logical_and, selectors.values(), True)
                local_X = row[np.newaxis, restricted]
                d = distance(local_X, division.centroids)
                assert d.shape[0] == 1 or d.shape[1] == 1
                d = d.ravel()
                label = np.argmin(d.ravel())
                path.append(label)
                division = division.subregions[label]
            path = tuple(path)
            distances.append(d[label])
            paths.append(path)

        if with_path:
            return np.array(distances), paths

        return np.array(distances)

    def predict(self, X):
        """Predict the closest cluster each sample in X belongs to.

        In the vector quantization literature, `cluster_centers_` is called
        the code book and each value returned by `predict` is the index of
        the closest code in the code book.

        Parameters
        ----------

        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            New data to predict.

        Returns
        -------

        labels : array, shape [n_samples,]
            Index of the cluster each sample belongs to.
        """
        _, paths = self.transform(X, with_path=True)
        return np.array([self.reverse_paths_[path] for path in paths])
