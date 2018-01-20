"""A setuptools based setup module for DiviK algorithm."""

from setuptools import setup, find_packages

setup(
    name='spectre-divik',
    version='0.0.0',
    description='Divisive iK-means algorithm implementation',
    url='https://github.com/spectre-team/spectre-divik',
    author='Grzegorz Mrukwa',
    author_email='Grzegorz.Mrukwa@polsl.pl',
    classifiers=[
        # based on https://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Development Status :: 1 - Planning',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        'Topic :: Scientific/Engineering :: Information Analysis',
        'Topic :: Scientific/Engineering :: Medical Science Apps.'
    ],
    packages=find_packages(exclude=['test']),
    # @gmrukwa: https://packaging.python.org/discussions/install-requires-vs-requirements/
    install_requires=[
        'numpy>=1.12.1',
        'tqdm>=4.11.2',
        'typing>=3.6.2'
    ],
    python_requires='>=3.4',
    package_data={
    }
)