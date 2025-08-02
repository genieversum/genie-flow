import os
from setuptools import setup

version = os.getenv('CI_COMMIT_TAG', '0.0.0.dev0')
version = version.split("-")[0]
setup(
    version=version,
)
