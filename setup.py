from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = [
        line.strip()
        for line in f
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="zkteco_attendance",
    version="1.0.0",
    description="ZKTeco Biometric Attendance Integration for ERPNext/Frappe",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Your Organization",
    author_email="admin@example.com",
    url="https://github.com/your-org/zkteco_attendance",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=install_requires,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Framework :: Flask",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
)
