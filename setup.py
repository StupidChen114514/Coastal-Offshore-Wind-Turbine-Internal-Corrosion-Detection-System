"""Setup script for the Wind Turbine Internal Corrosion Detection System."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="wind-turbine-corrosion-detection",
    version="1.0.0",
    author="Sensor Project Team",
    description="Coastal Offshore Wind Turbine Internal Corrosion Detection System",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/example/sensor_project",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
        "Topic :: Scientific/Engineering :: Atmospheric Science",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "corrosion-detector=main:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["config/*.json"],
    },
)
