import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

import mpl_inspector as mpl_inspector


def test_diagnose_invisible_artist():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    line.set_visible(False)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert any("visible=False" in issue for issue in issues)

    plt.close(fig)


def test_diagnose_zero_alpha():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    line.set_alpha(0)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert any("alpha=0" in issue for issue in issues)

    plt.close(fig)


def test_diagnose_hidden_axes():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    ax.set_visible(False)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert any("Axes" in issue for issue in issues)

    plt.close(fig)


def test_diagnose_empty_line():
    fig, ax = plt.subplots()
    (line,) = ax.plot([], [])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert any("no data" in issue for issue in issues)

    plt.close(fig)


def test_diagnose_no_issues():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert issues == []

    plt.close(fig)


def test_diagnose_negative_zorder():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    line.set_zorder(-1)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    issues = inspector.diagnose_visibility(line)

    assert any("zorder" in issue for issue in issues)

    plt.close(fig)
