from __future__ import absolute_import
import numpy as np
import itertools
import operator
import random
import sys
import copy

from benchmark.plotting.eval_range_search import compute_AP
from benchmark.sensors.power_capture import power_capture

def compute_recall_without_distance_ties(true_ids, run_ids, count):
    return len(set(true_ids) & set(run_ids))

def compute_recall_with_distance_ties(true_ids, true_dists, run_ids, count):
    # This function assumes "true_dists" is monotonic either increasing or decreasing

    found_tie = False
    gt_size = np.shape(true_dists)[0]

    if gt_size==count:
        # nothing fancy to do in this case
        recall =  len(set(true_ids[:count]) & set(run_ids))

    else:
        dist_tie_check = true_dists[count-1] # tie check anchored at count-1 in GT dists
     
        set_end = gt_size

        for i in range(count, gt_size):
          is_close = abs(dist_tie_check - true_dists[i] ) < 1e-6 
          if not is_close:
            set_end = i
            break

        found_tie = set_end > count

        recall =  len(set(true_ids[:set_end]) & set(run_ids))
 
    return recall, found_tie

import numpy as np

def get_recall_values_by_vecs(true_nn, run_nn, count, count_ties=True):
    num_queries = true_nn.shape[0]  
    recalls = np.zeros(num_queries)  
    queries_with_ties = 0  

    for i in range(num_queries):
        true_vecs = true_nn[i]  
        run_vecs = run_nn[i]    

        distances = np.linalg.norm(true_vecs[:, np.newaxis, :] - run_vecs[np.newaxis, :, :], axis=2)  
        min_distances = np.min(distances, axis=0)  

        if count_ties:
            found_tie = False
            for j in range(count):
                if np.sum(np.isclose(distances[:, j], min_distances[j])) > 1:
                    found_tie = True
                    break
            if found_tie:
                queries_with_ties += 1

        correct = 0
        for j in range(count):
            if np.any(np.isclose(distances[:, j], min_distances[j])):
                correct += 1

        recalls[i] = correct / count

    mean_recall = np.nanmean(recalls)
    std_recall = np.std(recalls)

    return mean_recall, std_recall, recalls, queries_with_ties
    
def get_recall_values(true_nn, run_nn, count, count_ties=True):
    true_ids, true_dists = true_nn

    if not count_ties:
        true_ids = true_ids[:, :count]
        assert true_ids.shape == run_nn.shape
    recalls = np.zeros(len(run_nn))
    queries_with_ties = 0
    # TODO probably not very efficient
    for i in range(len(run_nn)):
        if count_ties:
            recalls[i], found_tie = compute_recall_with_distance_ties(true_ids[i], true_dists[i], run_nn[i], count)
            if found_tie: queries_with_ties += 1 
        else:
            recalls[i] = compute_recall_without_distance_ties(true_ids[i], run_nn[i], count)
    return (np.nanmean(recalls) / float(count),
            np.std(recalls) / float(count),
            recalls,
            queries_with_ties)

def knn(true_nn, run_nn, count, metrics, use_vec=False):
    if 'knn' not in metrics:        
        print('Computing knn metrics')
        knn_metrics = metrics.create_group('knn')
  
        if use_vec:
            run_nn = np.transpose(run_nn, (2, 1, 0))
            true_nn = true_nn[0]
            assert true_nn.shape == run_nn.shape, \
                f"Arrays have the same shape: true_nn.shape={true_nn.shape}, run_nn.shape={run_nn.shape}"
                
            mean, std, recalls, queries_with_ties = get_recall_values_by_vecs(true_nn, run_nn, count)
        else:     
            mean, std, recalls, queries_with_ties = get_recall_values(true_nn, run_nn, count)

        if queries_with_ties > 0:
            print("Warning: %d/%d queries contained ties accounted for in recall" % (queries_with_ties, len(run_nn)))
        knn_metrics.attrs['mean'] = mean
        knn_metrics.attrs['std'] = std
        knn_metrics['recalls'] = recalls
    else:
        print("Found cached result")
    return metrics['knn']

def ap(true_nn, run_nn, metrics):
    if'ap' not in metrics:
        print('Computing ap metrics')
        gt_nres, gt_I, gt_D = true_nn
        nq = gt_nres.shape[0]
        gt_lims = np.zeros(nq + 1, dtype=int)
        gt_lims[1:] = np.cumsum(gt_nres)
        ap = compute_AP((gt_lims, gt_I, gt_D), run_nn)
        ap_metric = metrics.create_group('ap')
        ap_metric.attrs['mean'] = ap
    else:
        print("Found cached result")
    return metrics['ap'].attrs['mean']

def queries_per_second(nq, attrs):
    return nq / attrs["best_search_time"]


def index_size(attrs):
    return attrs.get("index_size", 0)


def build_time(attrs):
    return attrs.get("build_time", -1)


def dist_computations(nq, attrs):
    return attrs.get("dist_comps", 0) / (attrs['run_count'] * nq)

def watt_seconds_per_query(queries, attrs):
    return power_capture.compute_watt_seconds_per_query(queries, attrs )

def mean_ssd_ios(attrs):
    return attrs.get("mean_ssd_ios", 0)

def mean_latency(attrs):
    return attrs.get("mean_latency", 0)

def pendingWrite(attrs):
    return attrs.get("pendingWrite",-1)

def batchLatency(attrs, count=0):
    return attrs.get(f"latency(Insert)_{count}",-1)

def latencyQuery(attrs,count=0):
    return attrs.get(f"latencyOfQuery_{count}",-1)

def totalTime(attrs):
    return attrs.get("totalTime",-1)

def continuousLatency(attrs):
    lats = attrs.get("continuousQueryLatencies")
    sum = 0
    for i in range(len(lats)):
        sum+=lats[i]
    return sum/len(lats)





all_metrics = {
    "k-nn": {
        "description": "Recall",
        "function": lambda true_nn, run_nn, metrics, run_attrs: knn(true_nn, run_nn, run_attrs["count"], metrics, run_attrs["use_vec"]).attrs['mean'],  # noqa
        "worst": float("-inf"),
        "lim": [0.0, 1.03],
    },
    "ap": {
        "description": "Average Precision",
        "function": lambda true_nn, run_nn, metrics, run_attrs: ap(true_nn, run_nn, metrics),  # noqa
        "worst": float("-inf"),
        "lim": [0.0, 1.03],
        "search_type" : "range",
    },
    "qps": {
        "description": "Queries per second (1/s)",
        "function": lambda true_nn, run_nn, metrics, run_attrs: queries_per_second(len(true_nn[0]), run_attrs),  # noqa
        "worst": float("-inf")
    },
    "distcomps": {
        "description": "Distance computations",
        "function": lambda true_nn, run_nn,  metrics, run_attrs: dist_computations(len(true_nn[0]), run_attrs), # noqa
        "worst": float("inf")
    },
    "build": {
        "description": "Build time (s)",
        "function": lambda true_nn, run_nn, metrics, run_attrs: build_time(run_attrs), # noqa
        "worst": float("inf")
    },
    "indexsize": {
        "description": "Index size (kB)",
        "function": lambda true_nn, run_nn, metrics, run_attrs: index_size(run_attrs),  # noqa
        "worst": float("inf")
    },
    # "queriessize": {
    #     "description": "Index size (kB)/Queries per second (s)",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: index_size(run_attrs) / queries_per_second(len(true_nn[0]), run_attrs), # noqa
    #     "worst": float("inf")
    # },
    "wspq": {
        "description": "Watt seconds per query (watt*s/query)",
        "function": lambda true_nn, run_nn, metrics, run_attrs: watt_seconds_per_query(true_nn, run_attrs),  
        "worst": float("-inf")
    },
    # "mean_ssd_ios": {
    #     "description": "Average SSD I/Os per query",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: mean_ssd_ios(run_attrs),
    #     "worst": float("inf")
    # },
    # "mean_latency": {
    #     "description": "Mean latency across queries",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: mean_latency(run_attrs),
    #     "worst": float("inf")
    # },
    "search_times": {
        "description": "List of consecutive search times for the same run parameter",
        "function": lambda true_nn, run_nn, metrics, run_attrs: run_attrs.get("search_times",[]), 
        "worst": float("inf")
    },
    "pendingWriteTime": {
        "description": "Time to wait for the index to complete previous batches",
        "function": lambda true_nn, run_nn, metrics, run_attrs: pendingWrite(run_attrs),
        "worst": float("inf")
    },
    # f"batchLatency_{0}": {
    #     "description": "95% Latency to complete 0th batches to be inserted",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: batchLatency(run_attrs,0),
    #     "worst": float("inf")
    # },
    # f"batchLatency_{1}": {
    #     "description": "95% Latency to complete 1st batches to be inserted",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: batchLatency(run_attrs,1),
    #     "worst": float("inf")
    # },
    # f"batchLatency_{2}": {
    #     "description": "95% Latency to complete 2nd batches to be inserted",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: batchLatency(run_attrs,2),
    #     "worst": float("inf")
    # },
    # f"latencySearch_{0}": {
    #     "description": "latency to complete the 0th search",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: latencyQuery(run_attrs),
    #     "worst": float("inf")
    # },
    # f"latencySearch_{1}": {
    #     "description": "latency to complete the 1st search",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: latencyQuery(run_attrs,1),
    #     "worst": float("inf")
    # },
    # f"latencySearch_{2}": {
    #     "description": "latency to complete the 2nd search",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: latencyQuery(run_attrs,2),
    #     "worst": float("inf")
    # },

    "totalTime": {
        "description": "Total time (ms)",
        "function": lambda true_nn, run_nn, metrics, run_attrs: totalTime(run_attrs),
        "worst": float("inf")
    },
    # "continuousRecall_{0}":{
    #     "description": "Average recall during 0th continuous querying",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: knn(true_nn, run_nn, run_attrs["count"], metrics).attrs['mean'],  # noqa
    #     "worst": float("-inf"),
    #     "lim": [0.0, 1.03],
    # },
    # "continuousLatency_{0}":{
    #     "description": "Average search latency during continuous querying",
    #     "function": lambda true_nn, run_nn, metrics, run_attrs: continuousLatency(run_attrs),
    #     "worst": float("inf")
    #
    # }
}
