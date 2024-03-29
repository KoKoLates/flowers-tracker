from __future__ import absolute_import
from . import kalman_filter, linear_assignment, iou_matching, nn_matching, detection
from .track import Track

import numpy as np

class Tracker(object):
    """ multi-target tracker. """

    def __init__(self, metric:nn_matching.NearestNeighborDistanceMetric, 
                 max_iou_distance:float=0.7, max_age:int=50, n_init:int=3) -> None:
        """
        :param metric (NearestNeighborDistanceMetric): The distance metric used for 
        measurement to track association.
        :param max_age (int): Maximum number of missed misses before a track is deleted.
        :param n_init (int): Number of frames that a track remains in initialization phase.
        """
        self.metric, self.max_age = metric, max_age
        self.max_iou_distance, self.n_init = max_iou_distance, n_init

        self.tracks = []
        self._next_id = 1
        self.kf = kalman_filter.KalmanFilter()

    def predict(self) -> None:
        """ Propagate track state distributions one time step forward. """
        for track in self.tracks:
            track.predict(self.kf)

    def update(self, detections) -> None:
        """
        Perform measurement update and track management.
        :param detection: A list of detections at the current time step.
        """
        matches, unmatched_tracks, unmatched_detections = self._match(detections)

        # Update track set.
        for track_idx, detection_idx in matches:
            self.tracks[track_idx].update(
                self.kf, detections[detection_idx])
            
        for track_idx in unmatched_tracks:
            self.tracks[track_idx].mark_missed()

        for detection_idx in unmatched_detections:
            self._initiate_track(detections[detection_idx])

        self.tracks = [t for t in self.tracks if not t.is_deleted()]

        # Update distance metric.
        active_targets = [t.track_id for t in self.tracks if t.is_confirmed()]
        features, targets = [], []
        for track in self.tracks:
            if not track.is_confirmed():
                continue
            features += track.features
            targets += [track.track_id for _ in track.features]
            track.features = []
        self.metric.partial_fit(np.asarray(features), np.asarray(targets), active_targets)

    def _match(self, detections):

        def gated_metric(tracks, dets, track_indices, detection_indices):
            features = np.array([dets[i].feature for i in detection_indices])
            targets = np.array([tracks[i].track_id for i in track_indices])
            cost_matrix = self.metric.distance(features, targets)
            cost_matrix = linear_assignment.get_cost_matrix(
                self.kf, cost_matrix, tracks, dets, track_indices, detection_indices
            )
            return cost_matrix

        # Split track set into confirmed and unconfirmed tracks.
        confirmed_tracks = [i for i, t in enumerate(self.tracks) if t.is_confirmed()]
        unconfirmed_tracks = [i for i, t in enumerate(self.tracks) if not t.is_confirmed()]

        # Associate confirmed tracks using appearance features.
        matches_a, unmatched_tracks_a, unmatched_detections = linear_assignment.matching_cascade(
            gated_metric, self.metric.matching_threshold, self.max_age,
            self.tracks, detections, confirmed_tracks
        )

        # Associate remaining tracks together with unconfirmed tracks using IOU.
        iou_track_candidates = unconfirmed_tracks + [
            k for k in unmatched_tracks_a if
            self.tracks[k].time_since_update == 1]
        unmatched_tracks_a = [
            k for k in unmatched_tracks_a if
            self.tracks[k].time_since_update != 1]
        matches_b, unmatched_tracks_b, unmatched_detections = linear_assignment.min_cost_matching(
            iou_matching.iou_cost, self.max_iou_distance, self.tracks,
            detections, iou_track_candidates, unmatched_detections
        )

        matches = matches_a + matches_b
        unmatched_tracks = list(set(unmatched_tracks_a + unmatched_tracks_b))
        return matches, unmatched_tracks, unmatched_detections

    def _initiate_track(self, detection:detection.Detection):
        mean, covariance = self.kf.initiate(detection.to_xyah())
        self.tracks.append(Track(
            mean, covariance, self._next_id, self.n_init, self.max_age,
            detection.feature, detection.get_class()))
        self._next_id += 1
