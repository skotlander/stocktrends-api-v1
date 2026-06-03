# utils/volume.py


def volume_to_actual_shares(value) -> int | None:
    """Convert st_data.volume (stored in hundreds of shares) to actual shares traded."""
    if value is None:
        return None
    return int(value) * 100
