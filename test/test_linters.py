# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.

import logging
import os

from ament_flake8.main import main as run_flake8
from ament_mypy.main import main as run_mypy
from ament_pep257.main import main as run_pep257
import pkg_resources
import pytest
from yamllint.cli import run as run_yamllint


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    # this logger has been known to default to DEBUG and it is too noisy
    logging.getLogger('flake8').setLevel(logging.INFO)
    return_code = run_flake8(argv=[])
    assert return_code == 0, 'Found Flake8 errors / warnings'


@pytest.mark.mypy
@pytest.mark.linter
def test_mypy():
    assert run_mypy(argv=[]) == 0, 'Found mypy errors / warnings'


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    assert run_pep257(argv=['.']) == 0, 'Found pep257 errors / warnings'


@pytest.mark.linter
def test_yamllint():
    any_error = False
    mixins_dir = pkg_resources.resource_filename('robomaker_github_tools', 'data')
    for name in sorted(os.listdir(mixins_dir)):
        if name.endswith('.yaml'):
            print(
                'This package requires all YAML files use the .yml extension '
                f'(found .yaml instead: {name})')
            any_error = True
            continue

        if not name.endswith('.yml'):
            continue

        try:
            run_yamllint([
                '--config-data',
                '{'
                'extends: default, '
                'rules: {'
                'document-start: {present: false}, '
                'empty-lines: {max: 0}, '
                'key-ordering: {}, '
                'line-length: {max: 999}'
                '}'
                '}',
                '--strict',
                os.path.join(mixins_dir, name),
            ])
        except SystemExit as e:
            any_error |= bool(e.code)
            continue

    assert not any_error, 'Should not have seen any errors'
