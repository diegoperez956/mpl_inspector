import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

import mpl_inspector as mpl_inspector


def test_import_and_enable_disable_cycle():
    figure, _ = plt.subplots()

    inspector = mpl_inspector.inspect(figure, print_on_select=False)
    assert inspector.enabled is True

    disabled = mpl_inspector.disable(figure)
    assert disabled is True
    assert inspector.enabled is False

    enabled_again = mpl_inspector.enable(figure, print_on_select=False)
    assert enabled_again is inspector
    assert inspector.enabled is True

    plt.close(figure)
