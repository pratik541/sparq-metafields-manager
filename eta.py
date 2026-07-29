"""Live progress and time-remaining text, shared by the update tabs.

Estimates are extrapolated from measured throughput rather than a fixed
per-batch guess, so throttling, retries and slow network all show up in the
number the user sees instead of being hidden behind an optimistic constant.

Pure functions, no Streamlit, so the arithmetic is testable.
"""

# Rough per-batch cost used before any batch has completed and there is
# nothing to measure yet. Both update tabs send one HTTP request per batch
# with a 0.5s pause, so ~1.2s is a reasonable cold start.
ASSUMED_SECONDS_PER_BATCH = 1.2


def format_duration(seconds):
    """Human duration: '45s', '3m 20s', '1h 05m'. Returns '--' when unknown."""
    if seconds is None:
        return "--"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def eta_seconds(elapsed, done, total):
    """Seconds remaining, extrapolated from throughput so far.

    Returns None while nothing has finished (no rate to measure yet), and 0
    once everything is done.
    """
    if total <= 0 or done >= total:
        return 0.0
    if done <= 0 or elapsed <= 0:
        return None
    return (elapsed / done) * (total - done)


def upfront_estimate_seconds(total_batches, seconds_per_batch=ASSUMED_SECONDS_PER_BATCH):
    """Pre-run guess, shown before the first batch gives us real data."""
    return max(0, total_batches) * seconds_per_batch


def progress_line(elapsed, done, total, noun="Batch"):
    """One line combining position, elapsed and remaining.

    'Batch 12/300 · 14s elapsed · ~5m 50s remaining'
    """
    remaining = eta_seconds(elapsed, done, total)
    parts = [f"{noun} {done}/{total}", f"{format_duration(elapsed)} elapsed"]
    if remaining is None:
        parts.append("estimating...")
    elif remaining <= 0:
        parts.append("done")
    else:
        parts.append(f"~{format_duration(remaining)} remaining")
    return " · ".join(parts)
