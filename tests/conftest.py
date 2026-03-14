import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest


@pytest.fixture
def fig_ax():
    """Yield a fresh (figure, axes) pair and close it after the test."""
    fig, ax = plt.subplots()
    fig.canvas.draw()
    yield fig, ax
    plt.close(fig)
