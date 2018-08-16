#!/usr/bin/env python
from functools import partial
import logging
from multiprocessing import Pool
import os
import pickle
from typing import Tuple
import numpy as np
import pandas as pd
from tqdm import trange
import spdivik.distance as dst
import spdivik.kmeans as km
import spdivik.types as ty
import spdivik.score as sc
import spdivik._scripting as scr


def assert_configured(config, name):
    assert name in config, 'Missing "' + name + '" field in config.'


def build_experiment(config):
    assert_configured(config, 'distance')
    known_distances = {metric.value: metric for metric in dst.KnownMetric}
    assert config['distance'] in known_distances, \
        'Unknown distance {0}. Known: {1}'.format(
        config['distance'], list(known_distances.keys()))
    distance = dst.ScipyDistance(known_distances[config['distance']])
    labeling = km.Labeling(distance)
    assert_configured(config, 'initialization_percentile')
    initialization_percentile = float(config['initialization_percentile'])
    assert 0 <= initialization_percentile <= 100
    initialization = km.PercentileInitialization(
        distance=distance, percentile=initialization_percentile)
    assert_configured(config, 'number_of_iterations')
    number_of_iterations = int(config['number_of_iterations'])
    assert 0 <= number_of_iterations
    kmeans = km.KMeans(labeling=labeling, initialize=initialization,
                       number_of_iterations=number_of_iterations)
    assert_configured(config, 'gap_trials')
    gap_trials = int(config['gap_trials'])
    assert 0 <= gap_trials
    assert_configured(config, 'maximal_number_of_clusters')
    maximal_number_of_clusters = int(config['maximal_number_of_clusters'])
    assert 0 <= maximal_number_of_clusters
    pool_max_tasks = int(config.get('pool_max_tasks', 4))
    assert 0 <= pool_max_tasks
    pool = Pool(maxtasksperchild=pool_max_tasks)
    use_pool_for_grouping = bool(config.get('use_pool_for_grouping', False))
    gap = partial(sc.gap, distance=distance, n_trials=gap_trials, pool=pool,
                  return_deviation=True)
    return kmeans, gap, maximal_number_of_clusters, pool, \
           pool if use_pool_for_grouping else None


def split_into_one(data: ty.Data) -> Tuple[ty.IntLabels, ty.Centroids]:
    return np.zeros((data.shape[0],), dtype=int), np.mean(data, axis=0, keepdims=True)


class DataBoundKmeans:
    def __init__(self, kmeans, data):
        self.kmeans, self.data = kmeans, data

    def __call__(self, number_of_clusters):
        return self.kmeans(data=self.data,
                           number_of_clusters=number_of_clusters)


def split(data: ty.Data, kmeans: km.KMeans, pool: Pool,
          maximal_number_of_clusters: int):
    data_bound_kmeans = DataBoundKmeans(kmeans=kmeans, data=data)
    if pool is not None:
        logging.info('Segmenting data in parallel.')
        segmentations = pool.map(data_bound_kmeans,
                                 range(2, maximal_number_of_clusters+1))
    else:
        logging.info('Segmenting data in sequential.')
        segmentations = [
            data_bound_kmeans(number_of_clusters) for number_of_clusters
            in trange(2, maximal_number_of_clusters+1)
        ]
    logging.info('Data segmented.')
    return [split_into_one(data)] + segmentations


def build_splitter(kmeans, number_of_clusters):
    if number_of_clusters == 1:
        return split_into_one
    else:
        return partial(kmeans, number_of_clusters=number_of_clusters)


def score_splits(segmentations, data: ty.Data, kmeans: km.KMeans, gap,
                 maximal_number_of_clusters: int):
    logging.info('Scoring splits with GAP statistic.')
    scores = [
        gap(data=data, labels=labels, centroids=centroids,
            split=build_splitter(kmeans, number_of_clusters))
        for number_of_clusters, (labels, centroids)
        in zip(trange(1, maximal_number_of_clusters+1), segmentations)
    ]
    logging.info('Scoring completed.')
    return scores


def make_segmentations_matrix(segmentations) -> np.ndarray:
    return np.hstack([s[0].reshape(-1, 1) for s in segmentations])


def make_scores_report(scores) -> pd.DataFrame:
    report = pd.DataFrame(scores, columns=['GAP', 's_k'])
    report['number_of_clusters'] = range(1, len(scores) + 1)
    is_suggested = report.GAP[:-1].values > (report.GAP[1:] + report.s_k[1:])
    report['suggested_number_of_clusters'] = list(is_suggested) + [False]
    return report


def save(segmentations, scores, destination: str):
    logging.info("Saving result.")
    logging.info("Saving segmentations.")
    with open(os.path.join(destination, 'segmentations.pkl'), 'wb') as pkl:
        pickle.dump(segmentations, pkl)
    partitions = make_segmentations_matrix(segmentations)
    np.savetxt(os.path.join(destination, 'partitions.csv'), partitions,
               delimiter=', ', fmt='%i')
    logging.info("Saving scores.")
    report = make_scores_report(scores)
    report.to_csv(os.path.join(destination, 'scores.csv'))


def main():
    arguments = scr.parse_args()
    destination = scr.prepare_destination(arguments.destination)
    scr.setup_logger(destination)
    config = scr.load_config(arguments.config, destination)
    kmeans, gap, maximal_number_of_clusters, pool, kmeans_pool = build_experiment(config)
    data = scr.load_data(arguments.source)
    try:
        segmentations = split(data, kmeans, kmeans_pool, maximal_number_of_clusters)
        scores = score_splits(segmentations, data, kmeans, gap, maximal_number_of_clusters)
    except Exception as ex:
        logging.error("Failed with exception.")
        logging.error(repr(ex))
        raise
    finally:
        pool.close()
    save(segmentations, scores, destination)


if __name__ == '__main__':
    main()
