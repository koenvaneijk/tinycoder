import setuptools
from pathlib import Path

setuptools.setup(
    name="tinycoder",
    version="0.1.0",
    author="Koen van Eijk", 
    author_email="vaneijk.koen@gmail.com",
    description="A simplified AI coding assistant.",
    long_description=open('README.md', 'r', encoding='utf-8').read() if Path('README.md').exists() else "",
    long_description_content_type="text/markdown",
    url="https://github.com/koenvaneijk/tinycoder",
    packages=setuptools.find_packages(),
    include_package_data=True,
    package_data={
        # Ensure prompt files are included
        'tinycoder': ['prompts/*.md'],
    },
    entry_points={
        'console_scripts': [
            'tinycoder=tinycoder:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7', 
)
