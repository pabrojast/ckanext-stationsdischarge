# -*- coding: utf-8 -*-
from setuptools import setup, find_namespace_packages

setup(
    name="ckanext-stationsdischarge",
    version="0.1.0",
    description=(
        "CKAN extension for hydrometric station management — "
        "ThingsBoard IoT integration and discharge rating curves."
    ),
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="PabloRojast",
    url="https://github.com/pabrojast/ckanext-stationsdischarge",
    license="AGPL-3.0",
    packages=find_namespace_packages(include=["ckanext.*"]),
    include_package_data=True,
    package_data={
        "ckanext.stationsdischarge": [
            "schemas/*.yaml",
            "templates/**/*.html",
            "public/**/*",
            "logic/*.py",
        ],
    },
    python_requires=">=3.8",
    install_requires=[],
    entry_points={
        "ckan.plugins": [
            "stationsdischarge = ckanext.stationsdischarge.plugin:StationsDischargePlugin",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: CKAN",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Programming Language :: Python :: 3",
    ],
)
