from pathlib import Path

from setuptools import find_packages
from setuptools import setup

package_name = 'ros_github_scripts'
short_description = (
    'A set of scripts used to manage and report about ROS GitHub repositories.')

this_directory = Path(__file__).parent
with open(this_directory / 'README.md') as f:
    long_description = f.read()

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    maintainer='ROS Tooling Working Group',
    maintainer_email='ros-tooling@googlegroups.com',
    description=short_description,
    long_description=long_description,
    install_requires=[
        'markdown2==2.3.7',
        'PyGithub==1.43.5',
        'PyYAML==5.3.1',
        'retrying==1.3.3',
        # This package has not been released to pypi since 2019,
        # but the latest code contains features we need.
        # until it is released again, get it from github
        'jenkinsapi @ git+https://github.com/pycontribs/jenkinsapi@299a1b#egg=jenkinsapi',
    ],
    zip_safe=True,
    entry_points={'console_scripts': [
      'ros-ci-for-pr = ros_github_scripts.ci_for_pr:main',
      'ros-github-contribution-report = ros_github_scripts.generate_contribution_report:main',
    ]},
    python_requires='>=3.6',
)
