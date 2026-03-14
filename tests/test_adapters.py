import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

import mpl_inspector as mpl_inspector


def test_line_metadata_contains_core_fields():
    figure, axis = plt.subplots()
    (line,) = axis.plot([0, 1, 2], [2, 1, 3], label="series-a", linewidth=2.5)
    figure.canvas.draw()

    inspector = mpl_inspector.inspect(figure, print_on_select=False)
    metadata = inspector.describe_artist(line)

    assert metadata.title == "Line2D"
    assert metadata.properties["label"] == "series-a"
    assert metadata.properties["linewidth"] == 2.5
    assert metadata.data["points"] == 3
    assert "shape=(3,)" in metadata.data["x"]

    plt.close(figure)
