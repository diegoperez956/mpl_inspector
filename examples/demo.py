from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

import mpl_inspector


def main() -> None:
    rng = np.random.default_rng(7)
    x = np.linspace(0, 2 * np.pi, 250)

    figure, axes = plt.subplots(2, 2, figsize=(12, 7))
    figure.suptitle("mpl_inspector demo")

    line_ax, scatter_ax, bar_ax, image_ax = axes.flat

    line_ax.plot(x, np.sin(x), label="sin(x)", linewidth=2.0)
    line_ax.plot(x, np.cos(x), label="cos(x)", linewidth=2.0, linestyle="--")
    line_ax.set_title("Lines")
    line_ax.set_xlabel("x")
    line_ax.set_ylabel("y")
    line_ax.legend()
    line_ax.annotate("peak", xy=(np.pi / 2, 1.0), xytext=(2.0, 1.3), arrowprops={"arrowstyle": "->"})

    scatter_x = rng.normal(size=70)
    scatter_y = 0.6 * scatter_x + rng.normal(scale=0.55, size=70)
    scatter_ax.scatter(
        scatter_x,
        scatter_y,
        c=np.hypot(scatter_x, scatter_y),
        s=rng.uniform(40, 180, size=70),
        cmap="viridis",
        alpha=0.8,
        label="samples",
    )
    scatter_ax.axhline(0, color="#94a3b8", linewidth=1.0)
    scatter_ax.axvline(0, color="#94a3b8", linewidth=1.0)
    scatter_ax.errorbar([0, 1], [0.5, -0.5], yerr=0.3, fmt="s", color="#fb923c", label="errorbars")
    scatter_ax.set_title("Scatter / Collections")
    scatter_ax.legend(loc="upper left")

    categories = ["alpha", "beta", "gamma", "delta"]
    values = [3.2, 5.7, 2.4, 6.4]
    bars = bar_ax.bar(categories, values, color=["#60a5fa", "#f59e0b", "#34d399", "#f472b6"], label="bars")
    bars[1].set_hatch("//")
    bar_ax.axhspan(4.5, 5.5, color="#fde68a", alpha=0.25)
    bar_ax.fill_between(range(4), [0.5, 1.0, 0.8, 1.5], alpha=0.15, color="#818cf8", label="fill")
    bar_ax.set_title("Bars / Patches / Fill")
    bar_ax.legend()

    matrix = rng.normal(size=(18, 18))
    image = image_ax.pcolormesh(matrix, cmap="magma")
    image_ax.set_title("QuadMesh / Text")
    image_ax.text(2, 15, "Inspect me", color="white", fontsize=11)
    figure.colorbar(image, ax=image_ax, shrink=0.78)

    mpl_inspector.inspect(figure)
    plt.show()


if __name__ == "__main__":
    main()
