"""
Walk-forward model evaluation.

Implements §5.5 requirements:
  - Walk-forward only (no random train/test splits)
  - Brier score and log-loss for calibration
  - Simulated ROI vs flat-staking on historical BSP
  - Market-implied probability as the mandatory comparison baseline

All evaluation is at the race level (each race is a multi-horse probability
distribution), not at the individual runner level in isolation.
"""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, log_loss

log = logging.getLogger(__name__)


@dataclass
class EvalResult:
    n_races: int
    n_runners: int
    brier_score: float
    log_loss: float
    market_brier_score: float
    market_log_loss: float
    simulated_roi_flat: float    # vs BSP, flat-staking on positive-edge runners
    market_beat_margin_brier: float   # market_brier - model_brier (positive = model better)
    market_beat_margin_logloss: float


def evaluate_walk_forward(
    df: pd.DataFrame,
    train_cutoff: pd.Timestamp,
    *,
    prob_col: str = "win_prob",
    market_prob_col: str = "market_implied_prob",
    outcome_col: str = "won",
    bsp_col: str = "bsp",
    race_id_col: str = "race_id",
    min_races: int = 50,
) -> EvalResult:
    """
    Evaluate model on all races strictly after train_cutoff.

    df must have one row per runner with columns:
      race_id, win_prob, market_implied_prob, won (bool), bsp (decimal odds)
    """
    test = df[df["race_date"] > train_cutoff].copy()

    if len(test[race_id_col].unique()) < min_races:
        raise ValueError(
            f"Only {len(test[race_id_col].unique())} test races — need ≥{min_races}"
        )

    y_true = test[outcome_col].astype(int).values
    y_model = np.clip(test[prob_col].values, 1e-6, 1 - 1e-6)
    y_market = np.clip(test[market_prob_col].values, 1e-6, 1 - 1e-6)

    model_brier = brier_score_loss(y_true, y_model)
    model_ll = log_loss(y_true, y_model)
    market_brier = brier_score_loss(y_true, y_market)
    market_ll = log_loss(y_true, y_market)

    roi = _simulated_roi_flat(test, prob_col, market_prob_col, outcome_col, bsp_col)

    result = EvalResult(
        n_races=len(test[race_id_col].unique()),
        n_runners=len(test),
        brier_score=float(model_brier),
        log_loss=float(model_ll),
        market_brier_score=float(market_brier),
        market_log_loss=float(market_ll),
        simulated_roi_flat=roi,
        market_beat_margin_brier=float(market_brier - model_brier),
        market_beat_margin_logloss=float(market_ll - model_ll),
    )

    log.info(
        "Eval on %d races / %d runners | "
        "Brier: model=%.4f market=%.4f (delta=%.4f) | "
        "LogLoss: model=%.4f market=%.4f (delta=%.4f) | "
        "ROI flat: %.2f%%",
        result.n_races, result.n_runners,
        result.brier_score, result.market_brier_score, result.market_beat_margin_brier,
        result.log_loss, result.market_log_loss, result.market_beat_margin_logloss,
        result.simulated_roi_flat * 100,
    )
    return result


def _simulated_roi_flat(
    df: pd.DataFrame,
    prob_col: str,
    market_prob_col: str,
    outcome_col: str,
    bsp_col: str,
) -> float:
    """
    Flat-staking 1 unit on every runner where model probability > market-implied probability.
    Returns ROI = (total_return - total_staked) / total_staked.

    Uses BSP as the settlement price (most conservative / realistic assumption).
    """
    positive_edge = df[df[prob_col] > df[market_prob_col]].copy()
    if positive_edge.empty:
        return 0.0

    staked = len(positive_edge)
    returns = positive_edge.apply(
        lambda r: float(r[bsp_col]) - 1.0 if r[outcome_col] else -1.0, axis=1
    ).sum()

    return float(returns / staked)


def calibration_summary(
    df: pd.DataFrame,
    prob_col: str = "win_prob",
    outcome_col: str = "won",
    n_bins: int = 10,
) -> pd.DataFrame:
    """
    Returns a reliability table: for each predicted-probability bucket,
    the actual win rate. Used to plot calibration curves.
    """
    y_true = df[outcome_col].astype(int).values
    y_pred = df[prob_col].values
    fraction_of_positives, mean_predicted = calibration_curve(
        y_true, y_pred, n_bins=n_bins, strategy="quantile"
    )
    return pd.DataFrame({
        "predicted_prob": mean_predicted,
        "actual_win_rate": fraction_of_positives,
        "calibration_error": fraction_of_positives - mean_predicted,
    })


def beats_market(result: EvalResult) -> bool:
    """
    Promotion gate: candidate must beat production on BOTH calibration AND log-loss.
    Returns True if model beats the market-implied baseline on both metrics.
    """
    return result.market_beat_margin_brier > 0 and result.market_beat_margin_logloss > 0
