import setuptools
from pathlib import Path

setuptools.setup(
    name="tinycoder",
    version="0.4.6",
    author="Koen van Eijk",
    author_email="vaneijk.koen@gmail.com",
    description="A simplified AI coding assistant.",
    long_description=(
        open("README.md", "r", encoding="utf-8").read()
        if Path("README.md").exists()
        else ""
    ),
    long_description_content_type="text/markdown",
    url="https://github.com/koenvaneijk/tinycoder",
    packages=setuptools.find_packages(),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "tinycoder=tinycoder:main",
            "tc=tinycoder:main",
            "ask=tinycoder.ask:main_ask",
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
        "Programming Language :: Python :: 3",
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
