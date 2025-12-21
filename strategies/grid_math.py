from decimal import Decimal, getcontext
from typing import List

# Set precision high enough
getcontext().prec = 28


def calculate_arithmetic_grid(
    lower_price: Decimal, upper_price: Decimal, grid_count: int
) -> List[Decimal]:
    """
    Calculates grid levels with constant price difference.
    Returns list of prices from Lower to Upper inclusive.
    """
    if grid_count < 2:
        raise ValueError("Grid count must be at least 2")

    # Step size
    step = (upper_price - lower_price) / (grid_count - 1)

    levels = []
    for i in range(grid_count):
        price = lower_price + (step * i)
        levels.append(price)

    return levels


def calculate_geometric_grid(
    lower_price: Decimal, upper_price: Decimal, grid_count: int
) -> List[Decimal]:
    """
    Calculates grid levels with constant percentage difference.
    Returns list of prices from Lower to Upper inclusive.
    """
    if grid_count < 2:
        raise ValueError("Grid count must be at least 2")

    # Ratio
    # r = (upper / lower) ^ (1 / (n-1))
    ratio = (upper_price / lower_price) ** (Decimal("1") / (grid_count - 1))

    levels = []
    for i in range(grid_count):
        price = lower_price * (ratio**i)
        levels.append(price)

    return levels


def calculate_grid_levels(
    lower_price: Decimal,
    upper_price: Decimal,
    grid_count: int,
    mode: str = "ARITHMETIC",
) -> List[Decimal]:
    if mode.upper() == "GEOMETRIC":
        return calculate_geometric_grid(lower_price, upper_price, grid_count)
    else:
        return calculate_arithmetic_grid(lower_price, upper_price, grid_count)
