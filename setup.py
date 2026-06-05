# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = [l for l in f.read().strip().split("\n") if l and not l.startswith("#")]

from zkteco_attendance import __version__ as version

setup(
    name="zkteco_attendance",
    version=version,
    description="ZKTeco Biometric Attendance Integration for ERPNext/Frappe",
    author="Your Organization",
    author_email="admin@example.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
