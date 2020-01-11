from functools import partial
import sys
import uuid

import numpy as np
from sklearn.base import clone, BaseEstimator, ClusterMixin, TransformerMixin
from sklearn.utils.validation import check_is_fitted
import tqdm

from divik.cluster._kmeans._core import KMeans
from divik.score import gap, sampled_gap


_DATA = {}


class GAPSearch(BaseEstimator, ClusterMixin, TransformerMixin):
    """Select best number of cluters for k-means

    Parameters
    ----------
    kmeans : KMeans
        KMeans object to tune

    max_clusters: int
        The maximal number of clusters to form and score.

    min_clusters: int, default: 1
        The minimal number of clusters to form and score.

    n_jobs: int, default: 1
        The number of jobs to use for the computation. This works by computing
        each of the clustering & scoring runs in parallel.

    seed: int, default: 0
        Random seed for generating uniform data sets.

    n_trials: int, default: 10
        Number of data sets drawn as a reference.

    sample_size : int, default: 1000
        Size of the sample used for GAP statistic computation. Used only if
        introduces speedup.

    verbose: bool, default: False
        If True, shows progress with tqdm.

    Attributes
    ----------
    cluster_centers_: array, [n_clusters, n_features]
        Coordinates of cluster centers.

    labels_:
        Labels of each point.

    estimators_: List[KMeans]
        KMeans instances for n_clusters in range [min_clusters, max_clusters].

    scores_: array, [max_clusters - min_clusters + 1, ?]
        Array with scores for each estimator in each row.

    n_clusters_: int
        Estimated optimal number of clusters.

    best_score_: float
        Score of the optimal estimator.

    best_: KMeans
        The optimal estimator.

    """
    def __init__(self, kmeans: KMeans,
                 max_clusters: int, min_clusters: int = 1,
                 n_jobs: int = 1, seed: int = 0, n_trials: int = 10,
                 sample_size: int = 1000, verbose: bool = False):
        super().__init__()
        assert min_clusters <= max_clusters
        self.kmeans = kmeans
        self.min_clusters = min_clusters
        self.max_clusters = max_clusters
        self.n_jobs = n_jobs
        self.seed = seed
        self.n_trials = n_trials
        self.sample_size = sample_size
        self.verbose = verbose

    def _should_sample(self, data):
        sampled_complexity = 2 * self.n_trials * self.sample_size ** 2
        normal_complexity = self.n_trials * data.shape[0] ** 2
        return sampled_complexity < normal_complexity

    def _gap(self, data, kmeans):
        if self._should_sample(data):
            score = partial(sampled_gap, sample_size=self.sample_size)
        else:
            score = gap
        return score(data, kmeans, n_jobs=self.n_jobs, seed=self.seed,
                     n_trials=self.n_trials, return_deviation=True)

    def _fit_kmeans(self, n_clusters, data_ref):
        data = _DATA[data_ref]
        kmeans = clone(self.kmeans)
        kmeans.n_clusters = n_clusters
        kmeans.fit(data)
        idx, std = self._gap(data, kmeans)
        return kmeans, idx, std

    def fit(self, X, y=None):
        """Compute k-means clustering and estimate optimal number of clusters.

        Parameters
        ----------

        X : array-like or sparse matrix, shape=(n_samples, n_features)
            Training instances to cluster. It must be noted that the data
            will be converted to C ordering, which will cause a memory
            copy if the given data is not C-contiguous.

        y : Ignored
            not used, present here for API consistency by convention.

        """
        ref = str(uuid.uuid4())
        _DATA[ref] = X
        fit_kmeans = partial(self._fit_kmeans, data_ref=ref)
        n_clusters = range(self.min_clusters, self.max_clusters + 1)
        if self.verbose:
            n_clusters = tqdm.tqdm(n_clusters, leave=False, file=sys.stdout)

        self.fitted_ = False
        self.estimators_ = []
        self.scores_ = []
        prev_gap = -np.inf
        for n_clust in n_clusters:
            kmeans, gap_, std = fit_kmeans(n_clust)
            if prev_gap > gap_ + std:
                self.fitted_ = True
                break
            prev_gap = gap_
            self.estimators_.append(kmeans)
            self.scores_.append((gap_, std))
        if self.verbose:
            n_clusters.close()
        self.scores_ = np.array(self.scores_)
        del _DATA[ref]

        if self.fitted_:
            self.best_ = self.estimators_[-1]
            self.best_score_ = self.scores_[-1]
            self.n_clusters_ = self.best_.n_clusters
            self.labels_ = self.best_.labels_
            self.cluster_centers_ = self.best_.cluster_centers_
        else:
            self.best_ = None
            self.best_score_ = None
            self.n_clusters_ = None
            self.labels_ = None
            self.cluster_centers_ = None

        return self

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
        check_is_fitted(self)
        return self.best_.predict(X)

    def transform(self, X):
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

        X_new : array, shape [n_samples, k]
            X transformed in the new space.

        """
        check_is_fitted(self)
        return self.best_.transform(X)
