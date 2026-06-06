from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in zkteco_attendance/__init__.py
from zkteco_attendance import __version__ as version

setup(
	name="zkteco_attendance",
	version=version,
	description="The app to connect biometric attendance to erpnext",
	author="abdu",
	author_email="abdulsomed@0825@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
