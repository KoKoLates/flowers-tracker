from __future__ import absolute_import
from scipy.optimize import linear_sum_assignment as linear_assignment
from . import kalman_filter

import numpy as np

INFTY_COST = 1e+5

def min_cost_matching(distance_metric, max_distance: float, 
                      tracks, detections, track_indices=None, 
                      detection_indices=None) -> list:
    """
    Solving the linear assignment problem.
    :param distance_metric: a list of tracks and detections as well as
    a list of N track indices and M detection indices.
    :param max_distance (float): Gating threshold. Associations with 
    cost larger than this value are disregarded.
    :param tracks (List[track.Track]): A list of predicted tracks at the current time step.
    """
    if track_indices is None:
        track_indices = np.arange(len(tracks))
    if detection_indices is None:
        detection_indices = np.arange(len(detections))
    
    if (not track_indices) or (not detection_indices):
        # nothing to match
        return [], track_indices, detection_indices

    cost_matrix = distance_metric(tracks, detections, track_indices, detection_indices)
    cost_matrix[cost_matrix > max_distance] = max_distance + 1e-5
    indices = linear_assignment(cost_matrix)
    indices = np.transpose(np.asarray(indices))

    matches, unmatched_tracks, unmatched_detections = [], [], []
    for col, detection_idx in enumerate(detection_indices):
        if col not in indices[:, 1]:
            unmatched_detections.append(detection_idx)

    for row, track_idx in enumerate(track_indices):
        if row not in indices[:, 0]:
            unmatched_tracks.append(track_idx)

    for row, col in indices:
        track_idx = track_indices[row]
        detection_idx = detection_indices[col]
        if cost_matrix[row, col] > max_distance:
            unmatched_tracks.append(track_idx)
            unmatched_detections.append(detection_idx)
        else:
            matches.append((track_idx, detection_idx))
    return matches, unmatched_tracks, unmatched_detections

def matching_cascade(distance_metric, max_distance:float, cascade_depth:int, 
                     tracks, detections, track_indices=None, detection_indices=None) -> list:
    """
    Running matching cascade
    :param distance_metric: The distance metric is given a list of tracks 
    and detections as well as a list of N track indices and M detection indices.
    :param max_distance (float): Gating threshold
    :param cascade_depth (int): The cascade depth
    """
    if track_indices is None:
        track_indices = list(range(len(tracks)))

    if detection_indices is None:
        detection_indices = list(range(len(detections)))

    unmatched_detections = detection_indices
    matches = []
    for level in range(cascade_depth):
        if not len(unmatched_detections):  # No detections left
            break

        track_indices_l = [
            k for k in track_indices
            if tracks[k].time_since_update == 1 + level
        ]
        if not len(track_indices_l):  # Nothing to match at this level
            continue

        matches_l, _, unmatched_detections = min_cost_matching(
            distance_metric, max_distance, tracks, 
            detections, track_indices_l, unmatched_detections
        )
        matches += matches_l
    unmatched_tracks = list(set(track_indices) - set(k for k, _ in matches))
    return matches, unmatched_tracks, unmatched_detections


def get_cost_matrix(kf, cost_matrix: np.ndarray, tracks, 
                    detections, track_indices, detection_indices, 
                    gated_cost=INFTY_COST, only_position=False) -> np.ndarray:
    """
    Invalidate infeasible entries in cost matrix based on the state
    distributions obtained by Kalman filtering.
    """
    gating_dim = 2 if only_position else 4
    gating_threshold = kalman_filter.KalmanFilter.chi_square[gating_dim]
    measurements = np.asarray([detections[i].to_xyah() for i in detection_indices])
    for row, track_idx in enumerate(track_indices):
        track = tracks[track_idx]
        gating_distance = kf.gating_distance(
            track.mean, track.covariance, measurements, only_position
        )
        cost_matrix[row, gating_distance > gating_threshold] = gated_cost
    return cost_matrix
    