import numpy as np
from typing import List


def calculate_arithmetic_grid(
    lower_price: float, upper_price: float, grid_count: int
) -> List[float]:
    """
    Calculates grid levels with constant price difference.
    Returns list of prices from Lower to Upper inclusive.
    """
    if grid_count < 2:
        raise ValueError("Grid count must be at least 2")

    return np.linspace(lower_price, upper_price, grid_count).tolist()


def calculate_geometric_grid(
    lower_price: float, upper_price: float, grid_count: int
) -> List[float]:
    """
    Calculates grid levels with constant percentage difference.
    Returns list of prices from Lower to Upper inclusive.
    """
    if grid_count < 2:
        raise ValueError("Grid count must be at least 2")

    return np.geomspace(lower_price, upper_price, grid_count).tolist()


def calculate_grid_levels(
    lower_price: float, upper_price: float, grid_count: int, mode: str = "ARITHMETIC"
) -> List[float]:
    if mode.upper() == "GEOMETRIC":
        return calculate_geometric_grid(lower_price, upper_price, grid_count)
    else:
        return calculate_arithmetic_grid(lower_price, upper_price, grid_count)
